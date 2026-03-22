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

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    def _get_trial_info(self):
        """Return (trial_available, trial_days) for the current user."""
        if request.env.user._is_public():
            return False, 0
        partner = request.env.user.partner_id.sudo()
        trial_days = int(request.env['ir.config_parameter'].sudo().get_param(
            'saas_master.trial_days', '14',
        ))
        trial_available = not partner.saas_trial_used and trial_days > 0
        return trial_available, trial_days

    # ==================================================================
    #  1. Services Catalog  –  /services
    # ==================================================================

    @http.route('/services', type='http', auth='public', website=True, sitemap=True)
    def services_page(self, **kw):
        """Browse all published SaaS service products."""
        products = request.env['saas.product'].sudo().search([
            ('is_published', '=', True),
        ], order='sequence, id')

        return request.render('saas_website.services_page', {
            'products': products,
        })

    # ==================================================================
    #  2. Service Detail / Plan Selection  –  /services/<id>
    # ==================================================================

    @http.route('/services/<int:product_id>', type='http', auth='public',
                website=True, sitemap=True)
    def service_plans(self, product_id, **kw):
        """Show available plans for the selected service."""
        product = request.env['saas.product'].sudo().browse(product_id)
        if not product.exists() or not product.is_published:
            return request.redirect('/services')

        plans = product.plan_ids.sorted('sequence')

        trial_available, trial_days = self._get_trial_info()

        return request.render('saas_website.service_plans_page', {
            'product': product,
            'plans': plans,
            'trial_available': trial_available,
            'trial_days': trial_days,
        })

    # ==================================================================
    #  3. Configure Instance  –  /services/<id>/plans/<plan_id>/configure
    # ==================================================================

    @http.route('/services/<int:product_id>/plans/<int:plan_id>/configure',
                type='http', auth='user', website=True)
    def service_configure(self, product_id, plan_id, error=None, **kw):
        product = request.env['saas.product'].sudo().browse(product_id)
        plan = request.env['saas.plan'].sudo().browse(plan_id)
        if (not product.exists() or not product.is_published
                or not plan.exists()
                or plan.saas_product_id.id != product.id):
            return request.redirect('/services')

        is_trial = kw.get('trial') == '1'
        domains = request.env['saas.based.domain'].sudo().search([])
        versions = request.env['saas.odoo.version'].sudo().search([])

        return request.render('saas_website.service_configure_form', {
            'product': product,
            'plan': plan,
            'domains': domains,
            'versions': versions,
            'error': error,
            'is_trial': is_trial,
            'form_values': kw,
        })

    # ==================================================================
    #  4. Process Order  –  /services/order
    # ==================================================================

    @http.route('/services/order', type='http', auth='user', website=True,
                methods=['POST'], csrf=True)
    def service_order(self, **post):
        product_id = int(post.get('product_id', 0))
        plan_id = int(post.get('plan_id', 0))
        subdomain = (post.get('subdomain') or '').strip().lower()
        domain_id = int(post.get('domain_id', 0))
        version_id = int(post.get('odoo_version_id', 0))

        product = request.env['saas.product'].sudo().browse(product_id)
        plan = request.env['saas.plan'].sudo().browse(plan_id)
        if (not product.exists() or not product.is_published
                or not plan.exists()
                or plan.saas_product_id.id != product.id):
            return request.redirect('/services')

        # --- Subdomain validation ---
        if not subdomain or not SUBDOMAIN_RE.match(subdomain):
            return self.service_configure(
                product_id, plan_id,
                error=_("Invalid subdomain. Use only lowercase letters, digits, "
                        "and hyphens (max 63 chars, must start/end with alphanumeric)."),
                **post,
            )

        # Check uniqueness
        existing = request.env['saas.instance'].sudo().search([
            ('subdomain', '=', subdomain),
            ('domain_id', '=', domain_id),
            ('state', 'in', _ACTIVE_STATES),
        ], limit=1)
        if existing:
            return self.service_configure(
                product_id, plan_id,
                error=_("The subdomain '%s' is already taken. "
                        "Please choose another.") % subdomain,
                **post,
            )

        # --- Validate references ---
        domain = request.env['saas.based.domain'].sudo().browse(domain_id)
        version = request.env['saas.odoo.version'].sudo().browse(version_id)
        if not domain.exists() or not version.exists():
            return self.service_configure(
                product_id, plan_id,
                error=_("Please select a valid domain and Odoo version."),
                **post,
            )

        partner = request.env.user.partner_id
        is_trial = post.get('is_trial') == '1'

        # --- Rate limiting ---
        max_instances = int(request.env['ir.config_parameter'].sudo().get_param(
            'saas_master.max_instances_per_user', '5',
        ))
        if max_instances > 0:
            active_count = request.env['saas.instance'].sudo().search_count([
                ('partner_id', '=', partner.id),
                ('state', 'in', _ACTIVE_STATES),
            ])
            if active_count >= max_instances:
                return self.service_configure(
                    product_id, plan_id,
                    error=_("You have reached the maximum number of instances (%d). "
                            "Please delete or cancel an existing one first.") % max_instances,
                    **post,
                )

        # --- Trial: one per client ---
        if is_trial:
            partner_sudo = partner.sudo()
            if partner_sudo.saas_trial_used:
                return self.service_configure(
                    product_id, plan_id,
                    error=_("You have already used your free trial."),
                    **post,
                )

        # --- Validate infrastructure ---
        docker_servers = request.env['saas.container.physical.server'].sudo().search([], limit=1)
        db_servers = request.env['saas.psql.physical.server'].sudo().search([], limit=1)
        if not docker_servers or not db_servers:
            return self.service_configure(
                product_id, plan_id,
                error=_("Service is temporarily unavailable. "
                        "No infrastructure servers are configured. "
                        "Please contact support."),
                **post,
            )

        # --- Create instance ---
        try:
            vals = {
                'subdomain': subdomain,
                'domain_id': domain.id,
                'partner_id': partner.id,
                'saas_product_id': product.id,
                'plan_id': plan.id,
                'odoo_version_id': version.id,
            }
            if is_trial:
                vals['is_trial'] = True

            instance = request.env['saas.instance'].sudo().create(vals)
            instance._auto_assign_infrastructure()

            if is_trial:
                # Trial: skip billing, deploy immediately
                instance.action_deploy()
                return request.redirect('/my/instances/%s?access_token=%s' % (
                    instance.id, instance.access_token,
                ))

            # Paid: billing + auto-deploy flow
            instance.action_confirm_and_bill()

            # If free plan: auto-deployed already
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
            return self.service_configure(
                product_id, plan_id,
                error=str(e),
                **post,
            )

    # ==================================================================
    #  Legacy: keep /plans as redirect to /services
    # ==================================================================

    @http.route('/plans', type='http', auth='public', website=True, sitemap=False)
    def plans_page_redirect(self, **kw):
        return request.redirect('/services', code=301)

    # ==================================================================
    #  Subdomain Availability Check (unchanged)
    # ==================================================================

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
