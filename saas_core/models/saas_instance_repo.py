import hashlib
import hmac
import json
import logging
import secrets
import shlex
from urllib.parse import urlparse, urlunparse

import requests as http_requests

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

    # Webhook auto-deploy
    webhook_enabled = fields.Boolean(
        string='Auto-Deploy',
        default=True,
        help='Automatically pull and restart when code is pushed to the tracked branch.',
    )
    webhook_secret = fields.Char(
        string='Webhook Secret',
        copy=False,
        readonly=True,
        help='Secret token used to validate incoming webhook requests.',
    )
    webhook_url = fields.Char(
        string='Webhook URL',
        compute='_compute_webhook_url',
        help='Webhook endpoint registered on the Git provider.',
    )
    webhook_provider_id = fields.Char(
        string='Provider Webhook ID',
        readonly=True,
        copy=False,
        help='ID of the webhook on the Git provider (for cleanup on disable).',
    )
    webhook_last_event = fields.Datetime(
        string='Last Webhook Event',
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('webhook_secret'):
                vals['webhook_secret'] = secrets.token_hex(20)
            if 'webhook_enabled' not in vals:
                vals['webhook_enabled'] = True
        return super().create(vals_list)

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

    @staticmethod
    def _strip_userinfo(url):
        """Remove any user:pass@ credentials from an HTTPS URL."""
        if not url or not url.startswith('https://'):
            return url
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            # Rebuild without userinfo
            parsed = parsed._replace(netloc=parsed.hostname + (
                ':%s' % parsed.port if parsed.port else ''))
            return urlunparse(parsed)
        return url

    def _get_clone_url(self):
        """Return the clone URL, injecting token if needed for private repos."""
        self.ensure_one()
        url = self._strip_userinfo(self.repo_url)
        token = self.sudo().github_token
        if token and url.startswith('https://'):
            url = 'https://x-access-token:%s@%s' % (
                token, url[len('https://'):]
            )
        return url

    @api.onchange('repo_url')
    def _onchange_repo_url(self):
        if self.repo_url:
            self.repo_url = self._strip_userinfo(self.repo_url.strip())

    @api.depends('webhook_secret')
    def _compute_webhook_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            if rec.webhook_secret and rec.id:
                rec.webhook_url = '%s/saas/webhook/%s' % (base_url, rec.webhook_secret)
            else:
                rec.webhook_url = False

    def _get_public_base_url(self):
        """Return web.base.url only if it's a valid public URL, else False."""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        if not base_url:
            return False
        lower = base_url.lower()
        if 'localhost' in lower or '127.0.0.1' in lower or '0.0.0.0' in lower:
            return False
        if not lower.startswith('https://'):
            return False
        return base_url.rstrip('/')

    def _register_webhook_with_retry(self, max_retries=3):
        """Register webhook on Git provider with retries, then verify it's there."""
        self.ensure_one()
        import time

        base_url = self._get_public_base_url()
        if not base_url:
            _logger.warning(
                "Webhook: web.base.url is not a public HTTPS URL. "
                "Cannot register webhook for %s. "
                "Set web.base.url to your public domain.", self.name,
            )
            self.instance_id._append_log(
                "Auto-deploy webhook NOT registered: web.base.url is not a public HTTPS URL."
            )
            return False

        # If already registered, verify it still exists; skip if valid
        if self.webhook_provider_id:
            try:
                if self._verify_webhook_on_provider():
                    _logger.info("Webhook already registered and valid for %s", self.name)
                    return True
            except Exception:
                pass
            # Old hook is gone, clear and re-register
            self.webhook_provider_id = False

        # Retry registration
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                self._register_webhook_on_provider()
                break
            except Exception as e:
                last_error = e
                _logger.warning(
                    "Webhook register attempt %d/%d failed for %s: %s",
                    attempt, max_retries, self.name, e,
                )
                if attempt < max_retries:
                    time.sleep(2 * attempt)
        else:
            self.instance_id._append_log(
                "Auto-deploy webhook registration failed after %d attempts: %s"
                % (max_retries, last_error)
            )
            return False

        # Verify it's actually registered
        try:
            registered = self._verify_webhook_on_provider()
            if registered:
                self.instance_id._append_log(
                    "Auto-deploy webhook registered and verified for %s" % self.name
                )
                return True
            else:
                self.instance_id._append_log(
                    "Webhook sent to %s but could not be verified. "
                    "Check the repo webhook settings manually." % self._detect_provider()
                )
                return False
        except Exception as e:
            _logger.warning("Webhook verification failed for %s: %s", self.name, e)
            self.instance_id._append_log(
                "Auto-deploy webhook registered for %s (verification skipped: %s)"
                % (self.name, e)
            )
            return True

    def _verify_webhook_on_provider(self):
        """Check if our webhook URL exists on the Git provider. Returns True/False."""
        self.ensure_one()
        token = self.sudo().github_token
        if not token or not self.webhook_provider_id:
            return False

        provider = self._detect_provider()
        owner, repo_name = self._parse_owner_repo()
        if not provider or not owner or not repo_name:
            return False

        base = self._get_provider_base_url()
        hook_id = self.webhook_provider_id

        try:
            if provider == 'github':
                resp = http_requests.get(
                    '%s/repos/%s/%s/hooks/%s' % (base, owner, repo_name, hook_id),
                    headers={
                        'Authorization': 'token %s' % token,
                        'Accept': 'application/vnd.github+json',
                    },
                    timeout=15,
                )
                return resp.status_code == 200

            elif provider == 'gitlab':
                from urllib.parse import quote as url_quote
                project_path = '%s/%s' % (owner, repo_name)
                resp = http_requests.get(
                    '%s/projects/%s/hooks/%s' % (
                        base, url_quote(project_path, safe=''), hook_id,
                    ),
                    headers={'PRIVATE-TOKEN': token},
                    timeout=15,
                )
                return resp.status_code == 200

            elif provider == 'gitea':
                parsed = urlparse(self.repo_url)
                gitea_base = '%s://%s/api/v1' % (parsed.scheme or 'https', parsed.hostname)
                resp = http_requests.get(
                    '%s/repos/%s/%s/hooks/%s' % (gitea_base, owner, repo_name, hook_id),
                    headers={'Authorization': 'token %s' % token},
                    timeout=15,
                )
                return resp.status_code == 200

            elif provider == 'bitbucket':
                resp = http_requests.get(
                    '%s/repositories/%s/%s/hooks/%s' % (base, owner, repo_name, hook_id),
                    auth=(owner, token),
                    timeout=15,
                )
                return resp.status_code == 200

        except http_requests.RequestException:
            return False

        return False

    def action_enable_webhook(self):
        """Enable auto-deploy: generate secret and register webhook on Git provider."""
        for rec in self:
            base_url = rec._get_public_base_url()
            if not base_url:
                raise UserError(_(
                    "Cannot register webhook: web.base.url is '%s'.\n\n"
                    "Set it to your public HTTPS domain in:\n"
                    "Settings → Technical → System Parameters → web.base.url\n\n"
                    "Example: https://main.saas.odex.sa"
                ) % rec.env['ir.config_parameter'].sudo().get_param('web.base.url', ''))

            if not rec.webhook_secret:
                rec.webhook_secret = secrets.token_hex(20)
            rec.webhook_enabled = True
            rec._register_webhook_on_provider()

    def action_disable_webhook(self):
        """Disable auto-deploy and remove webhook from Git provider."""
        for rec in self:
            try:
                rec._unregister_webhook_from_provider()
            except Exception as e:
                _logger.warning("Auto-unregister webhook failed for %s: %s", rec.name, e)
            rec.webhook_enabled = False
            rec.webhook_provider_id = False

    def action_regenerate_webhook_secret(self):
        """Regenerate the webhook secret and re-register on provider."""
        for rec in self:
            # Remove old webhook
            try:
                rec._unregister_webhook_from_provider()
            except Exception:
                pass
            rec.webhook_secret = secrets.token_hex(20)
            if rec.webhook_enabled:
                try:
                    rec._register_webhook_on_provider()
                except Exception as e:
                    _logger.warning("Re-register webhook failed for %s: %s", rec.name, e)

    # ------------------------------------------------------------------
    # Git provider detection & API
    # ------------------------------------------------------------------

    def _detect_provider(self):
        """Detect the Git provider from the repo URL.
        Returns: 'github', 'gitlab', 'bitbucket', 'gitea', or False.
        """
        self.ensure_one()
        if not self.repo_url:
            return False
        url = self.repo_url.lower()
        if 'github.com' in url:
            return 'github'
        if 'gitlab.com' in url or 'gitlab' in url:
            return 'gitlab'
        if 'bitbucket.org' in url:
            return 'bitbucket'
        # Gitea / self-hosted: try Gitea API if token is present
        if self.sudo().github_token:
            return 'gitea'
        return False

    def _parse_owner_repo(self):
        """Extract owner/repo from the URL. Returns (owner, repo) or (False, False)."""
        self.ensure_one()
        url = self.repo_url.strip().rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]
        # Handle git@host:owner/repo
        if url.startswith('git@'):
            _, path = url.split(':', 1)
            parts = path.strip('/').split('/')
        else:
            parsed = urlparse(url)
            parts = parsed.path.strip('/').split('/')
        if len(parts) >= 2:
            return parts[-2], parts[-1]
        return False, False

    def _get_provider_base_url(self):
        """Get the API base URL for the provider."""
        self.ensure_one()
        url = self.repo_url.lower()
        if 'github.com' in url:
            return 'https://api.github.com'
        if 'gitlab.com' in url:
            return 'https://gitlab.com/api/v4'
        if 'bitbucket.org' in url:
            return 'https://api.bitbucket.org/2.0'
        # Self-hosted: extract base from repo URL
        parsed = urlparse(self.repo_url)
        return '%s://%s' % (parsed.scheme or 'https', parsed.hostname)

    def _register_webhook_on_provider(self):
        """Automatically register the webhook on the Git provider via API."""
        self.ensure_one()
        token = self.sudo().github_token
        if not token:
            _logger.info("No token for %s, skipping auto-register", self.name)
            return
        provider = self._detect_provider()
        if not provider:
            _logger.info("Unknown provider for %s, skipping auto-register", self.name)
            return

        webhook_url = self.webhook_url
        if not webhook_url:
            return

        owner, repo = self._parse_owner_repo()
        if not owner or not repo:
            return

        base = self._get_provider_base_url()
        headers = {}
        hook_id = False

        try:
            if provider == 'github':
                headers = {
                    'Authorization': 'token %s' % token,
                    'Accept': 'application/vnd.github+json',
                }
                resp = http_requests.post(
                    '%s/repos/%s/%s/hooks' % (base, owner, repo),
                    headers=headers,
                    json={
                        'name': 'web',
                        'active': True,
                        'events': ['push'],
                        'config': {
                            'url': webhook_url,
                            'content_type': 'json',
                            'secret': self.webhook_secret,
                            'insecure_ssl': '0',
                        },
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                hook_id = str(resp.json().get('id', ''))

            elif provider == 'gitlab':
                headers = {'PRIVATE-TOKEN': token}
                project_path = '%s/%s' % (owner, repo)
                from urllib.parse import quote as url_quote
                resp = http_requests.post(
                    '%s/projects/%s/hooks' % (base, url_quote(project_path, safe='')),
                    headers=headers,
                    json={
                        'url': webhook_url,
                        'push_events': True,
                        'token': self.webhook_secret,
                        'enable_ssl_verification': True,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                hook_id = str(resp.json().get('id', ''))

            elif provider == 'bitbucket':
                resp = http_requests.post(
                    '%s/repositories/%s/%s/hooks' % (base, owner, repo),
                    auth=(owner, token),
                    json={
                        'description': 'SaaS Auto-Deploy',
                        'url': webhook_url,
                        'active': True,
                        'events': ['repo:push'],
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                hook_id = str(resp.json().get('uuid', ''))

            elif provider == 'gitea':
                # Gitea API is GitHub-compatible
                parsed = urlparse(self.repo_url)
                gitea_base = '%s://%s/api/v1' % (
                    parsed.scheme or 'https', parsed.hostname,
                )
                headers = {'Authorization': 'token %s' % token}
                resp = http_requests.post(
                    '%s/repos/%s/%s/hooks' % (gitea_base, owner, repo),
                    headers=headers,
                    json={
                        'type': 'gitea',
                        'active': True,
                        'events': ['push'],
                        'config': {
                            'url': webhook_url,
                            'content_type': 'json',
                            'secret': self.webhook_secret,
                        },
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                hook_id = str(resp.json().get('id', ''))

            if hook_id:
                self.webhook_provider_id = hook_id
                _logger.info(
                    "Webhook auto-registered on %s for %s/%s (hook_id=%s)",
                    provider, owner, repo, hook_id,
                )

        except http_requests.RequestException as e:
            _logger.warning(
                "Failed to auto-register webhook on %s for %s/%s: %s",
                provider, owner, repo, e,
            )
            raise UserError(
                _("Could not register webhook on %s: %s\n"
                  "You can manually add this URL in your repo settings:\n%s")
                % (provider, e, webhook_url)
            )

    def _unregister_webhook_from_provider(self):
        """Remove the webhook from the Git provider via API."""
        self.ensure_one()
        token = self.sudo().github_token
        if not token or not self.webhook_provider_id:
            return

        provider = self._detect_provider()
        owner, repo = self._parse_owner_repo()
        if not provider or not owner or not repo:
            return

        base = self._get_provider_base_url()
        hook_id = self.webhook_provider_id

        try:
            if provider == 'github':
                http_requests.delete(
                    '%s/repos/%s/%s/hooks/%s' % (base, owner, repo, hook_id),
                    headers={
                        'Authorization': 'token %s' % token,
                        'Accept': 'application/vnd.github+json',
                    },
                    timeout=15,
                )

            elif provider == 'gitlab':
                from urllib.parse import quote as url_quote
                project_path = '%s/%s' % (owner, repo)
                http_requests.delete(
                    '%s/projects/%s/hooks/%s' % (
                        base, url_quote(project_path, safe=''), hook_id,
                    ),
                    headers={'PRIVATE-TOKEN': token},
                    timeout=15,
                )

            elif provider == 'bitbucket':
                http_requests.delete(
                    '%s/repositories/%s/%s/hooks/%s' % (base, owner, repo, hook_id),
                    auth=(owner, token),
                    timeout=15,
                )

            elif provider == 'gitea':
                parsed = urlparse(self.repo_url)
                gitea_base = '%s://%s/api/v1' % (
                    parsed.scheme or 'https', parsed.hostname,
                )
                http_requests.delete(
                    '%s/repos/%s/%s/hooks/%s' % (gitea_base, owner, repo, hook_id),
                    headers={'Authorization': 'token %s' % token},
                    timeout=15,
                )

            _logger.info(
                "Webhook removed from %s for %s/%s (hook_id=%s)",
                provider, owner, repo, hook_id,
            )
        except http_requests.RequestException as e:
            _logger.warning(
                "Failed to remove webhook from %s for %s/%s: %s",
                provider, owner, repo, e,
            )

    def action_check_webhook(self):
        """Check if the webhook is correctly registered on the Git provider."""
        self.ensure_one()
        token = self.sudo().github_token
        if not token:
            raise UserError(_("No token configured. Cannot check webhook status."))

        provider = self._detect_provider()
        owner, repo_name = self._parse_owner_repo()
        if not provider or not owner or not repo_name:
            raise UserError(_("Could not detect provider or parse owner/repo from URL."))

        base = self._get_provider_base_url()
        hooks = []

        try:
            if provider == 'github':
                resp = http_requests.get(
                    '%s/repos/%s/%s/hooks' % (base, owner, repo_name),
                    headers={
                        'Authorization': 'token %s' % token,
                        'Accept': 'application/vnd.github+json',
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                hooks = resp.json()

            elif provider == 'gitlab':
                from urllib.parse import quote as url_quote
                project_path = '%s/%s' % (owner, repo_name)
                resp = http_requests.get(
                    '%s/projects/%s/hooks' % (base, url_quote(project_path, safe='')),
                    headers={'PRIVATE-TOKEN': token},
                    timeout=15,
                )
                resp.raise_for_status()
                hooks = resp.json()

            elif provider == 'gitea':
                parsed = urlparse(self.repo_url)
                gitea_base = '%s://%s/api/v1' % (parsed.scheme or 'https', parsed.hostname)
                resp = http_requests.get(
                    '%s/repos/%s/%s/hooks' % (gitea_base, owner, repo_name),
                    headers={'Authorization': 'token %s' % token},
                    timeout=15,
                )
                resp.raise_for_status()
                hooks = resp.json()

        except http_requests.RequestException as e:
            raise UserError(_("Failed to fetch webhooks from %s: %s") % (provider, e))

        # Check if our webhook URL is in the list
        webhook_url = self.webhook_url
        found = False
        details = []
        for h in hooks:
            # GitHub/Gitea: config.url, GitLab: url
            hook_url = ''
            if isinstance(h, dict):
                hook_url = h.get('config', {}).get('url', '') or h.get('url', '')
            details.append("  ID=%s  URL=%s  Active=%s" % (
                h.get('id', '?'), hook_url, h.get('active', h.get('push_events', '?')),
            ))
            if webhook_url and webhook_url in hook_url:
                found = True

        msg = "Provider: %s\nRepo: %s/%s\nOur webhook URL: %s\n\n" % (
            provider, owner, repo_name, webhook_url,
        )
        if found:
            msg += "FOUND - Webhook is registered on %s" % provider
        else:
            msg += "NOT FOUND - Webhook is NOT registered on %s\n\n" % provider
            msg += "Registered webhooks (%d):\n%s" % (len(hooks), '\n'.join(details) if details else '  (none)')
            msg += "\n\nTIP: Click 'Enable Webhook' to register it, or add the URL manually in your repo settings."

        raise UserError(msg)

    @staticmethod
    def _normalize_repo_url(url):
        """Normalize a repo URL for comparison (strip protocol, auth, .git suffix)."""
        if not url:
            return ''
        url = url.strip().rstrip('/')
        # Remove .git suffix
        if url.endswith('.git'):
            url = url[:-4]
        # Remove protocol
        for prefix in ('https://', 'http://', 'git@', 'ssh://'):
            if url.startswith(prefix):
                url = url[len(prefix):]
                break
        # git@github.com:user/repo -> github.com/user/repo
        url = url.replace(':', '/', 1) if ':' in url and '/' not in url.split(':')[0] else url
        # Remove any auth info
        if '@' in url:
            url = url.split('@', 1)[1]
        return url.lower()

    def _match_webhook_repo_url(self, incoming_url):
        """Check if an incoming webhook repo URL matches this repo."""
        return self._normalize_repo_url(self.repo_url) == self._normalize_repo_url(incoming_url)

    def _match_webhook_branch(self, ref):
        """Check if a webhook ref (e.g. refs/heads/main) matches this repo's branch."""
        if not ref:
            return False
        branch = ref
        if branch.startswith('refs/heads/'):
            branch = branch[len('refs/heads/'):]
        return branch == self.branch

    @staticmethod
    def verify_signature(payload_body, secret, signature_header):
        """Verify webhook signature (supports GitHub, GitLab, Gitea HMAC-SHA256)."""
        if not signature_header or not secret:
            return False
        # GitHub: sha256=..., Gitea: sha256=...
        if signature_header.startswith('sha256='):
            expected = 'sha256=' + hmac.new(
                secret.encode(), payload_body, hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected, signature_header)
        # GitHub legacy: sha1=...
        if signature_header.startswith('sha1='):
            expected = 'sha1=' + hmac.new(
                secret.encode(), payload_body, hashlib.sha1,
            ).hexdigest()
            return hmac.compare_digest(expected, signature_header)
        # GitLab sends the token directly in X-Gitlab-Token header
        return hmac.compare_digest(secret, signature_header)

    # Lock to prevent concurrent deploys on the same instance
    _deploy_locks = {}

    def _do_webhook_pull_and_restart(self):
        """Pull repo and restart instance (runs in background thread from webhook).
        Includes debounce (skip if last event < 30s ago) and locking
        (prevent concurrent deploys on the same instance).
        """
        self.ensure_one()
        import time

        # Debounce: skip if last webhook event was less than 30 seconds ago
        if self.webhook_last_event:
            elapsed = (fields.Datetime.now() - self.webhook_last_event).total_seconds()
            if elapsed < 30:
                _logger.info(
                    "Webhook auto-deploy: skipping %s (last event %ds ago, debounce 30s)",
                    self.name, elapsed,
                )
                return

        # Lock: only one deploy per instance at a time
        import threading
        instance_id = self.instance_id.id
        lock = self._deploy_locks.setdefault(instance_id, threading.Lock())
        if not lock.acquire(blocking=False):
            _logger.info(
                "Webhook auto-deploy: skipping %s, another deploy is running for instance %s",
                self.name, self.instance_id.name,
            )
            return

        try:
            _logger.info(
                "Webhook auto-deploy: pulling %s for instance %s",
                self.name, self.instance_id.name,
            )
            self._do_pull_repo()
            self.instance_id._update_repo_config_and_restart()
            self.webhook_last_event = fields.Datetime.now()
            _logger.info(
                "Webhook auto-deploy: completed for %s / %s",
                self.name, self.instance_id.name,
            )
        finally:
            lock.release()

    def _get_remote_repo_path(self):
        """Return the full remote path inside the instance's addons directory."""
        self.ensure_one()
        instance = self.instance_id
        instance_path = instance._get_instance_path()
        return '%s/addons/%s' % (instance_path, self._get_repo_dir_name())

    def _get_container_addons_path(self):
        """Return the addons path inside the container for this repo."""
        self.ensure_one()
        base = '/mnt/extra-addons/%s' % self._get_repo_dir_name()
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

                    # Set permissions for container's odoo user
                    container_uid = instance._get_container_uid(ssh)
                    ssh.execute(
                        'sudo chown -R %s:%s %s && chmod -R 775 %s'
                        % (container_uid, container_uid,
                           shlex.quote(repo_path), shlex.quote(repo_path))
                    )

                    instance._append_log("Repository cloned successfully.")
                    rec.state = 'cloned'
                    rec.last_pull = fields.Datetime.now()
                    rec.error_message = False

                    # Auto-register webhook on Git provider
                    if rec.sudo().github_token and rec.webhook_enabled:
                        rec._register_webhook_with_retry()

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
        """Delete repo files from server, remove webhook, remove records, and update running instances."""
        for rec in self:
            if rec.webhook_enabled and rec.webhook_provider_id:
                try:
                    rec._unregister_webhook_from_provider()
                except Exception:
                    pass
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
