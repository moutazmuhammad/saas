import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class SaasInstanceDbOperation(models.Model):
    """Tracking record for an asynchronous database operation.

    Customer-initiated create / duplicate / drop on a hosting instance
    can each take 30-90 seconds (Odoo CLI init, pg_dump-style copy,
    drop-and-cleanup respectively). Doing them in-line during the HTTP
    request hits nginx's ``proxy_read_timeout`` and starves the saas
    master's worker pool — both observed in production as 502 Bad
    Gateway from the saas master and orphaned half-initialized
    databases on the customer's instance.

    This model is the queue/tracker. The portal creates one of these,
    spawns the real work in a background thread, and returns the HTTP
    response immediately. The background flips ``state`` to ``done`` or
    ``failed`` (with ``error_message``) when finished. The Databases
    page renders any pending or recently-failed ops so the customer
    sees what happened.
    """
    _name = 'saas.instance.db.operation'
    _description = 'SaaS Instance Database Operation'
    _order = 'create_date desc'

    instance_id = fields.Many2one(
        'saas.instance', required=True, ondelete='cascade', index=True,
    )
    db_name = fields.Char(
        required=True, index=True,
        help='Full (prefixed) database name the operation targets.',
    )
    operation = fields.Selection(
        [
            ('create', 'Create'),
            ('duplicate', 'Duplicate'),
            ('drop', 'Drop'),
            ('upgrade', 'Upgrade Module'),
        ],
        required=True,
    )
    # For ``duplicate`` ops, the source DB name. ``False`` for create / drop.
    source_db = fields.Char()
    # For ``upgrade`` ops, the module name passed to ``odoo -u``. Pre-
    # validated by the controller against ``_UPGRADE_MODULE_RE`` so an
    # arbitrary string can't smuggle shell or CLI flags into the
    # docker-compose-run command.
    module_name = fields.Char()
    state = fields.Selection(
        [('running', 'Running'), ('done', 'Done'), ('failed', 'Failed')],
        default='running', required=True, index=True,
    )
    error_message = fields.Text(readonly=True)
    output_log = fields.Text(
        readonly=True,
        help='Captured stdout/stderr of the underlying CLI invocation '
             '(currently used for ``upgrade`` ops so the customer sees '
             'why the upgrade failed — or that it succeeded — without '
             'having to dig in the docker host).',
    )

    def _run_create(self, login, password, lang, country_code):
        """Background worker: run the sync create, update state.

        Receives the secrets (login/password) via ``method_args`` so
        they never get persisted on this tracking record. The cursor
        is committed before re-raising so a failure leaves a clean
        ``failed`` row instead of a stuck ``running`` one when the
        thread's transaction rolls back.
        """
        self.ensure_one()
        try:
            self.instance_id.hosting_db_create(
                name=self.db_name,
                login=login,
                password=password,
                lang=lang,
                country_code=country_code,
            )
            # A freshly-created DB can't have meaningful prior backups —
            # any matching backup record is from a previous incarnation
            # of the same name (e.g. drop happened before the cleanup in
            # ``_run_drop`` was deployed, or the customer dropped the DB
            # directly outside the portal). Reap so a stale "Backup
            # ready" badge doesn't follow the new database around.
            self._reap_stale_backups()
            self.write({'state': 'done'})
            try:
                self.env.cr.commit()
            except Exception:
                pass
        except Exception as e:
            self.write({'state': 'failed', 'error_message': str(e)})
            try:
                self.env.cr.commit()
            except Exception:
                pass
            raise

    def _reap_stale_backups(self):
        """Unlink ephemeral / per-DB backup records pointing at ``self.db_name``.

        The :meth:`saas.instance.backup.unlink` override drops the
        bucket object before removing the row, so this cleans both
        sides. ``is_full_instance`` restic snapshots are skipped —
        they span every DB on the instance and can't be selectively
        carved up.
        """
        self.ensure_one()
        related = self.env['saas.instance.backup'].sudo().search([
            ('instance_id', '=', self.instance_id.id),
            ('db_name', '=', self.db_name),
            ('is_full_instance', '=', False),
        ])
        if not related:
            return
        try:
            related.unlink()
        except Exception:
            _logger.exception(
                "Failed to unlink backups for DB '%s' on instance %s "
                "during op %s",
                self.db_name, self.instance_id.id, self.operation,
            )

    def _run_duplicate(self):
        self.ensure_one()
        try:
            self.instance_id.hosting_db_duplicate(
                source=self.source_db,
                new_name=self.db_name,
            )
            # Same rationale as ``_run_create`` — the target name just
            # came into existence, so any pre-existing backup for it is
            # an orphan from a previous incarnation.
            self._reap_stale_backups()
            self.write({'state': 'done'})
            try:
                self.env.cr.commit()
            except Exception:
                pass
        except Exception as e:
            self.write({'state': 'failed', 'error_message': str(e)})
            try:
                self.env.cr.commit()
            except Exception:
                pass
            raise

    def _run_upgrade(self):
        """Background worker: ``odoo -u <module> -d <db>`` on the container.

        Recovery tool for when the customer's live Odoo is broken
        (500 Internal Server Error on every page). XML-RPC into the
        live worker won't work in that state, so we bypass it: stop
        the container, run ``docker compose run --rm odoo odoo -u``
        with ``--stop-after-init`` (one-shot, no HTTP), then start the
        container back up. The full stdout/stderr is captured on the
        op record so the portal can show it.
        """
        self.ensure_one()
        try:
            output = self.instance_id.hosting_db_upgrade_module(
                name=self.db_name,
                module=self.module_name or '',
            )
            self.write({'state': 'done', 'output_log': output or ''})
            try:
                self.env.cr.commit()
            except Exception:
                pass
        except Exception as e:
            # Pull the output off the exception when our helper raised
            # a ``UserError`` carrying the captured CLI output (so the
            # portal can render it). Plain exceptions just go to
            # error_message.
            output = getattr(e, '_saas_upgrade_output', None) or ''
            self.write({
                'state': 'failed',
                'error_message': str(e),
                'output_log': output,
            })
            try:
                self.env.cr.commit()
            except Exception:
                pass
            raise

    def _run_drop(self):
        self.ensure_one()
        try:
            self.instance_id.hosting_db_drop(name=self.db_name)
            # The PG database is gone — its on-demand zip backups are
            # now orphaned, so reap them from the bucket too.
            self._reap_stale_backups()
            self.write({'state': 'done'})
            try:
                self.env.cr.commit()
            except Exception:
                pass
        except Exception as e:
            self.write({'state': 'failed', 'error_message': str(e)})
            try:
                self.env.cr.commit()
            except Exception:
                pass
            raise
