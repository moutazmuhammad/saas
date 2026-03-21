import logging
import shlex

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaasVersionRepo(models.Model):
    _name = 'saas.version.repo'
    _description = 'Custom Module Repository per Odoo Version'
    _order = 'sequence, id'
    _sql_constraints = [
        ('unique_repo_per_version',
         'UNIQUE(version_id, repo_url)',
         'This repository is already added to this version.'),
    ]

    version_id = fields.Many2one(
        'saas.odoo.version',
        string='Odoo Version',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )
    repo_url = fields.Char(
        string='Repository URL',
        required=True,
        help='Git clone URL (HTTPS). e.g. https://github.com/user/repo.git',
    )
    branch = fields.Char(
        string='Branch',
        default='main',
        required=True,
    )
    github_token = fields.Char(
        string='GitHub Token',
        help='Personal access token for private repositories.',
        copy=False,
        groups='base.group_system',
    )
    addons_subdir = fields.Char(
        string='Addons Subdirectory',
        help='Subdirectory inside the repo containing addons. '
             'Leave empty if addons are at the root.',
    )
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('cloned', 'Cloned'),
            ('error', 'Error'),
        ],
        default='pending',
        string='Status',
        readonly=True,
    )
    product_id = fields.Many2one(
        'product.template',
        string='Product',
        readonly=True,
        ondelete='set null',
        help='Auto-created product representing this repo.',
    )
    last_pull = fields.Datetime(string='Last Pull', readonly=True)
    error_message = fields.Text(string='Error', readonly=True)

    @api.depends('repo_url')
    def _compute_name(self):
        for rec in self:
            if rec.repo_url:
                url = rec.repo_url.rstrip('/')
                if url.endswith('.git'):
                    url = url[:-4]
                rec.name = url.split('/')[-1] if '/' in url else url
            else:
                rec.name = ''

    def _get_repo_dir_name(self):
        self.ensure_one()
        return self.name or 'repo_%d' % self.id

    def _get_clone_url(self):
        self.ensure_one()
        url = self.repo_url
        token = self.sudo().github_token
        if token and url.startswith('https://'):
            url = 'https://x-access-token:%s@%s' % (
                token, url[len('https://'):]
            )
        return url

    def _get_remote_repo_path(self, server):
        """Return the path: product_repos/{odoo_version}/{repo}."""
        self.ensure_one()
        base = server.docker_base_path.rstrip('/')
        version_name = self.version_id.name
        return '%s/product_repos/%s/%s' % (base, version_name, self._get_repo_dir_name())

    def _get_container_addons_path(self):
        """Return the addons path inside a container for this repo."""
        self.ensure_one()
        base = '/mnt/version-repos/%s' % self._get_repo_dir_name()
        if self.addons_subdir:
            return '%s/%s' % (base, self.addons_subdir.strip('/'))
        return base

    def action_clone_repo(self):
        """Clone the repository on the Docker server."""
        for rec in self:
            version = rec.version_id
            server = version._get_container_server()
            repo_path = rec._get_remote_repo_path(server)
            clone_url = rec._get_clone_url()

            try:
                with server._get_ssh_connection() as ssh:
                    # Create parent dir
                    parent = '/'.join(repo_path.rsplit('/', 1)[:-1])
                    ssh.execute('mkdir -p %s' % shlex.quote(parent))

                    # Remove existing if re-cloning
                    ssh.execute('rm -rf %s' % shlex.quote(repo_path))

                    clone_cmd = (
                        'git clone --branch %s --single-branch '
                        '--depth 1 %s %s 2>&1'
                    ) % (
                        shlex.quote(rec.branch),
                        shlex.quote(clone_url),
                        shlex.quote(repo_path),
                    )
                    exit_code, stdout, stderr = ssh.execute(clone_cmd, timeout=300)
                    if exit_code != 0:
                        rec.state = 'error'
                        rec.error_message = stdout + '\n' + stderr
                        raise UserError(
                            _("Failed to clone repository:\n%s\n%s")
                            % (stdout[-500:], stderr[-500:])
                        )

                    ssh.execute('chmod -R 755 %s' % shlex.quote(repo_path))

                    rec.state = 'cloned'
                    rec.last_pull = fields.Datetime.now()
                    rec.error_message = False

            except UserError:
                raise
            except Exception as e:
                rec.state = 'error'
                rec.error_message = str(e)
                raise UserError(
                    _("Failed to clone repository: %s") % str(e)
                )

    def action_pull_repo(self):
        """Git pull the repo."""
        for rec in self:
            if rec.state != 'cloned':
                raise UserError(_("Repository must be cloned first."))

            version = rec.version_id
            server = version._get_container_server()
            repo_path = rec._get_remote_repo_path(server)
            clone_url = rec._get_clone_url()

            try:
                with server._get_ssh_connection() as ssh:
                    ssh.execute(
                        'cd %s && git remote set-url origin %s'
                        % (shlex.quote(repo_path), shlex.quote(clone_url))
                    )
                    pull_cmd = 'cd %s && git pull origin %s 2>&1' % (
                        shlex.quote(repo_path), shlex.quote(rec.branch),
                    )
                    exit_code, stdout, stderr = ssh.execute(pull_cmd, timeout=300)
                    if exit_code != 0:
                        rec.error_message = stdout + '\n' + stderr
                        raise UserError(
                            _("Git pull failed:\n%s\n%s")
                            % (stdout[-500:], stderr[-500:])
                        )

                    rec.last_pull = fields.Datetime.now()
                    rec.error_message = False

            except UserError:
                raise
            except Exception as e:
                rec.error_message = str(e)
                raise UserError(
                    _("Failed to pull repository: %s") % str(e)
                )

    def action_remove_repo(self):
        """Remove the repo from the server, clean up product and modules, delete the record."""
        self.unlink()
        return True

    def unlink(self):
        """Delete repo files from server, clean up products, and update running instances."""
        # Clean up associated custom modules and products
        for rec in self:
            custom_modules = self.env['product.template'].search([
                ('saas_source_repo_id', '=', rec.id),
                ('saas_type', '=', 'module'),
            ])
            if custom_modules:
                custom_modules.with_context(skip_repo_cleanup=True).unlink()
            if rec.product_id:
                rec.product_id.with_context(skip_repo_cleanup=True).unlink()

        # Collect running instances that mount these repos, to update after deletion
        instances_to_restart = self.env['saas.instance']
        for rec in self:
            if rec.state == 'cloned':
                try:
                    server = rec.version_id._get_container_server()
                    repo_path = rec._get_remote_repo_path(server)
                    with server._get_ssh_connection() as ssh:
                        ssh.execute('rm -rf %s' % shlex.quote(repo_path))
                except Exception:
                    _logger.exception("Failed to remove repo dir for %s", rec.name)

                # Find running instances using this version repo
                affected = self.env['saas.instance'].search([
                    ('odoo_version_id', '=', rec.version_id.id),
                    ('state', '=', 'running'),
                ])
                for inst in affected:
                    for line in inst.module_line_ids:
                        tmpl = None
                        if line.product_id:
                            tmpl = line.product_id.product_tmpl_id
                        elif line.module_id:
                            tmpl = line.module_id.product_tmpl_id
                        if tmpl and tmpl.saas_source_repo_id.id == rec.id:
                            instances_to_restart |= inst
                            break

        res = super().unlink()

        for instance in instances_to_restart:
            try:
                instance._update_repo_config_and_restart()
            except Exception:
                _logger.exception(
                    "Failed to update config after repo removal for instance %s",
                    instance.name,
                )
        return res
