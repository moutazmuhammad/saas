import json
import logging
import select
import threading
import time
import uuid

from werkzeug.exceptions import Forbidden, NotFound

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# In-memory store: session_id -> dict with channel, ssh_conn, metadata
_terminal_sessions = {}
_sessions_lock = threading.Lock()

SESSION_TIMEOUT = 600  # 10 minutes idle timeout
STREAM_READ_TIMEOUT = 300  # 5 minutes max stream


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
            server_model: 'saas.container.physical.server' or 'saas.psql.physical.server'
            server_id: ID of the server record
        Returns:
            dict with session_id
        """
        allowed_models = (
            'saas.container.physical.server',
            'saas.psql.physical.server',
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
            channel = transport.open_session()
            channel.get_pty(
                term='xterm-256color',
                width=120,
                height=40,
            )
            channel.invoke_shell()
        except Exception:
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
            }

        _logger.info(
            "Terminal session %s created for server %s by uid %s",
            session_id, server.name, request.env.uid,
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
    )
    def stream_output(self, session_id, **kwargs):
        """Stream terminal output as Server-Sent Events."""
        session = self._get_session(session_id)
        channel = session['channel']
        uid = request.env.uid

        def generate():
            try:
                yield b'retry: 100\n\n'

                start = time.time()
                while (time.time() - start) < STREAM_READ_TIMEOUT:
                    if channel.closed:
                        yield b'event: closed\ndata: session ended\n\n'
                        break

                    ready, _, _ = select.select([channel], [], [], 0.1)
                    if ready:
                        try:
                            data = channel.recv(4096)
                        except Exception:
                            yield b'event: closed\ndata: connection lost\n\n'
                            break
                        if not data:
                            yield b'event: closed\ndata: session ended\n\n'
                            break

                        # Base64-encode binary terminal data for safe SSE transport
                        import base64
                        encoded = base64.b64encode(data).decode('ascii')
                        yield ('data: %s\n\n' % json.dumps(encoded)).encode('utf-8')
                        session['last_activity'] = time.time()

                else:
                    yield b'event: timeout\ndata: stream timeout\n\n'

            except GeneratorExit:
                pass
            except Exception as e:
                _logger.exception("Terminal stream error for session %s", session_id)
                yield (
                    'event: error\ndata: %s\n\n' % json.dumps(str(e))
                ).encode('utf-8')

        return Response(
            generate(),
            content_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
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
            raise NotFound("Terminal session not found or expired")
        if session['uid'] != request.env.uid:
            raise Forbidden("Access denied to this terminal session")
        return session
