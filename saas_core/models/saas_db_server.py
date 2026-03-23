from odoo import fields, models, _
from odoo.exceptions import UserError, ValidationError

from ..utils import SSHConnection


class SaasPsqlPhysicalServer(models.Model):
    _name = 'saas.psql.physical.server'
    _description = 'PostgreSQL Host Server'
    _inherit = ['mail.thread']
    _order = 'sequence, name'

    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Order in which database servers are displayed and selected as defaults.',
    )
    name = fields.Char(
        string='Name',
        required=True,
        tracking=True,
        help='Human-readable label for this database server (e.g. "EU DB Primary").',
    )
    ssh_key_pair_id = fields.Many2one(
        'saas.ssh.key.pair',
        string='SSH Key Pair',
        help='SSH key used to authenticate when connecting to this server.',
    )
    ssh_user = fields.Char(
        string='SSH User',
        default='root',
        help='Operating system user for the SSH connection (e.g. root, ubuntu).',
    )
    ssh_port = fields.Integer(
        string='SSH Port',
        default=22,
        help='TCP port on which the SSH daemon listens.',
    )
    ip_v4 = fields.Char(
        string='Public IPv4',
        help='Public IPv4 address of this server, reachable from the internet.',
    )
    private_ip_v4 = fields.Char(
        string='Private IPv4',
        help='Private / internal IPv4 address. Odoo containers use this address '
             'to connect to PostgreSQL when both servers are on the same network.',
    )
    ssh_connect_using = fields.Selection(
        selection=[
            ('public_ip', 'Public IP'),
            ('private_ip', 'Private IP'),
        ],
        string='Connect via',
        default='public_ip',
        required=True,
        help='Which IP address the SaaS manager should use when opening SSH sessions.',
    )
    psql_port = fields.Integer(
        string='PostgreSQL Port',
        default=5432,
        help='TCP port on which the PostgreSQL service listens.',
    )

    def _get_ssh_ip(self):
        """Return the IP to use for SSH based on ssh_connect_using."""
        self.ensure_one()
        if self.ssh_connect_using == 'private_ip':
            if not self.private_ip_v4:
                raise ValidationError(
                    _("Private IP address is required on server '%s' when SSH is set to use Private IP.")
                    % self.name
                )
            return self.private_ip_v4
        if not self.ip_v4:
            raise ValidationError(
                _("Public IP address is required on server '%s'.") % self.name
            )
        return self.ip_v4

    def _get_ssh_connection(self):
        """Return an SSHConnection context manager for this server."""
        self.ensure_one()
        if not self.ssh_key_pair_id or not self.ssh_key_pair_id.private_key_file:
            raise ValidationError(
                _("SSH key pair with a private key file is required on server '%s'.")
                % self.name
            )
        ssh_ip = self._get_ssh_ip()
        return SSHConnection(
            host=ssh_ip,
            port=self.ssh_port or 22,
            user=self.ssh_user or 'root',
            private_key_b64=self.ssh_key_pair_id.private_key_file,
            key_type=self.ssh_key_pair_id.type or 'rsa',
        )

    def action_open_terminal(self):
        """Open a web-based SSH terminal to this server."""
        self.ensure_one()
        # Validate SSH is configured before opening the terminal
        self._get_ssh_ip()
        if not self.ssh_key_pair_id or not self.ssh_key_pair_id.private_key_file:
            raise ValidationError(
                _("SSH key pair with a private key file is required on server '%s'.")
                % self.name
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'ssh_terminal',
            'name': _("Terminal: %s") % self.name,
            'context': {
                'server_model': self._name,
                'server_id': self.id,
                'server_name': self.name,
            },
        }

    def action_test_connection(self):
        """Test SSH connection to the server."""
        self.ensure_one()
        try:
            ssh_ip = self._get_ssh_ip()
            with self._get_ssh_connection() as ssh:
                exit_code, stdout, stderr = ssh.execute(
                    'echo "Connection OK" && hostname'
                )
            if exit_code == 0:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Connection Successful"),
                        'message': _(
                            "SSH connection to %s succeeded. Hostname: %s"
                        ) % (ssh_ip, stdout.strip()),
                        'type': 'success',
                        'sticky': False,
                    },
                }
            else:
                raise UserError(
                    _("Connection test command failed:\n%s") % stderr
                )
        except (UserError, ValidationError):
            raise
        except Exception as e:
            raise UserError(
                _("SSH connection failed:\n%s") % str(e)
            )
