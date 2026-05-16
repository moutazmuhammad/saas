import base64
import hashlib
import io
import logging
import os
import threading

import paramiko

_logger = logging.getLogger(__name__)


def _host_key_sha256(key):
    """Return the SSH host key fingerprint as `SHA256:<base64>` (no padding).

    Matches the format printed by `ssh-keygen -l -f` and shown by OpenSSH
    on first connect.
    """
    digest = hashlib.sha256(key.asbytes()).digest()
    b64 = base64.b64encode(digest).decode('ascii').rstrip('=')
    return 'SHA256:' + b64


class _PinnedHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Refuse the connection unless the host key matches the pinned fingerprint.

    Replaces paramiko's default `AutoAddPolicy()` which silently trusts
    any host on first connect (every SSH call was MITM-able).
    """

    def __init__(self, expected_fingerprint):
        self.expected = expected_fingerprint.strip()
        if not self.expected.startswith('SHA256:'):
            self.expected = 'SHA256:' + self.expected.lstrip(':')

    def missing_host_key(self, client, hostname, key):
        actual = _host_key_sha256(key)
        if actual != self.expected:
            raise paramiko.SSHException(
                "Host key fingerprint mismatch for %s: expected %s, got %s"
                % (hostname, self.expected, actual)
            )


def run_in_background(record, method_name, method_args=(),
                      error_method=None, error_args=(),
                      thread_name=None):
    """Run record.method_name(*args) in a background thread with its own cursor.

    On success the cursor is committed.  On failure it is rolled back and,
    if *error_method* is given, ``record.error_method(exception, *error_args)``
    is called inside a fresh cursor that is then committed.

    Commits the current transaction first so the background thread sees the
    latest DB state, then starts the thread immediately.
    """
    from odoo import SUPERUSER_ID
    dbname = record.env.cr.dbname
    uid = SUPERUSER_ID
    context = dict(record.env.context)
    model_name = record._name
    record_id = record.id

    def _target():
        import odoo
        from odoo import api as odoo_api
        try:
            db_registry = odoo.modules.registry.Registry(dbname)
            with db_registry.cursor() as new_cr:
                new_env = odoo_api.Environment(new_cr, uid, context)
                rec = new_env[model_name].browse(record_id)
                try:
                    getattr(rec, method_name)(*method_args)
                    new_cr.commit()
                except Exception as e:
                    new_cr.rollback()
                    if error_method:
                        try:
                            with db_registry.cursor() as err_cr:
                                err_env = odoo_api.Environment(err_cr, uid, context)
                                err_rec = err_env[model_name].browse(record_id)
                                getattr(err_rec, error_method)(e, *error_args)
                                err_cr.commit()
                        except Exception:
                            _logger.exception(
                                "Error handler failed for %s#%s",
                                model_name, record_id,
                            )
                    _logger.exception(
                        "Background %s failed for %s#%s",
                        method_name, model_name, record_id,
                    )
        except Exception:
            _logger.exception(
                "Background thread crashed before executing %s for %s#%s",
                method_name, model_name, record_id,
            )

    name = thread_name or 'saas_bg_%s_%s' % (method_name, record_id)

    # Commit current transaction so the thread sees the latest state,
    # then start the thread immediately (no postcommit dependency).
    record.env.cr.commit()
    _logger.info(
        "Starting background thread '%s' for %s#%s",
        name, model_name, record_id,
    )
    t = threading.Thread(target=_target, name=name, daemon=True)
    t.start()

SSH_COMMAND_TIMEOUT = 120  # seconds
SSH_CONNECT_TIMEOUT = 30  # seconds


class SSHConnection:
    """Context manager for SSH connections using paramiko.

    Usage::

        with SSHConnection(host, port, user, private_key_b64, key_type) as ssh:
            exit_code, stdout, stderr = ssh.execute('ls -la')
            ssh.write_file('/remote/path/file.txt', 'file contents')
    """

    def __init__(self, host, port, user, private_key_b64, key_type='rsa',
                 timeout=SSH_COMMAND_TIMEOUT, expected_host_key=None):
        self.host = host
        self.port = port
        self.user = user
        self.private_key_b64 = private_key_b64
        self.key_type = key_type
        self.timeout = timeout
        self.expected_host_key = expected_host_key
        self._client = None

    def __enter__(self):
        self._connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._disconnect()
        return False

    def _connect(self):
        """Connect via paramiko, loading the key in-memory (no tempfile).

        Host-key policy:
        - If `expected_host_key` is set, only that fingerprint is accepted
          (MITM protection).
        - Otherwise the connection is allowed but a WARNING is logged so
          operators can spot infrastructure that hasn't been pinned yet.
          (Replaces paramiko's silent AutoAddPolicy.)
        """
        key_bytes = base64.b64decode(self.private_key_b64)
        pkey = self._load_private_key_bytes(key_bytes)

        self._client = paramiko.SSHClient()
        if self.expected_host_key:
            self._client.set_missing_host_key_policy(
                _PinnedHostKeyPolicy(self.expected_host_key)
            )
        else:
            _logger.warning(
                "SSH host key not pinned for %s (set expected_host_key_fingerprint "
                "on the saas.server record to enable MITM protection).",
                self.host,
            )
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            hostname=self.host,
            port=self.port,
            username=self.user,
            pkey=pkey,
            timeout=SSH_CONNECT_TIMEOUT,
            look_for_keys=False,
            allow_agent=False,
        )

    def _load_private_key_bytes(self, key_bytes):
        """Parse a private key from raw bytes (never touches the filesystem)."""
        key_classes = [
            ('rsa', paramiko.RSAKey),
            ('ed25519', paramiko.Ed25519Key),
            ('ecdsa', paramiko.ECDSAKey),
        ]
        if hasattr(paramiko, 'DSSKey'):
            key_classes.append(('dsa', paramiko.DSSKey))

        ordered = sorted(key_classes, key=lambda kv: kv[0] != self.key_type)

        errors = []
        for name, cls in ordered:
            try:
                return cls.from_private_key(io.StringIO(key_bytes.decode('utf-8')))
            except Exception as exc:
                errors.append((name, exc))

        error_details = '; '.join('%s: %s' % (n, e) for n, e in errors)
        raise paramiko.SSHException(
            "Unable to load private key (tried %s). Details: %s"
            % (', '.join(n for n, _ in errors), error_details)
        )

    def _disconnect(self):
        """Close SSH client."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def execute(self, command, timeout=None):
        """Execute a command over SSH.

        Returns:
            tuple: (exit_code, stdout_str, stderr_str)
        """
        _logger.debug("SSH [%s@%s:%s] executing command", self.user, self.host, self.port)
        stdin, stdout, stderr = self._client.exec_command(
            command, timeout=timeout or self.timeout,
        )
        # Read output BEFORE recv_exit_status to avoid deadlock when the
        # remote command produces large output that fills the SSH buffer.
        stdout_str = stdout.read().decode('utf-8', errors='replace')
        stderr_str = stderr.read().decode('utf-8', errors='replace')
        exit_code = stdout.channel.recv_exit_status()
        return exit_code, stdout_str, stderr_str

    def write_file(self, remote_path, content):
        """Write string content to a remote file via SFTP."""
        sftp = self._client.open_sftp()
        try:
            with sftp.file(remote_path, 'w') as f:
                f.write(content)
        finally:
            sftp.close()

    def read_file_bytes(self, remote_path):
        """Read a remote file and return its contents as bytes via SFTP."""
        sftp = self._client.open_sftp()
        try:
            with sftp.file(remote_path, 'rb') as f:
                return f.read()
        finally:
            sftp.close()
