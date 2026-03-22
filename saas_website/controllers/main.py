import re
from datetime import timedelta

from odoo import http, fields, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

SUBDOMAIN_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')

# States that represent "alive" instances (block subdomain reuse)
_ACTIVE_STATES = (
    'draft', 'pending_payment', 'paid', 'provisioning',
    'running', 'stopped', 'suspended',
)


class SaasWebsite(http.Controller):

    # ==================== Public Pricing Page ====================

    @http.route('/plans', type='http', auth='public', website=True, sitemap=True)
    def plans_page(self, **kw):
        plans = request.env['saas.plan'].sudo().search([
            ('product_id', '!=', False),
        ], order='sequence, id')

        # Check trial eligibility for logged-in users
        trial_available = False
        trial_days = 0
        if not request.env.user._is_public():
            partner = request.env.user.partner_id.sudo()
            trial_days = int(request.env['ir.config_parameter'].sudo().get_param(
                'saas_master.trial_days', '14',
            ))
            trial_available = not partner.saas_trial_used and trial_days > 0

        return request.render('saas_website.plans_page', {
            'plans': plans,
            'trial_available': trial_available,
            'trial_days': trial_days,
        })

    # ==================== Configure Instance ====================

    @http.route('/plans/<int:plan_id>/configure', type='http', auth='user', website=True)
    def plan_configure(self, plan_id, error=None, **kw):
        plan = request.env['saas.plan'].sudo().browse(plan_id)
        if not plan.exists() or not plan.product_id:
            return request.redirect('/plans')

        is_trial = kw.get('trial') == '1'
        domains = request.env['saas.based.domain'].sudo().search([])
        versions = request.env['saas.odoo.version'].sudo().search([])

        return request.render('saas_website.plan_configure_form', {
            'plan': plan,
            'domains': domains,
            'versions': versions,
            'error': error,
            'is_trial': is_trial,
            'form_values': kw,
        })

    # ==================== Process Order ====================

    @http.route('/plans/order', type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def plan_order(self, **post):
        plan_id = int(post.get('plan_id', 0))
        subdomain = (post.get('subdomain') or '').strip().lower()
        domain_id = int(post.get('domain_id', 0))
        version_id = int(post.get('odoo_version_id', 0))

        plan = request.env['saas.plan'].sudo().browse(plan_id)
        if not plan.exists() or not plan.product_id:
            return request.redirect('/plans')

        # Validate subdomain
        if not subdomain or not SUBDOMAIN_RE.match(subdomain):
            return self.plan_configure(
                plan_id,
                error=_("Invalid subdomain. Use only lowercase letters, digits, and hyphens "
                        "(max 63 chars, must start/end with alphanumeric)."),
                **post,
            )

        # Check uniqueness — only active instances block the subdomain
        existing = request.env['saas.instance'].sudo().search([
            ('subdomain', '=', subdomain),
            ('domain_id', '=', domain_id),
            ('state', 'in', _ACTIVE_STATES),
        ], limit=1)
        if existing:
            return self.plan_configure(
                plan_id,
                error=_("The subdomain '%s' is already taken. Please choose another.") % subdomain,
                **post,
            )

        # Validate references
        domain = request.env['saas.based.domain'].sudo().browse(domain_id)
        version = request.env['saas.odoo.version'].sudo().browse(version_id)
        if not domain.exists() or not version.exists():
            return self.plan_configure(
                plan_id,
                error=_("Please select a valid domain and Odoo version."),
                **post,
            )

        partner = request.env.user.partner_id
        is_trial = post.get('is_trial') == '1'

        # ---- Rate limiting: max instances per user ----
        max_instances = int(request.env['ir.config_parameter'].sudo().get_param(
            'saas_master.max_instances_per_user', '5',
        ))
        if max_instances > 0:
            active_count = request.env['saas.instance'].sudo().search_count([
                ('partner_id', '=', partner.id),
                ('state', 'in', _ACTIVE_STATES),
            ])
            if active_count >= max_instances:
                return self.plan_configure(
                    plan_id,
                    error=_("You have reached the maximum number of instances (%d). "
                            "Please delete or cancel an existing instance first.") % max_instances,
                    **post,
                )

        # ---- Trial: one per client (checked atomically in create()) ----
        if is_trial:
            partner_sudo = partner.sudo()
            if partner_sudo.saas_trial_used:
                return self.plan_configure(
                    plan_id,
                    error=_("You have already used your free trial."),
                    **post,
                )

        # ---- Validate infrastructure exists before creating ----
        docker_servers = request.env['saas.container.physical.server'].sudo().search([], limit=1)
        db_servers = request.env['saas.psql.physical.server'].sudo().search([], limit=1)
        if not docker_servers or not db_servers:
            return self.plan_configure(
                plan_id,
                error=_("Service is temporarily unavailable. "
                        "No infrastructure servers are configured. "
                        "Please contact support."),
                **post,
            )

        # Create instance
        try:
            vals = {
                'subdomain': subdomain,
                'domain_id': domain.id,
                'partner_id': partner.id,
                'plan_id': plan.id,
                'odoo_version_id': version.id,
            }
            if is_trial:
                vals['is_trial'] = True

            # create() handles:
            # - SELECT FOR UPDATE on partner for trial atomicity
            # - _sync_partner_trial() to set saas_trial_used + end date
            # - access_token generation
            instance = request.env['saas.instance'].sudo().create(vals)
            instance._auto_assign_infrastructure()

            if is_trial:
                # Trial: skip billing, deploy immediately
                # NOTE: partner trial flags already set by _sync_partner_trial()
                instance.action_deploy()
                return request.redirect('/my/instances/%s?access_token=%s' % (
                    instance.id, instance.access_token,
                ))

            # Paid: billing + auto-deploy flow
            instance.action_confirm_and_bill()

            # If free plan: action_confirm_and_bill auto-deployed, go to portal
            if instance.state in ('provisioning', 'running', 'paid'):
                return request.redirect('/my/instances/%s?access_token=%s' % (
                    instance.id, instance.access_token,
                ))

            # If paid plan: redirect to invoice for payment
            invoice = instance.sale_order_id.invoice_ids[:1]
            if invoice:
                return request.redirect(invoice.get_portal_url())

            return request.redirect('/my/instances/%s?access_token=%s' % (
                instance.id, instance.access_token,
            ))

        except (UserError, ValidationError) as e:
            return self.plan_configure(
                plan_id,
                error=str(e),
                **post,
            )

    # ==================== Subdomain Availability Check ====================

    @http.route('/saas/check-subdomain', type='json', auth='public', website=True)
    def check_subdomain(self, subdomain='', domain_id=0):
        subdomain = (subdomain or '').strip().lower()
        if not subdomain:
            return {'available': False, 'message': ''}

        if not SUBDOMAIN_RE.match(subdomain):
            return {
                'available': False,
                'message': _("Invalid format. Use lowercase letters, digits, and hyphens."),
            }

        # Only active instances block subdomain reuse
        existing = request.env['saas.instance'].sudo().search([
            ('subdomain', '=', subdomain),
            ('domain_id', '=', int(domain_id or 0)),
            ('state', 'in', _ACTIVE_STATES),
        ], limit=1)

        if existing:
            return {
                'available': False,
                'message': _("'%s' is already taken.") % subdomain,
            }

        return {
            'available': True,
            'message': _("'%s' is available!") % subdomain,
        }
