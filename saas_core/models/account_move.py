import logging
from dateutil.relativedelta import relativedelta

from odoo import fields, models, _

from ..utils import run_in_background

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def write(self, vals):
        result = super().write(vals)
        if 'payment_state' in vals and vals['payment_state'] in ('paid', 'in_payment'):
            self._saas_check_instance_payment()
        return result

    def _compute_payment_state(self):
        # Capture state before recomputation
        old_states = {inv.id: inv.payment_state for inv in self}
        super()._compute_payment_state()
        # Detect invoices that just became paid
        newly_paid = self.filtered(
            lambda m: m.payment_state in ('paid', 'in_payment')
            and old_states.get(m.id) not in ('paid', 'in_payment')
        )
        if newly_paid:
            newly_paid._saas_check_instance_payment()

        # Detect invoices that were paid but are now reversed/refunded
        newly_reversed = self.filtered(
            lambda m: m.payment_state in ('reversed', 'invoicing_legacy')
            and old_states.get(m.id) in ('paid', 'in_payment')
        )
        if newly_reversed:
            newly_reversed._saas_check_payment_reversal()

    def _saas_check_instance_payment(self):
        """Handle SaaS instance payments: deploy, upgrade, or restore."""
        paid_invoices = self.filtered(
            lambda m: m.payment_state in ('paid', 'in_payment')
        )
        if not paid_invoices:
            return

        # --- Handle daily-backup add-on payments ---
        # The customer clicked Enable Daily Backups, we created an
        # unpaid invoice and stored it on the instance. Now that the
        # invoice is paid, flip the feature on.
        backup_instances = self.env['saas.instance'].search([
            ('daily_backup_pending_invoice_id', 'in', paid_invoices.ids),
        ])
        for instance in backup_instances:
            _logger.info(
                "SaaS instance %s: daily-backup add-on paid (invoice %s), "
                "enabling daily backups.",
                instance.subdomain,
                instance.daily_backup_pending_invoice_id.name,
            )
            # Activation payment covers today → first of next month.
            # Anchor the monthly billing cycle there so the renewal
            # cron starts charging the customer on day 1 of next month.
            today = fields.Date.today()
            next_invoice = (today + relativedelta(months=1)).replace(day=1)
            instance.write({
                'daily_backup_enabled': True,
                'daily_backup_pending_invoice_id': False,
                'daily_backup_last_invoice_date': today,
                'daily_backup_next_invoice_date': next_invoice,
                # Surcharge for retaining the snapshot through
                # cancellation has been paid (it rode along on this
                # activation invoice if it was set) — clear the
                # flag so a future enable doesn't re-charge.
                'pending_retention_surcharge': False,
            })
            instance._append_log(
                "Daily backups enabled — add-on payment received. "
                "Next monthly invoice: %s." % next_invoice
            )
            instance.message_post(body=_(
                "Daily Backups add-on paid. The next 03:00 UTC backup "
                "cron will create the first snapshot, and renewal "
                "invoices will be issued monthly."
            ))

        # --- Handle restoration fee payments ---
        _logger.info(
            "Checking restoration invoices among paid: %s",
            paid_invoices.mapped('name'),
        )
        restoration_instances = self.env['saas.instance'].search([
            ('restoration_invoice_id', 'in', paid_invoices.ids),
        ])
        _logger.info(
            "Found %d instance(s) with restoration invoice: %s",
            len(restoration_instances),
            restoration_instances.mapped('subdomain'),
        )
        for instance in restoration_instances:
            _logger.info(
                "SaaS instance %s: restoration fee paid (invoice %s), triggering restore.",
                instance.subdomain,
                instance.restoration_invoice_id.name,
            )
            instance._append_log("Restoration fee paid. Starting data restore...")
            instance.message_post(body=_(
                "Restoration fee paid. Data restore triggered automatically."
            ))
            run_in_background(
                instance, '_do_paid_restore',
                error_method='_on_background_error',
                error_args=('running',),
                thread_name='saas_restore_%s' % instance.subdomain,
            )

        sale_orders = self.env['sale.order'].search([
            ('invoice_ids', 'in', paid_invoices.ids),
        ])
        if not sale_orders:
            return

        # --- Handle new instance deployment (pending_payment → paid) ---
        instances = self.env['saas.instance'].search([
            ('sale_order_id', 'in', sale_orders.ids),
            ('state', '=', 'pending_payment'),
            ('pending_plan_id', '=', False),
        ])
        for instance in instances:
            instance.state = 'paid'
            instance._set_next_invoice_date()
            instance._append_log("Payment received.")
            instance.message_post(
                body=_("Payment received. Deploying instance automatically."),
            )
            _logger.info(
                "SaaS instance %s: payment received, queuing auto-deploy.",
                instance.subdomain,
            )
            # Deploy in background thread — decoupled from the accounting write
            run_in_background(
                instance, '_do_deploy_after_payment',
                error_method='_on_background_error',
                error_args=('failed',),
                thread_name='saas_deploy_payment_%s' % instance.subdomain,
            )

        # --- Handle pending plan changes (trial upgrade or paid plan change) ---
        upgrade_instances = self.env['saas.instance'].search([
            ('sale_order_id', 'in', sale_orders.ids),
            ('pending_plan_id', '!=', False),
        ])
        for instance in upgrade_instances:
            # Pick the right method: trial upgrade or paid plan change
            if instance.is_trial:
                method = '_apply_pending_upgrade'
            else:
                method = '_apply_pending_plan_change'
            _logger.info(
                "SaaS instance %s: payment received, applying %s.",
                instance.subdomain, method,
            )
            run_in_background(
                instance, method,
                error_method='_on_background_error',
                error_args=(),
                thread_name='saas_planchange_%s' % instance.subdomain,
            )

    def _saas_check_payment_reversal(self):
        """Suspend running SaaS instances when a payment is reversed.

        This catches refund fraud: a customer pays, gets the instance
        deployed, then reverses the payment (chargeback / credit note).
        """
        reversed_invoices = self.filtered(
            lambda m: m.payment_state in ('reversed', 'invoicing_legacy')
        )
        if not reversed_invoices:
            return

        sale_orders = self.env['sale.order'].search([
            ('invoice_ids', 'in', reversed_invoices.ids),
        ])
        if not sale_orders:
            return

        instances = self.env['saas.instance'].search([
            ('sale_order_id', 'in', sale_orders.ids),
            ('state', '=', 'running'),
        ])
        for instance in instances:
            _logger.warning(
                "SaaS instance %s: payment reversed on invoice(s) %s — suspending.",
                instance.subdomain,
                ', '.join(reversed_invoices.mapped('name')),
            )
            instance._append_log(
                "PAYMENT REVERSED — instance suspended automatically."
            )
            instance.message_post(body=_(
                "Payment reversed (refund/chargeback). Instance suspended."
            ))
            try:
                instance.action_suspend()
            except Exception:
                _logger.exception(
                    "Failed to suspend instance %s after payment reversal",
                    instance.subdomain,
                )
