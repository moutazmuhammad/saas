from odoo import fields, models


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
        [('create', 'Create'), ('duplicate', 'Duplicate'), ('drop', 'Drop')],
        required=True,
    )
    # For ``duplicate`` ops, the source DB name. ``False`` for create / drop.
    source_db = fields.Char()
    state = fields.Selection(
        [('running', 'Running'), ('done', 'Done'), ('failed', 'Failed')],
        default='running', required=True, index=True,
    )
    error_message = fields.Text(readonly=True)

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

    def _run_duplicate(self):
        self.ensure_one()
        try:
            self.instance_id.hosting_db_duplicate(
                source=self.source_db,
                new_name=self.db_name,
            )
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

    def _run_drop(self):
        self.ensure_one()
        try:
            self.instance_id.hosting_db_drop(name=self.db_name)
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
