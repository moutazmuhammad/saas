import datetime
import logging
import math
import os
import re
import secrets
import shlex
import string
from dateutil.relativedelta import relativedelta
from jinja2 import Environment, FileSystemLoader

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from ..utils import run_in_background

_logger = logging.getLogger(__name__)

TEMPLATES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'templates',
)

_JINJA_ENV = Environment(
    loader=FileSystemLoader(TEMPLATES_PATH),
    keep_trailing_newline=True,
)

SUBDOMAIN_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')
DB_USER_RE = re.compile(r'^[a-z_][a-z0-9_]*$')


class SaasInstance(models.Model):
    _name = 'saas.instance'
    _description = 'SaaS Instance'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'create_date desc'

    # ========== Identity ==========
    subdomain = fields.Char(
        string='Subdomain',
        required=True,
        tracking=True,
        help='Unique subdomain prefix for this instance (e.g. "acme"). '
             'Combined with the base domain to form the full URL.',
    )
    domain_id = fields.Many2one(
        'saas.based.domain',
        string='Base Domain',
        default=lambda self: self.env['saas.based.domain'].search([], limit=1),
        help='The parent domain under which this instance is hosted '
             '(e.g. "odoo.example.com").',
    )
    name = fields.Char(
        string='Instance Name',
        compute='_compute_name',
        store=True,
        help='Full hostname of the instance, computed from subdomain and base domain.',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        tracking=True,
        help='The customer who owns this Odoo instance.',
    )
    url = fields.Char(
        string='URL',
        compute='_compute_url',
        store=True,
        help='Public HTTPS URL to access this instance.',
    )

    # ========== Service & Plan ==========
    saas_product_id = fields.Many2one(
        'saas.product',
        string='Service',
        tracking=True,
        help='The service/product this instance provides '
             '(e.g. "Pharmacy Management", "POS").',
    )
    plan_id = fields.Many2one(
        'saas.plan',
        string='Plan',
        tracking=True,
        help='Resource plan defining CPU, RAM, and storage limits for this instance.',
    )

    # ========== Infrastructure ==========
    odoo_version_id = fields.Many2one(
        'saas.odoo.version',
        string='Odoo Version',
        tracking=True,
        help='Odoo version and Docker image used by this instance.',
    )

    @api.onchange('saas_product_id')
    def _onchange_saas_product_id(self):
        if self.saas_product_id:
            self.odoo_version_id = self.saas_product_id.odoo_version_id
            if self.plan_id and self.plan_id.saas_product_ids and self.saas_product_id not in self.plan_id.saas_product_ids:
                self.plan_id = False
    docker_server_id = fields.Many2one(
        'saas.server',
        string='Docker Server',
        tracking=True,
        domain="[('is_docker_host', '=', True)]",
        help='Physical server where the Docker container for this instance runs. '
             'Leave empty for automatic allocation based on server capacity.',
    )
    db_server_id = fields.Many2one(
        'saas.server',
        string='Database Server',
        tracking=True,
        domain="[('is_db_server', '=', True)]",
        help='PostgreSQL server that hosts the database for this instance. '
             'Auto-derived from the Docker server topology when left empty.',
    )
    provisioning_mode = fields.Selection(
        selection=[
            ('strict', 'Strict'),
            ('flexible', 'Flexible'),
            ('manual', 'Manual'),
        ],
        string='Provisioning Mode',
        default='flexible',
        required=True,
        help='Controls how servers are allocated for this instance:\n'
             '- Strict: fail if no server has capacity.\n'
             '- Flexible: fallback to overcommit or pending state.\n'
             '- Manual: skip auto-allocation, expect manual assignment.',
    )
    is_overcommitted = fields.Boolean(
        string='Overcommitted',
        default=False,
        readonly=True,
        help='Set automatically when the instance was placed on a server '
             'that exceeded its capacity limits (overcommit fallback).',
    )
    deploy_retry_count = fields.Integer(
        string='Deploy Retries',
        default=0,
        readonly=True,
        help='Number of times deployment has been automatically retried.',
    )
    max_deploy_retries = fields.Integer(
        string='Max Retries',
        default=3,
        help='Maximum automatic deploy retries before marking as permanently failed. '
             '0 = no auto-retry.',
    )
    xmlrpc_port = fields.Integer(
        string='HTTP Port',
        readonly=True,
        help='Host port mapped to the Odoo XML-RPC / HTTP interface inside the container.',
    )
    longpolling_port = fields.Integer(
        string='Longpolling Port',
        readonly=True,
        help='Host port mapped to the Odoo longpolling / websocket interface inside the container.',
    )

    # ========== Credentials ==========
    admin_password = fields.Char(
        string='Admin Master Password',
        readonly=True,
        groups='saas_core.group_saas_manager',
        help='Odoo master password (admin_passwd in odoo.conf). '
             'Used for database management operations.',
    )
    db_user = fields.Char(
        string='Database User',
        readonly=True,
        groups='saas_core.group_saas_manager',
        help='PostgreSQL role name created for this instance.',
    )
    db_password = fields.Char(
        string='Database Password',
        readonly=True,
        groups='saas_core.group_saas_manager',
        help='Password for the PostgreSQL role used by this instance.',
    )

    # ========== Sales & Invoicing ==========
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        tracking=True,
        help='Sale order linked to this instance.',
    )
    sale_order_count = fields.Integer(
        string='Sale Orders',
        compute='_compute_sale_order_count',
    )
    invoice_count = fields.Integer(
        string='Invoices',
        compute='_compute_invoice_count',
    )

    # ========== Hosting ==========
    is_hosting = fields.Boolean(
        string='Hosting Instance',
        compute='_compute_is_hosting',
        store=True,
        help='True if this instance is a self-managed hosting instance.',
    )
    pip_packages = fields.Text(
        string='PyPI Packages',
        help='Python packages to install via pip on container startup. '
             'One package per line (e.g. phonenumbers, openpyxl).',
    )

    @api.depends('saas_product_id.is_hosting')
    def _compute_is_hosting(self):
        for rec in self:
            rec.is_hosting = rec.saas_product_id.is_hosting if rec.saas_product_id else False

    # ========== Free Trial ==========
    is_trial = fields.Boolean(
        string='Free Trial',
        default=False,
        tracking=True,
        help='Whether this instance was created during the client free trial.',
    )

    # ========== Billing Period (per-instance) ==========
    billing_period = fields.Selection(
        [('monthly', 'Monthly'), ('yearly', 'Yearly')],
        string='Billing Period',
        default='monthly',
        help='Billing cycle chosen by the client for this instance.',
    )

    # ========== Pending Upgrade (awaiting payment) ==========
    pending_plan_id = fields.Many2one(
        'saas.plan',
        string='Pending Upgrade Plan',
        help='Plan the client has chosen but not yet paid for. '
             'Applied automatically once payment is confirmed.',
    )
    pending_billing_period = fields.Selection(
        [('monthly', 'Monthly'), ('yearly', 'Yearly')],
        string='Pending Billing Period',
    )


    # ========== Scheduled Downgrade ==========
    scheduled_plan_id = fields.Many2one(
        'saas.plan',
        string='Scheduled Downgrade Plan',
        help='Lower plan to switch to at the end of the current billing cycle.',
    )
    scheduled_billing_period = fields.Selection(
        [('monthly', 'Monthly'), ('yearly', 'Yearly')],
        string='Scheduled Billing Period',
    )

    # ========== Recurring Billing ==========
    next_invoice_date = fields.Date(
        string='Next Invoice Date',
        tracking=True,
        help='Date on which the next recurring invoice will be generated. '
             'Set automatically after the first payment.',
    )
    last_invoice_date = fields.Date(
        string='Last Invoice Date',
        readonly=True,
    )
    suspension_warning_sent = fields.Boolean(
        default=False,
        help='Whether a suspension warning email has been sent for the '
             'current overdue period.',
    )

    # ========== Backups ==========
    backup_ids = fields.One2many(
        'saas.instance.backup', 'instance_id',
        string='Backups',
    )
    backup_count = fields.Integer(
        string='Backup Count', compute='_compute_backup_count',
    )

    # ========== Resource Usage ==========
    cpu_usage = fields.Char(
        string='CPU Usage',
        readonly=True,
        help='CPU usage as percentage of the plan CPU limit.',
    )
    cpu_usage_pct = fields.Float(
        string='CPU Usage %',
        readonly=True,
        help='CPU usage as a float percentage of the plan CPU limit.',
    )
    ram_usage = fields.Char(
        string='RAM Usage',
        readonly=True,
        help='RAM usage (used / plan limit).',
    )
    ram_percent = fields.Char(
        string='RAM %',
        readonly=True,
        help='RAM usage as percentage of the plan RAM limit.',
    )
    ram_usage_pct = fields.Float(
        string='RAM Usage %',
        readonly=True,
        help='RAM usage as a float percentage of the plan RAM limit.',
    )
    storage_usage_pct = fields.Float(
        string='Storage Usage %',
        readonly=True,
        help='Total storage usage as percentage of the plan storage limit.',
    )
    disk_usage = fields.Char(
        string='Container Disk',
        readonly=True,
        help='Disk space used by the instance folder on the Docker server.',
    )
    db_size = fields.Char(
        string='Database Size',
        readonly=True,
        help='Size of the PostgreSQL database on the database server.',
    )
    total_storage = fields.Char(
        string='Total Storage Size',
        readonly=True,
        help='Total storage: container files + PostgreSQL database.',
    )
    disk_usage_bytes = fields.Float(
        string='Container Disk (bytes)',
        readonly=True,
    )
    db_size_bytes = fields.Float(
        string='Database Size (bytes)',
        readonly=True,
    )
    total_storage_bytes = fields.Float(
        string='Total Storage (bytes)',
        readonly=True,
    )
    usage_last_updated = fields.Datetime(
        string='Usage Last Updated',
        readonly=True,
        help='Last time resource usage statistics were refreshed.',
    )

    # ========== Operations ==========
    provisioning_log = fields.Text(
        string='Provisioning Log',
        readonly=True,
        help='Timestamped log of all provisioning and deployment steps.',
    )
    extra_config = fields.Text(
        string='Extra Configuration',
        help='Additional odoo.conf directives, one key = value pair per line. '
             'Lines starting with # are ignored. '
             'Values here override auto-calculated settings (e.g. '
             'limit_memory_soft, limit_memory_hard, limit_time_real).',
    )
    override_docker_cpu = fields.Char(
        string='Docker CPU Override',
        groups='saas_core.group_saas_manager',
        help='Override cpus in docker-compose.yml (e.g. "2.0"). '
             'Leave empty to use the plan default.',
    )
    override_docker_mem = fields.Char(
        string='Docker Memory Override',
        groups='saas_core.group_saas_manager',
        help='Override mem_limit in docker-compose.yml (e.g. "2g", "2500m"). '
             'Leave empty to use the plan-based default (plan RAM × 1.3).',
    )
    override_docker_swap = fields.Char(
        string='Docker Swap Override',
        groups='saas_core.group_saas_manager',
        help='Override memswap_limit in docker-compose.yml (e.g. "3g"). '
             'Leave empty to use the same value as mem_limit. '
             'Set to "-1" for unlimited swap.',
    )

    # ========== Custom Repos ==========
    repo_ids = fields.One2many(
        'saas.instance.repo',
        'instance_id',
        string='Custom Repositories',
    )

    # ========== State ==========
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('pending_payment', 'Pending Payment'),
            ('paid', 'Paid'),
            ('pending_provision', 'Pending Provision'),
            ('provisioning', 'Provisioning'),
            ('running', 'Running'),
            ('stopped', 'Stopped'),
            ('failed', 'Failed'),
            ('suspended', 'Suspended'),
            ('cancelled', 'Cancelled'),
            ('cancelled_by_client', 'Cancelled by Client'),
        ],
        string='Status',
        default='draft',
        tracking=True,
        required=True,
        index=True,
        help='Current lifecycle state of the instance.',
    )
    cancellation_reason = fields.Text(
        string='Cancellation Reason',
        readonly=True,
        help='Details about why and when the instance was cancelled.',
    )
    retained_backup_path = fields.Char(
        string='Retained Backup',
        readonly=True,
        groups='saas_core.group_saas_manager',
        help='Cloud storage path of the most recent backup kept after '
             'instance deletion. Can be used to restore client data if '
             'they return. Not visible to the client.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        help='Company that manages this SaaS instance.',
    )

    # ========== Constraints ==========
    def init(self):
        """Create a partial unique index on subdomain+domain excluding cancelled instances.

        Replaces the old absolute UNIQUE constraint that blocked reuse of
        subdomains from cancelled instances.
        """
        self.env.cr.execute("""
            ALTER TABLE saas_instance
                DROP CONSTRAINT IF EXISTS saas_instance_unique_subdomain_per_domain;
            DROP INDEX IF EXISTS saas_instance_unique_subdomain_per_domain;
            CREATE UNIQUE INDEX saas_instance_unique_subdomain_per_domain
                ON saas_instance (subdomain, domain_id)
                WHERE state NOT IN ('cancelled', 'cancelled_by_client');
        """)

    _sql_constraints = [
        (
            'unique_xmlrpc_port_per_server',
            'UNIQUE(docker_server_id, xmlrpc_port)',
            'HTTP port must be unique per Docker server.',
        ),
        (
            'unique_longpolling_port_per_server',
            'UNIQUE(docker_server_id, longpolling_port)',
            'Longpolling port must be unique per Docker server.',
        ),
    ]

    @api.constrains('is_trial', 'partner_id')
    def _check_one_trial_per_client(self):
        for rec in self:
            if rec.is_trial and rec.partner_id:
                existing = self.search([
                    ('partner_id', '=', rec.partner_id.id),
                    ('is_trial', '=', True),
                    ('id', '!=', rec.id),
                    ('state', 'not in', ('cancelled', 'cancelled_by_client')),
                ], limit=1)
                if existing:
                    raise ValidationError(
                        _("Client '%s' already has a free trial instance (%s). "
                          "Only one trial is allowed per client.")
                        % (rec.partner_id.name, existing.subdomain)
                    )

    @api.constrains('subdomain')
    def _check_subdomain_format(self):
        for rec in self:
            if rec.subdomain and not SUBDOMAIN_RE.match(rec.subdomain):
                raise ValidationError(
                    _("Subdomain '%s' is invalid. Use only lowercase letters, "
                      "digits, and hyphens (max 63 chars, must start/end with alphanumeric).")
                    % rec.subdomain
                )

    # ========== CRUD Overrides ==========

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Block trial if the client has already used their free trial.
            # Separate trials for services vs hosting.
            # Use SELECT ... FOR UPDATE to prevent race conditions.
            if vals.get('is_trial') and vals.get('partner_id'):
                # Determine if this is a hosting trial
                is_hosting_trial = False
                if vals.get('saas_product_id'):
                    product = self.env['saas.product'].browse(vals['saas_product_id'])
                    is_hosting_trial = product.is_hosting

                trial_field = 'saas_hosting_trial_used' if is_hosting_trial else 'saas_trial_used'
                self.env.cr.execute(
                    "SELECT %s FROM res_partner "
                    "WHERE id = %%s FOR UPDATE" % trial_field,
                    (vals['partner_id'],),
                )
                row = self.env.cr.fetchone()
                if row and row[0]:
                    partner = self.env['res.partner'].browse(vals['partner_id'])
                    trial_type = 'hosting' if is_hosting_trial else 'service'
                    raise ValidationError(
                        _("Client '%s' has already used their free %s trial. "
                          "Only one trial per type is allowed.")
                        % (partner.name, trial_type)
                    )
            subdomain = vals.get('subdomain', '')
            if subdomain and not vals.get('db_user'):
                safe_subdomain = subdomain.replace('-', '_').replace('.', '_')
                vals['db_user'] = 'saas_%s' % safe_subdomain
            if not vals.get('db_password'):
                vals['db_password'] = SaasInstance._generate_random_password()
            if not vals.get('admin_password'):
                vals['admin_password'] = SaasInstance._generate_random_password()
        records = super().create(vals_list)
        for rec in records:
            if rec.docker_server_id and (not rec.xmlrpc_port or not rec.longpolling_port):
                rec._auto_assign_ports()
        return records

    def write(self, vals):
        return super().write(vals)

    def unlink(self):
        """Block deletion of instances that have live infrastructure.

        Only draft and cancelled instances (no running infra) can be deleted
        from the database.  Everything else must go through the
        action_delete_instance() teardown workflow first.
        """
        safe_states = ('draft', 'cancelled', 'cancelled_by_client')
        unsafe = self.filtered(lambda r: r.state not in safe_states)
        if unsafe:
            raise UserError(
                _("Cannot delete instances that have been deployed. "
                  "Use the 'Delete' action to tear down infrastructure first.\n"
                  "Affected: %s")
                % ', '.join(unsafe.mapped('subdomain'))
            )
        return super().unlink()

    def _sync_partner_trial(self):
        """Mark the partner as having used their trial (one per type: service / hosting)."""
        self.ensure_one()
        partner = self.partner_id
        trial_days = int(self.env['ir.config_parameter'].sudo().get_param(
            'saas_master.trial_days', '14',
        ))
        if self.is_hosting:
            if not partner.saas_hosting_trial_used:
                partner.write({
                    'saas_hosting_trial_used': True,
                    'saas_trial_end_date': fields.Date.today() + datetime.timedelta(days=trial_days),
                })
        else:
            if not partner.saas_trial_used:
                partner.write({
                    'saas_trial_used': True,
                    'saas_trial_end_date': fields.Date.today() + datetime.timedelta(days=trial_days),
                })

    # ========== Computed ==========
    @api.depends('subdomain', 'domain_id.name')
    def _compute_name(self):
        for rec in self:
            if rec.subdomain and rec.domain_id:
                rec.name = '%s.%s' % (rec.subdomain, rec.domain_id.name)
            else:
                rec.name = rec.subdomain or ''

    @api.depends('subdomain', 'domain_id.name')
    def _compute_url(self):
        for rec in self:
            if rec.subdomain and rec.domain_id:
                rec.url = 'https://%s.%s' % (rec.subdomain, rec.domain_id.name)
            else:
                rec.url = ''

    @api.depends('backup_ids')
    def _compute_backup_count(self):
        data = self.env['saas.instance.backup']._read_group(
            [('instance_id', 'in', self.ids)],
            ['instance_id'],
            ['__count'],
        )
        counts = {instance.id: count for instance, count in data}
        for rec in self:
            rec.backup_count = counts.get(rec.id, 0)

    def _compute_sale_order_count(self):
        for rec in self:
            rec.sale_order_count = 1 if rec.sale_order_id else 0

    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec._get_all_invoices())

    def _get_all_invoices(self):
        """Return all invoices related to this instance across all sale orders.

        Matches sale orders by exact origin patterns to avoid false
        positives (e.g. instance "app" matching "app-pro" orders).
        """
        self.ensure_one()
        instance_ref = self.name or self.subdomain
        if not instance_ref:
            return self.env['account.move']
        # Match all known origin patterns set by this module
        expected_origins = [
            instance_ref,
            _('Renewal: %s') % instance_ref,
            _('Subscription: %s') % instance_ref,
            _('Plan upgrade: %s') % instance_ref,
            _('Data restoration: %s') % instance_ref,
        ]
        domain = [
            ('partner_id', '=', self.partner_id.id),
            '|',
            ('origin', 'in', expected_origins),
            ('id', '=', self.sale_order_id.id if self.sale_order_id else 0),
        ]
        sale_orders = self.env['sale.order'].search(domain)
        if not sale_orders:
            return self.env['account.move']
        return sale_orders.mapped('invoice_ids')

    # ========== Sales & Invoicing Actions ==========

    def _get_billing_product(self):
        """Return the default product.product used on SaaS sale order lines.

        Creates it on first use if it doesn't exist yet.
        """
        product = self.env['product.product'].sudo().search(
            [('default_code', '=', 'SAAS-SUB')], limit=1,
        )
        if not product:
            product = self.env['product.product'].sudo().create({
                'name': 'SaaS Subscription',
                'default_code': 'SAAS-SUB',
                'type': 'service',
                'list_price': 0.0,
                'sale_ok': True,
                'purchase_ok': False,
                'taxes_id': [(5, 0, 0)],
            })
        return product

    def action_confirm_and_bill(self):
        """Validate instance, create sale order, confirm it, and generate invoice.

        This is the single entry point for the billing flow:
        draft → pending_payment (or paid if zero-amount).
        """
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Instance must be in Draft state to confirm and bill."))
        if self.sale_order_id:
            raise UserError(_("A sale order already exists for this instance."))
        if not self.partner_id:
            raise UserError(_("Please set a customer before confirming."))
        if not self.plan_id:
            raise UserError(_("Please set a plan before confirming."))

        plan = self.plan_id
        period = self.billing_period or 'monthly'
        price = plan._get_price_for_period(period)
        period_label = 'Monthly' if period == 'monthly' else 'Yearly'
        # -- Build order lines (respect partner pricelist when available) --
        pricelist = self.partner_id.property_product_pricelist
        order_lines = [(0, 0, {
            'product_id': self._get_billing_product().id,
            'name': _('%s (%s) — %s') % (plan.name, period_label, self.name or self.subdomain),
            'product_uom_qty': 1,
            'price_unit': price,
        })]

        # -- Create & confirm sale order --
        order_vals = {
            'partner_id': self.partner_id.id,
            'origin': self.name or self.subdomain,
            'order_line': order_lines,
        }
        if pricelist:
            order_vals['pricelist_id'] = pricelist.id
        order = self.env['sale.order'].create(order_vals)
        order.action_confirm()
        self.sale_order_id = order

        # -- Create & post invoice --
        invoice = order._create_invoices()
        invoice.action_post()

        # -- Transition state & auto-deploy --
        if invoice.amount_total <= 0:
            self.state = 'paid'
            self._set_next_invoice_date()
            self._append_log(
                "Sale order %s confirmed. Zero-amount invoice — deploying automatically."
                % order.name
            )
            self.message_post(body=_(
                "Sale order %s confirmed. No payment required — deploying now."
            ) % order.name)
            self.action_deploy()
            return True
        else:
            self.state = 'pending_payment'
            self._append_log(
                "Sale order %s confirmed. Invoice %s awaiting payment. "
                "Instance will deploy automatically once paid."
                % (order.name, invoice.name)
            )
            self.message_post(body=_(
                "Sale order %s confirmed. Invoice %s created and awaiting payment. "
                "Instance will deploy automatically once paid."
            ) % (order.name, invoice.name))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_mark_as_paid(self):
        """Manually mark as paid and auto-deploy (for wire transfers, trials, etc.)."""
        self.ensure_one()
        if self.state != 'pending_payment':
            raise UserError(_("Instance must be in 'Pending Payment' state."))
        self.state = 'paid'
        self._append_log("Manually marked as paid. Deploying automatically.")
        self.message_post(body=_("Manually marked as paid — deploying now."))
        self.action_deploy()

    def action_view_sale_order(self):
        """Open the linked sale order."""
        self.ensure_one()
        if not self.sale_order_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_invoices(self):
        """Open all invoices related to this instance."""
        self.ensure_one()
        invoices = self._get_all_invoices()
        if not invoices:
            return
        if len(invoices) == 1:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': invoices.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
            'target': 'current',
        }

    # ========== Private Helpers ==========

    @staticmethod
    def _generate_random_password(length=24):
        """Generate a cryptographically secure random password."""
        alphabet = string.ascii_letters + string.digits + '-_.~+='
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def _generate_db_user(self):
        """Generate a db username based on subdomain."""
        self.ensure_one()
        safe_subdomain = self.subdomain.replace('-', '_').replace('.', '_')
        db_user = 'saas_%s' % safe_subdomain
        if not DB_USER_RE.match(db_user):
            raise ValidationError(
                _("Cannot generate a safe database username from subdomain '%s'.")
                % self.subdomain
            )
        return db_user

    def _get_partner_code(self):
        """Return partner code for folder naming: partnercode_partnername."""
        self.ensure_one()
        code = self.partner_id.ref or str(self.partner_id.id)
        name = self.partner_id.name or ''
        safe_name = name.strip().lower().replace(' ', '_')
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
        return '%s_%s' % (code, safe_name)

    def _get_instance_path(self):
        """Return the full remote path for this instance."""
        self.ensure_one()
        server = self.docker_server_id
        return '%s/%s/%s' % (
            server.docker_base_path.rstrip('/'),
            self._get_partner_code(),
            self.subdomain,
        )

    def _get_container_name(self):
        """Return the Docker container name for this instance."""
        self.ensure_one()
        return 'odoo_%s' % self.subdomain

    def _get_db_host(self):
        """Return the hostname/IP the Odoo container should use to reach PostgreSQL.

        When Docker and DB are on the same server, the container cannot
        reach the host via 127.0.0.1 or the server's own private/public
        IP (DigitalOcean and similar providers block this).  Instead we
        use the Docker bridge gateway (172.17.0.1) which is always
        reachable from containers.

        When they are on different servers, we use the DB server's
        private IP (preferred) or public IP.
        """
        self.ensure_one()
        psql_server = self.db_server_id
        if psql_server == self.docker_server_id:
            return '172.17.0.1'
        return psql_server.private_ip_v4 or psql_server.ip_v4

    def _append_log(self, message):
        """Append a timestamped message to provisioning_log."""
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = '[%s] %s\n' % (timestamp, message)
        current = self.provisioning_log or ''
        self.provisioning_log = current + line

    def _render_template(self, template_name, context):
        """Render a Jinja2 template from the templates/ directory."""
        template = _JINJA_ENV.get_template(template_name)
        return template.render(context)

    def _get_all_addons_paths(self):
        """Return addons paths for odoo.conf from instance and product repos.

        All repos are cloned into the addons/ dir, already mounted at
        /mnt/extra-addons — no extra volume mounts needed.
        """
        self.ensure_one()

        # Instance-level repos
        instance_repos = self.repo_ids.filtered(lambda r: r.state == 'cloned')
        addons_paths = [r._get_container_addons_path() for r in instance_repos]

        # Product-level repos
        product = self.saas_product_id
        if product:
            for pr in product.repo_ids:
                addons_paths.append(pr._get_container_addons_path())

        return addons_paths

    def _parse_extra_config(self):
        """Parse the extra_config text field into a dict."""
        self.ensure_one()
        result = {}
        if self.extra_config:
            for line in self.extra_config.strip().splitlines():
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, _, value = line.partition('=')
                    result[key.strip()] = value.strip()
        return result or None

    def _provision_postgresql(self):
        """Create the PostgreSQL role and database on the database server via SSH."""
        self.ensure_one()
        psql_server = self.db_server_id
        if not psql_server:
            raise UserError(_("No database server configured on this instance."))

        db_user = self.db_user
        db_password = self.db_password
        db_name = self.subdomain

        if not DB_USER_RE.match(db_user):
            raise ValidationError(
                _("Database user '%s' contains unsafe characters.") % db_user
            )
        if not SUBDOMAIN_RE.match(db_name):
            raise ValidationError(
                _("Subdomain '%s' contains unsafe characters for a database name.") % db_name
            )

        sql_script = (
            "DO $body$\n"
            "BEGIN\n"
            "  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = %(user_lit)s) THEN\n"
            "    EXECUTE format('CREATE ROLE %%I WITH LOGIN PASSWORD %%L', %(user_lit)s, %(pass_lit)s);\n"
            "  ELSE\n"
            "    EXECUTE format('ALTER ROLE %%I WITH LOGIN PASSWORD %%L', %(user_lit)s, %(pass_lit)s);\n"
            "  END IF;\n"
            "END $body$;\n"
        ) % {
            'user_lit': "$$%s$$" % db_user,
            'pass_lit': "$$%s$$" % db_password.replace("$$", "$ $"),
        }

        ensure_role_cmd = "sudo -u postgres psql <<'SAAS_END_SQL'\n%s\nSAAS_END_SQL" % sql_script

        create_db_cmd = (
            "sudo -u postgres psql -tc "
            "\"SELECT 1 FROM pg_database WHERE datname='%(db)s'\" "
            "| grep -q 1 "
            "|| sudo -u postgres createdb -O %(user)s %(db)s"
        ) % {'db': db_name, 'user': db_user}

        with psql_server._get_ssh_connection() as ssh:
            self._append_log("Ensuring PostgreSQL role '%s'..." % db_user)
            exit_code, stdout, stderr = ssh.execute(ensure_role_cmd)
            self._append_log(
                "Role command result: exit=%s stdout=%s stderr=%s"
                % (exit_code, stdout.strip(), stderr.strip())
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to create/update PostgreSQL role '%s':\n%s")
                    % (db_user, stderr)
                )

            self._append_log("Ensuring database '%s'..." % db_name)
            exit_code, stdout, stderr = ssh.execute(create_db_cmd)
            self._append_log(
                "DB command result: exit=%s stdout=%s stderr=%s"
                % (exit_code, stdout.strip(), stderr.strip())
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to create database '%s':\n%s")
                    % (db_name, stderr)
                )

    def _ensure_can_ssh(self):
        """Validate that the instance has the necessary server config for SSH."""
        self.ensure_one()
        if not self.docker_server_id:
            raise ValidationError(_("No Docker server configured."))
        server = self.docker_server_id
        if not server.ssh_key_pair_id or not server.ssh_key_pair_id.private_key_file:
            raise ValidationError(
                _("SSH key pair with private key is required on server '%s'.")
                % server.name
            )
        server._get_ssh_ip()

    def _allocate_servers(self):
        """Auto-allocate Docker and DB servers using a multi-level strategy.

        Respects ``provisioning_mode``:
        - **manual**: skip allocation entirely (operator assigns servers).
        - **strict**: Level 1 only — fail hard if no capacity.
        - **flexible** (default): Level 1 → Level 2 → Level 3.

        Levels (flexible mode):
            1. Ideal — least-loaded host with available capacity.
            2. Overcommit — any host with ``allow_overcommit`` enabled,
               ignoring capacity limits.
            3. Pending — no server assigned; instance enters
               ``pending_provision`` state and waits for capacity.

        Returns True if a Docker server was assigned, False if the instance
        was marked as pending (caller should abort deployment).
        """
        self.ensure_one()
        Server = self.env['saas.server']
        mode = self.provisioning_mode or 'flexible'

        # -- Manual mode: operator is responsible for server assignment --
        if mode == 'manual':
            return bool(self.docker_server_id)

        # -- Docker server allocation --
        if not self.docker_server_id:
            plan = self.plan_id

            # Level 1 — Ideal allocation (respect capacity)
            if mode == 'strict':
                self.docker_server_id = Server._allocate_docker_server(
                    plan=plan, raise_on_failure=True,
                )
                self._append_log(
                    "Allocated Docker server (strict): %s"
                    % self.docker_server_id.name
                )
            else:
                server = Server._allocate_docker_server(plan=plan)
                if server:
                    self.docker_server_id = server
                    self._append_log(
                        "Allocated Docker server (ideal): %s" % server.name
                    )
                else:
                    # Level 2 — Overcommit fallback
                    server = Server._allocate_overcommit_server(plan=plan)
                    if server:
                        self.docker_server_id = server
                        self.is_overcommitted = True
                        self._append_log(
                            "Allocated Docker server (overcommit): %s"
                            % server.name
                        )
                        _logger.warning(
                            "Instance %s allocated to overcommitted "
                            "server %s (plan: %s).",
                            self.subdomain, server.name,
                            plan.name if plan else 'none',
                        )
                    else:
                        # Level 3 — No server available → pending
                        self._mark_as_pending()
                        return False

        # -- DB server allocation --
        if not self.db_server_id and self.docker_server_id:
            self._allocate_db_server()

        return True

    def _allocate_db_server(self):
        """Derive the DB server from the Docker host topology.

        Falls back to all-in-one detection, then any DB server.
        """
        self.ensure_one()
        Server = self.env['saas.server']
        docker_srv = self.docker_server_id

        if docker_srv.db_server_id:
            self.db_server_id = docker_srv.db_server_id
        elif docker_srv.is_db_server:
            self.db_server_id = docker_srv
        else:
            db_srv = Server.search(
                [('is_db_server', '=', True)], limit=1,
            )
            if not db_srv:
                if self.provisioning_mode == 'flexible':
                    self._mark_as_pending()
                    return
                raise ValidationError(
                    _("No database server is configured. Please set up a "
                      "DB server or configure one on the Docker host '%s'.")
                    % docker_srv.name
                )
            self.db_server_id = db_srv

        self._append_log(
            "Allocated DB server: %s" % self.db_server_id.name
        )

    def _mark_as_pending(self):
        """Set instance to pending_provision — deployment deferred until
        server capacity becomes available.
        """
        self.ensure_one()
        self.state = 'pending_provision'
        self._append_log(
            "No server available — instance marked as pending provision. "
            "Deployment will be retried automatically when capacity is freed."
        )
        _logger.info(
            "Instance %s moved to pending_provision (no available server).",
            self.subdomain,
        )

    def _auto_assign_ports(self):
        """Auto-assign xmlrpc_port and longpolling_port if not already set."""
        self.ensure_one()
        if self.xmlrpc_port and self.longpolling_port:
            return

        starting_port = int(self.env['ir.config_parameter'].sudo().get_param(
            'saas_master.default_instance_starting_port', '32000',
        ))

        # Lock sibling rows to prevent concurrent port allocation races
        self.env.cr.execute(
            "SELECT xmlrpc_port, longpolling_port FROM saas_instance "
            "WHERE docker_server_id = %s AND id != %s AND xmlrpc_port > 0 "
            "FOR UPDATE",
            (self.docker_server_id.id, self.id or 0),
        )
        used_ports = set()
        for row in self.env.cr.fetchall():
            if row[0]:
                used_ports.add(row[0])
            if row[1]:
                used_ports.add(row[1])

        candidate = starting_port
        while candidate < 65535:
            if candidate not in used_ports and (candidate + 1) not in used_ports:
                break
            candidate += 2

        if candidate >= 65535:
            raise ValidationError(
                _("No available port pair found on server '%s'.")
                % self.docker_server_id.name
            )

        self.xmlrpc_port = candidate
        self.longpolling_port = candidate + 1

    def _validate_deploy_fields(self):
        """Validate all required fields before deployment."""
        self.ensure_one()
        errors = []
        if not self.subdomain:
            errors.append(_("Subdomain is required."))
        if not self.docker_server_id:
            errors.append(_("Docker Server is required."))
        if not self.db_server_id:
            errors.append(_("Database Server is required."))
        if not self.odoo_version_id:
            errors.append(_("Odoo Version is required."))
        if not self.partner_id:
            errors.append(_("Customer is required."))
        if not self.odoo_version_id or not self.odoo_version_id.docker_image:
            errors.append(_("Docker image is not set on the selected Odoo version."))
        if not self.odoo_version_id or not self.odoo_version_id.docker_image_tag:
            errors.append(_("Docker image tag is not set on the selected Odoo version."))
        server = self.docker_server_id
        if server and (not server.ssh_key_pair_id or not server.ssh_key_pair_id.private_key_file):
            errors.append(_("Docker server SSH key pair with private key is required."))
        if server:
            if server.ssh_connect_using == 'private_ip' and not server.private_ip_v4:
                errors.append(_("Docker server Private IP is required (SSH is set to use Private IP)."))
            elif server.ssh_connect_using == 'public_ip' and not server.ip_v4:
                errors.append(_("Docker server Public IP address is required."))
        psql = self.db_server_id
        if psql and (not psql.ssh_key_pair_id or not psql.ssh_key_pair_id.private_key_file):
            errors.append(_("Database server SSH key pair with private key is required."))
        if psql:
            if psql.ssh_connect_using == 'private_ip' and not psql.private_ip_v4:
                errors.append(_("Database server Private IP is required (SSH is set to use Private IP)."))
            elif psql.ssh_connect_using == 'public_ip' and not psql.ip_v4:
                errors.append(_("Database server Public IP address is required."))
            if not psql.private_ip_v4 and not psql.ip_v4:
                errors.append(_("Database server needs at least one IP address for db_host configuration."))
        if errors:
            raise ValidationError('\n'.join(str(e) for e in errors))

    # ========== Resource Usage ==========

    @staticmethod
    def _format_bytes(size_bytes):
        """Format bytes into a human-readable string."""
        if size_bytes < 1024:
            return '%d B' % size_bytes
        elif size_bytes < 1024 ** 2:
            return '%.1f KB' % (size_bytes / 1024.0)
        elif size_bytes < 1024 ** 3:
            return '%.1f MB' % (size_bytes / 1024.0 ** 2)
        else:
            return '%.2f GB' % (size_bytes / 1024.0 ** 3)

    def action_refresh_usage(self):
        """Fetch CPU, RAM, disk, and database size for this instance."""
        for rec in self:
            rec._ensure_can_ssh()
            with rec.docker_server_id._get_ssh_connection() as ssh:
                rec._refresh_usage_with_ssh(ssh)
        return True

    def _safe_refresh_usage(self):
        """Refresh resource usage, silently ignoring errors."""
        try:
            self._ensure_can_ssh()
            with self.docker_server_id._get_ssh_connection() as ssh:
                self._refresh_usage_with_ssh(ssh)
        except Exception:
            _logger.debug(
                "Failed to refresh usage for instance %s", self.subdomain,
                exc_info=True,
            )

    @api.model
    def _cron_refresh_usage(self):
        """Cron: refresh resource usage for all running instances."""
        instances = self.search([('state', '=', 'running')])
        for instance in instances:
            try:
                instance._safe_refresh_usage()
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception(
                    "Cron: failed to refresh usage for %s", instance.subdomain,
                )

    @api.model
    def _cron_retry_pending_provision(self):
        """Cron: attempt to deploy instances stuck in pending_provision.

        For each pending instance, re-runs ``action_deploy()``.  If capacity
        is still unavailable the instance stays in ``pending_provision``;
        otherwise it proceeds to ``provisioning`` normally.
        """
        pending = self.search([('state', '=', 'pending_provision')])
        if not pending:
            return
        _logger.info(
            "Cron: retrying %d pending_provision instance(s).", len(pending),
        )
        for instance in pending:
            try:
                instance.action_deploy()
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception(
                    "Cron: retry failed for pending instance %s",
                    instance.subdomain,
                )

    @staticmethod
    def _parse_ram_string(ram_str):
        """Parse a RAM string like '512m', '1g', '2G' into bytes."""
        if not ram_str:
            return 0
        ram_str = ram_str.strip().lower()
        multipliers = {'k': 1024, 'm': 1024**2, 'g': 1024**3, 't': 1024**4}
        for suffix, mult in multipliers.items():
            if ram_str.endswith(suffix):
                try:
                    return float(ram_str[:-1]) * mult
                except (ValueError, TypeError):
                    return 0
        try:
            return float(ram_str)
        except (ValueError, TypeError):
            return 0

    def _refresh_usage_with_ssh(self, ssh):
        """Fetch resource usage relative to plan limits.

        CPU and RAM are reported as percentages of the plan's allocated
        resources (not the physical server), giving the client a clear
        picture of how much of *their* allocation they are consuming.
        """
        self.ensure_one()
        container_name = self._get_container_name()
        instance_path = self._get_instance_path()
        plan = self.plan_id

        # -- Plan limits --
        plan_cpu = plan.cpu_limit if plan else 0
        plan_ram_bytes = self._parse_ram_string(plan.ram_limit) if plan else 0
        plan_storage_gb = plan.storage_limit if plan else 0

        # -- Fetch container stats via docker stats JSON format --
        stats_cmd = (
            'docker stats --no-stream --format '
            '"{{.CPUPerc}}||{{.MemUsage}}||{{.MemPerc}}" %s'
        ) % shlex.quote(container_name)
        exit_code, stdout, stderr = ssh.execute(stats_cmd)

        raw_cpu_pct = 0.0  # CPU % relative to host (e.g. 150% = 1.5 cores)
        ram_used_bytes = 0
        if exit_code == 0 and stdout.strip():
            parts = stdout.strip().split('||')
            # Parse CPU % (relative to host total CPUs)
            if len(parts) >= 1:
                try:
                    raw_cpu_pct = float(parts[0].strip().replace('%', ''))
                except (ValueError, TypeError):
                    pass
            # Parse RAM used from "XXMiB / YYMiB" or "XXGiB / YYGiB"
            if len(parts) >= 2:
                mem_parts = parts[1].strip().split('/')
                if mem_parts:
                    ram_used_bytes = self._parse_mem_value(mem_parts[0].strip())

        # -- Resource usage multiplier (accounts for shared DB server overhead) --
        ICP = self.env['ir.config_parameter'].sudo()
        usage_multiplier = float(ICP.get_param('saas_master.resource_usage_multiplier', '2.0'))

        # -- Calculate CPU % relative to plan limit --
        # docker stats reports CPU% relative to ALL host cores.
        # E.g. on 8-core host using 1 core = 12.5%.
        # We need to convert: cores_used = raw_cpu_pct / 100
        # Then: plan_cpu_pct = (cores_used / plan_cpu) * 100
        cpu_pct = 0.0
        if plan_cpu > 0 and raw_cpu_pct > 0:
            cores_used = raw_cpu_pct / 100.0
            cpu_pct = min((cores_used * usage_multiplier / plan_cpu) * 100, 999)
        self.cpu_usage = '%.1f%%' % cpu_pct if cpu_pct else '0%'
        self.cpu_usage_pct = round(cpu_pct, 1)

        # -- Calculate RAM % relative to plan limit --
        ram_used_bytes = ram_used_bytes * usage_multiplier
        ram_pct = 0.0
        if plan_ram_bytes > 0 and ram_used_bytes > 0:
            ram_pct = min((ram_used_bytes / plan_ram_bytes) * 100, 999)
        ram_used_str = self._format_bytes(ram_used_bytes) if ram_used_bytes else '0'
        ram_limit_str = plan.ram_limit.upper() if plan and plan.ram_limit else '?'
        self.ram_usage = '%s / %s' % (ram_used_str, ram_limit_str)
        self.ram_percent = '%.1f%%' % ram_pct if ram_pct else '0%'
        self.ram_usage_pct = round(ram_pct, 1)

        # -- Fetch disk usage of the instance folder (in bytes) --
        disk_cmd = 'du -sb %s 2>/dev/null | cut -f1' % shlex.quote(instance_path)
        exit_code, stdout, stderr = ssh.execute(disk_cmd)
        disk_bytes = 0
        if exit_code == 0 and stdout.strip():
            try:
                disk_bytes = int(stdout.strip())
            except (ValueError, TypeError):
                pass
        self.disk_usage = self._format_bytes(disk_bytes) if disk_bytes else ''
        self.disk_usage_bytes = disk_bytes

        # -- Fetch database size from PostgreSQL server (in bytes) --
        db_bytes = 0
        if self.db_server_id and self.subdomain:
            try:
                safe_db = self.subdomain.replace("'", "''")
                with self.db_server_id._get_ssh_connection() as db_ssh:
                    db_size_cmd = (
                        "sudo -u postgres psql -At -c "
                        "\"SELECT pg_database_size('%s');\""
                    ) % safe_db
                    exit_code, stdout, stderr = db_ssh.execute(db_size_cmd)
                    if exit_code == 0 and stdout.strip():
                        try:
                            db_bytes = int(stdout.strip())
                        except (ValueError, TypeError):
                            pass
            except Exception:
                _logger.warning(
                    "Failed to fetch DB size for instance %s", self.subdomain,
                )
        self.db_size = self._format_bytes(db_bytes) if db_bytes else ''
        self.db_size_bytes = db_bytes

        # -- Total storage = disk + db (server-side only) --
        # Cloud backups (S3/GCS) are excluded: they live in external
        # storage, not on the server, and should not count against the
        # instance's plan storage limit.
        total_bytes = disk_bytes + db_bytes
        self.total_storage = self._format_bytes(total_bytes) if total_bytes else ''
        self.total_storage_bytes = total_bytes

        storage_pct = 0.0
        if plan_storage_gb > 0 and total_bytes > 0:
            storage_pct = (total_bytes / (plan_storage_gb * 1024**3)) * 100
        self.storage_usage_pct = round(storage_pct, 1)

        self.usage_last_updated = fields.Datetime.now()

    @staticmethod
    def _parse_mem_value(mem_str):
        """Parse docker stats memory value like '152.4MiB' or '1.5GiB' into bytes."""
        if not mem_str:
            return 0
        mem_str = mem_str.strip().lower()
        multipliers = {
            'kib': 1024, 'mib': 1024**2, 'gib': 1024**3, 'tib': 1024**4,
            'kb': 1000, 'mb': 1000**2, 'gb': 1000**3, 'tb': 1000**4,
            'b': 1,
        }
        for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
            if mem_str.endswith(suffix):
                try:
                    return float(mem_str[:-len(suffix)]) * mult
                except (ValueError, TypeError):
                    return 0
        try:
            return float(mem_str)
        except (ValueError, TypeError):
            return 0

    # ========== Config Rendering (DRY helper) ==========

    def _render_and_write_configs(self, ssh):
        """Render docker-compose.yml and odoo.conf from templates and write them via SSH."""
        self.ensure_one()
        instance_path = self._get_instance_path()
        all_addons_paths = self._get_all_addons_paths()

        # docker-compose.yml
        self._append_log("Writing docker-compose.yml...")
        # When a proxy server is configured, bind ports to 0.0.0.0 so the
        # remote proxy can reach the container.  Otherwise keep 127.0.0.1.
        proxy_server = self.domain_id.proxy_server_id
        # Only bind to 0.0.0.0 when the proxy is on a different machine
        needs_remote_access = proxy_server and proxy_server != self.docker_server_id
        host_ip = '0.0.0.0' if needs_remote_access else '127.0.0.1'
        # Compute memory limits from plan RAM
        plan = self.plan_id
        ram_limit_str = plan.ram_limit if plan else ''
        ram_bytes = self._parse_ram_string(ram_limit_str)
        cpu_limit = plan.cpu_limit if plan else 0
        workers = plan.workers if plan else 2

        # Odoo memory limits per worker:
        #   soft = RAM / max(workers, 1) — recycle after current request
        #   hard = soft * 1.3 — kill worker immediately (last resort)
        # Docker limit = plan RAM * 1.3 — safety net above Odoo hard limit
        if ram_bytes and workers:
            limit_memory_soft = int(ram_bytes / max(workers, 1))
            limit_memory_hard = int(limit_memory_soft * 1.3)
            docker_mem_bytes = int(ram_bytes * 1.3)
        elif ram_bytes:
            limit_memory_soft = int(ram_bytes * 0.8)
            limit_memory_hard = int(ram_bytes)
            docker_mem_bytes = int(ram_bytes * 1.3)
        else:
            limit_memory_soft = 2684354560   # 2.5 GB default
            limit_memory_hard = 3355443200   # ~3.1 GB default
            docker_mem_bytes = 0             # no Docker limit

        # Per-instance overrides take priority over plan-computed values.
        auto_mem = '%dm' % (docker_mem_bytes // (1024 * 1024)) if docker_mem_bytes else ''
        docker_cpu = self.override_docker_cpu.strip() if self.override_docker_cpu else str(cpu_limit) if cpu_limit else ''
        docker_mem = self.override_docker_mem.strip() if self.override_docker_mem else auto_mem
        docker_swap = self.override_docker_swap.strip() if self.override_docker_swap else docker_mem

        # Parse pip packages for hosting instances (deduplicated, lowercase)
        pip_packages_str = ''
        if self.pip_packages:
            seen = set()
            pkgs = []
            for p in self.pip_packages.splitlines():
                p = p.strip()
                if not p or p.startswith('#'):
                    continue
                key = p.lower().split('=')[0].split('<')[0].split('>')[0].split('!')[0].split('[')[0].strip()
                if key not in seen:
                    seen.add(key)
                    pkgs.append(p)
            if pkgs:
                pip_packages_str = ' '.join(pkgs)

        dc_context = {
            'odoo_image': self.odoo_version_id.docker_image,
            'odoo_version': self.odoo_version_id.docker_image_tag,
            'subdomain': self.subdomain,
            'host_ip': host_ip,
            'xmlrpc_port': self.xmlrpc_port,
            'longpolling_port': self.longpolling_port,
            'network_name': 'net_%s' % self.subdomain,
            'docker_cpu': docker_cpu,
            'docker_mem': docker_mem,
            'docker_swap': docker_swap,
            'pip_packages': pip_packages_str,
        }
        dc_content = self._render_template('docker-compose.yml.jinja', dc_context)
        ssh.write_file('%s/docker-compose.yml' % instance_path, dc_content)
        self._append_log("docker-compose.yml written.")

        # Write deduplicated requirements.txt (backup-safe copy on disk)
        if self.pip_packages:
            seen = set()
            unique_pkgs = []
            for p in self.pip_packages.splitlines():
                p = p.strip()
                if not p or p.startswith('#'):
                    continue
                key = p.lower().split('=')[0].split('<')[0].split('>')[0].split('!')[0].split('[')[0].strip()
                if key not in seen:
                    seen.add(key)
                    unique_pkgs.append(p)
            ssh.write_file('%s/requirements.txt' % instance_path, '\n'.join(unique_pkgs) + '\n')
            # Write the pip install script
            pip_script = self._render_template('pip_install.sh', {})
            ssh.write_file('%s/pip_install.sh' % instance_path, pip_script)
            ssh.execute('chmod +x %s/pip_install.sh' % instance_path)
        else:
            ssh.write_file('%s/requirements.txt' % instance_path, '')

        # odoo.conf
        self._append_log("Writing odoo.conf...")
        psql_server = self.db_server_id
        db_host = self._get_db_host()
        extra_config = self._parse_extra_config()
        # Collect keys the admin has overridden so the template can
        # skip the auto-generated lines and avoid duplicates.
        override_keys = set(extra_config.keys()) if extra_config else set()
        conf_context = {
            'master_pass': self.admin_password,
            'db_host': db_host,
            'db_port': psql_server.psql_port or 5432,
            'db_user': self.db_user,
            'db_password': self.db_password,
            'proxy_mode': True,
            'workers': workers,
            'limit_memory_soft': limit_memory_soft,
            'limit_memory_hard': limit_memory_hard,
            'extra_config': extra_config,
            'override_keys': override_keys,
            'repo_addons_paths': all_addons_paths,
        }
        conf_content = self._render_template('odoo.conf.jinja', conf_context)
        ssh.write_file('%s/config/odoo.conf' % instance_path, conf_content)
        self._append_log("odoo.conf written.")

    # ========== Snapshot Restore Helper ==========

    def _restore_snapshot(self, ssh):
        """Download and restore a pre-built database snapshot from cloud storage.

        The snapshot zip is expected to contain:
        - dump.sql — PostgreSQL plain-text dump
        - filestore/ — Odoo filestore directory

        Returns True if a snapshot was restored, False if none configured.
        """
        self.ensure_one()
        product = self.saas_product_id
        if not product or not product.backup_bucket_path:
            self._append_log("No snapshot configured — starting with empty database.")
            return False

        instance_path = self._get_instance_path()
        db_name = self.subdomain

        # Generate presigned URL for the snapshot
        self._append_log(
            "Generating download URL for snapshot at %s..."
            % product.backup_bucket_path
        )
        download_url = product._generate_snapshot_download_url()

        tmp_zip = '%s/snapshot.zip' % instance_path
        extract_dir = '%s/snapshot_extract' % instance_path

        # 1. Download snapshot
        self._append_log("Downloading snapshot...")
        dl_cmd = 'curl -fsSL -o %s %s 2>&1' % (
            shlex.quote(tmp_zip), shlex.quote(download_url),
        )
        exit_code, stdout, stderr = ssh.execute(dl_cmd, timeout=600)
        if exit_code != 0:
            raise UserError(
                _("Failed to download snapshot:\n%s\n%s") % (stdout, stderr)
            )
        self._append_log("Snapshot downloaded.")

        # 2. Extract the zip
        self._append_log("Extracting snapshot...")
        ssh.execute('mkdir -p %s' % shlex.quote(extract_dir))
        extract_cmd = 'unzip -o %s -d %s 2>&1' % (
            shlex.quote(tmp_zip), shlex.quote(extract_dir),
        )
        exit_code, stdout, stderr = ssh.execute(extract_cmd, timeout=300)
        if exit_code != 0:
            raise UserError(
                _("Failed to extract snapshot:\n%s\n%s") % (stdout, stderr)
            )
        self._append_log("Snapshot extracted.")

        # 3. Restore dump.sql into the database
        dump_path = '%s/dump.sql' % extract_dir
        self._append_log("Restoring database from dump.sql into %s..." % db_name)

        psql_server = self.db_server_id
        db_host = self._get_db_host()
        db_port = psql_server.psql_port or 5432

        # Use psql on the Docker server to restore — connect to the DB server
        restore_cmd = (
            'PGPASSWORD=%s psql -h %s -p %d -U %s -d %s -f %s 2>&1'
        ) % (
            shlex.quote(self.db_password),
            shlex.quote(db_host),
            db_port,
            shlex.quote(self.db_user),
            shlex.quote(db_name),
            shlex.quote(dump_path),
        )
        exit_code, stdout, stderr = ssh.execute(restore_cmd, timeout=600)
        if exit_code != 0:
            self._append_log("Restore output:\n%s" % stdout[-2000:])
            raise UserError(
                _("Database restore failed:\n%s\n%s")
                % (stdout[-500:], stderr[-500:])
            )
        self._append_log("Database restored successfully.")

        # 4. Place filestore
        filestore_src = '%s/filestore' % extract_dir
        filestore_dst = '%s/data/odoo/filestore/%s' % (instance_path, db_name)
        data_dir = '%s/data' % instance_path
        self._append_log("Placing filestore...")
        odoo_image = self.odoo_version_id._get_docker_image()
        fs_cmd = (
            'mkdir -p %(dst)s && '
            'if [ -d %(src)s ]; then '
            '  cp -a %(src)s/. %(dst)s/; '
            'fi && '
            'chmod -R 775 %(data)s'
        ) % {
            'dst': shlex.quote(filestore_dst),
            'src': shlex.quote(filestore_src),
            'data': shlex.quote(data_dir),
        }
        exit_code, stdout, stderr = ssh.execute(fs_cmd, timeout=300)
        if exit_code != 0:
            self._append_log("Warning: filestore placement issue: %s" % stderr)
        else:
            self._append_log("Filestore placed.")

        # 5. Cleanup temp files
        ssh.execute('rm -rf %s %s' % (
            shlex.quote(tmp_zip), shlex.quote(extract_dir),
        ))
        self._append_log("Snapshot temp files cleaned up.")

        return True

    def _clone_product_repos(self, ssh):
        """Clone the product's GitHub repositories into the instance directory."""
        self.ensure_one()
        product = self.saas_product_id
        if not product or not product.repo_ids:
            return

        instance_path = self._get_instance_path()

        for repo in product.repo_ids:
            repo_dir = '%s/addons/%s' % (
                instance_path, repo._get_repo_dir_name(),
            )
            clone_url = repo._get_clone_url()

            self._append_log(
                "Cloning product repo %s (branch: %s)..." % (repo.repo_url, repo.branch)
            )
            ssh.execute('mkdir -p %s' % shlex.quote(
                '%s/addons' % instance_path
            ))
            # Remove existing if re-cloning
            ssh.execute('rm -rf %s' % shlex.quote(repo_dir))

            clone_cmd = (
                'git clone --branch %s --single-branch '
                '--depth 1 %s %s 2>&1'
            ) % (
                shlex.quote(repo.branch),
                shlex.quote(clone_url),
                shlex.quote(repo_dir),
            )
            exit_code, stdout, stderr = ssh.execute(clone_cmd, timeout=300)
            if exit_code != 0:
                raise UserError(
                    _("Failed to clone product repo '%s':\n%s\n%s")
                    % (repo.repo_url, stdout[-500:], stderr[-500:])
                )
            ssh.execute('chmod -R 755 %s' % shlex.quote(repo_dir))
            self._append_log("Repository %s cloned." % repo.name)

    def _pull_product_repos(self, ssh):
        """Pull latest changes for the product's repositories."""
        self.ensure_one()
        product = self.saas_product_id
        if not product or not product.repo_ids:
            return

        instance_path = self._get_instance_path()

        for repo in product.repo_ids:
            repo_dir = '%s/addons/%s' % (
                instance_path, repo._get_repo_dir_name(),
            )
            clone_url = repo._get_clone_url()

            # Check if repo dir exists (already cloned)
            exit_code, _, _ = ssh.execute(
                'test -d %s' % shlex.quote(repo_dir)
            )
            if exit_code != 0:
                # Not cloned yet — clone it
                self._clone_product_repos(ssh)
                return

            ssh.execute(
                'cd %s && git remote set-url origin %s'
                % (shlex.quote(repo_dir), shlex.quote(clone_url))
            )
            self._append_log("Pulling product repo %s..." % repo.name)
            pull_cmd = 'cd %s && git pull origin %s 2>&1' % (
                shlex.quote(repo_dir), shlex.quote(repo.branch),
            )
            exit_code, stdout, stderr = ssh.execute(pull_cmd, timeout=300)
            if exit_code != 0:
                raise UserError(
                    _("Git pull failed for product repo '%s':\n%s\n%s")
                    % (repo.name, stdout[-500:], stderr[-500:])
                )
            self._append_log(
                "Pulled %s: %s" % (repo.name, stdout.strip()[:200])
            )

    # ========== Deploy Flow ==========

    def _do_deploy_after_payment(self):
        """Background deploy triggered by payment — instance already in 'paid' state."""
        self.ensure_one()
        self.action_deploy()

    def action_deploy(self):
        """Full deployment flow: provision Docker container over SSH (async).

        Allowed from ``paid``, ``failed``, and ``pending_provision`` states.
        Also allowed from ``draft`` when no plan is set (internal / test
        instances).

        In **flexible** provisioning mode the instance may transition to
        ``pending_provision`` instead of deploying immediately when no
        server capacity is available.
        """
        for rec in self:
            if rec.state == 'draft' and rec.plan_id and not rec.is_trial:
                raise UserError(
                    _("Instance '%s' has a plan assigned. "
                      "Please use 'Confirm & Bill' to create a sale order and "
                      "invoice before deploying.") % rec.subdomain
                )
            if rec.state not in ('draft', 'paid', 'failed', 'pending_provision'):
                raise UserError(
                    _("Cannot deploy instance '%s': must be in Draft "
                      "(trial/no plan), Paid, Failed, or Pending Provision "
                      "state (current: %s).")
                    % (rec.subdomain, rec.state)
                )

            servers_ready = rec._allocate_servers()
            if not servers_ready:
                # Instance moved to pending_provision — skip deployment
                continue

            rec._validate_deploy_fields()

            if not rec.db_user:
                rec.db_user = rec._generate_db_user()
            if not rec.db_password:
                rec.db_password = rec._generate_random_password()
            if not rec.admin_password:
                rec.admin_password = rec._generate_random_password()

            rec._auto_assign_ports()
            if not rec.deploy_retry_count:
                rec.provisioning_log = ''
            rec.state = 'provisioning'
            rec._append_log(
                "Deployment queued (attempt %d). Running in background..."
                % (rec.deploy_retry_count + 1)
            )
            run_in_background(
                rec, '_do_deploy',
                error_method='_on_background_error',
                error_args=('failed',),
                thread_name='saas_deploy_%s' % rec.subdomain,
            )

    def _do_deploy(self):
        """Internal deploy logic for a single record."""
        self.ensure_one()

        server = self.docker_server_id
        instance_path = self._get_instance_path()
        container_name = self._get_container_name()

        with server._get_ssh_connection() as ssh:

            # Create folder structure
            self._append_log("Creating directory structure at %s" % instance_path)
            mkdir_cmd = (
                'sudo mkdir -p %(path)s/addons '
                '%(path)s/config '
                '%(path)s/data/odoo'
            ) % {'path': instance_path}
            exit_code, stdout, stderr = ssh.execute(mkdir_cmd)
            if exit_code != 0:
                raise UserError(
                    _("Failed to create directories:\n%s") % stderr
                )
            self._append_log("Directory structure created.")

            # Set permissions so the odoo user inside the container can
            # read/write volumes.  We first try to discover the UID used by
            # the image (the "odoo" user is UID 101 in the official image).
            # Fallback: chmod 777 so any UID can access the files.
            self._append_log("Setting permissions...")
            perms_cmd = (
                'chmod -R 775 %(path)s/data %(path)s/config %(path)s/addons'
            ) % {'path': instance_path}
            exit_code, stdout, stderr = ssh.execute(perms_cmd)
            if exit_code != 0:
                raise UserError(
                    _("Failed to set permissions:\n%s") % stderr
                )
            self._append_log("Permissions set.")

            # Render and write config files
            self._render_and_write_configs(ssh)

            # Create PostgreSQL user and database
            self._append_log("Creating PostgreSQL role and database...")
            self._provision_postgresql()
            self._append_log("PostgreSQL role and database ready.")

            # Clone product repositories
            self._clone_product_repos(ssh)

            # Clone customer instance repos (for hosting instances)
            if self.is_hosting and self.repo_ids:
                for repo in self.repo_ids.filtered(lambda r: r.state == 'pending'):
                    self._append_log("Cloning customer repo: %s (%s)..." % (repo.repo_url, repo.branch))
                    repo._clone_repo()
                # Re-render configs to include the new addons paths
                self._render_and_write_configs(ssh)

            # Restore pre-built database snapshot (if configured)
            snapshot_restored = self._restore_snapshot(ssh)

            if not snapshot_restored:
                # No snapshot — initialize a bare database with base module
                self._append_log("Initializing database with base module...")
                init_cmd = (
                    'cd %s && docker compose run --rm -T odoo '
                    'odoo -d %s '
                    '-i base '
                    '--without-demo=all '
                    '--stop-after-init '
                    '--no-http 2>&1'
                ) % (
                    shlex.quote(instance_path),
                    shlex.quote(self.subdomain),
                )
                exit_code, stdout, stderr = ssh.execute(init_cmd, timeout=600)
                self._append_log(
                    "Init output (last 1000 chars):\n%s" % stdout[-1000:]
                )
                if exit_code != 0:
                    raise UserError(
                        _("Database initialization failed:\n%s\n%s")
                        % (stdout[-500:], stderr[-500:])
                    )
                self._append_log("Database initialized.")

            # Start the server
            self._append_log("Starting container with docker compose up -d...")
            up_cmd = 'cd %s && docker compose up -d 2>&1' % shlex.quote(instance_path)
            exit_code, stdout, stderr = ssh.execute(up_cmd)
            self._append_log(
                "docker compose up output:\n%s\n%s" % (stdout, stderr)
            )
            if exit_code != 0:
                raise UserError(
                    _("docker compose up failed:\n%s\n%s") % (stdout, stderr)
                )
            self._append_log("Container started.")

            # Wait for container to be ready
            self._append_log("Waiting for container to be ready...")
            wait_cmd = (
                'for i in $(seq 1 30); do '
                '  STATUS=$(docker inspect -f "{{.State.Status}}" %s 2>/dev/null); '
                '  if [ "$STATUS" = "running" ]; then echo "READY"; exit 0; fi; '
                '  if [ "$STATUS" = "exited" ] || [ "$STATUS" = "dead" ]; then '
                '    echo "FAILED:$STATUS"; exit 1; '
                '  fi; '
                '  sleep 2; '
                'done; '
                'echo "TIMEOUT"; exit 1'
            ) % shlex.quote(container_name)
            exit_code, stdout, stderr = ssh.execute(wait_cmd)
            if exit_code != 0 or 'READY' not in stdout:
                _ec, logs_out, _err = ssh.execute(
                    'docker logs --tail 50 %s 2>&1' % shlex.quote(container_name)
                )
                self._append_log(
                    "Container failed to start.\n"
                    "Container logs:\n%s"
                    % logs_out
                )
                raise UserError(
                    _("Container did not become ready within 60 seconds.\n"
                      "Container logs:\n%s")
                    % logs_out
                )
            self._append_log("Container is running.")

            # Configure Nginx reverse proxy with SSL
            self._append_log("Configuring Nginx reverse proxy with SSL...")
            proxy_server = self.domain_id.proxy_server_id
            if proxy_server and proxy_server != self.docker_server_id:
                # Proxy is on a different server — deploy Nginx there
                with proxy_server._get_ssh_connection() as proxy_ssh:
                    self._provision_nginx(proxy_ssh, backend_ip=self.docker_server_id.ip_v4)
            elif proxy_server:
                # Proxy and Docker are the same server — use localhost
                self._provision_nginx(ssh)
            else:
                # No proxy configured — deploy Nginx on the Docker server
                self._provision_nginx(ssh)
            self._append_log("Nginx configured successfully.")

        self.state = 'running'
        self.deploy_retry_count = 0
        self._append_log("Deployment completed successfully. State: running.")
        self._safe_refresh_usage()
        self._send_notification('saas_core.mail_template_saas_deployed')

        # Mark partner trial as used only after the deployment actually
        # succeeds.  This runs inside the background thread so a failed
        # deploy does not lock the customer out of retrying their trial.
        if self.is_trial:
            self._sync_partner_trial()

    # ========== Lifecycle Actions ==========

    def action_stop(self):
        """Stop the Docker container and set state to stopped (async)."""
        for rec in self:
            if rec.state != 'running':
                raise UserError(
                    _("Cannot stop instance '%s': must be in Running state (current: %s).")
                    % (rec.subdomain, rec.state)
                )
            rec._ensure_can_ssh()
            prev_state = rec.state
            rec.state = 'provisioning'
            rec._append_log("Stop queued. Running in background...")
            run_in_background(
                rec, '_do_stop',
                error_method='_on_background_error',
                error_args=(prev_state,),
                thread_name='saas_stop_%s' % rec.subdomain,
            )

    def _do_stop(self):
        """Stop container (runs in background thread)."""
        self.ensure_one()
        server = self.docker_server_id
        container_name = self._get_container_name()
        with server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(
                'docker stop %s' % shlex.quote(container_name),
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to stop container '%s':\n%s")
                    % (container_name, stderr)
                )
        self.state = 'stopped'
        self._append_log("Instance stopped successfully.")

    def action_restart(self):
        """Restart the Docker container via SSH (async)."""
        for rec in self:
            if rec.state not in ('running', 'stopped', 'suspended'):
                raise UserError(
                    _("Cannot restart instance '%s': must be Running, Stopped, or Suspended (current: %s).")
                    % (rec.subdomain, rec.state)
                )
            rec._ensure_can_ssh()
            prev_state = rec.state
            rec.state = 'provisioning'
            rec._append_log("Restart queued. Running in background...")
            run_in_background(
                rec, '_do_restart',
                error_method='_on_background_error',
                error_args=(prev_state,),
                thread_name='saas_restart_%s' % rec.subdomain,
            )

    def _do_restart(self):
        """Restart container (runs in background thread)."""
        self.ensure_one()
        server = self.docker_server_id
        container_name = self._get_container_name()
        with server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(
                'docker restart %s' % shlex.quote(container_name),
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to restart container '%s':\n%s")
                    % (container_name, stderr)
                )
        self.state = 'running'
        self._append_log("Instance restarted successfully.")
        self._safe_refresh_usage()

    def action_redeploy(self):
        """Redeploy: clone pending repos, pull cloned repos, update config/mounts,
        install pending modules, and restart the container (async)."""
        for rec in self:
            if rec.state not in ('running', 'stopped', 'suspended'):
                raise UserError(
                    _("Cannot redeploy instance '%s': must be Running, Stopped, or Suspended (current: %s).")
                    % (rec.subdomain, rec.state)
                )
            rec._ensure_can_ssh()
            prev_state = rec.state
            rec.state = 'provisioning'
            rec._append_log("Redeployment queued. Running in background...")
            run_in_background(
                rec, '_do_redeploy',
                error_method='_on_background_error',
                error_args=(prev_state,),
                thread_name='saas_redeploy_%s' % rec.subdomain,
            )

    def _do_redeploy(self):
        """Internal redeploy logic for a single record."""
        self.ensure_one()
        server = self.docker_server_id
        instance_path = self._get_instance_path()

        # 1. Clone any pending instance repos
        pending_repos = self.repo_ids.filtered(lambda r: r.state == 'pending')
        if pending_repos:
            pending_repos._clone_repo()

        # 2-5. Single SSH connection for pull, config update, and restart
        with server._get_ssh_connection() as ssh:
            # Pull all cloned instance repos
            cloned_repos = self.repo_ids.filtered(lambda r: r.state == 'cloned')
            for repo in cloned_repos:
                repo_path = repo._get_remote_repo_path()
                clone_url = repo._get_clone_url()
                ssh.execute(
                    'cd %s && git remote set-url origin %s'
                    % (shlex.quote(repo_path), shlex.quote(clone_url))
                )
                self._append_log("Pulling %s..." % repo.name)
                pull_cmd = 'cd %s && git pull origin %s 2>&1' % (
                    shlex.quote(repo_path), shlex.quote(repo.branch),
                )
                exit_code, stdout, stderr = ssh.execute(
                    pull_cmd, timeout=300,
                )
                if exit_code != 0:
                    repo.error_message = stdout + '\n' + stderr
                    raise UserError(
                        _("Git pull failed for '%s':\n%s\n%s")
                        % (repo.name, stdout[-500:], stderr[-500:])
                    )
                repo.last_pull = fields.Datetime.now()
                repo.error_message = False
                self._append_log(
                    "Pulled %s: %s" % (repo.name, stdout.strip()[:200])
                )

            # Pull product repos
            self._pull_product_repos(ssh)

            # Update docker-compose.yml and odoo.conf with current mounts
            self._append_log("Updating configuration...")
            self._render_and_write_configs(ssh)
            self._append_log("Configuration updated.")

            # Restart the container (down + up to pick up volume changes)
            self._append_log("Restarting container...")
            down_cmd = 'cd %s && docker compose down 2>&1' % shlex.quote(instance_path)
            exit_code, stdout, stderr = ssh.execute(down_cmd)
            if exit_code != 0:
                raise UserError(
                    _("docker compose down failed:\n%s\n%s") % (stdout, stderr)
                )
            up_cmd = 'cd %s && docker compose up -d 2>&1' % shlex.quote(instance_path)
            exit_code, stdout, stderr = ssh.execute(up_cmd)
            if exit_code != 0:
                raise UserError(
                    _("docker compose up -d failed:\n%s\n%s") % (stdout, stderr)
                )
            self._append_log("Container restarted successfully.")

        self.state = 'running'
        self._safe_refresh_usage()

    def action_suspend(self):
        """Stop container and set state to suspended (async)."""
        for rec in self:
            if rec.state != 'running':
                raise UserError(
                    _("Cannot suspend instance '%s': must be in Running state (current: %s).")
                    % (rec.subdomain, rec.state)
                )
            rec._ensure_can_ssh()
            prev_state = rec.state
            rec.state = 'provisioning'
            rec._append_log("Suspend queued. Running in background...")
            run_in_background(
                rec, '_do_suspend',
                error_method='_on_background_error',
                error_args=(prev_state,),
                thread_name='saas_suspend_%s' % rec.subdomain,
            )

    def _do_suspend(self):
        """Suspend container (runs in background thread)."""
        self.ensure_one()
        server = self.docker_server_id
        container_name = self._get_container_name()
        with server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(
                'docker stop %s' % shlex.quote(container_name),
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to stop container '%s':\n%s")
                    % (container_name, stderr)
                )
        self.state = 'suspended'
        self._append_log("Instance suspended successfully.")

    def action_cancel(self):
        """Cancel the instance, cleaning up infrastructure if it was deployed."""
        for rec in self:
            deployed_states = ('running', 'stopped', 'suspended', 'failed')
            if rec.state in deployed_states and rec.docker_server_id:
                # Infrastructure exists — do a full async deletion
                rec._ensure_can_ssh()
                prev_state = rec.state
                rec.state = 'provisioning'
                rec._append_log("Cancellation queued. Cleaning up infrastructure...")
                run_in_background(
                    rec, '_do_delete_instance',
                    error_method='_on_background_error',
                    error_args=(prev_state,),
                    thread_name='saas_cancel_%s' % rec.subdomain,
                )
            else:
                # Not yet deployed — just mark as cancelled
                rec.state = 'cancelled'

    def action_draft(self):
        """Reset to draft state."""
        allowed = (
            'failed', 'cancelled', 'pending_payment', 'paid',
            'pending_provision',
        )
        for rec in self:
            if rec.state not in allowed:
                raise UserError(
                    _("Can only reset to draft from Failed, Cancelled, "
                      "Pending Payment, Paid, or Pending Provision state.")
                )
            rec.state = 'draft'

    def _drop_postgresql(self):
        """Drop the PostgreSQL database and role on the database server via SSH."""
        self.ensure_one()
        psql_server = self.db_server_id
        if not psql_server:
            return

        db_name = self.subdomain
        db_user = self.db_user

        with psql_server._get_ssh_connection() as ssh:
            if db_name:
                safe_db = db_name.replace("'", "''")
                drop_db_cmd = (
                    "sudo -u postgres psql -tc "
                    "\"SELECT 1 FROM pg_database WHERE datname='%s'\" "
                    "| grep -q 1 "
                    "&& sudo -u postgres dropdb --force %s"
                ) % (safe_db, shlex.quote(db_name))
                exit_code, stdout, stderr = ssh.execute(drop_db_cmd)
                if exit_code != 0:
                    _logger.warning(
                        "Failed to drop database %s: %s", db_name, stderr
                    )

            if db_user:
                safe_user = db_user.replace("'", "''")
                drop_role_cmd = (
                    "sudo -u postgres psql -tc "
                    "\"SELECT 1 FROM pg_roles WHERE rolname='%s'\" "
                    "| grep -q 1 "
                    "&& sudo -u postgres dropuser %s"
                ) % (safe_user, shlex.quote(db_user))
                exit_code, stdout, stderr = ssh.execute(drop_role_cmd)
                if exit_code != 0:
                    _logger.warning(
                        "Failed to drop role %s: %s", db_user, stderr
                    )

    def action_delete_instance(self):
        """Remove container, volumes, network, database, db user, and instance folder (async)."""
        for rec in self:
            if rec.state == 'provisioning':
                raise UserError(
                    _("Cannot delete instance '%s' while it is being provisioned.")
                    % rec.subdomain
                )
            rec._ensure_can_ssh()
            prev_state = rec.state
            rec.state = 'provisioning'
            rec._append_log("Deletion queued. Running in background...")
            run_in_background(
                rec, '_do_delete_instance',
                error_method='_on_background_error',
                error_args=(prev_state,),
                thread_name='saas_delete_%s' % rec.subdomain,
            )
        return True

    def _do_delete_instance(self):
        """Delete instance (runs in background thread).

        Order of operations:
        1. Create a final backup (needs container + DB alive)
        2. Tear down infrastructure (container, files, nginx, DB)
        3. Upload final backup directly to cancelled_backups/ folder
        4. Delete ALL client backups from cloud (regular folder)
        5. Clean up backup records, set state to cancelled
        """
        self.ensure_one()
        server = self.docker_server_id
        instance_path = self._get_instance_path()
        Backup = self.env['saas.instance.backup']

        # 1. Create a final backup BEFORE tearing down infrastructure.
        #    Upload directly to cancelled_backups/ so there is no need
        #    to move it later — simpler and avoids copy+delete issues.
        retained_path = False
        try:
            self._append_log("Creating final backup before deletion...")
            now_str = fields.Datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            partner = self.partner_id
            partner_folder = '%s_%s' % (
                partner.id, Backup._sanitize_name(partner.name),
            ) if partner else 'no_partner'
            backup_name = 'final_backup_%s' % now_str
            # Upload directly into cancelled_backups/ folder
            object_key = 'cancelled_backups/%s/%s/%s.zip' % (
                partner_folder, self.subdomain, backup_name,
            )
            final_backup = Backup.create({
                'instance_id': self.id,
                'name': backup_name,
                'bucket_path': object_key,
                'state': 'running',
            })
            size_bytes = final_backup._create_and_upload_backup(
                self, object_key,
            )
            final_backup.write({
                'state': 'done',
                'size_mb': round(size_bytes / (1024 * 1024), 2),
            })
            retained_path = object_key
            self._append_log(
                "Final backup uploaded to cancelled folder: %s" % object_key
            )
        except Exception:
            _logger.exception(
                "Failed to create final backup for %s before deletion",
                self.subdomain,
            )
            self._append_log(
                "WARNING: Final backup creation failed. "
                "Proceeding with deletion without a retained backup."
            )

        # 2. Tear down infrastructure
        with server._get_ssh_connection() as ssh:
            down_cmd = (
                'cd %s && docker compose down -v --remove-orphans 2>&1'
                % shlex.quote(instance_path)
            )
            exit_code, stdout, stderr = ssh.execute(down_cmd)
            if exit_code != 0:
                _logger.warning(
                    "docker compose down failed for %s: %s",
                    self.subdomain, stderr,
                )

            exit_code, stdout, stderr = ssh.execute(
                'sudo rm -rf %s' % shlex.quote(instance_path),
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to remove instance directory '%s':\n%s")
                    % (instance_path, stderr)
                )

            # Remove Nginx config and SSL certificate
            proxy_server = self.domain_id.proxy_server_id
            if proxy_server and proxy_server != self.docker_server_id:
                with proxy_server._get_ssh_connection() as proxy_ssh:
                    self._remove_nginx(proxy_ssh)
            else:
                self._remove_nginx(ssh)

        self._drop_postgresql()

        # 3. Delete ALL client backups from cloud storage (regular folder).
        #    The final backup is already in cancelled_backups/ so it
        #    won't be touched.  Re-fetch from DB to avoid stale cache.
        all_backups = Backup.search([('instance_id', '=', self.id)])
        for backup in all_backups:
            if backup.bucket_path and not backup.bucket_path.startswith('cancelled_backups/'):
                backup._delete_from_bucket()

        # 4. Clean up and finalize
        all_backups.unlink()
        self.retained_backup_path = retained_path

        self.state = 'cancelled'
        self._append_log("Instance deleted successfully.")

    def action_config(self):
        """Read odoo.conf from the server and display it in a popup."""
        self.ensure_one()
        self._ensure_can_ssh()
        server = self.docker_server_id
        instance_path = self._get_instance_path()
        conf_path = '%s/config/odoo.conf' % instance_path

        with server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute('cat %s' % shlex.quote(conf_path))
            if exit_code != 0:
                raise UserError(
                    _("Failed to read odoo.conf:\n%s") % stderr
                )

        return {
            'type': 'ir.actions.act_window',
            'name': _("odoo.conf — %s") % self.name,
            'res_model': 'saas.config.viewer',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_content': stdout},
        }

    def action_docker_compose(self):
        """Read docker-compose.yml from the server and display it in a popup."""
        self.ensure_one()
        self._ensure_can_ssh()
        server = self.docker_server_id
        instance_path = self._get_instance_path()
        compose_path = '%s/docker-compose.yml' % instance_path

        with server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute('cat %s' % shlex.quote(compose_path))
            if exit_code != 0:
                raise UserError(
                    _("Failed to read docker-compose.yml:\n%s") % stderr
                )

        return {
            'type': 'ir.actions.act_window',
            'name': _("docker-compose.yml — %s") % self.name,
            'res_model': 'saas.config.viewer',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_content': stdout},
        }

    def _on_background_error(self, exception, prev_state):
        """Handle background operation failure.

        For deploy failures: if retries remain, queue the instance back to
        ``pending_provision`` so the cron picks it up automatically.
        Otherwise fall back to ``failed``.

        For non-deploy failures: revert to the previous state.
        """
        self._append_log("OPERATION FAILED: %s" % str(exception))

        if prev_state == 'failed':
            # This was a deploy attempt (error_args=('failed',))
            if self.max_deploy_retries and self.deploy_retry_count < self.max_deploy_retries:
                self.deploy_retry_count += 1
                self.state = 'pending_provision'
                self._append_log(
                    "Auto-queued for retry (%d/%d). Will retry automatically."
                    % (self.deploy_retry_count, self.max_deploy_retries)
                )
                return
            # Max retries exhausted
            self.state = 'failed'
            if self.max_deploy_retries:
                self._append_log(
                    "Max retries exhausted (%d/%d). Manual intervention required."
                    % (self.deploy_retry_count, self.max_deploy_retries)
                )
        else:
            self.state = prev_state

    def action_create_backup(self):
        """Create a backup in the background."""
        self.ensure_one()

        # Block backups for trial plans
        if self.plan_id and self.plan_id.is_trial_plan:
            raise UserError(_("Backups are not available on trial plans. Please upgrade to a paid plan."))

        # Block if a backup is already running
        running = self.backup_ids.filtered(lambda b: b.state == 'running')
        if running:
            raise UserError(_("A backup is already in progress. Please wait for it to finish."))

        # Check plan backup limit
        if self.plan_id and self.plan_id.max_backups > 0:
            done_count = len(self.backup_ids.filtered(lambda b: b.state == 'done'))
            if done_count >= self.plan_id.max_backups:
                raise UserError(_(
                    "Backup limit reached (%d). Delete an old backup first or upgrade your plan."
                ) % self.plan_id.max_backups)

        # Create the record NOW so subsequent clicks see state=running
        Backup = self.env['saas.instance.backup']
        now_str = fields.Datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup = Backup.create({
            'instance_id': self.id,
            'name': 'backup_%s' % now_str,
            'state': 'running',
        })

        self._append_log("Backup queued. Running in background...")
        run_in_background(
            backup, '_run_portal_backup',
            thread_name='saas_backup_%s' % self.subdomain,
        )
        return True

    def action_restore_backup(self, backup_id):
        """Restore a backup to this instance (async).

        Stops the container, drops the current database, restores the
        backup database and filestore, then restarts the container.
        """
        self.ensure_one()
        if self.state not in ('running', 'stopped'):
            raise UserError(
                _("Instance must be Running or Stopped to restore a backup.")
            )

        backup = self.env['saas.instance.backup'].browse(backup_id)
        if not backup.exists() or backup.instance_id != self:
            raise UserError(_("Invalid backup."))
        if backup.state != 'done':
            raise UserError(_("Only completed backups can be restored."))

        self._ensure_can_ssh()
        prev_state = self.state
        self.state = 'provisioning'
        self._append_log("Restore from backup '%s' queued..." % backup.name)
        run_in_background(
            self, '_do_restore_backup',
            method_args=(backup.id,),
            error_method='_on_background_error',
            error_args=(prev_state,),
            thread_name='saas_restore_%s' % self.subdomain,
        )
        return True

    def _do_restore_backup(self, backup_id):
        """Restore a backup — replace current DB and filestore (background)."""
        self.ensure_one()
        backup = self.env['saas.instance.backup'].browse(backup_id)
        server = self.docker_server_id
        container_name = self._get_container_name()
        instance_path = self._get_instance_path()
        db_name = self.subdomain
        psql_server = self.db_server_id
        db_host = self._get_db_host()
        db_port = psql_server.psql_port or 5432

        with server._get_ssh_connection() as ssh:
            # 1. Stop container
            self._append_log("Stopping container...")
            ssh.execute('docker stop %s 2>&1' % shlex.quote(container_name))

            # 2. Download backup from cloud
            self._append_log("Downloading backup...")
            download_url = backup._generate_presigned_url()
            tmp_zip = '/tmp/saas_restore_%s.zip' % db_name
            extract_dir = '/tmp/saas_restore_%s' % db_name

            dl_cmd = 'curl -fsSL -o %s %s 2>&1' % (
                shlex.quote(tmp_zip), shlex.quote(download_url),
            )
            exit_code, stdout, stderr = ssh.execute(dl_cmd, timeout=600)
            if exit_code != 0:
                raise UserError(
                    _("Failed to download backup:\n%s\n%s") % (stdout, stderr)
                )

            # 3. Extract
            self._append_log("Extracting...")
            ssh.execute('rm -rf %s && mkdir -p %s' % (
                shlex.quote(extract_dir), shlex.quote(extract_dir),
            ))
            exit_code, stdout, stderr = ssh.execute(
                'unzip -o %s -d %s 2>&1' % (
                    shlex.quote(tmp_zip), shlex.quote(extract_dir),
                ),
                timeout=300,
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to extract backup:\n%s\n%s") % (stdout, stderr)
                )

            # 4. Drop current DB and recreate empty
            self._append_log("Dropping current database...")
            def _run_on_db_server(cmd):
                if psql_server == server:
                    return ssh.execute(cmd)
                with psql_server._get_ssh_connection() as db_ssh:
                    return db_ssh.execute(cmd)

            _run_on_db_server(
                'sudo -u postgres dropdb --force --if-exists %s 2>&1'
                % shlex.quote(db_name)
            )
            _run_on_db_server(
                'sudo -u postgres createdb -O %s %s 2>&1'
                % (shlex.quote(self.db_user), shlex.quote(db_name))
            )

            # 5. Restore dump.sql
            self._append_log("Restoring database...")
            dump_path = '%s/dump.sql' % extract_dir
            restore_cmd = (
                'PGPASSWORD=%s psql -h %s -p %d -U %s -d %s -f %s 2>&1'
            ) % (
                shlex.quote(self.db_password),
                shlex.quote(db_host),
                db_port,
                shlex.quote(self.db_user),
                shlex.quote(db_name),
                shlex.quote(dump_path),
            )
            exit_code, stdout, stderr = ssh.execute(restore_cmd, timeout=600)
            if exit_code != 0:
                self._append_log("Restore output:\n%s" % stdout[-2000:])
                raise UserError(
                    _("Database restore failed:\n%s") % stderr[-500:]
                )

            # 6. Replace filestore
            self._append_log("Restoring filestore...")
            filestore_src = '%s/filestore' % extract_dir
            filestore_dst = '%s/data/odoo/filestore/%s' % (instance_path, db_name)
            data_dir = '%s/data' % instance_path
            odoo_image = self.odoo_version_id._get_docker_image()
            fs_cmd = (
                'rm -rf %(dst)s && mkdir -p %(dst)s && '
                'if [ -d %(src)s ]; then '
                '  cp -a %(src)s/. %(dst)s/; '
                'fi && '
                'chmod -R 775 %(data)s'
            ) % {
                'dst': shlex.quote(filestore_dst),
                'src': shlex.quote(filestore_src),
                'data': shlex.quote(data_dir),
            }
            ssh.execute(fs_cmd, timeout=300)

            # 7. Cleanup temp files
            ssh.execute('rm -rf %s %s' % (
                shlex.quote(tmp_zip), shlex.quote(extract_dir),
            ))

            # 8. Restart container
            self._append_log("Starting container...")
            start_cmd = 'cd %s && docker compose up -d 2>&1' % shlex.quote(instance_path)
            exit_code, stdout, stderr = ssh.execute(start_cmd)
            if exit_code != 0:
                raise UserError(
                    _("Failed to start container:\n%s") % stderr
                )

        self.state = 'running'
        self._append_log("Backup '%s' restored successfully." % backup.name)
        self._safe_refresh_usage()



    def _get_nginx_template_name(self):
        """Return the appropriate nginx template based on the Odoo version's nginx_template field."""
        self.ensure_one()
        if self.odoo_version_id.nginx_template == 'old':
            return 'nginx_old_odoo_versions.jinja'
        return 'nginx_new_odoo_versions.jinja'

    def _provision_nginx(self, ssh, backend_ip=None):
        """Obtain SSL certificate via Certbot and deploy Nginx config.

        Args:
            ssh: SSH connection to the server where Nginx will be configured
                 (proxy server or Docker server).
            backend_ip: IP address of the Docker server. When None (single-server
                        setup), the Nginx upstream uses 127.0.0.1. When set
                        (proxy server setup), it uses the Docker server's IP.
        """
        self.ensure_one()
        domain = self.name  # e.g. acme.odoo.example.com
        if not domain:
            raise UserError(_("Instance domain name is not set."))

        # Step 1: Obtain SSL certificate via Certbot
        self._append_log("Requesting SSL certificate for %s..." % domain)
        certbot_cmd = (
            'certbot certonly --nginx -d %s '
            '--non-interactive --agree-tos '
            '--register-unsafely-without-email 2>&1'
        ) % shlex.quote(domain)
        exit_code, stdout, stderr = ssh.execute(certbot_cmd, timeout=120)
        if exit_code != 0:
            # Try standalone mode as fallback
            self._append_log(
                "Certbot --nginx failed, trying standalone mode..."
            )
            certbot_cmd = (
                'certbot certonly --standalone -d %s '
                '--non-interactive --agree-tos '
                '--register-unsafely-without-email 2>&1'
            ) % shlex.quote(domain)
            exit_code, stdout, stderr = ssh.execute(certbot_cmd, timeout=120)
            if exit_code != 0:
                raise UserError(
                    _("Failed to obtain SSL certificate for '%s':\n%s\n%s")
                    % (domain, stdout[-500:], stderr[-500:])
                )
        self._append_log("SSL certificate obtained for %s." % domain)

        # Step 2: Render Nginx config from the appropriate template
        template_name = self._get_nginx_template_name()
        nginx_context = {
            'subdomain': self.subdomain,
            'subdomainchat': '%s-chat' % self.subdomain,
            'http_port': self.xmlrpc_port,
            'longpolling_port': self.longpolling_port,
            'domain': domain,
        }
        if backend_ip:
            nginx_context['backend_ip'] = backend_ip
        nginx_content = self._render_template(template_name, nginx_context)

        # Step 3: Write Nginx config to sites-enabled
        nginx_path = '/etc/nginx/sites-enabled/%s' % self.subdomain
        self._append_log("Writing Nginx config to %s..." % nginx_path)
        ssh.write_file(nginx_path, nginx_content)

        # Step 4: Test and reload Nginx
        exit_code, stdout, stderr = ssh.execute('nginx -t 2>&1')
        if exit_code != 0:
            # Remove the broken config to avoid breaking other sites
            ssh.execute('rm -f %s' % shlex.quote(nginx_path))
            raise UserError(
                _("Nginx configuration test failed:\n%s\n%s")
                % (stdout, stderr)
            )
        exit_code, stdout, stderr = ssh.execute('systemctl reload nginx 2>&1')
        if exit_code != 0:
            raise UserError(
                _("Failed to reload Nginx:\n%s\n%s") % (stdout, stderr)
            )
        self._append_log("Nginx reloaded successfully.")

    def _remove_nginx(self, ssh):
        """Remove Nginx config and SSL certificate from the given server."""
        self.ensure_one()
        nginx_path = '/etc/nginx/sites-enabled/%s' % self.subdomain
        ssh.execute('rm -f %s' % shlex.quote(nginx_path))
        ssh.execute('systemctl reload nginx 2>&1')
        if self.name:
            ssh.execute(
                'certbot delete --cert-name %s --non-interactive 2>&1'
                % shlex.quote(self.name)
            )

    def action_view_logs(self):
        """Open a live log stream for this instance's Odoo container."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'container_logs_stream',
            'name': _("Logs: %s") % self.name,
            'context': {
                'stream_url': '/saas/instance/%d/logs/stream' % self.id,
                'container_name': self._get_container_name(),
                'tail': 100,
            },
        }

    @api.model
    def _cron_check_container_health(self):
        """Check running instances for crashed/stopped containers and auto-restart them.

        Groups by Docker server to batch SSH connections.
        """
        instances = self.search([
            ('state', '=', 'running'),
            ('docker_server_id', '!=', False),
        ])
        if not instances:
            return

        by_server = {}
        for inst in instances:
            by_server.setdefault(inst.docker_server_id.id, []).append(inst)

        for server_id, inst_list in by_server.items():
            server = self.env['saas.server'].browse(server_id)
            try:
                with server._get_ssh_connection() as ssh:
                    for inst in inst_list:
                        try:
                            container = 'odoo_%s' % inst.subdomain
                            exit_code, stdout, stderr = ssh.execute(
                                'docker inspect -f "{{.State.Status}}" %s 2>/dev/null || echo "not_found"'
                                % container
                            )
                            status = (stdout or '').strip().strip('"')
                            if status in ('exited', 'dead', 'not_found'):
                                _logger.warning(
                                    "Container %s is %s — restarting instance %s",
                                    container, status, inst.name,
                                )
                                inst._append_log(
                                    "Container found in '%s' state — auto-restarting." % status
                                )
                                path = inst._get_instance_path()
                                ssh.execute('cd %s && docker compose up -d' % path)
                        except Exception:
                            _logger.exception(
                                "Health check failed for instance %s", inst.name
                            )
            except Exception:
                _logger.exception(
                    "Cannot connect to server %s for health check", server.name
                )

    def _cron_check_storage_limits(self):
        """Check total storage of running instances and suspend those exceeding their plan limit.

        Batches SSH calls by server to avoid opening N connections sequentially.
        """
        instances = self.search([
            ('state', '=', 'running'),
            ('plan_id', '!=', False),
            ('plan_id.storage_limit', '>', 0),
        ])
        if not instances:
            return

        # Group instances by docker server for batched SSH calls
        by_docker_server = {}
        for inst in instances:
            by_docker_server.setdefault(inst.docker_server_id.id, self.browse())
            by_docker_server[inst.docker_server_id.id] |= inst

        for server_id, server_instances in by_docker_server.items():
            server = server_instances[0].docker_server_id
            try:
                with server._get_ssh_connection() as ssh:
                    for instance in server_instances:
                        try:
                            instance._refresh_usage_with_ssh(ssh)
                        except Exception:
                            _logger.exception(
                                "Failed to refresh usage for instance %s (id=%s)",
                                instance.subdomain, instance.id,
                            )
                            continue

                        total_bytes = instance.total_storage_bytes
                        limit_bytes = int(round(instance.plan_id.storage_limit * (1024 ** 3)))
                        if total_bytes > limit_bytes:
                            # Log overage — extra GB will be charged on next renewal
                            extra_gb = (total_bytes - limit_bytes) / (1024 ** 3)
                            instance._append_log(
                                "STORAGE OVERAGE: %.2f GB used, plan limit %.2f GB, "
                                "extra %.2f GB (will be charged on next renewal)."
                                % (total_bytes / (1024 ** 3),
                                   instance.plan_id.storage_limit, extra_gb)
                            )
                            _logger.info(
                                "Instance %s: storage %.2f GB exceeds %.2f GB limit, "
                                "extra %.2f GB will be billed",
                                instance.subdomain, total_bytes / (1024 ** 3),
                                instance.plan_id.storage_limit, extra_gb,
                            )
            except Exception:
                _logger.exception(
                    "Failed to connect to docker server id=%s for storage checks", server_id,
                )

    # ========== Trial Expiry ==========

    @api.model
    def _cron_check_trial_expiry(self):
        """Suspend running trial instances whose client trial period has expired."""
        today = fields.Date.today()
        # Find partners whose trial has expired
        expired_partners = self.env['res.partner'].search([
            ('saas_trial_used', '=', True),
            ('saas_trial_end_date', '<=', today),
        ])
        if not expired_partners:
            return
        # Find their running trial instances
        expired_instances = self.search([
            ('state', '=', 'running'),
            ('is_trial', '=', True),
            ('partner_id', 'in', expired_partners.ids),
        ])
        for instance in expired_instances:
            try:
                # Clear any pending upgrade that was never paid
                if instance.pending_plan_id:
                    instance.write({
                        'pending_plan_id': False,
                        'pending_billing_period': False,
                    })
                    instance._append_log(
                        "Pending upgrade to %s cleared (trial expired)."
                        % instance.pending_plan_id.name
                    )
                instance.action_suspend()
                instance._append_log(
                    "AUTO-SUSPENDED: Client free trial expired on %s. "
                    "Please subscribe to a paid plan to reactivate."
                    % instance.partner_id.saas_trial_end_date
                )
                instance.message_post(
                    body=_(
                        "Free trial expired. Instance suspended. "
                        "Please subscribe to continue using the service."
                    ),
                    message_type='notification',
                )
                instance._send_notification(
                    'saas_core.mail_template_saas_suspended'
                )
                self.env.cr.commit()
                _logger.info(
                    "Trial instance %s suspended: client %s trial ended %s",
                    instance.subdomain, instance.partner_id.name,
                    instance.partner_id.saas_trial_end_date,
                )
            except Exception:
                self.env.cr.rollback()
                _logger.exception(
                    "Failed to suspend trial instance %s", instance.subdomain,
                )

    # ========== Repo Management ==========

    def _update_repo_config_and_restart(self):
        """Regenerate docker-compose.yml and odoo.conf with repo mounts, then restart."""
        self.ensure_one()
        self._ensure_can_ssh()
        server = self.docker_server_id

        with server._get_ssh_connection() as ssh:
            self._render_and_write_configs(ssh)

        # Restart the container
        self._restart_container()

    def _restart_container(self):
        """Restart the Docker container via docker compose."""
        self.ensure_one()
        self._ensure_can_ssh()
        server = self.docker_server_id
        instance_path = self._get_instance_path()

        with server._get_ssh_connection() as ssh:
            self._append_log("Restarting container...")
            # Use docker compose down + up to pick up volume changes
            down_cmd = 'cd %s && docker compose down 2>&1' % shlex.quote(instance_path)
            exit_code, stdout, stderr = ssh.execute(down_cmd)
            if exit_code != 0:
                raise UserError(
                    _("docker compose down failed:\n%s\n%s") % (stdout, stderr)
                )

            up_cmd = 'cd %s && docker compose up -d 2>&1' % shlex.quote(instance_path)
            exit_code, stdout, stderr = ssh.execute(up_cmd)
            if exit_code != 0:
                raise UserError(
                    _("docker compose up -d failed:\n%s\n%s") % (stdout, stderr)
                )
            self._append_log("Container restarted successfully.")

    # ========== Recurring Billing ==========

    def _set_next_invoice_date(self):
        """Compute and write the next invoice date based on the instance billing period."""
        self.ensure_one()
        if not self.plan_id or self.is_trial:
            return
        today = fields.Date.today()
        period = self.billing_period or 'monthly'
        if period == 'yearly':
            interval = relativedelta(years=1)
        else:
            interval = relativedelta(months=1)
        self.next_invoice_date = today + interval
        self.last_invoice_date = today
        self.suspension_warning_sent = False

    @api.model
    def _cron_generate_recurring_invoices(self):
        """Generate renewal invoices for running instances whose billing
        cycle has elapsed.  Skips trials and instances without a plan."""
        today = fields.Date.today()
        instances = self.search([
            ('state', '=', 'running'),
            ('is_trial', '=', False),
            ('plan_id', '!=', False),
            ('next_invoice_date', '<=', today),
        ])
        for instance in instances:
            try:
                instance._generate_renewal_invoice()
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception(
                    "Failed to generate renewal invoice for %s",
                    instance.subdomain,
                )

    def _generate_renewal_invoice(self):
        """Create a new sale order + invoice for the next billing period.

        If a downgrade is scheduled, apply it first so the renewal
        invoice uses the new (lower) plan price.
        """
        self.ensure_one()
        if self.is_trial:
            return

        # Apply scheduled downgrade at cycle boundary
        if self.scheduled_plan_id:
            old_plan = self.plan_id
            new_plan = self.scheduled_plan_id
            new_period = self.scheduled_billing_period or self.billing_period or 'monthly'
            self.write({
                'plan_id': new_plan.id,
                'billing_period': new_period,
                'scheduled_plan_id': False,
                'scheduled_billing_period': False,
            })
            self._append_log(
                "Scheduled downgrade applied at cycle end: %s → %s"
                % (old_plan.name if old_plan else 'None', new_plan.name)
            )
            self.message_post(body=_(
                "Downgrade applied: switched from %s to %s."
            ) % (old_plan.name if old_plan else '—', new_plan.name))

            # Update container resources for the lower plan
            if self.state == 'running':
                try:
                    self._update_container_resources()
                except Exception as e:
                    _logger.exception(
                        "Failed to update resources after downgrade for %s",
                        self.subdomain,
                    )
                try:
                    with self.docker_server_id._get_ssh_connection() as ssh:
                        self._render_and_write_configs(ssh)
                except Exception as e:
                    _logger.exception(
                        "Failed to regenerate configs after downgrade for %s",
                        self.subdomain,
                    )

            # Remove excess backups that exceed the new plan's lower limit
            try:
                self.env['saas.instance.backup']._cleanup_excess_for_instance(self)
            except Exception:
                _logger.exception(
                    "Failed to cleanup excess backups after downgrade for %s",
                    self.subdomain,
                )

        plan = self.plan_id
        if not plan:
            return

        period = self.billing_period or 'monthly'
        price = plan._get_price_for_period(period)
        period_label = 'Monthly' if period == 'monthly' else 'Yearly'

        pricelist = self.partner_id.property_product_pricelist
        order_lines = [(0, 0, {
            'product_id': self._get_billing_product().id,
            'name': _('%s (%s) — %s renewal') % (
                plan.name, period_label, self.name or self.subdomain,
            ),
            'product_uom_qty': 1,
            'price_unit': price,
        })]

        # Add extra storage charge if usage exceeds plan limit
        extra_storage_price = float(
            self.env['ir.config_parameter'].sudo().get_param(
                'saas_master.extra_storage_price_per_gb', '0'
            )
        )
        if extra_storage_price > 0 and plan.storage_limit > 0:
            total_bytes = self.total_storage_bytes
            limit_bytes = int(round(plan.storage_limit * (1024 ** 3)))
            if total_bytes > limit_bytes:
                extra_gb = math.ceil((total_bytes - limit_bytes) / (1024 ** 3))
                extra_charge = extra_gb * extra_storage_price
                order_lines.append((0, 0, {
                    'product_id': self._get_billing_product().id,
                    'name': _('Extra storage: %d GB over %s limit (%s)') % (
                        extra_gb, '%.2f GB' % plan.storage_limit,
                        self.name or self.subdomain,
                    ),
                    'product_uom_qty': 1,
                    'price_unit': extra_charge,
                }))

        order_vals = {
            'partner_id': self.partner_id.id,
            'origin': _('Renewal: %s') % (self.name or self.subdomain),
            'order_line': order_lines,
        }
        if pricelist:
            order_vals['pricelist_id'] = pricelist.id
        order = self.env['sale.order'].create(order_vals)
        order.action_confirm()
        # Keep sale_order_id pointing to the original SO for payment detection;
        # renewal invoices are tracked via partner + origin for dunning.
        invoice = order._create_invoices()
        invoice.action_post()

        # Advance billing cycle
        if period == 'yearly':
            interval = relativedelta(years=1)
        else:
            interval = relativedelta(months=1)
        self.write({
            'next_invoice_date': self.next_invoice_date + interval,
            'last_invoice_date': fields.Date.today(),
            'suspension_warning_sent': False,
        })
        self._append_log(
            "Renewal invoice %s created for %s period."
            % (invoice.name, period_label)
        )
        self.message_post(body=_(
            "Renewal invoice %s created (%s). Payment due.",
        ) % (invoice.name, period_label))

        # Send payment-due notification
        self._send_notification('saas_core.mail_template_saas_payment_due')

    # ========== Dunning / Grace Period ==========

    @api.model
    def _cron_check_overdue_invoices(self):
        """Suspend instances whose invoices are overdue past the grace period.

        Checks both running AND stopped instances so that a customer
        cannot dodge suspension by stopping their instance before the
        cron runs.

        Also sends a warning email when the invoice first becomes overdue.
        """
        today = fields.Date.today()
        instances = self.search([
            ('state', 'in', ('running', 'stopped')),
            ('is_trial', '=', False),
            ('sale_order_id', '!=', False),
        ])
        for instance in instances:
            try:
                instance._check_dunning(today)
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception(
                    "Dunning check failed for %s", instance.subdomain,
                )

    # SO origins for optional charges (upgrades the client can back out of).
    # Unpaid invoices with these origins should NOT trigger suspension.
    _OPTIONAL_INVOICE_ORIGINS = (
        'Subscription:',   # trial → paid (client can cancel)
        'Plan upgrade:',   # paid plan upgrade (client can cancel)
    )

    def _is_optional_invoice(self, invoice):
        """Return True if the invoice is for an optional upgrade that
        the client can back out of without losing their current service."""
        so_origins = invoice.line_ids.sale_line_ids.order_id.mapped('origin')
        return any(
            origin and any(origin.startswith(prefix) for prefix in self._OPTIONAL_INVOICE_ORIGINS)
            for origin in so_origins
        )

    def _check_dunning(self, today):
        """Check if any linked invoices are overdue and act accordingly.

        Searches ALL invoices related to this instance (across all sale
        orders, including renewals) so that unpaid renewal invoices are
        caught even though sale_order_id points to the original order.

        Skips optional upgrade/subscription invoices — the client may
        have requested an upgrade but decided not to pay. These should
        not cause suspension of an otherwise active subscription.

        Handles both running and stopped instances:
        - Running: calls action_suspend() to stop the container via SSH.
        - Stopped: container is already stopped, so we just mark the
          state as 'suspended' directly (no SSH needed).
        """
        self.ensure_one()
        if not self.partner_id:
            return

        # Find all invoices related to this instance (initial + renewals)
        all_invoices = self._get_all_invoices()
        if not all_invoices:
            return

        overdue_invoices = all_invoices.filtered(
            lambda m: m.move_type == 'out_invoice'
            and m.payment_state not in ('paid', 'in_payment')
            and m.state == 'posted'
            and m.invoice_date_due
            and m.invoice_date_due < today
        )
        if not overdue_invoices:
            return

        # Exclude optional upgrade invoices — these are charges the
        # client initiated but can choose not to pay (they keep their
        # current plan).  Only mandatory invoices (initial subscription,
        # renewals, data restoration) should trigger suspension.
        mandatory_overdue = overdue_invoices.filtered(
            lambda m: not self._is_optional_invoice(m)
        )
        if not mandatory_overdue:
            return
        overdue_invoices = mandatory_overdue

        grace_days = self.plan_id.grace_period_days if self.plan_id else 7
        oldest = min(overdue_invoices, key=lambda m: m.invoice_date_due)
        oldest_due = oldest.invoice_date_due
        days_overdue = (today - oldest_due).days

        if days_overdue > grace_days:
            # Grace period exceeded — suspend
            if self.state == 'running':
                self.action_suspend()
            elif self.state == 'stopped':
                # Container is already stopped — just mark as suspended
                # so the customer cannot restart without paying.
                self.state = 'suspended'
            self._append_log(
                "AUTO-SUSPENDED: Invoice %s overdue by %d days (grace: %d)."
                % (oldest.name, days_overdue, grace_days)
            )
            self._send_notification('saas_core.mail_template_saas_suspended')
        elif not self.suspension_warning_sent:
            # Within grace period — send warning
            self.suspension_warning_sent = True
            self._send_notification('saas_core.mail_template_saas_payment_due')
            self._append_log(
                "Payment overdue warning sent. Invoice %s due %s. "
                "Grace period: %d days."
                % (oldest.name, oldest_due, grace_days)
            )

    # ========== Plan Upgrade/Downgrade ==========

    def action_subscribe_from_trial(self, new_plan_id, billing_period='monthly'):
        """Start a trial-to-paid upgrade: create invoice and wait for payment.

        The actual plan switch happens in _apply_pending_upgrade() which is
        called automatically when payment is confirmed.

        Args:
            new_plan_id: ID of the target plan
            billing_period: 'monthly' or 'yearly'

        Returns the created invoice (or True if zero-amount).
        """
        self.ensure_one()
        if not self.is_trial:
            raise UserError(_("This instance is not on a trial plan."))
        if self.state not in ('running', 'suspended'):
            raise UserError(
                _("Instance must be running or suspended to subscribe.")
            )

        new_plan = self.env['saas.plan'].browse(int(new_plan_id))
        if not new_plan.exists():
            raise UserError(_("Invalid plan."))
        if new_plan.is_trial_plan:
            raise UserError(_("Cannot subscribe to another trial plan."))
        if (self.saas_product_id and new_plan.saas_product_ids
                and self.saas_product_id not in new_plan.saas_product_ids):
            raise UserError(_("Selected plan does not belong to this service."))

        if billing_period not in ('monthly', 'yearly'):
            billing_period = 'monthly'
        if billing_period == 'yearly' and not new_plan.yearly_price:
            billing_period = 'monthly'

        price = new_plan._get_price_for_period(billing_period)
        period_label = 'Monthly' if billing_period == 'monthly' else 'Yearly'

        # Store the chosen plan and period — applied on payment
        self.write({
            'pending_plan_id': new_plan.id,
            'pending_billing_period': billing_period,
        })

        # Create sale order and invoice
        pricelist = self.partner_id.property_product_pricelist
        order_vals = {
            'partner_id': self.partner_id.id,
            'origin': _('Subscription: %s') % (self.name or self.subdomain),
            'order_line': [(0, 0, {
                'product_id': self._get_billing_product().id,
                'name': _('%s (%s) — %s') % (
                    new_plan.name, period_label,
                    self.name or self.subdomain,
                ),
                'product_uom_qty': 1,
                'price_unit': price,
            })],
        }
        if pricelist:
            order_vals['pricelist_id'] = pricelist.id
        order = self.env['sale.order'].create(order_vals)
        order.action_confirm()
        self.sale_order_id = order

        invoice = order._create_invoices()
        invoice.action_post()

        self._append_log(
            "Upgrade to %s (%s) requested. Invoice %s created — awaiting payment."
            % (new_plan.name, period_label, invoice.name)
        )
        self.message_post(body=_(
            "Upgrade to %s (%s) requested. Awaiting payment."
        ) % (new_plan.name, period_label))

        # Zero-amount plan: apply immediately
        if invoice.amount_total <= 0:
            self._apply_pending_upgrade()
            return True

        return invoice

    def _apply_pending_upgrade(self):
        """Apply the pending plan upgrade after payment is confirmed."""
        self.ensure_one()
        new_plan = self.pending_plan_id
        if not new_plan:
            return

        old_plan = self.plan_id

        billing_period = self.pending_billing_period or 'monthly'

        self.write({
            'plan_id': new_plan.id,
            'is_trial': False,
            'billing_period': billing_period,
            'pending_plan_id': False,
            'pending_billing_period': False,
        })

        self._set_next_invoice_date()

        self._append_log(
            "Payment received. Plan upgraded: %s → %s"
            % (old_plan.name if old_plan else 'Trial', new_plan.name)
        )
        self.message_post(body=_(
            "Payment confirmed. Upgraded from trial to paid plan: %s."
        ) % new_plan.name)

        # Update container resources if running
        if self.state == 'running':
            try:
                self._update_container_resources()
            except Exception as e:
                _logger.exception(
                    "Failed to update container resources on subscription for %s",
                    self.subdomain,
                )
                self._append_log(
                    "WARNING: Plan updated but container resource update failed: %s" % e
                )

        # Reactivate if suspended (trial expired)
        if self.state == 'suspended':
            self._append_log("Reactivating instance after paid subscription.")
            self.action_restart()

        # Regenerate configs with new plan settings (workers, etc.)
        if self.state == 'running':
            try:
                with self.docker_server_id._get_ssh_connection() as ssh:
                    self._render_and_write_configs(ssh)
            except Exception as e:
                _logger.exception(
                    "Failed to regenerate configs on subscription for %s",
                    self.subdomain,
                )

    @staticmethod
    def _to_monthly_equivalent(price, period):
        """Normalize a period price to its monthly equivalent for comparison."""
        if period == 'yearly' and price > 0:
            return price / 12.0
        return price

    def action_request_plan_change(self, new_plan_id, billing_period=None):
        """Request a plan change from the portal.

        UPGRADE (new effective monthly cost > old effective monthly cost):
          - Calculate remaining value of current plan
          - Charge: new_plan_price - remaining_value (min 0)
          - Applied immediately after payment
          - Billing cycle resets from today

        DOWNGRADE (new effective monthly cost <= old effective monthly cost):
          - NO refund, NO credit, NO proration
          - Blocked if current DB size >= 75% of target plan's db_size_limit
          - Scheduled for end of current billing cycle
          - Client keeps current (higher) plan until then

        Upgrade vs downgrade is determined by comparing effective monthly
        costs so that switching periods (monthly ↔ yearly) is classified
        correctly.

        Returns:
          - Invoice record (upgrade, needs payment)
          - True (upgrade, zero charge)
          - 'scheduled' (downgrade scheduled)
        """
        self.ensure_one()
        # Lock the instance row to prevent concurrent plan changes
        # (two browser tabs submitting at the same time).
        self.env.cr.execute(
            "SELECT id FROM saas_instance WHERE id = %s FOR UPDATE NOWAIT",
            (self.id,),
        )
        # Re-read fields after lock to get latest state
        self.invalidate_recordset()

        if self.state not in ('running', 'stopped', 'suspended'):
            raise UserError(
                _("Can only change plan on running, stopped, or suspended instances.")
            )

        # Auto-cancel existing pending upgrade if client changes their mind.
        # This allows switching to a different plan without manual cancellation.
        if self.pending_plan_id:
            self._cancel_pending_upgrade()
        if self.scheduled_plan_id:
            raise UserError(_(
                "A downgrade is already scheduled. "
                "Please cancel the scheduled downgrade before requesting another plan change."
            ))

        new_plan = self.env['saas.plan'].browse(int(new_plan_id))
        if not new_plan.exists():
            raise UserError(_("Invalid plan."))
        if new_plan.is_trial_plan:
            raise UserError(_("Cannot switch to a trial plan."))
        billing_period = billing_period or self.billing_period or 'monthly'

        if new_plan.id == self.plan_id.id and billing_period == (self.billing_period or 'monthly'):
            raise UserError(_("Already on this plan and billing period."))

        # Block yearly → monthly on the same plan.
        # Annual subscribers must wait until their subscription period ends.
        if (new_plan.id == self.plan_id.id
                and (self.billing_period or 'monthly') == 'yearly'
                and billing_period == 'monthly'):
            raise UserError(_(
                "You cannot switch from yearly to monthly billing before your "
                "current annual subscription ends%s. "
                "Your yearly plan will remain active until then."
            ) % (
                ' (%s)' % self.next_invoice_date.strftime('%B %d, %Y')
                if self.next_invoice_date else ''
            ))
        new_price = new_plan._get_price_for_period(billing_period)
        old_period = self.billing_period or 'monthly'
        old_price = self.plan_id._get_price_for_period(old_period) if self.plan_id else 0

        # Monthly → Yearly on the same plan is always an immediate upgrade
        # (customer commits to paying more upfront, with remaining days credited).
        if (new_plan.id == self.plan_id.id
                and old_period == 'monthly'
                and billing_period == 'yearly'):
            return self._request_upgrade(new_plan, billing_period, new_price, old_price)

        # Compare effective monthly costs to correctly classify
        # cross-period changes (e.g. $10/month vs $100/year = $8.33/month)
        new_monthly = self._to_monthly_equivalent(new_price, billing_period)
        old_monthly = self._to_monthly_equivalent(old_price, old_period)

        if new_monthly > old_monthly:
            return self._request_upgrade(new_plan, billing_period, new_price, old_price)
        else:
            return self._request_downgrade(new_plan, billing_period)

    # ---------- AUTO-CANCEL PENDING ----------

    def _cancel_pending_upgrade(self):
        """Cancel the current pending upgrade and its unpaid invoice.

        Called automatically when the client selects a different plan
        while an upgrade is still awaiting payment.
        """
        self.ensure_one()
        old_plan_name = self.pending_plan_id.name if self.pending_plan_id else 'Unknown'

        # Find and cancel the unpaid invoice for this pending upgrade
        if self.sale_order_id:
            for inv in self.sale_order_id.invoice_ids.sorted('create_date', reverse=True):
                if (inv.state == 'posted'
                        and inv.payment_state not in ('paid', 'in_payment')
                        and inv.amount_residual > 0):
                    inv.button_cancel()
                    break

        self._append_log(
            "Auto-cancelled pending upgrade to %s (client selected a different plan)."
            % old_plan_name
        )
        self.write({
            'pending_plan_id': False,
            'pending_billing_period': False,
        })

    # ---------- UPGRADE ----------

    def _request_upgrade(self, new_plan, billing_period, new_price, old_price):
        """Create proration invoice for an upgrade. Applied on payment."""
        self.ensure_one()
        today = fields.Date.today()
        period_label = 'Yearly' if billing_period == 'yearly' else 'Monthly'

        # Calculate remaining value of current subscription
        # Deduct 2 days (today + processing day) from remaining days
        remaining_value = 0.0
        remaining_info = ''
        if self.next_invoice_date and self.last_invoice_date:
            total_days = (self.next_invoice_date - self.last_invoice_date).days
            remaining_days = (self.next_invoice_date - today).days - 2
            if total_days > 0 and remaining_days > 0:
                remaining_value = (old_price / total_days) * remaining_days
                remaining_info = (
                    ' (credit %.2f for %d remaining days on %s)'
                    % (remaining_value, remaining_days, self.plan_id.name)
                )

        # Final charge = new plan price - remaining value (min 0)
        final_charge = max(new_price - remaining_value, 0)

        self._append_log(
            "Upgrade calculation: new_price=%.2f, remaining_value=%.2f, "
            "final_charge=%.2f%s"
            % (new_price, remaining_value, final_charge, remaining_info)
        )

        # Store pending upgrade
        self.write({
            'pending_plan_id': new_plan.id,
            'pending_billing_period': billing_period,
        })

        line_name = _('%s (%s) — %s — Plan upgrade%s') % (
            new_plan.name, period_label,
            self.name or self.subdomain, remaining_info,
        )

        # Create invoice
        pricelist = self.partner_id.property_product_pricelist
        order_vals = {
            'partner_id': self.partner_id.id,
            'origin': _('Plan upgrade: %s') % (self.name or self.subdomain),
            'order_line': [(0, 0, {
                'product_id': self._get_billing_product().id,
                'name': line_name,
                'product_uom_qty': 1,
                'price_unit': final_charge,
            })],
        }
        if pricelist:
            order_vals['pricelist_id'] = pricelist.id
        order = self.env['sale.order'].create(order_vals)
        order.action_confirm()
        self.sale_order_id = order

        invoice = order._create_invoices()
        invoice.action_post()

        self.message_post(body=_(
            "Upgrade to %s (%s) requested. Invoice %s (%.2f) — awaiting payment."
        ) % (new_plan.name, period_label, invoice.name, final_charge))

        # Zero charge: apply immediately
        if invoice.amount_total <= 0:
            self._apply_pending_plan_change()
            return True

        return invoice

    def _apply_pending_plan_change(self):
        """Apply a pending upgrade after payment is confirmed."""
        self.ensure_one()
        new_plan = self.pending_plan_id
        if not new_plan:
            return

        billing_period = self.pending_billing_period or self.billing_period or 'monthly'
        old_plan = self.plan_id

        # Switch plan and reset billing cycle from today
        self.write({
            'plan_id': new_plan.id,
            'billing_period': billing_period,
            'pending_plan_id': False,
            'pending_billing_period': False,
        })

        # Reset billing cycle from today
        self._set_next_invoice_date()

        self._append_log(
            "Payment received. Plan upgraded: %s → %s. Billing cycle reset."
            % (old_plan.name if old_plan else 'None', new_plan.name)
        )
        self.message_post(body=_(
            "Payment confirmed. Upgraded from %s to %s. Billing cycle reset."
        ) % (old_plan.name if old_plan else '—', new_plan.name))

        if self.state == 'running':
            try:
                self._update_container_resources()
            except Exception as e:
                _logger.exception(
                    "Failed to update container resources for %s", self.subdomain,
                )
                self._append_log(
                    "WARNING: Plan updated but resource update failed: %s" % e
                )
            try:
                with self.docker_server_id._get_ssh_connection() as ssh:
                    self._render_and_write_configs(ssh)
            except Exception as e:
                _logger.exception(
                    "Failed to regenerate configs for %s", self.subdomain,
                )

    # ---------- DOWNGRADE ----------

    DOWNGRADE_THRESHOLD = 0.75  # 75% of target plan's db_size_limit

    def _request_downgrade(self, new_plan, billing_period):
        """Validate and schedule a downgrade for end of billing cycle.

        Blocked if current total storage >= 75% of the target plan's storage_limit.
        No refund, no credit, no proration.
        """
        self.ensure_one()

        # Refresh storage usage before checking threshold to avoid
        # blocking on stale data (e.g. client deleted data recently).
        self._safe_refresh_usage()

        # --- Storage threshold check (75% of target plan limit) ---
        if new_plan.storage_limit > 0:
            current_usage_gb = (self.total_storage_bytes or 0) / (1024 ** 3)
            threshold_gb = self.DOWNGRADE_THRESHOLD * new_plan.storage_limit

            self._append_log(
                "Downgrade check: current_usage=%.2f GB, "
                "target_storage_limit=%.2f GB, threshold(75%%)=%.2f GB"
                % (current_usage_gb, new_plan.storage_limit, threshold_gb)
            )

            if current_usage_gb >= threshold_gb:
                raise UserError(_(
                    "Your current storage usage is too high for the selected plan.\n\n"
                    "Current usage: %.2f GB\n"
                    "Target plan limit: %.2f GB\n"
                    "Minimum required headroom: 25%% free (threshold: %.2f GB)\n\n"
                    "Please reduce your data before downgrading, "
                    "or choose a plan with a higher limit."
                ) % (current_usage_gb, new_plan.storage_limit, threshold_gb))

        # --- Schedule the downgrade ---
        self.write({
            'scheduled_plan_id': new_plan.id,
            'scheduled_billing_period': billing_period,
        })

        end_date = self.next_invoice_date or _('end of billing cycle')
        self._append_log(
            "Downgrade to %s scheduled for %s. No refund, no credit."
            % (new_plan.name, end_date)
        )
        self.message_post(body=_(
            "Downgrade to %s scheduled for %s. "
            "Your current plan remains active until then."
        ) % (new_plan.name, end_date))

        return 'scheduled'

    def action_cancel_scheduled_downgrade(self):
        """Cancel a pending scheduled downgrade."""
        self.ensure_one()
        if self.scheduled_plan_id:
            plan_name = self.scheduled_plan_id.name
            self.write({
                'scheduled_plan_id': False,
                'scheduled_billing_period': False,
            })
            self._append_log("Scheduled downgrade to %s cancelled." % plan_name)
            self.message_post(body=_(
                "Scheduled downgrade to %s has been cancelled."
            ) % plan_name)

    def _update_container_resources(self):
        """Update CPU/RAM limits on a running container via docker update.

        Respects per-instance overrides (override_docker_cpu,
        override_docker_mem) so admin changes take effect immediately
        without a full redeploy.
        """
        self.ensure_one()
        if not self.plan_id or self.state != 'running':
            return
        self._ensure_can_ssh()
        container_name = self._get_container_name()
        plan = self.plan_id

        # Resolve effective values (override > plan)
        cpu = self.override_docker_cpu.strip() if self.override_docker_cpu else str(plan.cpu_limit)
        ram_bytes = self._parse_ram_string(plan.ram_limit)
        auto_mem = '%dm' % (int(ram_bytes * 1.3) // (1024 * 1024)) if ram_bytes else ''
        mem = self.override_docker_mem.strip() if self.override_docker_mem else auto_mem
        swap = self.override_docker_swap.strip() if self.override_docker_swap else mem

        # docker update --cpus=X --memory=Y --memory-swap=Z container
        parts = ['docker update']
        if cpu:
            parts.append('--cpus=%s' % shlex.quote(cpu))
        if mem:
            parts.append('--memory=%s' % shlex.quote(mem))
        if swap:
            parts.append('--memory-swap=%s' % shlex.quote(swap))
        parts.append(shlex.quote(container_name))
        update_cmd = ' '.join(parts)

        with self.docker_server_id._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(update_cmd)
            if exit_code != 0:
                raise UserError(
                    _("Failed to update container resources:\n%s") % stderr
                )
            # Also regenerate docker-compose.yml so next restart uses new limits
            self._render_and_write_configs(ssh)

        self._append_log(
            "Container resources updated: CPU=%s, RAM=%s"
            % (plan.cpu_limit, plan.ram_limit)
        )

    # ========== Email Notifications ==========

    def _send_notification(self, template_xmlid):
        """Send an email notification using the given mail template XML ID."""
        self.ensure_one()
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=False)

    # ========== Deployment Status Endpoint Helper ==========

    def _get_status_dict(self):
        """Return a dict suitable for JSON API responses."""
        self.ensure_one()
        return {
            'id': self.id,
            'state': self.state,
            'state_label': dict(
                self._fields['state'].selection
            ).get(self.state, self.state),
            'url': self.url or '',
            'provisioning_log': self.provisioning_log or '',
            'pending_plan_id': self.pending_plan_id.id if self.pending_plan_id else False,
        }

    # ========== Portal Self-Service Actions ==========

    def action_portal_restart(self):
        """Restart from portal — only allowed for running instances."""
        self.ensure_one()
        if self.state != 'running':
            raise UserError(_("Instance must be running to restart."))
        self.action_restart()

    def action_portal_stop(self):
        """Stop from portal — only allowed for running instances."""
        self.ensure_one()
        if self.state != 'running':
            raise UserError(_("Instance must be running to stop."))
        self.action_stop()

    def _has_overdue_invoices_past_grace(self):
        """Return True if this instance has invoices overdue past the grace period."""
        self.ensure_one()
        if self.is_trial or not self.partner_id:
            return False
        all_invoices = self._get_all_invoices()
        if not all_invoices:
            return False
        today = fields.Date.today()
        overdue = all_invoices.filtered(
            lambda m: m.move_type == 'out_invoice'
            and m.payment_state not in ('paid', 'in_payment', 'reversed')
            and m.state == 'posted'
            and m.invoice_date_due
            and m.invoice_date_due < today
        )
        if not overdue:
            return False
        grace_days = self.plan_id.grace_period_days if self.plan_id else 7
        oldest_due = min(overdue, key=lambda m: m.invoice_date_due).invoice_date_due
        return (today - oldest_due).days > grace_days

    def action_portal_start(self):
        """Start from portal — only allowed for stopped instances with no overdue invoices."""
        self.ensure_one()
        if self.state != 'stopped':
            raise UserError(_("Instance must be stopped to start."))
        if self._has_overdue_invoices_past_grace():
            raise UserError(
                _("Cannot start instance: you have overdue invoices. "
                  "Please complete your payment first.")
            )
        self.action_restart()

    def action_reactivate(self, new_plan_id, billing_period='monthly'):
        """Reactivate a cancelled instance with a new plan.

        Reuses the same record — resets state to draft, assigns the new
        plan, clears old infrastructure fields, then runs the billing /
        deploy flow.  The retained_backup_path is preserved so the admin
        can still restore data if the client requests it.
        """
        self.ensure_one()
        if self.state not in ('cancelled', 'cancelled_by_client'):
            raise UserError(_("Only cancelled instances can be reactivated."))

        new_plan = self.env['saas.plan'].browse(int(new_plan_id))
        if not new_plan.exists() or new_plan.is_trial_plan:
            raise UserError(_("Please select a valid paid plan."))

        if billing_period not in ('monthly', 'yearly'):
            billing_period = 'monthly'
        if billing_period == 'yearly' and not new_plan.yearly_price:
            billing_period = 'monthly'

        # Reset to draft with new plan — clear old infra but keep history.
        # cancellation_reason and retained_backup_path are intentionally
        # NOT cleared so the admin can still see the history and restore
        # the retained backup after reactivation.
        self.write({
            'state': 'draft',
            'plan_id': new_plan.id,
            'billing_period': billing_period,
            'is_trial': False,
            # Clear stale infrastructure (will be re-allocated on deploy)
            'docker_server_id': False,
            'db_server_id': False,
            'xmlrpc_port': False,
            'longpolling_port': False,
            'deploy_retry_count': 0,
            'is_overcommitted': False,
            # Clear stale billing refs (new SO will be created)
            'sale_order_id': False,
            'pending_plan_id': False,
            'pending_billing_period': False,
            'scheduled_plan_id': False,
            'scheduled_billing_period': False,
            'suspension_warning_sent': False,
            # retained_backup_path is intentionally NOT cleared
        })

        self._append_log(
            "Instance reactivated by client. New plan: %s (%s)."
            % (new_plan.name, billing_period)
        )
        self.message_post(body=_(
            "Instance reactivated. New plan: %s (%s)."
        ) % (new_plan.name, billing_period))

        # Run billing flow (creates SO + invoice)
        self.action_confirm_and_bill()
        return True

