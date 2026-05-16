import json
import logging
import threading

from odoo import http, SUPERUSER_ID, api
from odoo.http import request

_logger = logging.getLogger(__name__)


class SaasWebhookController(http.Controller):
    """Generic Git webhook receiver for auto-deploy.

    Supports:
      - GitHub   (X-Hub-Signature-256, X-GitHub-Event)
      - GitLab   (X-Gitlab-Token, X-Gitlab-Event)
      - Bitbucket (X-Hub-Signature-256, X-Event-Key)
      - Gitea    (X-Hub-Signature-256, X-Gitea-Event)

    Endpoint: POST /saas/webhook/<secret>

    Hard requirements (security):
    - Method must be POST. GET requests would log the secret in Nginx
      access logs / browser history.
    - A valid HMAC signature header MUST be present and verified. The
      URL path is treated as a routing key only, NOT as authentication
      on its own (it can leak via logs/history).
    - SHA-1 signatures are rejected. Modern providers all send SHA-256.
    - Same provider delivery-id is processed at most once (idempotency).
    """

    @http.route(
        '/saas/webhook/<string:secret>',
        type='http',
        auth='none',
        methods=['POST'],
        csrf=False,
    )
    def handle_webhook(self, secret, **kw):
        env = api.Environment(request.cr, SUPERUSER_ID, {})
        Repo = env['saas.instance.repo']
        headers = request.httprequest.headers

        # 1. Find the repo by secret. Do this BEFORE parsing the body so
        #    we can refuse early without consuming resources.
        repo = Repo.search([
            ('webhook_secret', '=', secret),
            ('webhook_enabled', '=', True),
        ], limit=1)
        if not repo:
            _logger.warning("Webhook: no matching repo for incoming secret")
            return request.make_json_response(
                {'status': 'ignored', 'reason': 'unknown secret'}, status=404,
            )

        # 2. Read signature header. Missing signature == reject (URL secret
        #    alone is not authentication).
        signature = (
            headers.get('X-Hub-Signature-256')   # GitHub / Gitea / Bitbucket
            or headers.get('X-Gitlab-Token')      # GitLab (token compare)
        )
        # Explicitly reject SHA-1: deprecated for years.
        if not signature and headers.get('X-Hub-Signature'):
            _logger.warning(
                "Webhook: SHA-1 signature received for repo %s — rejected",
                repo.name,
            )
            return request.make_json_response(
                {'status': 'error', 'reason': 'sha1 signatures not accepted'},
                status=403,
            )
        if not signature:
            _logger.warning(
                "Webhook: missing signature header for repo %s — rejected",
                repo.name,
            )
            return request.make_json_response(
                {'status': 'error', 'reason': 'signature required'}, status=403,
            )

        # 3. Verify signature against the raw payload BEFORE any parsing.
        payload_body = request.httprequest.get_data()
        if not Repo.verify_signature(payload_body, repo.webhook_secret, signature):
            _logger.warning(
                "Webhook: signature verification failed for repo %s", repo.name,
            )
            return request.make_json_response(
                {'status': 'error', 'reason': 'invalid signature'}, status=403,
            )

        # 4. Idempotency: drop duplicate deliveries (provider retries,
        #    deliberate replays). The handler is otherwise unauthenticated
        #    so this is the only replay defence we have.
        delivery_id = (
            headers.get('X-GitHub-Delivery')
            or headers.get('X-Gitea-Delivery')
            or headers.get('X-Request-Id')
            or ''
        ).strip()
        if delivery_id:
            if repo.last_delivery_id == delivery_id:
                _logger.info(
                    "Webhook: duplicate delivery %s for repo %s — ignored",
                    delivery_id, repo.name,
                )
                return request.make_json_response(
                    {'status': 'ignored', 'reason': 'duplicate delivery'},
                )
            repo.write({'last_delivery_id': delivery_id})

        # 5. Sanity-check instance and repo state.
        instance = repo.instance_id
        if instance.state not in ('running', 'stopped'):
            return request.make_json_response(
                {'status': 'ignored', 'reason': 'instance not running'},
            )
        if repo.state not in ('cloned', 'error'):
            return request.make_json_response(
                {'status': 'ignored', 'reason': 'repo not cloned'},
            )

        # 6. Parse body now that signature has been verified.
        try:
            payload = json.loads(payload_body)
        except (ValueError, TypeError):
            return request.make_json_response(
                {'status': 'error', 'reason': 'invalid JSON'}, status=400,
            )

        # 7. Determine event type and filter to push events on the tracked branch.
        event_type = (
            headers.get('X-GitHub-Event')
            or headers.get('X-Gitea-Event')
            or headers.get('X-Gitlab-Event', '').replace(' ', '_').lower()
            or headers.get('X-Event-Key', '')
        )
        if not self._is_push_event(event_type, payload):
            return request.make_json_response(
                {'status': 'ignored', 'reason': 'not a push event'},
            )
        ref = self._extract_ref(payload)
        if not repo._match_webhook_branch(ref):
            return request.make_json_response(
                {'status': 'ignored', 'reason': 'branch mismatch'},
            )

        # 8. Trigger async pull + restart in a separate thread with its own
        #    cursor. The per-repo lock inside _do_webhook_pull_and_restart
        #    serialises concurrent pushes to the same repo on this worker.
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
                        _logger.exception(
                            "Error handler also failed for repo #%s", repo_id,
                        )

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
        if event_type == 'push':
            return True
        if event_type in ('push_hook', 'tag_push_hook'):
            return True
        if event_type.startswith('repo:push'):
            return True
        # Fallback: GitHub/Gitea-shaped push payloads carry both `ref`
        # AND a `commits` list (PR events have `ref` but no `commits`).
        if 'ref' in payload and isinstance(payload.get('commits'), list):
            return True
        # Bitbucket push (no event header on some setups)
        if isinstance(payload.get('push'), dict) \
                and isinstance(payload['push'].get('changes'), list):
            return True
        return False

    @staticmethod
    def _extract_ref(payload):
        """Extract the branch ref from various provider payloads."""
        if 'ref' in payload:
            return payload['ref']
        try:
            changes = payload.get('push', {}).get('changes', [])
            if changes:
                new = changes[0].get('new', {})
                return 'refs/heads/%s' % new.get('name', '')
        except (KeyError, IndexError, TypeError):
            pass
        return ''
