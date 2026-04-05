from datetime import timedelta

from odoo import http, fields, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.saas_core.models.saas_instance import SUBDOMAIN_RE

# States that represent "alive" instances (block subdomain reuse)
_ACTIVE_STATES = (
    'draft', 'pending_payment', 'paid', 'pending_provision',
    'provisioning', 'running', 'stopped', 'suspended',
)


class SaasWebsite(http.Controller):

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    def _get_trial_info(self, hosting=False):
        """Return (trial_available, trial_days) for the current user.

        :param hosting: if True, check hosting trial; otherwise service trial.
        """
        trial_days = int(request.env['ir.config_parameter'].sudo().get_param(
            'saas_master.trial_days', '14',
        ))
        if request.env.user._is_public():
            return trial_days > 0, trial_days
        partner = request.env.user.partner_id.sudo()
        if hosting:
            trial_available = not partner.saas_hosting_trial_used and trial_days > 0
        else:
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
            ('is_hosting', '=', False),
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
        trial_plan = all_plans.filtered(lambda p: p.is_trial_plan)[:1]

        trial_available, trial_days = self._get_trial_info()

        custom_config = self._get_custom_plan_config()

        return request.render('saas_website.service_plans_page', {
            'product': product,
            'trial_plan': trial_plan,
            'trial_available': trial_available,
            'trial_days': trial_days,
            'custom_config': custom_config,
        })

    # ==================================================================
    #  3. Configure Instance  –  /services/<id>/plans/<plan_id>/configure
    # ==================================================================

    @http.route('/services/<int:product_id>/plans/<int:plan_id>/configure',
                type='http', auth='public', website=True)
    def service_configure(self, product_id, plan_id, error=None, **kw):
        # Public users must register/login first
        if request.env.user._is_public():
            is_trial = kw.get('trial') == '1'
            params = 'product_id=%d&plan_id=%d' % (product_id, plan_id)
            if is_trial:
                params += '&is_trial=1'
            return request.redirect('/services/register?%s' % params)

        product = request.env['saas.product'].sudo().browse(product_id)
        plan = request.env['saas.plan'].sudo().browse(plan_id)
        if (not product.exists() or not product.is_published
                or not plan.exists()
                or product not in plan.saas_product_ids):
            return request.redirect('/services')

        is_trial = kw.get('trial') == '1'
        billing_period = kw.get('billing', 'monthly')
        if billing_period not in ('monthly', 'yearly'):
            billing_period = 'monthly'
        domains = request.env['saas.based.domain'].sudo().search([])

        return request.render('saas_website.service_configure_form', {
            'product': product,
            'plan': plan,
            'domains': domains,
            'error': error,
            'is_trial': is_trial,
            'billing_period': billing_period,
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
        billing_period = post.get('billing_period', 'monthly')
        if billing_period not in ('monthly', 'yearly'):
            billing_period = 'monthly'

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
            support_email = request.env['ir.config_parameter'].sudo().get_param(
                'saas_master.support_email', ''
            )
            support_msg = (
                _(" Please contact us at %s.") % support_email
                if support_email else _(" Please contact support.")
            )
            return self.service_configure(
                product_id, plan_id,
                error=_("Please select a valid domain.") if not domain.exists()
                       else _("No Odoo version configured for this service.") + support_msg,
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
            support_email = request.env['ir.config_parameter'].sudo().get_param(
                'saas_master.support_email', ''
            )
            support_msg = (
                _("Please contact us at %s.") % support_email
                if support_email else _("Please contact support.")
            )
            return self.service_configure(
                product_id, plan_id,
                error=_("Service is temporarily unavailable. "
                        "No infrastructure servers are configured. ") + support_msg,
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
                'billing_period': billing_period,
            }
            if is_trial:
                vals['is_trial'] = True

            instance = request.env['saas.instance'].sudo().create(vals)

            # Server allocation is handled by _allocate_servers() inside
            # action_deploy(), which enforces capacity limits
            # (max_instances, max_cpu_cores, max_ram_gb) and falls back
            # to overcommit servers only when explicitly allowed from
            # the backend.  Do NOT pre-assign servers here.

            if is_trial:
                # Trial: skip billing, deploy immediately.
                # The partner's trial flag (saas_trial_used) is set inside
                # _do_deploy() only after the deployment actually succeeds,
                # so that a failed deploy does not permanently lock the
                # customer out of their trial.
                instance.action_deploy()
                return request.redirect('/my/instances/%s?access_token=%s' % (
                    instance.id, instance.access_token,
                ))

            # Paid: billing + auto-deploy flow
            instance.action_confirm_and_bill()

            # Redirect to checkout for immediate payment
            return request.redirect('/my/instances/%s/checkout' % instance.id)

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
    #  5. Custom Plan Builder  –  pricing config & calculation
    # ==================================================================

    def _get_custom_plan_config(self):
        """Return custom plan builder configuration from system parameters."""
        ICP = request.env['ir.config_parameter'].sudo()
        return {
            'worker_price': float(ICP.get_param('saas_master.worker_price', '15.0')),
            'storage_price_per_gb': float(ICP.get_param('saas_master.storage_price_per_gb', '0.5')),
            'min_workers': int(ICP.get_param('saas_master.custom_plan_min_workers', '2')),
            'max_workers': int(ICP.get_param('saas_master.custom_plan_max_workers', '8')),
            'min_storage': int(ICP.get_param('saas_master.custom_plan_min_storage', '5')),
            'max_storage': int(ICP.get_param('saas_master.custom_plan_max_storage', '200')),
            'cpu_per_worker': float(ICP.get_param('saas_master.custom_plan_cpu_per_worker', '0.5')),
            'ram_per_worker': int(ICP.get_param('saas_master.custom_plan_ram_per_worker', '512')),
            'min_backups': int(ICP.get_param('saas_master.custom_plan_min_backups', '3')),
            'max_backups': int(ICP.get_param('saas_master.custom_plan_max_backups', '14')),
            'users_per_worker_min': int(ICP.get_param('saas_master.custom_plan_users_per_worker_min', '6')),
            'users_per_worker_max': int(ICP.get_param('saas_master.custom_plan_users_per_worker_max', '10')),
            'yearly_discount_pct': int(ICP.get_param('saas_master.custom_plan_yearly_discount_pct', '20')),
            'currency': request.env.company.currency_id.name or 'USD',
        }

    @http.route('/saas/custom-plan/calculate', type='json', auth='public', website=True)
    def custom_plan_calculate(self, workers=2, storage=5):
        """Real-time price calculation for the custom plan builder."""
        config = self._get_custom_plan_config()
        workers = max(config['min_workers'], min(int(workers), config['max_workers']))
        storage = max(config['min_storage'], min(int(storage), config['max_storage']))

        workers_cost = workers * config['worker_price']
        storage_cost = storage * config['storage_price_per_gb']
        monthly_total = workers_cost + storage_cost

        min_users = workers * config['users_per_worker_min']
        max_users = workers * config['users_per_worker_max']

        return {
            'workers': workers,
            'storage': storage,
            'workers_cost': workers_cost,
            'storage_cost': storage_cost,
            'monthly_total': monthly_total,
            'yearly_total': monthly_total * 12,
            'min_users': min_users,
            'max_users': max_users,
            'currency': config['currency'],
        }

    @http.route('/services/<int:product_id>/custom/configure',
                type='http', auth='public', website=True)
    def service_custom_configure(self, product_id, workers=4, storage=20,
                                 billing='monthly', error=None, **kw):
        """Configure instance page for a custom plan."""
        if request.env.user._is_public():
            params = 'product_id=%d&custom=1&workers=%s&storage=%s&billing=%s' % (
                product_id, workers, storage, billing,
            )
            return request.redirect('/services/register?%s' % params)

        product = request.env['saas.product'].sudo().browse(product_id)
        if not product.exists() or not product.is_published:
            return request.redirect('/services')

        billing_period = billing if billing in ('monthly', 'yearly') else 'monthly'

        config = self._get_custom_plan_config()
        workers = max(config['min_workers'], min(int(workers), config['max_workers']))
        storage = max(config['min_storage'], min(int(storage), config['max_storage']))

        workers_cost = workers * config['worker_price']
        storage_cost = storage * config['storage_price_per_gb']
        monthly_total = workers_cost + storage_cost

        discount = config['yearly_discount_pct'] / 100.0
        if billing_period == 'yearly':
            yearly_total = monthly_total * 12 * (1 - discount)
            display_total = yearly_total
            yearly_savings = (monthly_total * 12) - yearly_total
        else:
            yearly_total = monthly_total * 12
            display_total = monthly_total
            yearly_savings = 0

        domains = request.env['saas.based.domain'].sudo().search([])

        return request.render('saas_website.service_custom_configure_form', {
            'product': product,
            'domains': domains,
            'error': error,
            'workers': workers,
            'storage': storage,
            'workers_cost': workers_cost,
            'storage_cost': storage_cost,
            'monthly_total': monthly_total,
            'yearly_total': yearly_total,
            'display_total': display_total,
            'yearly_savings': yearly_savings,
            'billing_period': billing_period,
            'config': config,
            'form_values': kw,
        })

    @http.route('/services/custom-order', type='http', auth='user', website=True,
                methods=['POST'], csrf=True)
    def service_custom_order(self, **post):
        """Process a custom plan order."""
        product_id = int(post.pop('product_id', 0))
        workers = int(post.get('workers', 4))
        storage = int(post.get('storage', 20))
        subdomain = (post.get('subdomain') or '').strip().lower()
        domain_id = int(post.get('domain_id', 0))
        billing_period = post.get('billing_period', 'monthly')
        if billing_period not in ('monthly', 'yearly'):
            billing_period = 'monthly'

        product = request.env['saas.product'].sudo().browse(product_id)
        if not product.exists() or not product.is_published:
            return request.redirect('/services')

        config = self._get_custom_plan_config()
        workers = max(config['min_workers'], min(workers, config['max_workers']))
        storage = max(config['min_storage'], min(storage, config['max_storage']))

        # Subdomain validation
        if not subdomain or not SUBDOMAIN_RE.match(subdomain):
            return self.service_custom_configure(
                product_id, workers=workers, storage=storage,
                error=_("Invalid subdomain. Use only lowercase letters, digits, "
                        "and hyphens (max 63 chars, must start/end with alphanumeric)."),
                **post,
            )

        existing = request.env['saas.instance'].sudo().search([
            ('subdomain', '=', subdomain),
            ('domain_id', '=', domain_id),
            ('state', 'in', _ACTIVE_STATES),
        ], limit=1)
        if existing:
            return self.service_custom_configure(
                product_id, workers=workers, storage=storage,
                error=_("The subdomain '%s' is already taken.") % subdomain,
                **post,
            )

        domain = request.env['saas.based.domain'].sudo().browse(domain_id)
        version = product.odoo_version_id
        if not domain.exists() or not version:
            return self.service_custom_configure(
                product_id, workers=workers, storage=storage,
                error=_("Please select a valid domain.") if not domain.exists()
                       else _("No Odoo version configured for this service."),
                **post,
            )

        partner = request.env.user.partner_id

        # Rate limiting
        max_instances = int(request.env['ir.config_parameter'].sudo().get_param(
            'saas_master.max_instances_per_user', '5',
        ))
        if max_instances > 0:
            active_count = request.env['saas.instance'].sudo().search_count([
                ('partner_id', '=', partner.id),
                ('state', 'in', _ACTIVE_STATES),
            ])
            if active_count >= max_instances:
                return self.service_custom_configure(
                    product_id, workers=workers, storage=storage,
                    error=_("You have reached the maximum number of instances (%d).") % max_instances,
                    **post,
                )

        # Validate infrastructure
        docker_servers = request.env['saas.server'].sudo().search(
            [('is_docker_host', '=', True)], limit=1,
        )
        db_servers = request.env['saas.server'].sudo().search(
            [('is_db_server', '=', True)], limit=1,
        )
        if not docker_servers or not db_servers:
            return self.service_custom_configure(
                product_id, workers=workers, storage=storage,
                error=_("Service is temporarily unavailable."),
                **post,
            )

        # Find or create a matching plan for this custom configuration
        # We look for a plan that matches exactly, or create a dynamic one
        plan = self._get_or_create_custom_plan(product, workers, storage, config)

        instance = None
        try:
            vals = {
                'subdomain': subdomain,
                'domain_id': domain.id,
                'partner_id': partner.id,
                'saas_product_id': product.id,
                'plan_id': plan.id,
                'odoo_version_id': version.id,
                'billing_period': billing_period,
            }
            instance = request.env['saas.instance'].sudo().create(vals)
            instance.action_confirm_and_bill()

            return request.redirect('/my/instances/%s/checkout' % instance.id)

        except (UserError, ValidationError) as e:
            if instance and instance.exists() and instance.state == 'draft':
                instance.unlink()
            return self.service_custom_configure(
                product_id, workers=workers, storage=storage,
                error=str(e),
                **post,
            )

    def _get_or_create_custom_plan(self, product, workers, storage, config):
        """Find or create a plan matching the custom configuration."""
        Plan = request.env['saas.plan'].sudo()
        plan_name = 'Custom (%dW / %dGB)' % (workers, storage)

        monthly_price = (workers * config['worker_price']) + (storage * config['storage_price_per_gb'])

        # Search for existing matching custom plan
        plan = Plan.search([
            ('is_custom', '=', True),
            ('workers', '=', workers),
            ('storage_limit', '=', float(storage)),
            ('price', '=', monthly_price),
            ('saas_product_ids', 'in', product.id),
        ], limit=1)

        if not plan:
            cpu_limit = max(1.0, workers * config['cpu_per_worker'])
            ram_mb = workers * config['ram_per_worker']
            # Format RAM: use 'g' for >= 1024 MB, else 'm'
            if ram_mb >= 1024:
                ram_limit = '%dg' % (ram_mb // 1024)
            else:
                ram_limit = '%dm' % ram_mb

            discount = config['yearly_discount_pct'] / 100.0
            yearly_price = monthly_price * 12 * (1 - discount)
            recommended_users = workers * config['users_per_worker_max']

            # Scale backups based on plan size (0.0 = smallest, 1.0 = largest)
            w_range = max(1, config['max_workers'] - config['min_workers'])
            s_range = max(1, config['max_storage'] - config['min_storage'])
            w_pct = (workers - config['min_workers']) / w_range
            s_pct = (storage - config['min_storage']) / s_range
            plan_size = (w_pct + s_pct) / 2.0
            backup_count = max(config['min_backups'], min(config['max_backups'],
                config['min_backups'] + round(
                    plan_size * (config['max_backups'] - config['min_backups'])
                )
            ))

            plan = Plan.create({
                'name': plan_name,
                'is_custom': True,
                'price': monthly_price,
                'yearly_price': yearly_price,
                'workers': workers,
                'storage_limit': float(storage),
                'cpu_limit': cpu_limit,
                'ram_limit': ram_limit,
                'max_backups': backup_count,
                'recommended_users': recommended_users,
                'saas_product_ids': [(4, product.id)],
                'sequence': 999,
            })

        return plan

    # ==================================================================
    #  Legacy: keep /plans as redirect to /services
    # ==================================================================

    @http.route('/plans', type='http', auth='public', website=True, sitemap=False)
    def plans_page_redirect(self, **kw):
        return request.redirect('/services', code=301)

    # ==================================================================
    #  6. Hosting  –  /hosting
    # ==================================================================

    def _get_hosting_plan_config(self):
        """Return hosting plan builder configuration from system parameters."""
        ICP = request.env['ir.config_parameter'].sudo()
        return {
            'worker_price': float(ICP.get_param('saas_master.hosting_worker_price', '10.0')),
            'storage_price_per_gb': float(ICP.get_param('saas_master.hosting_storage_price_per_gb', '0.3')),
            'min_workers': int(ICP.get_param('saas_master.hosting_min_workers', '2')),
            'max_workers': int(ICP.get_param('saas_master.hosting_max_workers', '8')),
            'min_storage': int(ICP.get_param('saas_master.hosting_min_storage', '5')),
            'max_storage': int(ICP.get_param('saas_master.hosting_max_storage', '200')),
            'cpu_per_worker': float(ICP.get_param('saas_master.hosting_cpu_per_worker', '0.5')),
            'ram_per_worker': int(ICP.get_param('saas_master.hosting_ram_per_worker', '512')),
            'min_backups': int(ICP.get_param('saas_master.hosting_min_backups', '3')),
            'max_backups': int(ICP.get_param('saas_master.hosting_max_backups', '14')),
            'yearly_discount_pct': int(ICP.get_param('saas_master.hosting_yearly_discount_pct', '20')),
            'currency': request.env.company.currency_id.name or 'USD',
        }

    def _get_or_create_hosting_product(self):
        """Get or auto-create the single hosting product record."""
        Product = request.env['saas.product'].sudo()
        product = Product.search([('is_hosting', '=', True)], limit=1)
        if not product:
            product = Product.create({
                'name': 'Cloud Hosting',
                'subtitle': 'Self-managed Odoo hosting',
                'icon': 'fa fa-server',
                'is_hosting': True,
                'is_published': True,
            })
        return product

    def _get_or_create_hosting_plan(self, product, workers, storage, config):
        """Find or create a plan matching the hosting configuration."""
        Plan = request.env['saas.plan'].sudo()
        monthly_price = (workers * config['worker_price']) + (storage * config['storage_price_per_gb'])
        plan_name = 'Hosting (%dW / %dGB)' % (workers, storage)

        plan = Plan.search([
            ('is_custom', '=', True),
            ('workers', '=', workers),
            ('storage_limit', '=', float(storage)),
            ('price', '=', monthly_price),
            ('saas_product_ids', 'in', product.id),
        ], limit=1)

        if not plan:
            cpu_limit = max(1.0, workers * config['cpu_per_worker'])
            ram_mb = workers * config['ram_per_worker']
            ram_limit = '%dg' % (ram_mb // 1024) if ram_mb >= 1024 else '%dm' % ram_mb

            discount = config['yearly_discount_pct'] / 100.0
            yearly_price = monthly_price * 12 * (1 - discount)

            w_range = max(1, config['max_workers'] - config['min_workers'])
            s_range = max(1, config['max_storage'] - config['min_storage'])
            w_pct = (workers - config['min_workers']) / w_range
            s_pct = (storage - config['min_storage']) / s_range
            plan_size = (w_pct + s_pct) / 2.0
            backup_count = max(config['min_backups'], min(config['max_backups'],
                config['min_backups'] + round(plan_size * (config['max_backups'] - config['min_backups']))
            ))

            plan = Plan.create({
                'name': plan_name,
                'is_custom': True,
                'price': monthly_price,
                'yearly_price': yearly_price,
                'workers': workers,
                'storage_limit': float(storage),
                'cpu_limit': cpu_limit,
                'ram_limit': ram_limit,
                'max_backups': backup_count,
                'saas_product_ids': [(4, product.id)],
                'sequence': 999,
            })

        return plan

    def _get_or_create_hosting_trial_plan(self, product, config):
        """Get or create a trial plan for hosting."""
        Plan = request.env['saas.plan'].sudo()
        plan = Plan.search([
            ('is_trial_plan', '=', True),
            ('saas_product_ids', 'in', product.id),
        ], limit=1)

        if not plan:
            plan = Plan.create({
                'name': 'Hosting Trial',
                'is_trial_plan': True,
                'is_custom': True,
                'price': 0,
                'yearly_price': 0,
                'workers': config['min_workers'],
                'storage_limit': float(config['min_storage']),
                'cpu_limit': max(1.0, config['min_workers'] * config['cpu_per_worker']),
                'ram_limit': '%dm' % (config['min_workers'] * config['ram_per_worker']),
                'max_backups': 0,
                'saas_product_ids': [(4, product.id)],
                'sequence': 0,
            })
        return plan

    @http.route('/hosting', type='http', auth='public', website=True, sitemap=True)
    def hosting_page(self, **kw):
        """Hosting landing page with plan builder and version selection."""
        hosting_config = self._get_hosting_plan_config()
        versions = request.env['saas.odoo.version'].sudo().search(
            [('is_hosting_version', '=', True)], order='name desc',
        )
        trial_available, trial_days = self._get_trial_info(hosting=True)

        return request.render('saas_website.hosting_page', {
            'hosting_config': hosting_config,
            'versions': versions,
            'trial_available': trial_available,
            'trial_days': trial_days,
        })

    @http.route('/hosting/configure', type='http', auth='public', website=True)
    def hosting_configure(self, workers=0, storage=0, billing='monthly',
                          odoo_version_id='0', error=None, **kw):
        """Configure hosting instance: subdomain, repo, version."""
        if request.env.user._is_public():
            params = 'hosting=1&workers=%s&storage=%s&billing=%s&odoo_version_id=%s' % (
                workers, storage, billing, odoo_version_id,
            )
            if kw.get('is_trial') == '1':
                params += '&is_trial=1'
            return request.redirect('/services/register?%s' % params)

        billing_period = billing if billing in ('monthly', 'yearly') else 'monthly'
        config = self._get_hosting_plan_config()
        workers = max(config['min_workers'], min(int(workers), config['max_workers']))
        storage = max(config['min_storage'], min(int(storage), config['max_storage']))

        workers_cost = workers * config['worker_price']
        storage_cost = storage * config['storage_price_per_gb']
        monthly_total = workers_cost + storage_cost
        discount = config['yearly_discount_pct'] / 100.0
        yearly_total = monthly_total * 12 * (1 - discount)

        versions = request.env['saas.odoo.version'].sudo().search(
            [('is_hosting_version', '=', True)], order='name desc',
        )
        domains = request.env['saas.based.domain'].sudo().search([])

        # Compute backup count
        w_range = max(1, config['max_workers'] - config['min_workers'])
        s_range = max(1, config['max_storage'] - config['min_storage'])
        plan_size = ((workers - config['min_workers']) / w_range + (storage - config['min_storage']) / s_range) / 2.0
        backup_count = max(config['min_backups'], min(config['max_backups'],
            config['min_backups'] + round(plan_size * (config['max_backups'] - config['min_backups']))
        ))

        return request.render('saas_website.hosting_configure_form', {
            'domains': domains,
            'versions': versions,
            'error': error,
            'workers': workers,
            'storage': storage,
            'workers_cost': workers_cost,
            'storage_cost': storage_cost,
            'monthly_total': monthly_total,
            'yearly_total': yearly_total,
            'backup_count': backup_count,
            'billing_period': billing_period,
            'config': config,
            'odoo_version_id': int(odoo_version_id or 0),
            'form_values': kw,
        })

    @http.route('/hosting/order', type='http', auth='user', website=True,
                methods=['POST'], csrf=True)
    def hosting_order(self, **post):
        """Process a hosting order."""
        workers = int(post.get('workers', 4))
        storage = int(post.get('storage', 20))
        subdomain = (post.get('subdomain') or '').strip().lower()
        domain_id = int(post.get('domain_id', 0))
        billing_period = post.get('billing_period', 'monthly')
        odoo_version_id = int(post.get('odoo_version_id', 0))
        repo_url = (post.get('repo_url') or '').strip()
        repo_branch = (post.get('repo_branch') or 'main').strip()
        git_token = (post.get('git_token') or '').strip()
        pip_packages = (post.get('pip_packages') or '').strip()
        is_trial = post.get('is_trial') == '1'

        if billing_period not in ('monthly', 'yearly'):
            billing_period = 'monthly'

        config = self._get_hosting_plan_config()
        workers = max(config['min_workers'], min(workers, config['max_workers']))
        storage = max(config['min_storage'], min(storage, config['max_storage']))

        err_redirect = '/hosting/configure?workers=%d&storage=%d&billing=%s&odoo_version_id=%d&error=%%s' % (
            workers, storage, billing_period, odoo_version_id,
        )

        # Subdomain validation
        if not subdomain or not SUBDOMAIN_RE.match(subdomain):
            return request.redirect(err_redirect % 'Invalid+subdomain')

        existing = request.env['saas.instance'].sudo().search([
            ('subdomain', '=', subdomain),
            ('domain_id', '=', domain_id),
            ('state', 'in', _ACTIVE_STATES),
        ], limit=1)
        if existing:
            return request.redirect(err_redirect % ('Subdomain+already+taken'))

        # Version validation
        version = request.env['saas.odoo.version'].sudo().browse(odoo_version_id)
        if not version.exists() or not version.is_hosting_version:
            return request.redirect(err_redirect % ('Please+select+an+Odoo+version'))

        domain = request.env['saas.based.domain'].sudo().browse(domain_id)
        if not domain.exists():
            return request.redirect(err_redirect % ('Please+select+a+domain'))

        partner = request.env.user.partner_id

        # Rate limiting
        max_instances = int(request.env['ir.config_parameter'].sudo().get_param(
            'saas_master.max_instances_per_user', '5',
        ))
        if max_instances > 0:
            active_count = request.env['saas.instance'].sudo().search_count([
                ('partner_id', '=', partner.id),
                ('state', 'in', _ACTIVE_STATES),
            ])
            if active_count >= max_instances:
                return request.redirect(err_redirect % ('Maximum+instances+reached'))

        # Infrastructure validation
        docker_servers = request.env['saas.server'].sudo().search(
            [('is_docker_host', '=', True)], limit=1,
        )
        db_servers = request.env['saas.server'].sudo().search(
            [('is_db_server', '=', True)], limit=1,
        )
        if not docker_servers or not db_servers:
            return request.redirect(err_redirect % ('Service+temporarily+unavailable'))

        # Hosting trial: one per client
        if is_trial:
            partner_sudo = partner.sudo()
            if partner_sudo.saas_hosting_trial_used:
                return request.redirect(err_redirect % ('You+have+already+used+your+free+hosting+trial'))

        # Get or create hosting product and plan
        product = self._get_or_create_hosting_product()

        # For trial, use a trial plan
        if is_trial:
            plan = self._get_or_create_hosting_trial_plan(product, config)
        else:
            plan = self._get_or_create_hosting_plan(product, workers, storage, config)

        instance = None
        try:
            vals = {
                'subdomain': subdomain,
                'domain_id': domain.id,
                'partner_id': partner.id,
                'saas_product_id': product.id,
                'plan_id': plan.id,
                'odoo_version_id': version.id,
                'billing_period': billing_period,
                'pip_packages': pip_packages or False,
            }
            if is_trial:
                vals['is_trial'] = True

            instance = request.env['saas.instance'].sudo().create(vals)

            # Create the customer's repository record (if provided)
            if repo_url:
                request.env['saas.instance.repo'].sudo().create({
                    'instance_id': instance.id,
                    'repo_url': repo_url,
                    'branch': repo_branch,
                    'github_token': git_token or False,
                    'webhook_enabled': bool(git_token),
                })

            if is_trial:
                # Trial: skip billing, deploy immediately
                instance.action_deploy()
                return request.redirect('/my/instances/%s?access_token=%s' % (
                    instance.id, instance.access_token,
                ))

            instance.action_confirm_and_bill()

            return request.redirect('/my/instances/%s/checkout' % instance.id)

        except (UserError, ValidationError) as e:
            if instance and instance.exists() and instance.state == 'draft':
                instance.unlink()
            return request.redirect(err_redirect % str(e).replace(' ', '+'))

    @http.route('/saas/hosting-plan/calculate', type='json', auth='public', website=True)
    def hosting_plan_calculate(self, workers=2, storage=5):
        """Real-time price calculation for the hosting plan builder."""
        config = self._get_hosting_plan_config()
        workers = max(config['min_workers'], min(int(workers), config['max_workers']))
        storage = max(config['min_storage'], min(int(storage), config['max_storage']))

        workers_cost = workers * config['worker_price']
        storage_cost = storage * config['storage_price_per_gb']
        monthly_total = workers_cost + storage_cost

        return {
            'workers': workers,
            'storage': storage,
            'workers_cost': workers_cost,
            'storage_cost': storage_cost,
            'monthly_total': monthly_total,
            'yearly_total': monthly_total * 12,
            'currency': config['currency'],
        }

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
