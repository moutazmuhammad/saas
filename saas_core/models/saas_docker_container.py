import shlex

from odoo import fields, models, _
from odoo.exceptions import UserError


class SaasDockerContainer(models.Model):
    _name = 'saas.docker.container'
    _description = 'Docker Container'
    _order = 'name'

    server_id = fields.Many2one(
        'saas.server',
        string='Docker Server',
        required=True,
        ondelete='cascade',
        help='The Docker host server where this container is running.',
    )
    container_id = fields.Char(
        string='Container ID',
        readonly=True,
        help='Short 12-character Docker container identifier.',
    )
    name = fields.Char(
        string='Container Name',
        readonly=True,
        help='Docker container name assigned at creation.',
    )
    image = fields.Char(
        string='Image',
        readonly=True,
        help='Docker image and tag this container was started from.',
    )
    command = fields.Char(
        string='Command',
        readonly=True,
        help='Entrypoint command running inside the container.',
    )
    created = fields.Char(
        string='Created',
        readonly=True,
        help='Date and time when the container was created.',
    )
    status = fields.Char(
        string='Status',
        readonly=True,
        help='Current container status reported by Docker (e.g. "Up 3 hours", "Exited (0)").',
    )
    ports = fields.Char(
        string='Ports',
        readonly=True,
        help='Port mappings between the host and the container.',
    )

    def action_stop_container(self):
        """Stop this Docker container via SSH."""
        self.ensure_one()
        server = self.server_id
        with server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(
                'docker stop %s' % shlex.quote(self.name),
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to stop container '%s':\n%s") % (self.name, stderr)
                )
        return server.action_refresh_containers()

    def action_restart_container(self):
        """Restart this Docker container via SSH."""
        self.ensure_one()
        server = self.server_id
        with server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(
                'docker restart %s' % shlex.quote(self.name),
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to restart container '%s':\n%s") % (self.name, stderr)
                )
        return server.action_refresh_containers()

    def action_view_logs(self):
        """Open a live log stream for this container."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'container_logs_stream',
            'name': _("Logs: %s") % self.name,
            'context': {
                'stream_url': '/saas/container/%d/logs/stream' % self.id,
                'container_name': self.name,
                'tail': 100,
            },
        }
