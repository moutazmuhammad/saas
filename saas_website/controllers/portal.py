import datetime
import logging

import werkzeug.utils

from odoo import fields, http, _
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.addons.payment.controllers.portal import PaymentPortal

_logger = logging.getLogger(__name__)


class SaasPortal(CustomerPortal):

    # States visible to clients in the portal
    # Excludes: cancelled, cancelled_by_client
    _PORTAL_VISIBLE_STATES = (
        'draft', 'pending_payment', 'paid', 'provisioning',
        'running', 'stopped', 'suspended', 'failed',
    )

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'instance_count' in counters:
            partner = request.env.user.partner_id
            Instance = request.env['saas.instance']
            values['instance_count'] = Instance.search_count([
                ('partner_id', '=', partner.id),
                ('state', 'in', self._PORTAL_VISIBLE_STATES),
            ]) if Instance.has_access('read') else 0
        return values

    # ==================== Instance List ====================

    @http.route(
        ['/my/instances', '/my/instances/page/<int:page>'],
        type='http', auth='user', website=True,
    )
    def portal_my_instances(self, page=1, sortby=None, **kw):
        partner = request.env.user.partner_id
        Instance = request.env['saas.instance']
        domain = [
            ('partner_id', '=', partner.id),
            ('state', 'in', self._PORTAL_VISIBLE_STATES),
        ]

        sortings = {
            'date': {'label': _('Newest'), 'order': 'create_date desc'},
            'name': {'label': _('Name'), 'order': 'subdomain asc'},
            'state': {'label': _('Status'), 'order': 'state asc'},
        }
        sortby = sortby if sortby in sortings else 'date'

        instance_count = Instance.search_count(domain)
        pager = portal_pager(
            url='/my/instances',
            total=instance_count,
            page=page,
            step=20,
            url_args={'sortby': sortby},
        )

        instances = Instance.search(
            domain,
            order=sortings[sortby]['order'],
            limit=20,
            offset=pager['offset'],
        )

        values = self._prepare_portal_layout_values()
        values.update({
            'instances': instances,
            'page_name': 'saas_instances',
            'pager': pager,
            'sortby': sortby,
            'searchbar_sortings': sortings,
            'default_url': '/my/instances',
        })
        return request.render('saas_website.portal_my_instances', values)

    # ==================== Instance Detail ====================

    @http.route(
        '/my/instances/<int:instance_id>',
        type='http', auth='user', website=True,
    )
    def portal_my_instance_detail(self, instance_id, access_token=None, **kw):
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        # Fetch backups for portal display (show all states so client sees progress)
        backups = instance_sudo.backup_ids.filtered(
            lambda b: b.state in ('done', 'running')
        ).sorted('create_date', reverse=True)[:10]

        values = self._prepare_portal_layout_values()
        values.update({
            'instance': instance_sudo,
            'backups': backups,
            'page_name': 'saas_instance_detail',
        })
        return request.render('saas_website.portal_instance_detail', values)

    # ==================== Deployment Status Polling ====================

    @http.route(
        '/my/instances/<int:instance_id>/status',
        type='json', auth='user', website=True,
    )
    def portal_instance_status(self, instance_id, access_token=None, **kw):
        """JSON endpoint for polling deployment status."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return {'error': 'Access denied'}
        return instance_sudo._get_status_dict()

    # ==================== Portal Self-Service Actions ====================

    @http.route(
        '/my/instances/<int:instance_id>/restart',
        type='json', auth='user', website=True,
    )
    def portal_instance_restart(self, instance_id, access_token=None, **kw):
        """Restart an instance from the portal."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return {'error': 'Access denied'}
        try:
            instance_sudo.action_portal_restart()
            return {'success': True, 'message': _('Instance restart initiated.')}
        except UserError as e:
            return {'error': str(e)}

    @http.route(
        '/my/instances/<int:instance_id>/stop',
        type='json', auth='user', website=True,
    )
    def portal_instance_stop(self, instance_id, access_token=None, **kw):
        """Stop an instance from the portal."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return {'error': 'Access denied'}
        try:
            instance_sudo.action_portal_stop()
            return {'success': True, 'message': _('Instance stop initiated.')}
        except UserError as e:
            return {'error': str(e)}

    @http.route(
        '/my/instances/<int:instance_id>/start',
        type='json', auth='user', website=True,
    )
    def portal_instance_start(self, instance_id, access_token=None, **kw):
        """Start a stopped instance from the portal."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return {'error': 'Access denied'}
        try:
            instance_sudo.action_portal_start()
            return {'success': True, 'message': _('Instance start initiated.')}
        except UserError as e:
            return {'error': str(e)}

    # ==================== Plan Upgrade (Trial → Paid) ====================

    @http.route(
        '/my/instances/<int:instance_id>/upgrade',
        type='http', auth='user', website=True,
    )
    def portal_instance_upgrade(self, instance_id, access_token=None, **kw):
        """Show available paid plans for upgrading a trial instance."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        if not instance_sudo.is_trial:
            return request.redirect('/my/instances/%s' % instance_id)

        # Fetch paid plans for the same service
        domain = [('is_trial_plan', '=', False)]
        if instance_sudo.saas_product_id:
            domain.append(('saas_product_id', '=', instance_sudo.saas_product_id.id))
        plans = request.env['saas.plan'].sudo().search(domain, order='sequence, price')

        values = self._prepare_portal_layout_values()
        values.update({
            'instance': instance_sudo,
            'plans': plans,
            'page_name': 'saas_instance_upgrade',
            'error': kw.get('error'),
        })
        return request.render('saas_website.portal_instance_upgrade', values)

    @http.route(
        '/my/instances/<int:instance_id>/subscribe',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_instance_subscribe(self, instance_id, access_token=None, **kw):
        """Process plan subscription from trial."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        plan_id = kw.get('plan_id')
        billing_period = kw.get('billing_period', 'monthly')
        if not plan_id:
            return request.redirect(
                '/my/instances/%s/upgrade?error=%s' % (instance_id, 'Please select a plan.')
            )

        try:
            result = instance_sudo.action_subscribe_from_trial(
                int(plan_id), billing_period=billing_period,
            )
        except UserError as e:
            return request.redirect(
                '/my/instances/%s/upgrade?error=%s' % (instance_id, str(e))
            )

        # If result is an invoice, redirect to checkout page
        if hasattr(result, 'get_portal_url') and result.amount_total > 0:
            return request.redirect('/my/instances/%s/checkout' % instance_id)

        # Zero-amount or boolean True — go back to instance detail
        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Checkout Page ====================

    @http.route(
        '/my/instances/<int:instance_id>/checkout',
        type='http', auth='user', website=True,
    )
    def portal_checkout(self, instance_id, access_token=None, **kw):
        """Show a checkout page with order summary and embedded payment form."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        # Find the latest unpaid invoice with amount > 0
        invoice = None
        if instance_sudo.sale_order_id and instance_sudo.sale_order_id.invoice_ids:
            for inv in instance_sudo.sale_order_id.invoice_ids.sorted('create_date', reverse=True):
                if (inv.state == 'posted'
                        and inv.payment_state not in ('paid', 'in_payment')
                        and inv.amount_residual > 0):
                    invoice = inv
                    break

        if not invoice:
            # No unpaid invoice — nothing to pay, go to instance page
            return request.redirect('/my/instances/%s' % instance_id)

        # Get the plan being purchased (pending or current)
        target_plan = instance_sudo.pending_plan_id or instance_sudo.plan_id

        # Prepare payment form values (same approach as account_payment)
        partner_sudo = request.env.user.partner_id
        invoice_company = invoice.company_id or request.env.company
        landing_route = '/my/instances/%s' % instance_id

        availability_report = {}
        providers_sudo = request.env['payment.provider'].sudo()._get_compatible_providers(
            invoice_company.id,
            partner_sudo.id,
            invoice.amount_residual,
            currency_id=invoice.currency_id.id,
            report=availability_report,
        )
        payment_methods_sudo = request.env['payment.method'].sudo()._get_compatible_payment_methods(
            providers_sudo.ids,
            partner_sudo.id,
            currency_id=invoice.currency_id.id,
            report=availability_report,
        )
        tokens_sudo = request.env['payment.token'].sudo()._get_available_tokens(
            providers_sudo.ids, partner_sudo.id
        )

        # Get the invoice's portal access token
        invoice_access_token = invoice._portal_ensure_token()

        values = self._prepare_portal_layout_values()
        values.update({
            'instance': instance_sudo,
            'invoice': invoice,
            'target_plan': target_plan,
            'page_name': 'saas_checkout',
            # Payment form context (required by payment.form template)
            'amount': invoice.amount_residual,
            'currency': invoice.currency_id,
            'partner_id': partner_sudo.id,
            'providers_sudo': providers_sudo,
            'payment_methods_sudo': payment_methods_sudo,
            'tokens_sudo': tokens_sudo,
            'availability_report': availability_report,
            'transaction_route': '/invoice/transaction/%d' % invoice.id,
            'landing_route': landing_route,
            'access_token': invoice_access_token,
            'show_tokenize_input_mapping': PaymentPortal._compute_show_tokenize_input_mapping(
                providers_sudo
            ),
            'company_mismatch': not PaymentPortal._can_partner_pay_in_company(
                partner_sudo, invoice_company
            ),
            'expected_company': invoice_company,
            'invoice_id': invoice.id,
        })
        return request.render('saas_website.portal_checkout', values)

    # ==================== Change Plan (Paid → Paid) ====================

    @http.route(
        '/my/instances/<int:instance_id>/change-plan',
        type='http', auth='user', website=True,
    )
    def portal_instance_change_plan(self, instance_id, access_token=None, **kw):
        """Show available plans for changing a paid instance's plan."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        if instance_sudo.is_trial or instance_sudo.state not in ('running', 'stopped', 'suspended'):
            return request.redirect('/my/instances/%s' % instance_id)

        # Fetch all paid plans for the same service, excluding the current one
        domain = [
            ('is_trial_plan', '=', False),
            ('id', '!=', instance_sudo.plan_id.id),
        ]
        if instance_sudo.saas_product_id:
            domain.append(('saas_product_id', '=', instance_sudo.saas_product_id.id))
        plans = request.env['saas.plan'].sudo().search(domain, order='sequence, price')

        values = self._prepare_portal_layout_values()
        values.update({
            'instance': instance_sudo,
            'plans': plans,
            'current_plan': instance_sudo.plan_id,
            'page_name': 'saas_instance_change_plan',
            'error': kw.get('error'),
        })
        return request.render('saas_website.portal_instance_change_plan', values)

    @http.route(
        '/my/instances/<int:instance_id>/do-change-plan',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_instance_do_change_plan(self, instance_id, access_token=None, **kw):
        """Create a proration invoice for the plan change, require payment first."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        plan_id = kw.get('plan_id')
        billing_period = kw.get('billing_period', instance_sudo.billing_period or 'monthly')
        if not plan_id:
            return request.redirect(
                '/my/instances/%s/change-plan?error=%s' % (instance_id, 'Please select a plan.')
            )

        try:
            new_plan = request.env['saas.plan'].sudo().browse(int(plan_id))
            if not new_plan.exists() or new_plan.is_trial_plan:
                raise UserError(_("Invalid plan."))

            result = instance_sudo.action_request_plan_change(
                new_plan.id, billing_period=billing_period,
            )
        except UserError as e:
            return request.redirect(
                '/my/instances/%s/change-plan?error=%s' % (instance_id, str(e))
            )

        # Upgrade: redirect to checkout
        if hasattr(result, 'get_portal_url') and result.amount_total > 0:
            return request.redirect('/my/instances/%s/checkout' % instance_id)

        # Downgrade scheduled or zero-charge upgrade — back to detail
        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Cancel Scheduled Downgrade ====================

    @http.route(
        '/my/instances/<int:instance_id>/cancel-downgrade',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_cancel_downgrade(self, instance_id, access_token=None, **kw):
        """Cancel a scheduled plan downgrade."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')
        instance_sudo.action_cancel_scheduled_downgrade()
        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Cancel Unpaid Invoice ====================

    @http.route(
        '/my/instances/<int:instance_id>/cancel-invoice/<int:invoice_id>',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_cancel_invoice(self, instance_id, invoice_id, access_token=None, **kw):
        """Cancel an unpaid invoice and clean up the pending upgrade."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        # Only allow cancelling unpaid invoices belonging to this instance
        if not instance_sudo.sale_order_id:
            return request.redirect('/my/instances/%s' % instance_id)
        invoice = instance_sudo.sale_order_id.invoice_ids.filtered(
            lambda inv: inv.id == invoice_id
                        and inv.state == 'posted'
                        and inv.payment_state not in ('paid', 'in_payment')
        )
        if not invoice:
            return request.redirect('/my/instances/%s' % instance_id)

        # Cancel the invoice
        invoice.button_cancel()

        # Clear pending upgrade if this was the related invoice
        if instance_sudo.pending_plan_id:
            instance_sudo.write({
                'pending_plan_id': False,
                'pending_billing_period': False,
            })
            instance_sudo._append_log("Pending upgrade cancelled by client.")
            instance_sudo.message_post(body=_(
                "Pending plan change cancelled. Invoice %s voided."
            ) % invoice.name)
            return request.redirect('/my/instances/%s' % instance_id)

        # If instance was never deployed (pending_payment or draft),
        # cancel it entirely to free up the subdomain
        if instance_sudo.state in ('pending_payment', 'draft'):
            subdomain = instance_sudo.name or instance_sudo.subdomain
            plan_name = instance_sudo.plan_id.name if instance_sudo.plan_id else 'N/A'
            partner_name = instance_sudo.partner_id.name
            previous_state = dict(
                instance_sudo._fields['state'].selection
            ).get(instance_sudo.state, instance_sudo.state)

            reason = (
                "Client cancelled before payment.\n"
                "Previous state: %s\n"
                "Plan: %s\n"
                "Invoice: %s\n"
                "Subdomain: %s"
            ) % (previous_state, plan_name, invoice.name, subdomain)

            instance_sudo.write({
                'state': 'cancelled_by_client',
                'cancellation_reason': reason,
            })
            instance_sudo._append_log(
                "Order cancelled by client. Subdomain released."
            )
            # Log for support follow-up (visible in backend chatter)
            from markupsafe import Markup
            instance_sudo.message_post(
                body=Markup(
                    "<b>Order cancelled by client</b><br/>"
                    "Client <b>%s</b> cancelled before payment.<br/>"
                    "Instance: %s<br/>"
                    "Plan: %s<br/>"
                    "Invoice: %s (cancelled)<br/>"
                    "This client may need a follow-up."
                ) % (partner_name, subdomain, plan_name, invoice.name),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )
            return request.redirect('/my/instances')

        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Restore Backup ====================

    @http.route(
        '/my/instances/<int:instance_id>/backup/<int:backup_id>/restore',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_restore_backup(self, instance_id, backup_id, access_token=None, **kw):
        """Restore a backup to the instance from the portal."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        if instance_sudo.state not in ('running', 'stopped'):
            return request.redirect('/my/instances/%s' % instance_id)

        backup = instance_sudo.backup_ids.filtered(
            lambda b: b.id == backup_id and b.state == 'done'
        )
        if not backup:
            return request.redirect('/my/instances/%s' % instance_id)

        try:
            instance_sudo.action_restore_backup(backup.id)
        except Exception:
            _logger.exception(
                "Backup restore failed for instance %s", instance_sudo.name
            )
            # Reset state if it was changed before the error
            if instance_sudo.state == 'provisioning':
                instance_sudo.state = 'running'

        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Refresh Usage ====================

    @http.route(
        '/my/instances/<int:instance_id>/refresh-usage',
        type='json', auth='user',
    )
    def portal_refresh_usage(self, instance_id, access_token=None, **kw):
        """Refresh resource usage data and return updated values as JSON."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return {'error': 'Access denied'}

        if instance_sudo.state != 'running':
            return {'error': 'Instance not running'}

        try:
            instance_sudo.action_refresh_usage()
        except Exception as e:
            return {'error': str(e)}

        return {
            'cpu_usage': instance_sudo.cpu_usage or '0%',
            'cpu_pct': instance_sudo.cpu_usage_pct or 0,
            'ram_percent': instance_sudo.ram_percent or '0%',
            'ram_pct': instance_sudo.ram_usage_pct or 0,
            'total_storage': instance_sudo.total_storage or '—',
            'storage_pct': instance_sudo.storage_usage_pct or 0,
            'storage_limit': int(instance_sudo.plan_id.storage_limit) if instance_sudo.plan_id else 0,
        }

    # ==================== Create Backup ====================

    @http.route(
        '/my/instances/<int:instance_id>/create-backup',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_create_backup(self, instance_id, access_token=None, **kw):
        """Create a new backup from the portal."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')
        if instance_sudo.state != 'running':
            return request.redirect('/my/instances/%s' % instance_id)

        # Block if a backup is already in progress
        # Block backups for trial plans
        if instance_sudo.plan_id and instance_sudo.plan_id.is_trial_plan:
            return request.redirect('/my/instances/%s' % instance_id)

        running = instance_sudo.backup_ids.filtered(lambda b: b.state == 'running')
        if running:
            return request.redirect('/my/instances/%s' % instance_id)

        # Check backup limit
        plan = instance_sudo.plan_id
        if plan and plan.max_backups > 0:
            existing = instance_sudo.backup_ids.filtered(
                lambda b: b.state == 'done'
            )
            if len(existing) >= plan.max_backups:
                return request.redirect('/my/instances/%s' % instance_id)

        # Create the backup record NOW (state=running) so the UI sees it
        # immediately, then run the actual backup in the background.
        Backup = request.env['saas.instance.backup'].sudo()
        now_str = fields.Datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup = Backup.create({
            'instance_id': instance_sudo.id,
            'name': 'backup_%s' % now_str,
            'state': 'running',
        })

        from odoo.addons.saas_core.utils import run_in_background
        run_in_background(
            backup, '_run_portal_backup',
            thread_name='saas_backup_%s' % instance_sudo.subdomain,
        )

        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Delete Backup ====================

    @http.route(
        '/my/instances/<int:instance_id>/backup/<int:backup_id>/delete',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_delete_backup(self, instance_id, backup_id, access_token=None, **kw):
        """Delete a backup from the portal."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        backup = instance_sudo.backup_ids.filtered(
            lambda b: b.id == backup_id and b.state in ('done', 'failed')
        )
        if backup:
            backup.action_delete_backup()

        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Backup Download Regeneration ====================

    @http.route(
        '/my/instances/<int:instance_id>/backup/<int:backup_id>/download',
        type='http', auth='user',
    )
    def portal_backup_download(self, instance_id, backup_id, access_token=None, **kw):
        """Generate a fresh presigned URL and redirect to it for download."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        backup = instance_sudo.backup_ids.filtered(
            lambda b: b.id == backup_id and b.state == 'done'
        )
        if not backup:
            return request.redirect('/my/instances/%s' % instance_id)

        try:
            url = backup._generate_presigned_url()
            if url:
                return werkzeug.utils.redirect(url, 302)
        except Exception as e:
            _logger.exception("Failed to generate download URL for backup %s", backup_id)

        return request.redirect('/my/instances/%s' % instance_id)
