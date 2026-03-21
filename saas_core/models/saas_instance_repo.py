import logging
import shlex

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..utils import run_in_background

_logger = logging.getLogger(__name__)


class SaasInstanceRepo(models.Model):
    _name = 'saas.instance.repo'
    _description = 'Custom Module Repository'
    _order = 'sequence, id'
    _sql_constraints = [
        ('unique_repo_per_instance',
         'UNIQUE(instance_id, repo_url)',
         'This repository is already added to this instance.'),
    ]

    instance_id = fields.Many2one(
        'saas.instance',
        string='Instance',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
        help='Repository name derived from the URL.',
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
        help='Personal access token for private repositories. '
             'Leave empty for public repos.',
        copy=False,
        groups='base.group_system',
    )
    addons_subdir = fields.Char(
        string='Addons Subdirectory',
        help='Subdirectory inside the repo that contains addons. '
             'Leave empty if addons are at the root of the repo.',
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
    last_pull = fields.Datetime(string='Last Pull', readonly=True)
    error_message = fields.Text(string='Error', readonly=True)

    @api.depends('repo_url')
    def _compute_name(self):
        for rec in self:
            if rec.repo_url:
                # Extract repo name from URL
                url = rec.repo_url.rstrip('/')
                if url.endswith('.git'):
                    url = url[:-4]
                rec.name = url.split('/')[-1] if '/' in url else url
            else:
                rec.name = ''

    def _get_repo_dir_name(self):
        """Return a safe directory name for this repo."""
        self.ensure_one()
        return self.name or 'repo_%d' % self.id

    def _get_clone_url(self):
        """Return the clone URL, injecting token if needed for private repos."""
        self.ensure_one()
        url = self.repo_url
        token = self.sudo().github_token
        if token and url.startswith('https://'):
            url = 'https://x-access-token:%s@%s' % (
                token, url[len('https://'):]
            )
        return url

    def _get_remote_repo_path(self):
        """Return the full remote path: custom_repos/{odoo_version}/{subdomain}/{repo}."""
        self.ensure_one()
        instance = self.instance_id
        server = instance.docker_server_id
        base = server.docker_base_path.rstrip('/')
        version_name = instance.odoo_version_id.name
        return '%s/custom_repos/%s/%s/%s' % (
            base, version_name, instance.subdomain, self._get_repo_dir_name(),
        )

    def _get_container_addons_path(self):
        """Return the addons path inside the container for this repo."""
        self.ensure_one()
        base = '/mnt/repos/%s' % self._get_repo_dir_name()
        if self.addons_subdir:
            return '%s/%s' % (base, self.addons_subdir.strip('/'))
        return base

    def _clone_repo(self):
        """Clone the repository on the remote server (no config update or restart)."""
        for rec in self:
            instance = rec.instance_id
            instance._ensure_can_ssh()
            server = instance.docker_server_id
            repo_path = rec._get_remote_repo_path()
            clone_url = rec._get_clone_url()

            try:
                with server._get_ssh_connection() as ssh:
                    # Create parent directory
                    parent = '/'.join(repo_path.rsplit('/', 1)[:-1])
                    ssh.execute('mkdir -p %s' % shlex.quote(parent))

                    # Remove existing repo dir if re-cloning
                    ssh.execute('rm -rf %s' % shlex.quote(repo_path))

                    # Clone
                    instance._append_log(
                        "Cloning repo %s (branch: %s)..." % (rec.repo_url, rec.branch)
                    )
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

                    # Set permissions
                    ssh.execute(
                        'chmod -R 755 %s' % shlex.quote(repo_path)
                    )

                    instance._append_log("Repository cloned successfully.")
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

    def action_clone_repo(self):
        """Clone the repository, update config, and restart the instance (async)."""
        for rec in self:
            rec.instance_id._ensure_can_ssh()
            run_in_background(
                rec, '_do_clone_and_restart',
                error_method='_on_repo_background_error',
                thread_name='saas_inst_clone_%s' % rec.id,
            )

    def _do_clone_and_restart(self):
        """Clone repo and restart instance (runs in background thread)."""
        self._clone_repo()
        self.instance_id._update_repo_config_and_restart()

    def _on_repo_background_error(self, exception):
        """Handle background repo operation failure."""
        self.state = 'error'
        self.error_message = str(exception)

    def action_pull_repo(self):
        """Git pull the repo (async, no restart)."""
        for rec in self:
            if rec.state != 'cloned':
                raise UserError(_("Repository must be cloned first."))
            run_in_background(
                rec, '_do_pull_repo',
                error_method='_on_repo_background_error',
                thread_name='saas_inst_pull_%s' % rec.id,
            )

    def _do_pull_repo(self):
        """Pull repo (runs in background thread)."""
        self.ensure_one()
        instance = self.instance_id
        instance._ensure_can_ssh()
        server = instance.docker_server_id
        repo_path = self._get_remote_repo_path()
        clone_url = self._get_clone_url()

        try:
            with server._get_ssh_connection() as ssh:
                ssh.execute(
                    'cd %s && git remote set-url origin %s'
                    % (shlex.quote(repo_path), shlex.quote(clone_url))
                )

                instance._append_log(
                    "Pulling latest changes for %s..." % self.name
                )
                pull_cmd = 'cd %s && git pull origin %s 2>&1' % (
                    shlex.quote(repo_path), shlex.quote(self.branch),
                )
                exit_code, stdout, stderr = ssh.execute(pull_cmd, timeout=300)
                if exit_code != 0:
                    self.error_message = stdout + '\n' + stderr
                    raise UserError(
                        _("Git pull failed:\n%s\n%s")
                        % (stdout[-500:], stderr[-500:])
                    )

                instance._append_log("Pull completed: %s" % stdout.strip()[:200])
                self.last_pull = fields.Datetime.now()
                self.error_message = False

        except UserError:
            raise
        except Exception as e:
            self.error_message = str(e)
            raise UserError(
                _("Failed to pull repository: %s") % str(e)
            )

    def action_remove_repo(self):
        """Remove the repo from the server, update config, and restart."""
        self.unlink()
        return True

    def unlink(self):
        """Delete repo files from server, remove records, and update running instances."""
        instances_to_restart = self.env['saas.instance']
        for rec in self:
            instance = rec.instance_id
            if instance.docker_server_id and rec.state == 'cloned':
                try:
                    instance._ensure_can_ssh()
                    server = instance.docker_server_id
                    repo_path = rec._get_remote_repo_path()
                    with server._get_ssh_connection() as ssh:
                        ssh.execute('rm -rf %s' % shlex.quote(repo_path))
                    instance._append_log("Removed repo directory %s" % repo_path)
                except Exception:
                    _logger.exception("Failed to remove repo dir for %s", rec.name)
            if instance.state == 'running':
                instances_to_restart |= instance

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
