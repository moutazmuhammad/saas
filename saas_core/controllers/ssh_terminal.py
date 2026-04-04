import json
import logging
import os
import select
import threading
import time
import uuid

from werkzeug.exceptions import Forbidden, NotFound

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# In-memory store: session_id -> dict with channel, ssh_conn, metadata
# NOTE: this is per-process, so Odoo MUST run with --workers=0 (threaded mode)
# or gevent mode for terminal to work. Multi-process workers do NOT share memory.
_terminal_sessions = {}
_sessions_lock = threading.Lock()
_worker_pid = os.getpid()

SESSION_TIMEOUT = 600  # 10 minutes idle timeout
STREAM_READ_TIMEOUT = 300  # 5 minutes max stream
SSH_KEEPALIVE_INTERVAL = 15  # seconds between SSH keepalive packets
SSE_HEARTBEAT_INTERVAL = 10  # seconds between SSE heartbeat comments


def _cleanup_session(session_id):
    """Close and remove a terminal session."""
    with _sessions_lock:
        session = _terminal_sessions.pop(session_id, None)
    if session:
        try:
            channel = session.get('channel')
            if channel:
                channel.close()
        except Exception:
            pass
        try:
            ssh_conn = session.get('ssh_conn')
            if ssh_conn:
                ssh_conn._disconnect()
        except Exception:
            pass
        _logger.info("Terminal session %s cleaned up (pid %s)", session_id, os.getpid())


def _cleanup_stale_sessions():
    """Remove sessions that have been idle for too long."""
    now = time.time()
    stale = []
    with _sessions_lock:
        for sid, session in _terminal_sessions.items():
            if now - session.get('last_activity', 0) > SESSION_TIMEOUT:
                stale.append(sid)
    for sid in stale:
        _logger.info("Cleaning up stale terminal session %s", sid)
        _cleanup_session(sid)


