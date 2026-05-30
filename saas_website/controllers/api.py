# -*- coding: utf-8 -*-
"""JSON API consumed by the VELTNEX single-page frontend.

Every endpoint speaks Odoo's ``type='json'`` (JSON-RPC 2.0) protocol and
returns a uniform envelope::

    {"ok": true,  "data": <payload>}
    {"ok": false, "error": "<friendly message>", "code": "<machine code>"}

Auth is the ordinary Odoo session cookie — because the SPA is served from
the same origin (see ``spa.py``), the browser sends it automatically. We
keep ``auth='public'`` on protected endpoints and check the user ourselves
so we can return a clean ``auth_required`` envelope instead of an Odoo
redirect/exception that the SPA would have to special-case.

This controller deliberately contains NO business logic: ordering,
billing, plan changes, and payment all stay on the existing QWeb routes
(``/services/order``, ``/hosting/order``, ``/my/instances/<id>/checkout``,
…). The SPA hands off to those with a normal navigation when money is
involved.
"""
import logging
import re

from odoo import http, fields, _
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.http import request

from odoo.addons.saas_core.models.saas_instance import SUBDOMAIN_RE
from .main import SaasWebsite, _ACTIVE_STATES

_logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PHONE_RE = re.compile(r'^\+?[\d\s\-\(\)]{7,20}$')

# Map account.move payment/state to the four labels the SPA renders.
_INVOICE_STATUS = {
    'paid': 'paid',
    'in_payment': 'paid',
    'partial': 'open',
    'not_paid': 'open',
    'reversed': 'draft',
}

# Map backup state to the SPA's StatusBadge vocabulary.
_BACKUP_STATUS = {'done': 'available', 'running': 'in_progress', 'failed': 'failed'}


def ok(data=None):
    return {'ok': True, 'data': data if data is not None else {}}


def err(message, code='error'):
    return {'ok': False, 'error': message, 'code': code}


