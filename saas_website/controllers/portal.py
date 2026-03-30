import datetime
import logging
from urllib.parse import quote as url_quote

import werkzeug.utils

from odoo import fields, http, _
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.addons.payment.controllers.portal import PaymentPortal

_logger = logging.getLogger(__name__)


class SaasPortal(CustomerPortal):

    # Only show paid orders to customers in the portal.
    # Unpaid/cancelled orders are internal artifacts from plan changes.
    def _prepare_orders_domain(self, partner):
        domain = super()._prepare_orders_domain(partner)
        # Only include orders where at least one invoice is paid
        domain.append(('invoice_ids.payment_state', 'in', ('paid', 'in_payment')))
        return domain

    # States visible to clients in the portal
    _PORTAL_VISIBLE_STATES = (
        'draft', 'pending_payment', 'paid', 'pending_provision',
        'provisioning', 'running', 'stopped', 'suspended', 'failed',
        'cancelled', 'cancelled_by_client',
    )

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'instance_count' in counters:
            partner = request.env.user.partner_id
            values['instance_count'] = request.env['saas.instance'].sudo().search_count([
                ('partner_id', '=', partner.id),
                ('state', 'in', self._PORTAL_VISIBLE_STATES),
            ])
        return values

    # ==================== Instance List ====================

    @http.route(
        ['/my/instances', '/my/instances/page/<int:page>'],
        type='http', auth='user', website=True,
    )
    def portal_my_instances(self, page=1, sortby=None, folder=None, itype=None, **kw):
        partner = request.env.user.partner_id
        Instance = request.env['saas.instance'].sudo()
        Folder = request.env['saas.instance.folder'].sudo()

        domain = [
            ('partner_id', '=', partner.id),
            ('state', 'in', self._PORTAL_VISIBLE_STATES),
        ]

        # Type filtering (services vs hosting)
        active_type = itype or 'all'
        if active_type == 'services':
            domain.append(('is_hosting', '=', False))
        elif active_type == 'hosting':
            domain.append(('is_hosting', '=', True))

        # Folder filtering (includes subfolders)
        active_folder_id = False
        if folder == 'unfiled':
            domain.append(('folder_id', '=', False))
        elif folder:
            try:
                active_folder_id = int(folder)
                folder_rec = Folder.search([
                    ('id', '=', active_folder_id),
                    ('partner_id', '=', partner.id),
                ], limit=1)
                if folder_rec:
                    all_ids = folder_rec._get_all_descendant_ids()
                    domain.append(('folder_id', 'in', all_ids))
                else:
                    domain.append(('folder_id', '=', active_folder_id))
            except (ValueError, TypeError):
                pass

        sortings = {
            'date': {'label': _('Newest'), 'order': 'create_date desc'},
            'name': {'label': _('Name'), 'order': 'subdomain asc'},
            'state': {'label': _('Status'), 'order': 'state asc'},
        }
        sortby = sortby if sortby in sortings else 'date'

        url_args = {'sortby': sortby}
        if active_type and active_type != 'all':
            url_args['itype'] = active_type
        if folder:
            url_args['folder'] = folder

        instance_count = Instance.search_count(domain)
        pager = portal_pager(
            url='/my/instances',
            total=instance_count,
            page=page,
            step=20,
            url_args=url_args,
        )

        instances = Instance.search(
            domain,
            order=sortings[sortby]['order'],
            limit=20,
            offset=pager['offset'],
        )

        # Fetch user's folders with instance counts
        folders = Folder.search([('partner_id', '=', partner.id)])

        # Total instance count (all folders) for "All" tab
        all_domain = [
            ('partner_id', '=', partner.id),
            ('state', 'in', self._PORTAL_VISIBLE_STATES),
        ]
        all_count = Instance.search_count(all_domain)

        # Unfiled count
        unfiled_count = Instance.search_count(all_domain + [('folder_id', '=', False)])

        # Type counts
        services_count = Instance.search_count(all_domain + [('is_hosting', '=', False)])
        hosting_count = Instance.search_count(all_domain + [('is_hosting', '=', True)])

        # Active folder name for rename/delete buttons
        active_folder_name = ''
        if active_folder_id:
            active_folder_rec = folders.filtered(lambda f: f.id == active_folder_id)
            active_folder_name = active_folder_rec.name if active_folder_rec else ''

        values = self._prepare_portal_layout_values()
        values.update({
            'instances': instances,
            'page_name': 'saas_instances',
            'pager': pager,
            'sortby': sortby,
            'searchbar_sortings': sortings,
            'default_url': '/my/instances',
            'folders': folders,
            'active_folder': folder or 'all',
            'active_folder_id': active_folder_id,
            'active_folder_name': active_folder_name,
            'all_count': all_count,
            'unfiled_count': unfiled_count,
            'services_count': services_count,
            'hosting_count': hosting_count,
            'active_type': active_type,
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

        # Fetch all invoices across all sale orders (initial + renewals + upgrades)
        # Hide cancelled invoices from the client — they are internal artifacts
        # from plan change replacements and would only confuse the customer.
        all_invoices = instance_sudo._get_all_invoices()
        invoices = all_invoices.filtered(
            lambda inv: inv.state != 'cancel'
        ).sorted('create_date', reverse=True)

        support_email = request.env['ir.config_parameter'].sudo().get_param(
            'saas_master.support_email', ''
        )

        # Cutoff for showing the "Upgrade Credit Applied" banner (7 days)
        credit_notice_cutoff = fields.Datetime.now() - datetime.timedelta(days=7)

        values = self._prepare_portal_layout_values()
        values.update({
            'instance': instance_sudo,
            'backups': backups,
            'invoices': invoices,
            'support_email': support_email,
            'page_name': 'saas_instance_detail',
            'credit_notice_cutoff': credit_notice_cutoff,
            'is_hosting': instance_sudo.is_hosting,
            'repos': instance_sudo.repo_ids if instance_sudo.is_hosting else [],
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
        """Show custom plan builder for upgrading a trial instance."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        if not instance_sudo.is_trial or instance_sudo.state not in ('running', 'stopped'):
            return request.redirect('/my/instances/%s' % instance_id)

        from odoo.addons.saas_website.controllers.main import SaasWebsite
        if instance_sudo.is_hosting:
            custom_config = SaasWebsite._get_hosting_plan_config(self)
        else:
            custom_config = SaasWebsite._get_custom_plan_config(self)

        values = self._prepare_portal_layout_values()
        values.update({
            'instance': instance_sudo,
            'custom_config': custom_config,
            'page_name': 'saas_instance_upgrade',
            'error': kw.get('error'),
            'product_id': instance_sudo.saas_product_id.id if instance_sudo.saas_product_id else 0,
        })
        return request.render('saas_website.portal_instance_upgrade', values)

    @http.route(
        '/my/instances/<int:instance_id>/subscribe',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_instance_subscribe(self, instance_id, access_token=None, **kw):
        """Process custom plan subscription from trial."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        workers = int(kw.get('workers', 0))
        storage = int(kw.get('storage', 0))
        billing_period = kw.get('billing_period', 'monthly')
        if billing_period not in ('monthly', 'yearly'):
            billing_period = 'monthly'

        if not workers or not storage:
            return request.redirect(
                '/my/instances/%s/upgrade?error=%s' % (
                    instance_id, url_quote('Please configure your plan.'))
            )

        # Create the custom plan (use hosting config for hosting instances)
        from odoo.addons.saas_website.controllers.main import SaasWebsite
        if instance_sudo.is_hosting:
            config = SaasWebsite._get_hosting_plan_config(self)
        else:
            config = SaasWebsite._get_custom_plan_config(self)
        workers = max(config['min_workers'], min(workers, config['max_workers']))
        storage = max(config['min_storage'], min(storage, config['max_storage']))

        if instance_sudo.is_hosting:
            plan = SaasWebsite._get_or_create_hosting_plan(
                self, instance_sudo.saas_product_id, workers, storage, config,
            )
        else:
            plan = SaasWebsite._get_or_create_custom_plan(
                self, instance_sudo.saas_product_id, workers, storage, config,
            )

        try:
            result = instance_sudo.action_subscribe_from_trial(
                plan.id, billing_period=billing_period,
            )
        except UserError as e:
            return request.redirect(
                '/my/instances/%s/upgrade?error=%s' % (instance_id, url_quote(str(e)))
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

        # Find the unpaid invoice — check restoration invoice first,
        # then the regular sale order invoices.
        invoice = None

        # Restoration invoice takes priority
        if (instance_sudo.restoration_invoice_id
                and instance_sudo.restoration_invoice_id.state == 'posted'
                and instance_sudo.restoration_invoice_id.payment_state not in ('paid', 'in_payment')
                and instance_sudo.restoration_invoice_id.amount_residual > 0):
            invoice = instance_sudo.restoration_invoice_id

        # Regular sale order invoices
        if not invoice and instance_sudo.sale_order_id and instance_sudo.sale_order_id.invoice_ids:
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
        landing_route = '/my/instances/%s?payment=success' % instance_id

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

        # Compute proration details for display
        proration_credit = 0.0
        proration_remaining_days = 0
        original_plan_name = ''
        target_full_price = target_plan._get_price_for_period(
            instance_sudo.pending_billing_period or instance_sudo.billing_period or 'monthly'
        ) if target_plan else 0
        if instance_sudo.plan_id and instance_sudo.pending_plan_id:
            # This is an upgrade — calculate what was credited
            old_period = instance_sudo.billing_period or 'monthly'
            old_price = instance_sudo.plan_id._get_price_for_period(old_period)
            original_plan_name = instance_sudo.plan_id.name
            if instance_sudo.next_invoice_date and instance_sudo.last_invoice_date:
                total_days = (instance_sudo.next_invoice_date - instance_sudo.last_invoice_date).days
                remaining_days = (instance_sudo.next_invoice_date - fields.Date.today()).days - 2
                if total_days > 0 and remaining_days > 0:
                    proration_credit = (old_price / total_days) * remaining_days
                    proration_remaining_days = remaining_days

        values = self._prepare_portal_layout_values()
        values.update({
            'instance': instance_sudo,
            'invoice': invoice,
            'target_plan': target_plan,
            'page_name': 'saas_checkout',
            'proration_credit': proration_credit,
            'proration_remaining_days': proration_remaining_days,
            'original_plan_name': original_plan_name,
            'target_full_price': target_full_price,
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
            'support_email': request.env['ir.config_parameter'].sudo().get_param(
                'saas_master.support_email', ''
            ),
        })
        return request.render('saas_website.portal_checkout', values)

    # ==================== Change Plan (Paid → Paid) ====================

    @http.route(
        '/my/instances/<int:instance_id>/change-plan',
        type='http', auth='user', website=True,
    )
    def portal_instance_change_plan(self, instance_id, access_token=None, **kw):
        """Show custom plan builder for changing a paid instance's plan."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        if instance_sudo.is_trial or instance_sudo.state not in ('running', 'stopped', 'suspended'):
            return request.redirect('/my/instances/%s' % instance_id)

        from odoo.addons.saas_website.controllers.main import SaasWebsite
        if instance_sudo.is_hosting:
            custom_config = SaasWebsite._get_hosting_plan_config(self)
        else:
            custom_config = SaasWebsite._get_custom_plan_config(self)

        current_plan = instance_sudo.plan_id
        current_workers = current_plan.workers if current_plan else 2
        current_storage = int(current_plan.storage_limit) if current_plan else 5

        # Proration info for display
        today = fields.Date.today()
        old_period = instance_sudo.billing_period or 'monthly'
        old_price = current_plan._get_price_for_period(old_period) if current_plan else 0
        remaining_value = 0.0
        remaining_days = 0
        if instance_sudo.next_invoice_date and instance_sudo.last_invoice_date:
            total_days = (instance_sudo.next_invoice_date - instance_sudo.last_invoice_date).days
            remaining_days = (instance_sudo.next_invoice_date - today).days - 2
            if total_days > 0 and remaining_days > 0:
                remaining_value = (old_price / total_days) * remaining_days

        values = self._prepare_portal_layout_values()
        values.update({
            'instance': instance_sudo,
            'current_plan': current_plan,
            'current_workers': current_workers,
            'current_storage': current_storage,
            'custom_config': custom_config,
            'remaining_value': remaining_value,
            'remaining_days': remaining_days,
            'old_price': old_price,
            'old_period': old_period,
            'page_name': 'saas_instance_change_plan',
            'error': kw.get('error'),
        })
        return request.render('saas_website.portal_instance_change_plan', values)

    @http.route(
        '/my/instances/<int:instance_id>/do-change-plan',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_instance_do_change_plan(self, instance_id, access_token=None, **kw):
        """Process a custom plan change.

        Rules:
        - Storage cannot be reduced (hard block).
        - Worker reduction is scheduled for next billing cycle (downgrade).
        - Worker increase / storage increase is an immediate upgrade.
        """
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        new_workers = int(kw.get('workers', 0))
        new_storage = int(kw.get('storage', 0))
        billing_period = kw.get('billing_period', instance_sudo.billing_period or 'monthly')
        if billing_period not in ('monthly', 'yearly'):
            billing_period = 'monthly'

        current_plan = instance_sudo.plan_id
        current_workers = current_plan.workers if current_plan else 0
        current_storage = int(current_plan.storage_limit) if current_plan else 0

        err_redirect = '/my/instances/%s/change-plan?error=%s'

        # Block storage reduction
        if new_storage < current_storage:
            return request.redirect(err_redirect % (
                instance_id,
                url_quote(_("Storage cannot be reduced. Current storage: %d GB.") % current_storage),
            ))

        if not new_workers or not new_storage:
            return request.redirect(err_redirect % (
                instance_id, url_quote(_("Please configure your plan.")),
            ))

        # Clamp to config limits
        from odoo.addons.saas_website.controllers.main import SaasWebsite
        if instance_sudo.is_hosting:
            config = SaasWebsite._get_hosting_plan_config(self)
        else:
            config = SaasWebsite._get_custom_plan_config(self)
        new_workers = max(config['min_workers'], min(new_workers, config['max_workers']))
        new_storage = max(current_storage, min(new_storage, config['max_storage']))

        if (new_workers == current_workers
                and new_storage == current_storage
                and billing_period == (instance_sudo.billing_period or 'monthly')):
            return request.redirect(err_redirect % (
                instance_id, url_quote(_("No changes selected.")),
            ))

        # Find or create the new plan
        if instance_sudo.is_hosting:
            new_plan = SaasWebsite._get_or_create_hosting_plan(
                self, instance_sudo.saas_product_id,
                new_workers, new_storage, config,
            )
        else:
            new_plan = SaasWebsite._get_or_create_custom_plan(
                self, instance_sudo.saas_product_id,
                new_workers, new_storage, config,
            )

        try:
            if new_workers < current_workers:
                # Worker reduction: always schedule for next billing cycle
                result = instance_sudo._request_downgrade(new_plan, billing_period)
            else:
                # Workers same or increased (storage can only increase):
                # use normal plan change flow
                result = instance_sudo.action_request_plan_change(
                    new_plan.id, billing_period=billing_period,
                )
        except UserError as e:
            return request.redirect(err_redirect % (
                instance_id, url_quote(str(e)),
            ))

        # Upgrade: redirect to checkout
        if hasattr(result, 'get_portal_url') and result.amount_total > 0:
            return request.redirect('/my/instances/%s/checkout' % instance_id)

        # Downgrade scheduled or zero-charge upgrade — back to detail
        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Cancel Scheduled Downgrade ====================

    @http.route(
        '/my/instances/<int:instance_id>/cancel-upgrade',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_cancel_upgrade(self, instance_id, access_token=None, **kw):
        """Cancel a pending plan upgrade and its unpaid invoice."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')
        if instance_sudo.pending_plan_id:
            instance_sudo._cancel_pending_upgrade()
        return request.redirect('/my/instances/%s' % instance_id)

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

        # Block cancellation of mandatory invoices.
        # Only optional invoices (plan upgrades, subscriptions) can be
        # cancelled by the client. Renewal and restoration invoices are
        # mandatory — the dunning system enforces payment.
        # invoice_origin is the SO name (e.g. S00123), so we trace
        # back to the sale order's origin field.
        so_origins = invoice.line_ids.sale_line_ids.order_id.mapped('origin')
        non_cancellable_prefixes = ('Renewal:', 'Data restoration:')
        if any(
            o and any(o.startswith(prefix) for prefix in non_cancellable_prefixes)
            for o in so_origins
        ):
            return request.redirect('/my/instances/%s' % instance_id)

        # Cancel the invoice
        invoice.button_cancel()

        # Clear pending upgrade if this was the related invoice
        if instance_sudo.pending_plan_id:
            instance_sudo._append_log("Pending upgrade cancelled by client.")
            from markupsafe import Markup
            instance_sudo.message_post(body=Markup(
                "<b>Client cancelled plan upgrade payment</b><br/>"
                "Was upgrading to: <b>%s</b> (%s)<br/>"
                "Invoice: %s — %s %s<br/>"
                "Current plan: %s"
            ) % (
                instance_sudo.pending_plan_id.name,
                instance_sudo.pending_billing_period or instance_sudo.billing_period or 'monthly',
                invoice.name,
                invoice.currency_id.symbol if invoice.currency_id else '',
                '%.2f' % invoice.amount_total,
                instance_sudo.plan_id.name if instance_sudo.plan_id else 'N/A',
            ))
            # Send notification before clearing pending plan so template can access it
            instance_sudo._send_notification(
                'saas_core.mail_template_saas_payment_cancelled',
            )
            instance_sudo.write({
                'pending_plan_id': False,
                'pending_billing_period': False,
            })
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
            # Notify support team to follow up with the client
            instance_sudo._send_notification(
                'saas_core.mail_template_saas_payment_cancelled',
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

    # ==================== Log Stream Proxy (Hosting) ====================

    @http.route(
        '/my/instances/<int:instance_id>/logs/stream',
        type='http', auth='user', csrf=False,
    )
    def portal_instance_log_stream(self, instance_id, tail='100', access_token=None, **kw):
        """Portal-safe SSE proxy for live container logs.

        Validates ownership, then extracts SSH connection details
        BEFORE the streaming generator starts, so the ORM cursor
        is not held open during the long-lived SSE connection.
        """
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            from werkzeug.exceptions import Forbidden
            raise Forbidden()

        if instance_sudo.state != 'running' or not instance_sudo.docker_server_id:
            from werkzeug.exceptions import NotFound
            raise NotFound()

        # Extract everything we need BEFORE the generator runs
        # (the generator runs after the ORM transaction closes)
        server = instance_sudo.docker_server_id.sudo()
        container_name = 'odoo_%s' % instance_sudo.subdomain

        # Get SSH connection details while cursor is still open
        ssh_conn = server._get_ssh_connection()

        import json as _json
        import select as _select
        import shlex as _shlex

        try:
            tail_int = int(tail)
        except (ValueError, TypeError):
            tail_int = 100

        safe_name = _shlex.quote(container_name)

        def generate():
            try:
                ssh_conn._connect()
                transport = ssh_conn._client.get_transport()
                channel = transport.open_session()
                channel.exec_command(
                    'docker logs -f --tail %d %s 2>&1' % (tail_int, safe_name)
                )
                channel.settimeout(300)

                yield b'retry: 1000\n\n'

                buf = b''
                while not channel.exit_status_ready():
                    ready, _, _ = _select.select([channel], [], [], 1.0)
                    if ready:
                        chunk = channel.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                        while b'\n' in buf:
                            line, buf = buf.split(b'\n', 1)
                            text = line.decode('utf-8', errors='replace')
                            yield ('data: %s\n\n' % _json.dumps(text)).encode('utf-8')

                while channel.recv_ready():
                    chunk = channel.recv(4096)
                    buf += chunk
                if buf:
                    text = buf.decode('utf-8', errors='replace')
                    yield ('data: %s\n\n' % _json.dumps(text)).encode('utf-8')

                yield b'event: done\ndata: stream ended\n\n'

            except Exception as e:
                _logger.exception("Log streaming error for %s", container_name)
                yield ('event: error\ndata: %s\n\n' % _json.dumps(str(e))).encode('utf-8')
            finally:
                ssh_conn._disconnect()

        from odoo.http import Response
        return Response(
            generate(),
            content_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive',
            },
            direct_passthrough=True,
        )

    # ==================== Update Repository (Hosting) ====================

    @http.route(
        '/my/instances/<int:instance_id>/update-repo',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_update_repo(self, instance_id, access_token=None, **kw):
        """Update or create repository for a hosting instance and redeploy."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        if not instance_sudo.is_hosting or instance_sudo.state != 'running':
            return request.redirect('/my/instances/%s' % instance_id)

        repo_url = (kw.get('repo_url') or '').strip()
        repo_branch = (kw.get('repo_branch') or 'main').strip()
        git_token = (kw.get('git_token') or '').strip()

        Repo = request.env['saas.instance.repo'].sudo()
        existing_repo = instance_sudo.repo_ids[:1]

        if repo_url:
            if existing_repo:
                # Update existing repo
                vals = {
                    'repo_url': repo_url,
                    'branch': repo_branch,
                }
                if git_token:
                    vals['github_token'] = git_token
                    vals['webhook_enabled'] = True
                existing_repo.write(vals)
            else:
                # Create new repo
                Repo.create({
                    'instance_id': instance_sudo.id,
                    'repo_url': repo_url,
                    'branch': repo_branch,
                    'github_token': git_token or False,
                    'webhook_enabled': bool(git_token),
                })
            # Redeploy to clone/pull the repo
            try:
                instance_sudo.action_redeploy()
                instance_sudo._append_log("Repository updated by client: %s (%s)" % (repo_url, repo_branch))
            except Exception:
                _logger.exception("Failed to redeploy instance %s after repo update", instance_sudo.name)
        elif existing_repo:
            # Repo URL cleared — remove the repo
            existing_repo.unlink()
            try:
                instance_sudo.action_restart()
                instance_sudo._append_log("Repository removed by client.")
            except Exception:
                _logger.exception("Failed to restart instance %s after repo removal", instance_sudo.name)

        return request.redirect('/my/instances/%s' % instance_id)

    @http.route(
        '/my/instances/<int:instance_id>/remove-repo',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_remove_repo(self, instance_id, access_token=None, **kw):
        """Remove the custom repository and restart the instance."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        if not instance_sudo.is_hosting or instance_sudo.state != 'running':
            return request.redirect('/my/instances/%s' % instance_id)

        existing_repo = instance_sudo.repo_ids[:1]
        if existing_repo:
            # Unregister webhook before removing
            if existing_repo.webhook_provider_id:
                try:
                    existing_repo._unregister_webhook_from_provider()
                except Exception:
                    pass
            existing_repo.unlink()
            try:
                instance_sudo.action_redeploy()
                instance_sudo._append_log("Repository removed by client.")
            except Exception:
                _logger.exception(
                    "Failed to redeploy instance %s after repo removal",
                    instance_sudo.name,
                )

        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Data Restore Request ====================

    @http.route(
        '/my/instances/<int:instance_id>/request-restore',
        type='json', auth='user', website=True,
    )
    def portal_request_restore(self, instance_id, note='', **kw):
        """Client requests data restoration — sends email to support."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id,
            )
        except (AccessError, MissingError):
            return {'error': _('Access denied.')}

        if not instance_sudo.retained_backup_path:
            return {'error': _('No backup available for restore.')}

        partner = request.env.user.partner_id
        support_email = request.env['ir.config_parameter'].sudo().get_param(
            'saas_master.support_email', ''
        )
        if not support_email:
            return {'error': _('Support email is not configured. Please contact us directly.')}

        # Send email to support
        subject = _('Data Restore Request — %s') % instance_sudo.subdomain
        body = _(
            "Data restore request from client:\n\n"
            "Client: %s (%s)\n"
            "Instance: %s\n"
            "Subdomain: %s.%s\n"
            "Plan: %s (%s)\n"
            "Retained Backup: %s\n"
            "Client Note: %s\n\n"
            "Action: Open the instance in the backend and use "
            "'Restore to Instance & Invoice' to create the restoration "
            "invoice and schedule the restore."
        ) % (
            partner.name,
            partner.email or 'no email',
            instance_sudo.name or instance_sudo.subdomain,
            instance_sudo.subdomain,
            instance_sudo.domain_id.name if instance_sudo.domain_id else '',
            instance_sudo.plan_id.name if instance_sudo.plan_id else 'N/A',
            instance_sudo.billing_period or 'N/A',
            instance_sudo.retained_backup_path,
            note or '(none)',
        )

        try:
            mail = request.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': '<pre>%s</pre>' % body.replace('\n', '<br/>'),
                'email_from': partner.email or support_email,
                'email_to': support_email,
                'auto_delete': True,
            })
            mail.send()
        except Exception as e:
            _logger.exception("Failed to send restore request email")
            return {'error': _('Failed to send request. Please contact support directly.')}

        instance_sudo._append_log(
            "Client requested data restore via portal. Note: %s" % (note or '(none)')
        )
        instance_sudo.message_post(body=_(
            "Client requested data restore. Note: %s"
        ) % (note or '(none)'))

        return {'success': True, 'message': _('Your request has been sent to support.')}

    @http.route(
        '/my/instances/<int:instance_id>/dismiss-restore-banner',
        type='json', auth='user', website=True,
    )
    def portal_dismiss_restore_banner(self, instance_id, **kw):
        """Dismiss the data restore suggestion banner."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id,
            )
        except (AccessError, MissingError):
            return {'error': _('Access denied.')}
        instance_sudo.restore_banner_dismissed = True
        return {'success': True}

    # ==================== List Installed Packages (Hosting) ====================

    @http.route(
        '/my/instances/<int:instance_id>/installed-packages',
        type='json', auth='user',
    )
    def portal_installed_packages(self, instance_id, access_token=None, **kw):
        """Fetch list of installed pip packages from the running container."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return {'error': 'Access denied'}

        if not instance_sudo.is_hosting or instance_sudo.state != 'running':
            return {'error': 'Instance not running'}

        try:
            server = instance_sudo.docker_server_id.sudo()
            container = 'odoo_%s' % instance_sudo.subdomain
            with server._get_ssh_connection() as ssh:
                # List from both default site-packages and custom target path
                exit_code, stdout, stderr = ssh.execute(
                    'docker exec %s bash -c "'
                    'pip3 list --path=/var/lib/odoo/pip_packages --format=columns 2>/dev/null; '
                    'pip3 list --format=columns 2>/dev/null'
                    '" 2>/dev/null' % container
                )
                result = stdout
            # Parse pip list output into structured data (deduplicated)
            packages = []
            seen = set()
            if result:
                for line in result.strip().splitlines():
                    line = line.strip()
                    if not line or line.startswith('Package') or line.startswith('-'):
                        continue
                    parts = line.split()
                    if not parts:
                        continue
                    name = parts[0]
                    if name.lower() in seen:
                        continue
                    seen.add(name.lower())
                    version = parts[1] if len(parts) >= 2 else ''
                    packages.append({'name': name, 'version': version})
            packages.sort(key=lambda p: p['name'].lower())
            return {'packages': packages, 'count': len(packages)}
        except Exception as e:
            _logger.exception("Failed to list packages for instance %s", instance_sudo.name)
            return {'error': str(e)}

    # ==================== Update Packages (Hosting) ====================

    @http.route(
        '/my/instances/<int:instance_id>/update-packages',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_update_packages(self, instance_id, access_token=None, **kw):
        """Update pip packages for a hosting instance and restart to apply."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        if not instance_sudo.is_hosting or instance_sudo.state != 'running':
            return request.redirect('/my/instances/%s' % instance_id)

        raw_packages = (kw.get('pip_packages') or '').strip()
        # Deduplicate packages
        seen = set()
        unique_pkgs = []
        for p in raw_packages.splitlines():
            p = p.strip()
            if not p or p.startswith('#'):
                continue
            key = p.lower().split('=')[0].split('<')[0].split('>')[0].split('!')[0].split('[')[0].strip()
            if key not in seen:
                seen.add(key)
                unique_pkgs.append(p)
        new_packages = '\n'.join(unique_pkgs) if unique_pkgs else ''
        old_packages = (instance_sudo.pip_packages or '').strip()

        if new_packages != old_packages:
            instance_sudo.pip_packages = new_packages or False
            install_result = 'success'
            install_output = ''
            try:
                with instance_sudo.docker_server_id.sudo()._get_ssh_connection() as ssh:
                    # Update requirements.txt and docker-compose on disk (for persistence)
                    instance_sudo._render_and_write_configs(ssh)

                    # Install packages live into the running container
                    # Use /var/lib/odoo/pip_packages — already persisted via ./data/odoo volume
                    container = 'odoo_%s' % instance_sudo.subdomain
                    if unique_pkgs:
                        install_cmd = (
                            'docker exec %s bash -c "'
                            'mkdir -p /var/lib/odoo/pip_packages && '
                            'pip3 install --target=/var/lib/odoo/pip_packages '
                            '--upgrade --no-warn-script-location %s'
                            '" 2>&1'
                        ) % (container, ' '.join(unique_pkgs))
                        exit_code, stdout, stderr = ssh.execute(install_cmd)
                        install_output = stdout or stderr or ''
                        instance_sudo._append_log(
                            "Packages installed live (exit=%s): %s\n%s"
                            % (exit_code, ' '.join(unique_pkgs), install_output)
                        )
                        if exit_code != 0:
                            install_result = 'partial'

                    # Restart Odoo to pick up new packages (graceful)
                    instance_sudo.action_restart()
                    instance_sudo._append_log("Packages updated by client: %s" % (new_packages or '(cleared)'))
            except Exception as e:
                _logger.exception("Failed to update packages for instance %s", instance_sudo.name)
                install_result = 'error'
                install_output = str(e)

            return request.redirect(
                '/my/instances/%s?pkg_result=%s' % (instance_id, install_result)
            )

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

    # ==================== Live Logs (Hosting) ====================

    @http.route(
        '/my/instances/<int:instance_id>/logs',
        type='http', auth='user', website=True,
    )
    def portal_instance_logs(self, instance_id, access_token=None, **kw):
        """Show live container logs for a hosting instance."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        if instance_sudo.state != 'running':
            return request.redirect('/my/instances/%s' % instance_id)

        values = self._prepare_portal_layout_values()
        values.update({
            'instance': instance_sudo,
            'page_name': 'saas_instance_logs',
            'stream_url': '/my/instances/%d/logs/stream' % instance_sudo.id,
        })
        return request.render('saas_website.portal_instance_logs', values)

    # ==================== Create Backup ====================

    @http.route(
        '/my/instances/<int:instance_id>/create-backup',
        type='json', auth='user', website=True,
    )
    def portal_create_backup(self, instance_id, **kw):
        """Create a new backup from the portal (JSON, no page refresh)."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id,
            )
        except (AccessError, MissingError):
            return {'error': _('Access denied.')}
        if instance_sudo.state != 'running':
            return {'error': _('Instance must be running.')}
        if instance_sudo.plan_id and instance_sudo.plan_id.is_trial_plan:
            return {'error': _('Backups are not available on trial plans.')}

        running = instance_sudo.backup_ids.filtered(lambda b: b.state == 'running')
        if running:
            return {'error': _('A backup is already in progress.')}

        # Auto-rotate: delete oldest if at plan limit
        plan = instance_sudo.plan_id
        if plan and plan.max_backups > 0:
            done_backups = instance_sudo.backup_ids.filtered(
                lambda b: b.state == 'done'
            ).sorted('create_date')
            while len(done_backups) >= plan.max_backups:
                oldest = done_backups[0]
                instance_sudo._append_log(
                    "Auto-removing oldest backup '%s' (limit: %d)."
                    % (oldest.name, plan.max_backups)
                )
                oldest._delete_from_bucket()
                oldest.unlink()
                done_backups -= oldest

        # Create the backup record NOW (state=running) so polling detects it
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

        return {'success': True, 'message': _('Backup started.')}

    # ==================== Delete Backup ====================

    @http.route(
        '/my/instances/<int:instance_id>/backup/<int:backup_id>/delete',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_delete_backup(self, instance_id, backup_id, access_token=None, **kw):
        """Backup deletion is not available from the portal."""
        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Backup Download Regeneration ====================

    @http.route(
        '/my/instances/<int:instance_id>/backup/<int:backup_id>/download',
        type='http', auth='user',
    )
    def portal_backup_download(self, instance_id, backup_id, access_token=None, **kw):
        """Backup download is not available from the portal."""
        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Reactivate Cancelled Instance ====================

    @http.route(
        '/my/instances/<int:instance_id>/reactivate',
        type='http', auth='user', website=True,
    )
    def portal_instance_reactivate(self, instance_id, access_token=None, **kw):
        """Show dynamic plan builder to reactivate a cancelled instance.

        Uses the same workers/storage slider UI as the change-plan page.
        """
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        if instance_sudo.state not in ('cancelled', 'cancelled_by_client'):
            return request.redirect('/my/instances/%s' % instance_id)

        product = instance_sudo.saas_product_id
        if not product or not product.is_published:
            return request.redirect('/services')

        from odoo.addons.saas_website.controllers.main import SaasWebsite
        if instance_sudo.is_hosting:
            custom_config = SaasWebsite._get_hosting_plan_config(self)
        else:
            custom_config = SaasWebsite._get_custom_plan_config(self)

        # Minimum resources = what the instance had before cancellation
        old_plan = instance_sudo.plan_id
        min_workers = old_plan.workers if old_plan else custom_config['min_workers']
        min_storage = int(old_plan.storage_limit) if old_plan else custom_config['min_storage']

        values = self._prepare_portal_layout_values()
        values.update({
            'instance': instance_sudo,
            'current_workers': min_workers,
            'current_storage': min_storage,
            'custom_config': custom_config,
            'page_name': 'saas_instance_reactivate',
            'error': kw.get('error'),
        })
        return request.render('saas_website.portal_instance_reactivate', values)

    @http.route(
        '/my/instances/<int:instance_id>/do-reactivate',
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_instance_do_reactivate(self, instance_id, access_token=None, **kw):
        """Process reactivation: build a plan from workers/storage, reset
        the cancelled instance, and run the billing flow."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        new_workers = int(kw.get('workers', 0))
        new_storage = int(kw.get('storage', 0))
        billing_period = kw.get('billing_period', 'monthly')
        if billing_period not in ('monthly', 'yearly'):
            billing_period = 'monthly'

        err_redirect = '/my/instances/%s/reactivate?error=%%s' % instance_id

        if not new_workers or not new_storage:
            return request.redirect(
                err_redirect % url_quote('Please configure your plan.')
            )

        from odoo.addons.saas_website.controllers.main import SaasWebsite
        if instance_sudo.is_hosting:
            config = SaasWebsite._get_hosting_plan_config(self)
        else:
            config = SaasWebsite._get_custom_plan_config(self)
        # Enforce minimum = previous plan resources
        old_plan = instance_sudo.plan_id
        min_workers = old_plan.workers if old_plan else config['min_workers']
        min_storage = int(old_plan.storage_limit) if old_plan else config['min_storage']
        new_workers = max(min_workers, min(new_workers, config['max_workers']))
        new_storage = max(min_storage, min(new_storage, config['max_storage']))

        # Find or create the plan
        product = instance_sudo.saas_product_id
        if instance_sudo.is_hosting:
            new_plan = SaasWebsite._get_or_create_hosting_plan(
                self, product, new_workers, new_storage, config,
            )
        else:
            new_plan = SaasWebsite._get_or_create_custom_plan(
                self, product, new_workers, new_storage, config,
            )

        try:
            instance_sudo.action_reactivate(new_plan.id, billing_period)
        except UserError as e:
            return request.redirect(
                err_redirect % url_quote(str(e))
            )

        # Redirect to checkout if there's an unpaid invoice, else to detail
        if (instance_sudo.sale_order_id
                and instance_sudo.sale_order_id.invoice_ids.filtered(
                    lambda i: i.state == 'posted'
                    and i.payment_state not in ('paid', 'in_payment')
                    and i.amount_residual > 0
                )):
            return request.redirect(
                '/my/instances/%s/checkout' % instance_id
            )
        return request.redirect('/my/instances/%s' % instance_id)

    # ==================== Instance Folders ====================

    @http.route(
        '/my/instances/folder/create',
        type='json', auth='user', website=True,
    )
    def portal_folder_create(self, name, parent_id=False, **kw):
        """Create a new instance folder, optionally nested under parent_id."""
        name = (name or '').strip()
        if not name:
            return {'error': _('Folder name is required.')}
        partner = request.env.user.partner_id
        vals = {
            'name': name,
            'partner_id': partner.id,
        }
        if parent_id:
            parent = request.env['saas.instance.folder'].sudo().search([
                ('id', '=', int(parent_id)),
                ('partner_id', '=', partner.id),
            ], limit=1)
            if parent:
                vals['parent_id'] = parent.id
        folder = request.env['saas.instance.folder'].sudo().create(vals)
        return {'success': True, 'folder_id': folder.id, 'name': folder.name}

    @http.route(
        '/my/instances/folder/<int:folder_id>/rename',
        type='json', auth='user', website=True,
    )
    def portal_folder_rename(self, folder_id, name, **kw):
        """Rename an instance folder."""
        name = (name or '').strip()
        if not name:
            return {'error': _('Folder name is required.')}
        partner = request.env.user.partner_id
        folder = request.env['saas.instance.folder'].sudo().search([
            ('id', '=', folder_id),
            ('partner_id', '=', partner.id),
        ], limit=1)
        if not folder:
            return {'error': _('Folder not found.')}
        folder.name = name
        return {'success': True, 'folder_id': folder.id, 'name': folder.name}

    @http.route(
        '/my/instances/folder/<int:folder_id>/delete',
        type='json', auth='user', website=True,
    )
    def portal_folder_delete(self, folder_id, **kw):
        """Delete a folder and all subfolders. Instances are moved to unfiled."""
        partner = request.env.user.partner_id
        folder = request.env['saas.instance.folder'].sudo().search([
            ('id', '=', folder_id),
            ('partner_id', '=', partner.id),
        ], limit=1)
        if not folder:
            return {'error': _('Folder not found.')}
        if folder.child_ids:
            return {'error': _('Cannot delete a folder that has subfolders. Delete or move the subfolders first.')}
        # Move instances in this folder to unfiled
        folder.instance_ids.write({'folder_id': False})
        folder.unlink()
        return {'success': True}

    @http.route(
        '/my/instances/move',
        type='json', auth='user', website=True,
    )
    def portal_instance_move_to_folder(self, instance_ids, folder_id=False, **kw):
        """Move instances to a folder (or unfiled if folder_id is False)."""
        partner = request.env.user.partner_id
        Instance = request.env['saas.instance'].sudo()
        instances = Instance.search([
            ('id', 'in', instance_ids),
            ('partner_id', '=', partner.id),
        ])
        if not instances:
            return {'error': _('No instances found.')}
        if folder_id:
            folder = request.env['saas.instance.folder'].sudo().search([
                ('id', '=', folder_id),
                ('partner_id', '=', partner.id),
            ], limit=1)
            if not folder:
                return {'error': _('Folder not found.')}
        instances.write({'folder_id': folder_id or False})
        return {'success': True}
