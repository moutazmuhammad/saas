import json
import logging
import threading

from odoo import http, SUPERUSER_ID, api
from odoo.http import request

_logger = logging.getLogger(__name__)


class SaasWebhookController(http.Controller):
    """
    Generic Git webhook receiver for auto-deploy.

    Supports:
      - GitHub   (X-Hub-Signature-256, X-GitHub-Event)
      - GitLab   (X-Gitlab-Token, X-Gitlab-Event)
      - Bitbucket (X-Hub-Signature, X-Event-Key)
      - Gitea    (X-Hub-Signature-256, X-Gitea-Event)
      - Generic  (push events with repository.clone_url / ref in body)

    Endpoint: POST /saas/webhook/<secret>
    The <secret> identifies which repo config this belongs to.
    """

    @http.route(
        '/saas/webhook-test',
        type='http',
        auth='none',
        methods=['GET', 'POST'],
        csrf=False,
    )
    def webhook_test(self, **kw):
        """Simple test endpoint to verify the server is reachable."""
        _logger.info("Webhook TEST endpoint hit! Method=%s", request.httprequest.method)
        return request.make_json_response({
            'status': 'ok',
            'message': 'Webhook endpoint is reachable',
        })

    @http.route(
        '/saas/webhook/<string:secret>',
        type='http',
        auth='none',
        methods=['GET', 'POST'],
        csrf=False,
    )
    def handle_webhook(self, secret, **kw):
        _logger.info("=== WEBHOOK RECEIVED === secret=%s...", secret[:8])
        _logger.info("Headers: %s", dict(request.httprequest.headers))

        # Use a proper env with superuser since auth='none'
        env = api.Environment(request.cr, SUPERUSER_ID, {})
        Repo = env['saas.instance.repo']

        # 1. Find the repo record by webhook secret
        repo = Repo.search([
            ('webhook_secret', '=', secret),
            ('webhook_enabled', '=', True),
        ], limit=1)

        if not repo:
            _logger.warning("Webhook: no matching repo for secret")
            return request.make_json_response(
                {'status': 'ignored', 'reason': 'unknown secret'}, status=404,
            )

        # 2. Check instance is running
        instance = repo.instance_id
        if instance.state != 'running':
            _logger.info(
                "Webhook: instance %s not running (state=%s), skipping",
                instance.name, instance.state,
            )
            return request.make_json_response(
                {'status': 'ignored', 'reason': 'instance not running'},
            )

        # 3. Repo must be cloned
        if repo.state != 'cloned':
            _logger.info("Webhook: repo %s not cloned yet, skipping", repo.name)
            return request.make_json_response(
                {'status': 'ignored', 'reason': 'repo not cloned'},
            )

        # 4. Read and parse body
        try:
            payload_body = request.httprequest.get_data()
            payload = json.loads(payload_body)
        except (ValueError, TypeError):
            return request.make_json_response(
                {'status': 'error', 'reason': 'invalid JSON'}, status=400,
            )

        # 5. Validate signature (if provider sends one)
        headers = request.httprequest.headers
        signature = (
            headers.get('X-Hub-Signature-256')       # GitHub / Gitea
            or headers.get('X-Hub-Signature')         # Bitbucket / GitHub legacy
            or headers.get('X-Gitlab-Token')          # GitLab
        )
        if signature:
            if not Repo.verify_signature(payload_body, repo.webhook_secret, signature):
                _logger.warning("Webhook: signature verification failed for repo %s", repo.name)
                return request.make_json_response(
                    {'status': 'error', 'reason': 'invalid signature'}, status=403,
                )

        # 6. Determine if this is a push event for the tracked branch
        event_type = (
            headers.get('X-GitHub-Event')
            or headers.get('X-Gitea-Event')
            or headers.get('X-Gitlab-Event', '').replace(' ', '_').lower()
            or headers.get('X-Event-Key', '')          # Bitbucket
        )

        if not self._is_push_event(event_type, payload):
            _logger.info("Webhook: event '%s' is not a push, skipping", event_type)
            return request.make_json_response(
                {'status': 'ignored', 'reason': 'not a push event'},
            )

        # 7. Check branch match
        ref = self._extract_ref(payload)
        if not repo._match_webhook_branch(ref):
            _logger.info(
                "Webhook: push to %s doesn't match tracked branch %s, skipping",
                ref, repo.branch,
            )
            return request.make_json_response(
                {'status': 'ignored', 'reason': 'branch mismatch'},
            )

        # 8. Trigger async pull + restart in a separate thread with its own cursor
        #    (cannot use run_in_background/postcommit here because auth='none'
        #    may not trigger postcommit reliably)
        dbname = request.cr.dbname
        repo_id = repo.id

        _logger.info(
            "Webhook: triggering auto-deploy for %s on instance %s (ref=%s)",
            repo.name, instance.name, ref,
        )

        def _do_deploy():
            import odoo
            db_registry = odoo.modules.registry.Registry(dbname)
            with db_registry.cursor() as new_cr:
                new_env = api.Environment(new_cr, SUPERUSER_ID, {})
                rec = new_env['saas.instance.repo'].browse(repo_id)
                try:
                    rec._do_webhook_pull_and_restart()
                    new_cr.commit()
                except Exception as e:
                    new_cr.rollback()
                    _logger.exception(
                        "Webhook auto-deploy failed for repo #%s: %s",
                        repo_id, e,
                    )
                    try:
                        with db_registry.cursor() as err_cr:
                            err_env = api.Environment(err_cr, SUPERUSER_ID, {})
                            err_rec = err_env['saas.instance.repo'].browse(repo_id)
                            err_rec._on_repo_background_error(e)
                            err_cr.commit()
                    except Exception:
                        _logger.exception("Error handler also failed for repo #%s", repo_id)

        t = threading.Thread(
            target=_do_deploy,
            name='saas_webhook_%s' % repo_id,
            daemon=True,
        )
        t.start()

        return request.make_json_response({
            'status': 'ok',
            'message': 'Auto-deploy triggered for %s' % repo.name,
        })

    @staticmethod
    def _is_push_event(event_type, payload):
        """Detect if the webhook event is a push/commit event."""
        event_type = (event_type or '').lower()
        # GitHub, Gitea
        if event_type == 'push':
            return True
        # GitLab
        if event_type in ('push_hook', 'tag_push_hook'):
            return True
        # Bitbucket
        if event_type.startswith('repo:push'):
            return True
        # Fallback: if the payload has "ref" and "commits", it's likely a push
        if 'ref' in payload and ('commits' in payload or 'push' in payload):
            return True
        return False

    @staticmethod
    def _extract_ref(payload):
        """Extract the branch ref from various provider payloads."""
        # GitHub, GitLab, Gitea: top-level "ref"
        if 'ref' in payload:
            return payload['ref']
        # Bitbucket: push.changes[0].new.name
        try:
            changes = payload.get('push', {}).get('changes', [])
            if changes:
                new = changes[0].get('new', {})
                return 'refs/heads/%s' % new.get('name', '')
        except (KeyError, IndexError, TypeError):
            pass
        return ''
