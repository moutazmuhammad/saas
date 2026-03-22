import json
import logging
import shlex
import select

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

STREAM_TIMEOUT = 300  # 5 minutes max


class ContainerLogsController(http.Controller):

    @http.route(
        '/saas/instance/<int:instance_id>/logs/stream',
        type='http',
        auth='user',
    )
    def stream_instance_logs(self, instance_id, tail='100', **kwargs):
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
        container = request.env['saas.docker.container'].browse(container_id)
        if not container.exists():
            raise NotFound()
        container.check_access('read')
        return self._stream(container.server_id, container.name, tail)

    def _stream(self, server, container_name, tail):
        safe_name = shlex.quote(container_name)

        # Validate tail is a safe integer
        try:
            tail_int = int(tail)
        except (ValueError, TypeError):
            tail_int = 100

        # Obtain SSH connection while the ORM cursor is still open.
        # The generator runs after the request transaction ends,
        # so ORM access inside generate() would hit a closed cursor.
        ssh_conn = server._get_ssh_connection()

        def generate():
            try:
                ssh_conn._connect()  # noqa: uses ssh_conn from outer scope
                transport = ssh_conn._client.get_transport()
                channel = transport.open_session()
                channel.exec_command(
                    'docker logs -f --tail %d %s 2>&1' % (tail_int, safe_name)
                )
                channel.settimeout(STREAM_TIMEOUT)

                # Send initial SSE comment to establish connection
                yield b'retry: 1000\n\n'

                buf = b''
                while not channel.exit_status_ready():
                    # Wait for data with a short timeout so we can check exit
                    ready, _, _ = select.select([channel], [], [], 1.0)
                    if ready:
                        chunk = channel.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                        # Split on newlines and send complete lines
                        while b'\n' in buf:
                            line, buf = buf.split(b'\n', 1)
                            text = line.decode('utf-8', errors='replace')
                            yield ('data: %s\n\n' % json.dumps(text)).encode('utf-8')

                # Drain remaining data
                while channel.recv_ready():
                    chunk = channel.recv(4096)
                    buf += chunk
                if buf:
                    text = buf.decode('utf-8', errors='replace')
                    yield ('data: %s\n\n' % json.dumps(text)).encode('utf-8')

                yield b'event: done\ndata: stream ended\n\n'

            except Exception as e:
                _logger.exception("Log streaming error for container %s", container_name)
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