class SaasApi(http.Controller):

    # ==================================================================
    #  Auth helpers
    # ==================================================================

    def _user(self):
        """Return the logged-in res.users, or None for the public user."""
        user = request.env.user
        return None if user._is_public() else user

    def _partner(self):
        user = self._user()
        return user.partner_id if user else None

    def _instance(self, instance_id, access_token=None):
        """Authorized sudo recordset for an instance the caller may see.

        Mirrors the portal's ``_document_check_access`` semantics: a
        logged-in owner (record rules) or anyone holding the instance's
        access token. Raises AccessError/MissingError on failure.
        """
        Instance = request.env['saas.instance']
        instance = Instance.browse(int(instance_id))
        if not instance.exists():
            raise MissingError(_("Instance not found."))
        if access_token and instance.sudo().access_token == access_token:
            return instance.sudo()
        # Record-rule check: will raise AccessError if not the owner.
        instance.check_access_rights('read')
        instance.check_access_rule('read')
        return instance.sudo()

    # ==================================================================
    #  Session / account
    # ==================================================================

    @http.route('/saas/api/v1/me', type='json', auth='public')
    def me(self):
        partner = self._partner()
        if not partner:
            return err(_("Please sign in to continue."), 'auth_required')
        return ok(self._serialize_user(partner))

    @http.route('/saas/api/v1/auth/login', type='json', auth='public')
    def login(self, login=None, password=None, **kw):
        if not login or not password:
            return err(_("Email and password are required."), 'invalid')
        try:
            request.session.authenticate(
                request.db,
                {'login': login, 'password': password, 'type': 'password'},
            )
        except Exception:
            return err(
                _("Those credentials don't match an account. Please try again."),
                'invalid_credentials',
            )
        partner = self._partner()
        if not partner:
            return err(_("Sign-in failed. Please try again."), 'invalid_credentials')
        return ok(self._serialize_user(partner))

    @http.route('/saas/api/v1/auth/logout', type='json', auth='public')
    def logout(self):
        request.session.logout(keep_db=True)
        return ok({})

    # ------- Registration (phone OTP, mirrors registration.py) --------

    def _validate_registration(self, p):
        name = (p.get('name') or '').strip()
        email = (p.get('email') or '').strip()
        phone = (p.get('phone') or '').strip()
        password = p.get('password') or ''
        if not name:
            return _("Full name is required.")
        if not email or not EMAIL_RE.match(email):
            return _("A valid email address is required.")
        if not phone or not PHONE_RE.match(phone):
            return _("A valid phone number is required.")
        if not p.get('country_id'):
            return _("Please select your country.")
        if not (p.get('city') or '').strip():
            return _("City is required.")
        if len(password) < 8:
            return _("Password must be at least 8 characters.")
        Users = request.env['res.users'].sudo()
        if Users.search([('login', '=', email)], limit=1):
            return _("An account with this email already exists. Please sign in.")
        Partner = request.env['res.partner'].sudo()
        if Partner.search([('email', '=ilike', email)], limit=1):
            return _("This email address is already registered.")
        if Partner.search([('phone', '=', phone)], limit=1):
            return _("This phone number is already registered.")
        return None

    @http.route('/saas/api/v1/auth/register/start', type='json', auth='public')
    def register_start(self, **p):
        if not request.env.user._is_public():
            return err(_("You're already signed in."), 'already_authenticated')
        error = self._validate_registration(p)
        if error:
            return err(error, 'invalid')
        try:
            otp = request.env['saas.registration.otp'].sudo()._generate_and_send_phone(
                p.get('phone').strip()
            )
        except Exception:
            _logger.exception("Failed to send registration OTP")
            return err(
                _("We couldn't send your verification code. Please try again."),
                'otp_send_failed',
            )
        # TODO: REMOVE before production — exposes the OTP to the client
        # for testing (mirrors registration.py's `debug_phone_otp`).
        return ok({'otp_sent': True, 'debug_otp': otp.code})

    @http.route('/saas/api/v1/auth/register/resend', type='json', auth='public')
    def register_resend(self, phone=None, **kw):
        phone = (phone or '').strip()
        if not phone:
            return err(_("Phone number is required."), 'invalid')
        try:
            otp = request.env['saas.registration.otp'].sudo()._generate_and_send_phone(phone)
        except Exception:
            return err(_("Couldn't resend the code. Please try again."), 'otp_send_failed')
        # TODO: REMOVE before production — exposes the OTP for testing.
        return ok({'otp_sent': True, 'debug_otp': otp.code})

    @http.route('/saas/api/v1/auth/register/verify', type='json', auth='public')
    def register_verify(self, **p):
        phone = (p.get('phone') or '').strip()
        code = (p.get('otp') or '').strip()
        if not code:
            return err(_("Please enter the verification code."), 'invalid')
        OTP = request.env['saas.registration.otp'].sudo()
        if not OTP._verify(phone, code, 'phone'):
            return err(
                _("That code is invalid or expired. Please try again or resend."),
                'otp_invalid',
            )
        # Re-validate (guards against a race between start and verify).
        error = self._validate_registration(p)
        if error:
            return err(error, 'invalid')
        email = p.get('email').strip()
        password = p.get('password')
        try:
            partner_vals = {
                'name': p.get('name').strip(),
                'email': email,
                'phone': phone,
                'city': (p.get('city') or '').strip(),
            }
            if p.get('company_name'):
                partner_vals['company_name'] = p['company_name'].strip()
            if p.get('country_id'):
                partner_vals['country_id'] = int(p['country_id'])
            if p.get('street'):
                partner_vals['street'] = p['street'].strip()
            partner = request.env['res.partner'].sudo().create(partner_vals)
            new_user = request.env['res.users'].sudo().with_context(
                no_reset_password=True,
            ).create({
                'name': p.get('name').strip(),
                'login': email,
                'partner_id': partner.id,
                'groups_id': [(6, 0, [request.env.ref('base.group_portal').id])],
            })
            new_user.password = password
            OTP._cleanup(phone)
            request.env.cr.commit()
            request.session.authenticate(
                request.db,
                {'login': email, 'password': password, 'type': 'password'},
            )
        except Exception as exc:
            _logger.exception("API registration failed for %s", email)
            return err(_("Account creation failed. Please try again."), 'create_failed')
        return ok(self._serialize_user(self._partner()))

    # ==================================================================
    #  Public catalog + pricing
    # ==================================================================

    @http.route('/saas/api/v1/meta', type='json', auth='public')
    def meta(self):
        """One-shot bootstrap data the SPA needs across pages."""
        site = SaasWebsite()
        ICP = request.env['ir.config_parameter'].sudo()
        countries = request.env['res.country'].sudo().search([], order='name')
        domains = request.env['saas.based.domain'].sudo().search([])
        versions = request.env['saas.odoo.version'].sudo().search(
            [('is_hosting_version', '=', True)], order='name desc',
        )
        # Free-trial availability (mirrors the old site). _get_trial_info
        # accounts for trial_days > 0 and whether this user already used
        # their trial; for anonymous visitors it reports availability.
        svc_trial, trial_days = site._get_trial_info()
        host_trial, _hd = site._get_trial_info(hosting=True)
        return ok({
            'hosting_config': site._get_hosting_plan_config(),
            'custom_config': site._get_custom_plan_config(),
            'trial': {
                'days': trial_days,
                'services_available': svc_trial,
                'hosting_available': host_trial,
            },
            'sections': {
                'services': site._section_enabled('services'),
                'hosting': site._section_enabled('hosting'),
            },
            'support_email': ICP.get_param('saas_master.support_email', ''),
            'countries': [{'id': c.id, 'name': c.name, 'code': c.code} for c in countries],
            'domains': [{'id': d.id, 'name': d.name} for d in domains],
            'hosting_versions': [
                {'id': v.id, 'name': v.name} for v in versions
            ],
        })

    @http.route('/saas/api/v1/services', type='json', auth='public')
    def services(self):
        products = request.env['saas.product'].sudo().search([
            ('is_published', '=', True),
            ('is_hosting', '=', False),
        ], order='sequence, id')
        return ok([self._serialize_product(p) for p in products])

    @http.route('/saas/api/v1/services/<int:product_id>', type='json', auth='public')
    def service_detail(self, product_id):
        product = request.env['saas.product'].sudo().browse(product_id)
        if not product.exists() or not product.is_published:
            return err(_("Service not found."), 'not_found')
        return ok(self._serialize_product(product, detail=True))

    @http.route('/saas/api/v1/hosting/calculate', type='json', auth='public')
    def hosting_calculate(self, workers=2, storage=5, billing='monthly'):
        site = SaasWebsite()
        config = site._get_hosting_plan_config()
        return ok(self._price(config, workers, storage, billing))

    @http.route('/saas/api/v1/services/calculate', type='json', auth='public')
    def services_calculate(self, workers=2, storage=5, billing='monthly'):
        site = SaasWebsite()
        config = site._get_custom_plan_config()
        return ok(self._price(config, workers, storage, billing))

    @http.route('/saas/api/v1/check-subdomain', type='json', auth='public')
    def check_subdomain(self, subdomain='', domain_id=0):
        # Delegate to the canonical implementation.
        return ok(SaasWebsite().check_subdomain(subdomain=subdomain, domain_id=domain_id))

    def _price(self, config, workers, storage, billing):
        """Compute one customer-facing total. Per-resource rates stay hidden."""
        workers = max(config['min_workers'], min(int(workers), config['max_workers']))
        storage = max(config['min_storage'], min(int(storage), config['max_storage']))
        monthly = (workers * config['worker_price']
                   + storage * config['storage_price_per_gb'])
        discount = config['yearly_discount_pct'] / 100.0
        yearly = monthly * 12 * (1 - discount)
        yearly_savings = (monthly * 12) - yearly
        is_yearly = billing == 'yearly'
        return {
            'workers': workers,
            'storage': storage,
            'billing': 'yearly' if is_yearly else 'monthly',
            'total': round(yearly if is_yearly else monthly, 2),
            'monthly_equivalent': round(yearly / 12 if is_yearly else monthly, 2),
            'yearly_savings': round(yearly_savings, 2),
            'savings_percent': int(config['yearly_discount_pct']),
            'currency': config['currency'],
            'limits': {
                'workers': {'min': config['min_workers'], 'max': config['max_workers']},
                'storage': {'min': config['min_storage'], 'max': config['max_storage']},
            },
        }

    # ==================================================================
    #  Portal: instances
    # ==================================================================

    @http.route('/saas/api/v1/dashboard', type='json', auth='public')
    def dashboard(self):
        partner = self._partner()
        if not partner:
            return err(_("Please sign in."), 'auth_required')
        Instance = request.env['saas.instance'].sudo()
        instances = Instance.search([
            ('partner_id', '=', partner.id),
            ('state', 'in', _ACTIVE_STATES),
        ], order='create_date desc')
        invoices = self._partner_invoices(partner)
        open_invoices = [i for i in invoices if i.payment_state not in ('paid', 'in_payment')
                         and i.state == 'posted']
        return ok({
            'instances': [self._serialize_instance(i) for i in instances],
            'recent_invoices': [self._serialize_invoice(i) for i in invoices[:5]],
            'stats': {
                'instances': len(instances),
                'running': len(instances.filtered(lambda i: i.state == 'running')),
                'open_invoices': len(open_invoices),
                'outstanding': round(sum(i.amount_residual for i in open_invoices), 2),
            },
        })

    @http.route('/saas/api/v1/instances', type='json', auth='public')
    def instances(self, itype=None):
        partner = self._partner()
        if not partner:
            return err(_("Please sign in."), 'auth_required')
        domain = [
            ('partner_id', '=', partner.id),
            ('state', 'in', _ACTIVE_STATES),
        ]
        if itype == 'services':
            domain.append(('is_hosting', '=', False))
        elif itype == 'hosting':
            domain.append(('is_hosting', '=', True))
        instances = request.env['saas.instance'].sudo().search(
            domain, order='create_date desc',
        )
        return ok([self._serialize_instance(i) for i in instances])

    @http.route('/saas/api/v1/instances/<int:instance_id>', type='json', auth='public')
    def instance_detail(self, instance_id, access_token=None):
        try:
            instance = self._instance(instance_id, access_token)
        except (AccessError, MissingError):
            return err(_("Instance not found."), 'not_found')
        return ok(self._serialize_instance(instance, detail=True))

    @http.route('/saas/api/v1/instances/<int:instance_id>/status',
                type='json', auth='public')
    def instance_status(self, instance_id, access_token=None):
        try:
            instance = self._instance(instance_id, access_token)
        except (AccessError, MissingError):
            return err(_("Instance not found."), 'not_found')
        status = instance._get_status_dict()
        status['usage'] = self._usage(instance)
        return ok(status)

    @http.route('/saas/api/v1/instances/<int:instance_id>/action',
                type='json', auth='public')
    def instance_action(self, instance_id, action=None, access_token=None):
        try:
            instance = self._instance(instance_id, access_token)
        except (AccessError, MissingError):
            return err(_("Instance not found."), 'not_found')
        handlers = {
            'start': instance.action_portal_start,
            'stop': instance.action_portal_stop,
            'restart': instance.action_portal_restart,
            'refresh_usage': instance.action_refresh_usage,
        }
        handler = handlers.get(action)
        if not handler:
            return err(_("Unknown action."), 'invalid')
        try:
            handler()
        except UserError as e:
            return err(str(e), 'action_failed')
        except Exception:
            _logger.exception("Instance action %s failed for %s", action, instance_id)
            return err(_("That action couldn't be completed. Please try again."), 'action_failed')
        return ok(instance._get_status_dict())

    # ==================================================================
    #  Portal: hosting databases
    # ==================================================================

    def _hosting(self, instance_id, access_token=None):
        instance = self._instance(instance_id, access_token)
        if not instance.is_hosting:
            raise AccessError(_("Database management is only available for hosting."))
        return instance

    @http.route('/saas/api/v1/instances/<int:instance_id>/databases',
                type='json', auth='public')
    def db_list(self, instance_id, access_token=None):
        try:
            instance = self._hosting(instance_id, access_token)
        except (AccessError, MissingError):
            return err(_("Instance not found."), 'not_found')
        if instance.state != 'running':
            return ok({'databases': [], 'ready': False, 'state': instance.state})
        try:
            dbs = instance.hosting_db_list()
        except UserError as e:
            return err(str(e), 'list_failed')
        except Exception:
            _logger.exception("DB list failed for %s", instance_id)
            return err(_("We couldn't load your databases right now."), 'list_failed')
        ops = request.env['saas.instance.db.operation'].sudo().search([
            ('instance_id', '=', instance.id),
            ('state', '=', 'running'),
        ])
        return ok({
            'databases': [{'name': d.get('name'), 'login': d.get('login', '')}
                          for d in dbs],
            'ready': True,
            # Instance host (https://<sub>.<domain>). The SPA opens a
            # specific DB at <url>/web?db=<name> — all DBs share the
            # host, so the db must be selected via the query param.
            'url': instance.url or '',
            'pending_ops': [{'db_name': o.db_name, 'operation': o.operation} for o in ops],
        })

    @http.route('/saas/api/v1/instances/<int:instance_id>/databases/create',
                type='json', auth='public')
    def db_create(self, instance_id, name=None, login=None, password=None,
                  access_token=None, **kw):
        try:
            instance = self._hosting(instance_id, access_token)
        except (AccessError, MissingError):
            return err(_("Instance not found."), 'not_found')
        try:
            op = instance.hosting_db_create_async(
                name=name or '', login=login or '',
                password=password or '', lang='en_US', country_code=None,
            )
        except UserError as e:
            return err(str(e), 'create_failed')
        return ok({'db_name': op.db_name})

    @http.route('/saas/api/v1/instances/<int:instance_id>/databases/drop',
                type='json', auth='public')
    def db_drop(self, instance_id, name=None, access_token=None, **kw):
        try:
            instance = self._hosting(instance_id, access_token)
        except (AccessError, MissingError):
            return err(_("Instance not found."), 'not_found')
        try:
            op = instance.hosting_db_drop_async(name=name or '')
        except UserError as e:
            return err(str(e), 'drop_failed')
        return ok({'db_name': op.db_name})

    @http.route('/saas/api/v1/instances/<int:instance_id>/daily-backup/enable',
                type='json', auth='public')
    def daily_backup_enable(self, instance_id, access_token=None, **kw):
        """Create the daily-backup add-on activation invoice and return
        the checkout URL for the customer to pay. Enabling itself happens
        once that invoice is paid (account_move hook)."""
        try:
            instance = self._hosting(instance_id, access_token)
        except (AccessError, MissingError):
            return err(_("Instance not found."), 'not_found')
        try:
            instance.action_purchase_daily_backup()
        except UserError as e:
            return err(str(e), 'enable_failed')
        except Exception:
            _logger.exception("Daily-backup enable failed for %s", instance_id)
            return err(_("We couldn't start the daily-backup checkout. "
                         "Please try again."), 'enable_failed')
        return ok({
            'checkout_url': '/my/instances/%s/daily-backup/checkout' % instance.id,
        })

    @http.route('/saas/api/v1/instances/<int:instance_id>/databases/backup',
                type='json', auth='public')
    def db_backup(self, instance_id, name=None, format=None,
                  access_token=None, **kw):
        try:
            instance = self._hosting(instance_id, access_token)
        except (AccessError, MissingError):
            return err(_("Instance not found."), 'not_found')
        try:
            instance.hosting_db_backup(
                name=name or '',
                backup_format='dump' if format == 'dump' else 'zip',
            )
        except UserError as e:
            return err(str(e), 'backup_failed')
        except Exception:
            _logger.exception("DB backup failed for %s", instance_id)
            return err(_("Couldn't start the backup. Please try again."), 'backup_failed')
        return ok({})

    @http.route('/saas/api/v1/instances/<int:instance_id>/databases/reset-password',
                type='json', auth='public')
    def db_reset_password(self, instance_id, name=None, new_password=None,
                          login=None, access_token=None, **kw):
        try:
            instance = self._hosting(instance_id, access_token)
        except (AccessError, MissingError):
            return err(_("Instance not found."), 'not_found')
        if not new_password or len(new_password) < 6:
            return err(_("Choose a password of at least 6 characters."), 'invalid')
        try:
            reset_login = instance.hosting_db_reset_admin_password(
                name=name or '', new_password=new_password,
                login=(login or '').strip() or None,
            )
        except UserError as e:
            return err(str(e), 'reset_failed')
        return ok({'login': reset_login})

    # ==================================================================
    #  Portal: backups
    # ==================================================================

    @http.route('/saas/api/v1/instances/<int:instance_id>/backups',
                type='json', auth='public')
    def backups(self, instance_id, access_token=None):
        try:
            instance = self._instance(instance_id, access_token)
        except (AccessError, MissingError):
            return err(_("Instance not found."), 'not_found')
        backups = instance.backup_ids.filtered(
            lambda b: b.state in ('done', 'running')
        ).sorted('create_date', reverse=True)[:30]
        return ok([self._serialize_backup(b) for b in backups])

    @http.route('/saas/api/v1/instances/<int:instance_id>/backups/create',
                type='json', auth='public')
    def backup_create(self, instance_id, access_token=None, **kw):
        try:
            instance = self._instance(instance_id, access_token)
        except (AccessError, MissingError):
            return err(_("Instance not found."), 'not_found')
        try:
            instance.action_create_backup()
        except UserError as e:
            return err(str(e), 'backup_failed')
        except Exception:
            _logger.exception("Backup create failed for %s", instance_id)
            return err(_("Couldn't start the backup. Please try again."), 'backup_failed')
        return ok({})

    # ==================================================================
    #  Portal: invoices
    # ==================================================================

    @http.route('/saas/api/v1/invoices', type='json', auth='public')
    def invoices(self):
        partner = self._partner()
        if not partner:
            return err(_("Please sign in."), 'auth_required')
        return ok([self._serialize_invoice(i) for i in self._partner_invoices(partner)])

    @http.route('/saas/api/v1/invoices/<int:invoice_id>', type='json', auth='public')
    def invoice_detail(self, invoice_id):
        partner = self._partner()
        if not partner:
            return err(_("Please sign in."), 'auth_required')
        inv = request.env['account.move'].sudo().browse(invoice_id)
        if not inv.exists() or inv.partner_id != partner:
            return err(_("Invoice not found."), 'not_found')
        return ok(self._serialize_invoice(inv, detail=True))

    def _partner_invoices(self, partner):
        return request.env['account.move'].sudo().search([
            ('partner_id', '=', partner.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '!=', 'cancel'),
        ], order='invoice_date desc, create_date desc')

    # ==================================================================
    #  Serializers
    # ==================================================================

    def _serialize_user(self, partner):
        initials = ''.join(
            w[0] for w in (partner.name or '').split()[:2]
        ).upper() or 'U'
        return {
            'id': partner.id,
            'name': partner.name,
            'email': partner.email or '',
            'company': partner.commercial_company_name or partner.company_name or partner.name,
            'initials': initials,
            'phone': partner.phone or '',
            # Internal (backend) users get a link to the Odoo backend in the
            # SPA account menu — portal users don't. `_serialize_user` is
            # always called for the current user, so env.user is correct.
            'is_internal': request.env.user.has_group('base.group_user'),
        }

    def _usage(self, instance):
        return {
            'cpu': round(instance.cpu_usage_pct or 0.0),
            'ram': round(instance.ram_usage_pct or 0.0),
            'storage': round(instance.storage_usage_pct or 0.0),
        }

    def _serialize_instance(self, instance, detail=False):
        plan = instance.plan_id
        data = {
            'id': instance.id,
            'name': instance.subdomain or instance.name,
            'domain': instance.name or '',
            'url': instance.url or '',
            'region': instance.docker_server_id.name or (
                instance.domain_id.name or ''
            ),
            'version': instance.odoo_version_id.name or '',
            'state': instance.state,
            'state_label': dict(
                instance._fields['state'].selection
            ).get(instance.state, instance.state),
            'workers': plan.workers if plan else 0,
            'storage_gb': int(plan.storage_limit) if plan else 0,
            'billing_cycle': instance.billing_period or 'monthly',
            'created': fields.Datetime.to_string(instance.create_date) if instance.create_date else '',
            'is_hosting': instance.is_hosting,
            'is_trial': instance.is_trial,
            'usage': self._usage(instance),
            'access_token': instance.access_token,
        }
        if detail:
            invoices = instance._get_all_invoices().filtered(
                lambda i: i.state != 'cancel'
            ).sorted('create_date', reverse=True)
            backups = instance.backup_ids.filtered(
                lambda b: b.state in ('done', 'running')
            ).sorted('create_date', reverse=True)[:10]
            data.update({
                'plan_name': plan.name if plan else '',
                'next_invoice_date': fields.Date.to_string(instance.next_invoice_date)
                    if instance.next_invoice_date else '',
                'daily_backup_enabled': instance.daily_backup_enabled,
                'daily_backup_suspended': instance.daily_backup_suspended,
                'daily_backup_pending': bool(instance.daily_backup_pending_invoice_id),
                'daily_backup_price': instance._get_daily_backup_price(),
                'daily_backup_next_invoice_date': fields.Date.to_string(
                    instance.daily_backup_next_invoice_date
                ) if instance.daily_backup_next_invoice_date else '',
                'pending_plan': instance.pending_plan_id.name if instance.pending_plan_id else '',
                'scheduled_plan': instance.scheduled_plan_id.name if instance.scheduled_plan_id else '',
                'backups': [self._serialize_backup(b) for b in backups],
                'invoices': [self._serialize_invoice(i) for i in invoices],
                'has_unpaid_invoice': any(
                    i.state == 'posted' and i.payment_state not in ('paid', 'in_payment')
                    and i.amount_residual > 0 for i in invoices
                ),
                'checkout_url': '/my/instances/%s/checkout' % instance.id,
            })
        return data

    def _serialize_backup(self, b):
        return {
            'id': b.id,
            'label': b.name or _('Backup'),
            'type': 'manual' if b.ephemeral else 'automatic',
            'size_mb': round(b.size_mb or 0.0, 1),
            'created': fields.Datetime.to_string(b.create_date) if b.create_date else '',
            'status': _BACKUP_STATUS.get(b.state, 'available'),
            'download_url': b.download_url or '',
            'is_full_instance': b.is_full_instance,
            'db_name': b.db_name or '',
            'format': b.format or '',
        }

    def _serialize_invoice(self, inv, detail=False):
        if inv.payment_state in ('paid', 'in_payment'):
            status = 'paid'
        elif inv.state == 'draft':
            status = 'draft'
        elif (inv.invoice_date_due and inv.invoice_date_due < fields.Date.today()
              and inv.amount_residual > 0):
            status = 'overdue'
        else:
            status = _INVOICE_STATUS.get(inv.payment_state, 'open')
        instance = request.env['saas.instance'].sudo().search(
            [('sale_order_id', 'in', inv.line_ids.sale_line_ids.order_id.ids)], limit=1,
        )
        data = {
            'id': inv.id,
            'number': inv.name or _('Draft'),
            'status': status,
            'issued': fields.Date.to_string(inv.invoice_date) if inv.invoice_date
                else (fields.Datetime.to_string(inv.create_date) if inv.create_date else ''),
            'due': fields.Date.to_string(inv.invoice_date_due) if inv.invoice_date_due else '',
            'total': round(inv.amount_total, 2),
            'residual': round(inv.amount_residual, 2),
            'currency': inv.currency_id.name or 'USD',
            'currency_symbol': inv.currency_id.symbol or '$',
            'instance_name': instance.subdomain if instance else '',
            'portal_url': inv.get_portal_url(),
            'payable': inv.state == 'posted' and inv.payment_state not in ('paid', 'in_payment')
                       and inv.amount_residual > 0,
        }
        if detail:
            data['lines'] = [{
                'description': line.name,
                'quantity': line.quantity,
                'total': round(line.price_subtotal, 2),
            } for line in inv.invoice_line_ids.filtered(lambda l: l.display_type == False)]
            data['subtotal'] = round(inv.amount_untaxed, 2)
            data['tax'] = round(inv.amount_tax, 2)
        return data

    def _serialize_product(self, product, detail=False):
        data = {
            'id': product.id,
            'name': product.name,
            'tagline': product.subtitle or '',
            'icon': product.icon or 'fa fa-cube',
            'is_hosting': product.is_hosting,
            'image_url': '/web/image/saas.product/%s/image' % product.id if product.image else '',
        }
        if detail:
            data['description'] = product.description or ''
            data['features'] = [
                {'title': f.name, 'description': getattr(f, 'description', '') or ''}
                for f in product.feature_line_ids
            ]
            # Trial plan for this service (if configured), for the
            # "Start free trial" button. Trial plans may be flagged custom,
            # so we look across all plans here, not just the public ones.
            trial_plan = product.plan_ids.filtered(lambda p: p.is_trial_plan)[:1]
            data['trial_plan_id'] = trial_plan.id if trial_plan else 0
            data['plans'] = [{
                'id': p.id,
                'name': p.name,
                'workers': p.workers,
                'storage_gb': int(p.storage_limit),
                'is_trial': p.is_trial_plan,
                'recommended_users': p.recommended_users,
            } for p in product.plan_ids.sorted('sequence') if not p.is_custom]
        else:
            data['highlights'] = [f.name for f in product.feature_line_ids][:3]
        return data
