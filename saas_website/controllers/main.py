import re
from datetime import timedelta

from odoo import http, fields, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

SUBDOMAIN_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')

# States that represent "alive" instances (block subdomain reuse)
_ACTIVE_STATES = (
    'draft', 'pending_payment', 'paid', 'pending_provision',
    'provisioning', 'running', 'stopped', 'suspended',
)


class SaasWebsite(http.Controller):

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    def _get_trial_info(self):
        """Return (trial_available, trial_days) for the current user."""
        trial_days = int(request.env['ir.config_parameter'].sudo().get_param(
            'saas_master.trial_days', '14',
        ))
        if request.env.user._is_public():
            # Show trial to public users so they know it's available
            return trial_days > 0, trial_days
        partner = request.env.user.partner_id.sudo()
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

        all_plans = product.plan_ids.sorted('sequence')
        paid_plans = all_plans.filtered(lambda p: not p.is_trial_plan)
        trial_plan = all_plans.filtered(lambda p: p.is_trial_plan)[:1]

        trial_available, trial_days = self._get_trial_info()

        return request.render('saas_website.service_plans_page', {
            'product': product,
            'plans': paid_plans,
            'trial_plan': trial_plan,
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
                or product not in plan.saas_product_ids):
            return request.redirect('/services')

        is_trial = kw.get('trial') == '1'
        domains = request.env['saas.based.domain'].sudo().search([])

        return request.render('saas_website.service_configure_form', {
            'product': product,
            'plan': plan,
            'domains': domains,
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
        product_id = int(post.pop('product_id', 0))
        plan_id = int(post.pop('plan_id', 0))
        subdomain = (post.get('subdomain') or '').strip().lower()
        domain_id = int(post.get('domain_id', 0))

        product = request.env['saas.product'].sudo().browse(product_id)
        plan = request.env['saas.plan'].sudo().browse(plan_id)
        if (not product.exists() or not product.is_published
                or not plan.exists()
                or product not in plan.saas_product_ids):
            return request.redirect('/services')

        # --- Trial / paid plan validation ---
        is_trial = post.get('is_trial') == '1'
        if is_trial and not plan.is_trial_plan:
            return self.service_configure(
                product_id, plan_id,
                error=_("This plan is not available for free trial."),
                **post,
            )
        if not is_trial and plan.is_trial_plan:
            return self.service_configure(
                product_id, plan_id,
                error=_("This plan is only available as a free trial."),
                **post,
            )

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
        version = product.odoo_version_id
        if not domain.exists() or not version:
            return self.service_configure(
                product_id, plan_id,
                error=_("Please select a valid domain.") if not domain.exists()
                       else _("No Odoo version configured for this service. Please contact support."),
                **post,
            )

        partner = request.env.user.partner_id

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
        docker_servers = request.env['saas.server'].sudo().search(
            [('is_docker_host', '=', True)], limit=1,
        )
        db_servers = request.env['saas.server'].sudo().search(
            [('is_db_server', '=', True)], limit=1,
        )
        if not docker_servers or not db_servers:
            return self.service_configure(
                product_id, plan_id,
                error=_("Service is temporarily unavailable. "
                        "No infrastructure servers are configured. "
                        "Please contact support."),
                **post,
            )

        # --- Create instance ---
        instance = None
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
                # Mark trial as used only after successful deploy
                instance._sync_partner_trial()
                return request.redirect('/my/instances/%s?access_token=%s' % (
                    instance.id, instance.access_token,
                ))

            # Paid: billing + auto-deploy flow
            instance.action_confirm_and_bill()

            # Always redirect to instance detail page.
            # - Free/zero-amount: already deploying, shows provisioning progress
            # - Paid: shows "Awaiting Payment" with Pay Now button
            return request.redirect('/my/instances/%s?access_token=%s' % (
                instance.id, instance.access_token,
            ))

        except (UserError, ValidationError) as e:
            # Clean up the draft instance so the user can retry
            if instance and instance.exists() and instance.state == 'draft':
                instance.unlink()
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
