import json
import logging
import re
import shlex
import select

from werkzeug.exceptions import Forbidden, NotFound

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

STREAM_TIMEOUT = 300  # 5 minutes max
# Cap the in-process line buffer per stream. A noisy container could
# otherwise grow this without bound if the client reads slowly.
MAX_BUFFER_BYTES = 1 * 1024 * 1024
# Strip ANSI escape sequences before forwarding — a tenant can put any
# bytes into their own logs and we don't want them rendered into the
# manager's HTML log viewer.
_ANSI_RE = re.compile(rb'\x1b\[[0-9;?]*[a-zA-Z]')

# Group required for the cross-container log endpoint (which can target
# any container on any server, including other tenants').
ADMIN_LOG_GROUP = 'saas_core.group_saas_manager'


class ContainerLogsController(http.Controller):

    @http.route(
        '/saas/instance/<int:instance_id>/logs/stream',
        type='http',
        auth='user',
    )
    def stream_instance_logs(self, instance_id, tail='100', **kwargs):
        # Per-instance route: any user with read access to the instance
        # may stream logs. Record rules on saas.instance scope visibility.
        instance = request.env['saas.instance'].browse(instance_id)
        if not instance.exists():
            raise NotFound()
        instance.check_access('read')
        return self._stream(
            instance.docker_server_id, instance._get_container_name(), tail,
        )

    @http.route(
        '/saas/container/<int:container_id>/logs/stream',
        type='http',
        auth='user',
    )
    def stream_logs(self, container_id, tail='100', **kwargs):
        # Cross-tenant route: a single container record can reference
        # any container on any server. Restrict to managers — read access
        # alone on saas.docker.container does not imply ownership.
        if not request.env.user.has_group(ADMIN_LOG_GROUP):
            raise Forbidden(
                "SaaS Manager privileges required to stream container logs."
            )
        container = request.env['saas.docker.container'].browse(container_id)
        if not container.exists():
            raise NotFound()
        container.check_access('read')
        return self._stream(container.server_id, container.name, tail)

    @http.route(
        '/saas/instance/<int:instance_id>/metrics/stream',
        type='http',
        auth='user',
    )
    def stream_instance_metrics(self, instance_id, **kwargs):
        """Live CPU/RAM SSE — same plumbing/path family as the log stream
        so it goes through the proxy's SSE-friendly handling. A host-side
        loop runs ``docker stats --no-stream`` ~every 2s; each sample is
        converted to plan-relative percentages (identical math to
        ``_refresh_usage_with_ssh``) and emitted as an SSE event."""
        instance = request.env['saas.instance'].browse(instance_id)
        if not instance.exists():
            raise NotFound()
        instance.check_access('read')
        if instance.state != 'running' or not instance.docker_server_id:
            raise NotFound()
        # Capture everything the generator needs while the cursor is open.
        server = instance.docker_server_id.sudo()
        container_name = instance._get_container_name()
        plan = instance.plan_id
        plan_cpu = float(plan.cpu_limit) if plan and plan.cpu_limit else 0.0
        plan_ram_bytes = (
            instance._parse_ram_string(plan.ram_limit)
            if plan and plan.ram_limit else 0
        )
        multiplier = float(request.env['ir.config_parameter'].sudo().get_param(
            'saas_master.resource_usage_multiplier', '2.0',
        ) or 2.0)
        return self._stream_metrics(
            server, container_name, plan_cpu, plan_ram_bytes, multiplier,
        )

    def _stream_metrics(self, server, container_name, plan_cpu,
                        plan_ram_bytes, multiplier):
        safe_name = shlex.quote(container_name)
        ssh_conn = server._get_ssh_connection()

        def _mem_used_bytes(field):
            # "152.4MiB / 2GiB" → used bytes
            try:
                used = field.split('/')[0].strip()
                num = ''.join(c for c in used if c.isdigit() or c == '.')
                unit = used[len(num):].strip().lower()
                mult = {
                    'b': 1, 'kib': 1024, 'kb': 1000, 'mib': 1024 ** 2,
                    'mb': 1000 ** 2, 'gib': 1024 ** 3, 'gb': 1000 ** 3,
                    'tib': 1024 ** 4, 'tb': 1000 ** 4,
                }.get(unit, 1)
                return (float(num) if num else 0.0) * mult
            except Exception:
                return 0.0

        def generate():
            try:
                ssh_conn._connect()
                transport = ssh_conn._client.get_transport()
                channel = transport.open_session()
                channel.exec_command(
                    "sh -c 'while true; do docker stats --no-stream "
                    "--format \"{{.CPUPerc}}||{{.MemUsage}}\" %s 2>/dev/null; "
                    "sleep 1; done'" % safe_name
                )
                channel.settimeout(STREAM_TIMEOUT)
                yield b'retry: 2000\n\n'

                buf = b''
                while not channel.exit_status_ready():
                    ready, _, _ = select.select([channel], [], [], 1.0)
                    if not ready:
                        continue
                    chunk = channel.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    if len(buf) > MAX_BUFFER_BYTES:
                        buf = buf[-MAX_BUFFER_BYTES:]
                    while b'\n' in buf:
                        line, buf = buf.split(b'\n', 1)
                        text = line.decode('utf-8', 'replace').strip()
                        if '||' not in text:
                            continue
                        parts = text.split('||')
                        try:
                            raw_cpu = float(parts[0].replace('%', '').strip())
                        except (ValueError, IndexError):
                            raw_cpu = 0.0
                        ram_used = _mem_used_bytes(parts[1]) if len(parts) > 1 else 0.0
                        cpu_pct = (
                            min((raw_cpu / 100.0) * multiplier / plan_cpu * 100, 999)
                            if plan_cpu > 0 and raw_cpu > 0 else 0.0
                        )
                        ram_used_m = ram_used * multiplier
                        ram_pct = (
                            min(ram_used_m / plan_ram_bytes * 100, 999)
                            if plan_ram_bytes > 0 and ram_used_m > 0 else 0.0
                        )
                        yield ('data: %s\n\n' % json.dumps({
                            'cpu': round(cpu_pct), 'ram': round(ram_pct),
                        })).encode('utf-8')

                yield b'event: done\ndata: stream ended\n\n'
            except Exception as e:
                _logger.exception(
                    "Metrics streaming error for %s", container_name,
                )
                yield ('event: error\ndata: %s\n\n' % json.dumps(str(e))).encode('utf-8')
            finally:
                ssh_conn._disconnect()

        return Response(
            generate(),
            content_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            },
            direct_passthrough=True,
        )

    def _stream(self, server, container_name, tail):
        safe_name = shlex.quote(container_name)

        # Validate tail is a safe integer
        try:
            tail_int = max(0, min(int(tail), 10000))
        except (ValueError, TypeError):
            tail_int = 100

        # Obtain SSH connection while the ORM cursor is still open.
        # The generator runs after the request transaction ends,
        # so ORM access inside generate() would hit a closed cursor.
        ssh_conn = server._get_ssh_connection()

        def generate():
            try:
                ssh_conn._connect()
                transport = ssh_conn._client.get_transport()
                channel = transport.open_session()
                channel.exec_command(
                    'docker logs -f --tail %d %s 2>&1' % (tail_int, safe_name)
                )
                channel.settimeout(STREAM_TIMEOUT)

                yield b'retry: 1000\n\n'

                buf = b''
                while not channel.exit_status_ready():
                    ready, _, _ = select.select([channel], [], [], 1.0)
                    if ready:
                        chunk = channel.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                        # Bound buffer growth — drop oldest data if a
                        # noisy container outpaces the client.
                        if len(buf) > MAX_BUFFER_BYTES:
                            buf = buf[-MAX_BUFFER_BYTES:]
                        while b'\n' in buf:
                            line, buf = buf.split(b'\n', 1)
                            line = _ANSI_RE.sub(b'', line)
                            text = line.decode('utf-8', errors='replace')
                            yield ('data: %s\n\n' % json.dumps(text)).encode('utf-8')

                while channel.recv_ready():
                    chunk = channel.recv(4096)
                    buf += chunk
                if buf:
                    text = _ANSI_RE.sub(b'', buf).decode('utf-8', errors='replace')
                    yield ('data: %s\n\n' % json.dumps(text)).encode('utf-8')

                yield b'event: done\ndata: stream ended\n\n'

            except Exception as e:
                _logger.exception(
                    "Log streaming error for container %s", container_name,
                )
                yield ('event: error\ndata: %s\n\n' % json.dumps(str(e))).encode('utf-8')
            finally:
                ssh_conn._disconnect()

        return Response(
            generate(),
            content_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            },
            direct_passthrough=True,
        )
