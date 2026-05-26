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

    def _section_enabled(self, name):
        """Return True if the ``Services`` / ``Hosting`` section is enabled
        in settings. Default-on so a fresh install behaves like before.

        ``name`` is ``'services'`` or ``'hosting'``.
        """
        key = 'saas_master.show_%s_section' % name
        return request.env['ir.config_parameter'].sudo().get_param(
            key, 'True',
        ) != 'False'

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
        if not self._section_enabled('services'):
            return request.redirect('/')
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
        if not self._section_enabled('services'):
            return request.redirect('/')
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
        if not self._section_enabled('services'):
            return request.redirect('/')
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
        if not self._section_enabled('services'):
            return request.redirect('/')
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
        if not self._section_enabled('services'):
            return request.redirect('/')
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
        if not self._section_enabled('services'):
            return request.redirect('/')
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
        if not self._section_enabled('services'):
            return request.redirect('/')
        return request.redirect('/services', code=301)

    # ==================================================================
    #  Customer Documentation  –  /docs
    # ==================================================================
    @http.route('/docs', type='http', auth='public', website=True, sitemap=True)
    def docs_page(self, **kw):
        """Render the customer-facing how-to documentation."""
        return request.render('saas_website.portal_docs_page', {})

    # ==================================================================
    #  Fix: force-apply Arabic translations  –  /saas/fix-arabic-translations
    # ==================================================================
    @http.route(
        '/saas/fix-arabic-translations',
        type='http', auth='user', website=True,
        sitemap=False, multilang=False,
    )
    def saas_fix_arabic_translations(self, **kwargs):
        """Force-apply the Arabic translation dictionary to every
        saas_website view, with a verbose report. Use this when the
        migration didn't load translations and the customer-facing
        text is still English under /ar/."""
        if not request.env.user.has_group('base.group_user'):
            return request.make_response(
                'Forbidden — must be an internal user.',
                headers=[('Content-Type', 'text/plain; charset=utf-8')],
                status=403,
            )

        from odoo.addons.saas_website.i18n.ar_translations import (
            TRANSLATIONS,
        )
        out = []
        out.append('=== SAAS FIX-ARABIC-TRANSLATIONS ===')
        out.append('Dictionary entries: %d' % len(TRANSLATIONS))

        ordered = sorted(TRANSLATIONS.items(), key=lambda kv: -len(kv[0]))

        IrModelData = request.env['ir.model.data'].sudo()
        view_ids = IrModelData.search([
            ('module', '=', 'saas_website'),
            ('model', '=', 'ir.ui.view'),
        ]).mapped('res_id')
        out.append('saas_website views found: %d' % len(view_ids))

        View = request.env['ir.ui.view'].sudo()
        views = View.browse(view_ids).exists()

        applied = 0
        no_match = 0
        failed = 0
        for view in views:
            try:
                source = view.with_context(lang='en_US').arch_db or ''
            except Exception as e:
                out.append('  ! Could not read en_US arch_db for view %s: %s' % (view.id, e))
                failed += 1
                continue
            if not source:
                continue
            translated = source
            replacement_count = 0
            for en, ar in ordered:
                if en in translated:
                    translated = translated.replace(en, ar)
                    replacement_count += 1
            if translated == source:
                no_match += 1
                continue
            try:
                view.with_context(lang='ar_001').write({'arch_db': translated})
                applied += 1
                xmlid = view.xml_id or '(no xmlid, id=%s)' % view.id
                out.append('  ✓ %s — %d strings replaced' % (xmlid, replacement_count))
            except Exception as e:
                failed += 1
                out.append('  ✗ view id=%s — write FAILED: %s' % (view.id, e))

        request.env.cr.commit()
        # Bust ormcache so the next read picks up the new translations.
        try:
            request.env.registry.clear_cache()
            out.append('Cleared registry cache.')
        except Exception as e:
            out.append('Could not clear cache: %s' % e)

        out.append('')
        out.append('Summary:')
        out.append('  Views with translations written: %d' % applied)
        out.append('  Views with no matching strings:  %d' % no_match)
        out.append('  Views that failed:               %d' % failed)
        out.append('')

        # Verify by reading back one specific known string.
        try:
            layout = request.env.ref(
                'saas_website.cloudodoo_layout', raise_if_not_found=False,
            )
            if layout:
                en_arch = layout.with_context(lang='en_US').arch_db
                ar_arch = layout.with_context(lang='ar_001').arch_db
                out.append('Verification — cloudodoo_layout:')
                out.append('  en_US contains "Hosting": %s' % ('Hosting' in (en_arch or '')))
                out.append('  ar_001 contains "الاستضافة": %s' % ('الاستضافة' in (ar_arch or '')))
                out.append('  ar_001 still contains "Hosting": %s' % ('Hosting' in (ar_arch or '')))
        except Exception as e:
            out.append('Verification failed: %s' % e)

        return request.make_response(
            '\n'.join(out),
            headers=[('Content-Type', 'text/plain; charset=utf-8')],
        )

    # ==================================================================
    #  Fix: force-add Arabic to the current website  –  /saas/fix-arabic
    # ==================================================================
    # Manual one-click fix in case the migration script's
    # ``website.write({'language_ids': [(4, lang.id)]})`` line didn't
    # persist (we've seen this happen in some Odoo 18.x builds where
    # the m2m write needs an explicit cr.commit() inside the migration
    # context, or the write happens against an env that doesn't
    # propagate). Hitting this URL while logged in as a SaaS manager
    # ensures Arabic ends up in every website's language_ids.
    @http.route(
        '/saas/fix-arabic',
        type='http', auth='user', website=True,
        sitemap=False, multilang=False,
    )
    def saas_fix_arabic(self, **kwargs):
        # Restrict to internal users (anyone with backend access).
        # The earlier saas_core.group_saas_manager check was too narrow
        # for an operator running this once during setup.
        if not request.env.user.has_group('base.group_user'):
            return request.make_response(
                'Forbidden — must be an internal user (sign in to the '
                'Odoo backend first).',
                headers=[('Content-Type', 'text/plain; charset=utf-8')],
                status=403,
            )

        Lang = request.env['res.lang'].sudo().with_context(active_test=False)
        ar = Lang.search([('code', '=', 'ar_001')], limit=1)
        out = []
        out.append('=== SAAS FIX-ARABIC ===')

        if not ar:
            out.append('FATAL: ar_001 not found in res.lang.')
            return request.make_response('\n'.join(out), headers=[('Content-Type', 'text/plain; charset=utf-8')])

        if not ar.active:
            ar.write({'active': True})
            request.env.cr.commit()
            out.append('Flipped ar_001.active to True (was False).')
        else:
            out.append('ar_001.active already True.')

        Website = request.env['website'].sudo()
        websites = Website.search([])
        out.append('Found %d website(s).' % len(websites))

        for w in websites:
            current_codes = w.language_ids.mapped('code')
            out.append('--- Website %s (id=%s) ---' % (w.name, w.id))
            out.append('  Before: %s' % current_codes)
            if 'ar_001' in current_codes:
                out.append('  Skipping — Arabic already linked.')
                continue
            try:
                w.write({'language_ids': [(4, ar.id)]})
                request.env.cr.commit()
                # Re-read after commit to confirm persistence.
                w.invalidate_recordset(['language_ids'])
                after_codes = w.language_ids.mapped('code')
                if 'ar_001' in after_codes:
                    out.append('  OK — Arabic linked. After: %s' % after_codes)
                else:
                    out.append(
                        '  WARNING — write returned cleanly but '
                        'language_ids is still %s after commit.' % after_codes
                    )
            except Exception as e:
                request.env.cr.rollback()
                out.append('  FAILED with %s: %s' % (type(e).__name__, e))

        # Bust the cached ``_get_frontend`` so the next request sees
        # the new language list immediately.
        try:
            request.env.registry.clear_cache()
            out.append('Cleared registry cache.')
        except Exception as e:
            out.append('Could not clear cache: %s' % e)

        out.append('')
        out.append('Done. Hit /saas/debug-lang to verify, then try the '
                   'language switcher again.')
        return request.make_response(
            '\n'.join(out),
            headers=[('Content-Type', 'text/plain; charset=utf-8')],
        )

    # ==================================================================
    #  Debug: language configuration  –  /saas/debug-lang
    # ==================================================================
    @http.route(
        '/saas/debug-lang',
        type='http', auth='public', website=True,
        sitemap=False, multilang=False,
    )
    def saas_debug_lang(self, **kwargs):
        """Dump the current language configuration. Hit this to see
        whether Arabic is activated and linked to the website."""
        Lang = request.env['res.lang'].sudo().with_context(active_test=False)
        ar = Lang.search([('code', '=', 'ar_001')], limit=1)
        en = Lang.search([('code', '=', 'en_US')], limit=1)
        website = request.website
        cookie = request.httprequest.cookies.get('frontend_lang')
        lines = [
            '=== SAAS LANGUAGE DEBUG ===',
            'Active context lang: %s' % request.env.lang,
            'frontend_lang cookie: %s' % (cookie or '(not set)'),
            '',
            '--- res.lang records ---',
            'en_US: id=%s active=%s url_code=%r direction=%s' % (
                en.id, en.active, en.url_code, en.direction,
            ),
            'ar_001: id=%s active=%s url_code=%r direction=%s' % (
                ar.id, ar.active, ar.url_code, ar.direction,
            ),
            '',
            '--- Current website ---',
            'website.id: %s' % website.id,
            'website.name: %s' % website.name,
            'website.default_lang_id: id=%s code=%s' % (
                website.default_lang_id.id, website.default_lang_id.code,
            ),
            'website.language_ids: %s' % [
                {'id': l.id, 'code': l.code, 'url_code': l.url_code}
                for l in website.language_ids
            ],
            '',
            'Is ar_001 in website.language_ids? %s' % (
                ar.id in website.language_ids.ids
            ),
            'Module version (installed): %s' % (
                request.env['ir.module.module'].sudo().search(
                    [('name', '=', 'saas_website')], limit=1,
                ).latest_version,
            ),
        ]
        return request.make_response(
            '\n'.join(lines),
            headers=[('Content-Type', 'text/plain; charset=utf-8')],
        )

    # ==================================================================
    #  Language switch  –  /saas/switch-lang/<code>
    # ==================================================================
    # We can't use Odoo's stock /website/lang/<url_code> route because
    # its ``request.redirect()`` doesn't reliably prepend the URL
    # language prefix (``/ar/``) for non-default languages — the
    # cookie gets set but the customer lands back on a URL without
    # the prefix, and Odoo's multilang router treats prefix-less URLs
    # as the default language regardless of the cookie. This route
    # does the prefix-handling explicitly + sets the cookie, so
    # clicking "العربية" actually lands on ``/ar/...`` (or strips
    # ``/ar/`` when switching back to English).
    @http.route(
        '/saas/switch-lang/<string:code>',
        type='http', auth='public', website=True,
        sitemap=False, multilang=False,
    )
    def saas_switch_lang(self, code, r='/', **kwargs):
        Lang = request.env['res.lang'].sudo().with_context(active_test=False)
        # Accept either the full code (``ar_001``) or the short
        # url_code (``ar``) so callers don't have to guess.
        lang = Lang.search(['|', ('code', '=', code), ('url_code', '=', code)], limit=1)
        if not lang or not lang.active:
            return request.redirect('/')

        # Compute the destination path with the right language prefix.
        # Strip any existing language prefix first so switching
        # between non-default languages also works (no double-prefix).
        target = r or '/'
        if not target.startswith('/'):
            target = '/' + target
        # If the website is a multilang site, every language with a
        # non-empty ``url_code`` may appear as a path prefix. Strip
        # whichever one matches the current target so we can apply
        # the new one cleanly.
        website = request.website
        all_langs = website.language_ids
        for other in all_langs:
            if other.url_code:
                pref = '/' + other.url_code
                if target == pref or target.startswith(pref + '/'):
                    target = target[len(pref):] or '/'
                    break

        # Add the new prefix unless this is the website's default
        # language (default lang serves at the root, no prefix).
        if lang != website.default_lang_id and lang.url_code:
            if target == '/':
                target = '/' + lang.url_code
            else:
                target = '/' + lang.url_code + target

        response = request.redirect(target)
        # ``frontend_lang`` is the cookie Odoo's website middleware
        # consults to remember the customer's choice across requests.
        response.set_cookie('frontend_lang', lang.code)
        return response

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
            'daily_backup_price': float(ICP.get_param(
                'saas_master.hosting_daily_backup_price', '5.0',
            )),
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
        if not self._section_enabled('hosting'):
            return request.redirect('/')
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
        if not self._section_enabled('hosting'):
            return request.redirect('/')
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

        # Backup add-on: a hidden checkbox on the form. Trials get it
        # free or not at all (per spec — paid feature only).
        daily_backup = (kw.get('daily_backup') == '1')

        workers_cost = workers * config['worker_price']
        storage_cost = storage * config['storage_price_per_gb']
        backup_cost = config['daily_backup_price'] if daily_backup else 0.0
        monthly_total = workers_cost + storage_cost + backup_cost
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
            'backup_cost': backup_cost,
            'daily_backup': daily_backup,
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
        if not self._section_enabled('hosting'):
            return request.redirect('/')
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
        if not version.docker_image or not version.docker_image_tag:
            return request.redirect(err_redirect % ('Selected+Odoo+version+is+not+properly+configured.+Please+contact+support.'))

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

        # Validate repo URL format (if provided)
        if repo_url:
            if not (repo_url.startswith('https://') or repo_url.startswith('git@')):
                return request.redirect(err_redirect % 'Repository+URL+must+start+with+https://+or+git@')
            if not git_token and ('github.com' in repo_url or 'gitlab.com' in repo_url or 'bitbucket.org' in repo_url):
                # Private repos need a token; public might work without one
                pass  # Allow it — clone will fail with clear error if repo is private

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
                # Paid daily-backup add-on. Trials don't get it.
                'daily_backup_enabled': (
                    not is_trial and post.get('daily_backup') == '1'
                ),
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