class SshTerminalController(http.Controller):

    @http.route(
        '/saas/terminal/create',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def create_session(self, server_model, server_id, **kwargs):
        """Create a new interactive SSH terminal session.

        Args:
            server_model: 'saas.server'
            server_id: ID of the server record
        Returns:
            dict with session_id
        """
        allowed_models = (
            'saas.server',
        )
        if server_model not in allowed_models:
            raise Forbidden("Invalid server model")

        server = request.env[server_model].browse(int(server_id))
        if not server.exists():
            raise NotFound("Server not found")
        server.check_access('read')

        # Clean up stale sessions first
        _cleanup_stale_sessions()

        # Create SSH connection and open interactive shell
        ssh_conn = server._get_ssh_connection()
        ssh_conn._connect()

        try:
            transport = ssh_conn._client.get_transport()
            # Enable SSH keepalive to prevent NAT/firewall from dropping
            # idle connections. This sends a keepalive packet every N seconds.
            transport.set_keepalive(SSH_KEEPALIVE_INTERVAL)

            channel = transport.open_session()
            channel.get_pty(
                term='xterm-256color',
                width=120,
                height=40,
            )
            channel.invoke_shell()
            channel.settimeout(0)  # non-blocking reads
        except Exception as e:
            _logger.error(
                "Failed to open SSH shell to %s: %s", server.name, e,
            )
            ssh_conn._disconnect()
            raise

        session_id = str(uuid.uuid4())

        with _sessions_lock:
            _terminal_sessions[session_id] = {
                'channel': channel,
                'ssh_conn': ssh_conn,
                'uid': request.env.uid,
                'server_name': server.name,
                'last_activity': time.time(),
                'created': time.time(),
                'pid': os.getpid(),
            }

        _logger.info(
            "Terminal session %s created for server %s by uid %s (pid %s)",
            session_id, server.name, request.env.uid, os.getpid(),
        )

        return {'session_id': session_id}

    @http.route(
        '/saas/terminal/input',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def send_input(self, session_id, data, **kwargs):
        """Send keyboard input to the terminal session.

        Args:
            session_id: Terminal session UUID
            data: String data to send (keystrokes)
        """
        session = self._get_session(session_id)
        channel = session['channel']

        if channel.closed:
            _cleanup_session(session_id)
            return {'status': 'closed'}

        channel.sendall(data.encode('utf-8'))
        session['last_activity'] = time.time()
        return {'status': 'ok'}

    @http.route(
        '/saas/terminal/resize',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def resize(self, session_id, cols, rows, **kwargs):
        """Resize the PTY.

        Args:
            session_id: Terminal session UUID
            cols: Number of columns
            rows: Number of rows
        """
        session = self._get_session(session_id)
        channel = session['channel']

        if not channel.closed:
            channel.resize_pty(width=int(cols), height=int(rows))
            session['last_activity'] = time.time()

        return {'status': 'ok'}

    @http.route(
        '/saas/terminal/output/<string:session_id>',
        type='http',
        auth='user',
        methods=['GET'],
        csrf=False,
    )
    def stream_output(self, session_id, **kwargs):
        """Stream terminal output as Server-Sent Events."""
        _logger.info(
            "stream_output called for session %s (pid %s)",
            session_id, os.getpid(),
        )
        session = self._get_session(session_id)
        channel = session['channel']

        def generate():
            import base64
            try:
                yield b'retry: 3000\n\n'

                start = time.time()
                last_heartbeat = time.time()

                while (time.time() - start) < STREAM_READ_TIMEOUT:
                    if channel.closed:
                        yield b'event: closed\ndata: session ended\n\n'
                        break

                    # Also check if the SSH transport is still alive
                    ssh_conn = session.get('ssh_conn')
                    if ssh_conn and ssh_conn._client:
                        transport = ssh_conn._client.get_transport()
                        if not transport or not transport.is_active():
                            _logger.warning(
                                "SSH transport died for session %s",
                                session_id,
                            )
                            yield b'event: closed\ndata: connection lost\n\n'
                            break

                    ready, _, _ = select.select([channel], [], [], 0.5)
                    if ready:
                        try:
                            data = channel.recv(16384)
                        except Exception:
                            yield b'event: closed\ndata: connection lost\n\n'
                            break
                        if not data:
                            yield b'event: closed\ndata: session ended\n\n'
                            break

                        # Base64-encode binary terminal data for safe SSE transport
                        encoded = base64.b64encode(data).decode('ascii')
                        yield ('data: %s\n\n' % json.dumps(encoded)).encode('utf-8')
                        session['last_activity'] = time.time()
                        last_heartbeat = time.time()
                    else:
                        # Send SSE comment as heartbeat to keep connection alive
                        # through proxies (Nginx, load balancers, etc.)
                        now = time.time()
                        if now - last_heartbeat >= SSE_HEARTBEAT_INTERVAL:
                            yield b': heartbeat\n\n'
                            last_heartbeat = now

                else:
                    yield b'event: timeout\ndata: stream timeout\n\n'

            except GeneratorExit:
                _logger.info("Client closed SSE connection for session %s", session_id)
            except Exception as e:
                _logger.exception("Terminal stream error for session %s", session_id)
                try:
                    yield (
                        'event: error\ndata: %s\n\n' % json.dumps(str(e))
                    ).encode('utf-8')
                except Exception:
                    pass

        return Response(
            generate(),
            content_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive',
            },
            direct_passthrough=True,
        )

    @http.route(
        '/saas/terminal/close',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def close_session(self, session_id, **kwargs):
        """Close a terminal session."""
        # Verify ownership
        self._get_session(session_id)
        _cleanup_session(session_id)
        _logger.info("Terminal session %s closed by user", session_id)
        return {'status': 'closed'}

    def _get_session(self, session_id):
        """Get session dict, verifying the current user owns it."""
        with _sessions_lock:
            session = _terminal_sessions.get(session_id)
        if not session:
            _logger.warning(
                "Terminal session %s not found on pid %s "
                "(have %d sessions: %s). "
                "If using --workers > 0, terminal requires --workers=0.",
                session_id, os.getpid(),
                len(_terminal_sessions),
                list(_terminal_sessions.keys())[:5],
            )
            raise NotFound(
                "Terminal session not found or expired. "
                "If Odoo uses multiple workers (--workers > 0), "
                "terminal requires single-process mode (--workers=0)."
            )
        if session['uid'] != request.env.uid:
            raise Forbidden("Access denied to this terminal session")
        return session
