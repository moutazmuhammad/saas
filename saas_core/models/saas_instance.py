import datetime
import logging
import math
import os
import re
import secrets
import shlex
import string
import uuid
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
    _inherit = ['mail.thread', 'mail.activity.mixin']
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
            if self.plan_id and self.plan_id.saas_product_id != self.saas_product_id:
                self.plan_id = False
    docker_server_id = fields.Many2one(
        'saas.container.physical.server',
        string='Docker Server',
        tracking=True,
        default=lambda self: self.env['saas.container.physical.server'].search([], limit=1),
        help='Physical server where the Docker container for this instance runs.',
    )
    db_server_id = fields.Many2one(
        'saas.psql.physical.server',
        string='Database Server',
        tracking=True,
        default=lambda self: self.env['saas.psql.physical.server'].search([], limit=1),
        help='PostgreSQL server that hosts the database for this instance.',
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
             'Lines starting with # are ignored.',
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
        alphabet = string.ascii_letters + string.digits + '-_.~+='
        for vals in vals_list:
            # Block trial if the client has already used their free trial.
            # Use SELECT ... FOR UPDATE to prevent race conditions where
            # two concurrent requests both pass the check.
            if vals.get('is_trial') and vals.get('partner_id'):
                self.env.cr.execute(
                    "SELECT saas_trial_used FROM res_partner "
                    "WHERE id = %s FOR UPDATE",
                    (vals['partner_id'],),
                )
                row = self.env.cr.fetchone()
                if row and row[0]:
                    partner = self.env['res.partner'].browse(vals['partner_id'])
                    raise ValidationError(
                        _("Client '%s' has already used their free trial. "
                          "Only one trial is allowed per client.")
                        % partner.name
                    )
            # Generate access token for portal security (field added by saas_website)
            if 'access_token' in self._fields and not vals.get('access_token'):
                vals['access_token'] = uuid.uuid4().hex
            subdomain = vals.get('subdomain', '')
            if subdomain and not vals.get('db_user'):
                safe_subdomain = subdomain.replace('-', '_').replace('.', '_')
                vals['db_user'] = 'saas_%s' % safe_subdomain
            if not vals.get('db_password'):
                vals['db_password'] = ''.join(
                    secrets.choice(alphabet) for _ in range(24)
                )
            if not vals.get('admin_password'):
                vals['admin_password'] = ''.join(
                    secrets.choice(alphabet) for _ in range(24)
                )
        records = super().create(vals_list)
        for rec in records:
            if rec.docker_server_id and (not rec.xmlrpc_port or not rec.longpolling_port):
                rec._auto_assign_ports()
            if rec.is_trial and rec.partner_id:
                rec._sync_partner_trial()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get('is_trial'):
            for rec in self:
                if rec.is_trial and rec.partner_id:
                    rec._sync_partner_trial()
        return res

    def unlink(self):
        """Block deletion of instances that have live infrastructure.

        Only draft and cancelled instances (no running infra) can be deleted
        from the database.  Everything else must go through the
        action_delete_instance() teardown workflow first.
        """
        safe_states = ('draft', 'cancelled')
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
        """Mark the partner as having used their trial (one-time)."""
        self.ensure_one()
        partner = self.partner_id
        if not partner.saas_trial_used:
            trial_days = int(self.env['ir.config_parameter'].sudo().get_param(
                'saas_master.trial_days', '14',
            ))
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
        """Return all invoices related to this instance across all sale orders."""
        self.ensure_one()
        instance_ref = self.name or self.subdomain
        if not instance_ref:
            return self.env['account.move']
        sale_orders = self.env['sale.order'].search([
            ('partner_id', '=', self.partner_id.id),
            '|',
            ('origin', 'ilike', instance_ref),
            ('id', '=', self.sale_order_id.id if self.sale_order_id else 0),
        ])
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
        # -- Build order lines (respect partner pricelist when available) --
        pricelist = self.partner_id.property_product_pricelist
        order_lines = [(0, 0, {
            'product_id': self._get_billing_product().id,
            'name': _('%s — %s') % (plan.name, self.name or self.subdomain),
            'product_uom_qty': 1,
            'price_unit': plan.price,
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

    def _generate_random_password(self, length=24):
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

    def _get_all_repo_context(self):
        """Return repo context dicts for docker-compose and addons paths.

        Combines instance-level repos and product-level repos.
        """
        self.ensure_one()
        server = self.docker_server_id
        instance_path = self._get_instance_path()

        # All repos (instance + product) are cloned into addons/ dir,
        # already mounted at /mnt/extra-addons — no extra volume mounts needed.
        repos = []
        version_repos = []

        # Instance-level repos
        instance_repos = self.repo_ids.filtered(lambda r: r.state == 'cloned')
        addons_paths = [r._get_container_addons_path() for r in instance_repos]

        # Product-level repos
        product = self.saas_product_id
        if product:
            for pr in product.repo_ids:
                addons_paths.append(pr._get_container_addons_path())

        return repos, version_repos, addons_paths

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

    def _auto_assign_ports(self):
        """Auto-assign xmlrpc_port and longpolling_port if not already set."""
        self.ensure_one()
        if self.xmlrpc_port and self.longpolling_port:
            return

        starting_port = int(self.env['ir.config_parameter'].sudo().get_param(
            'saas_master.default_instance_starting_port', '32000',
        ))

        siblings = self.env['saas.instance'].search([
            ('docker_server_id', '=', self.docker_server_id.id),
            ('id', '!=', self.id),
            ('xmlrpc_port', '>', 0),
        ])

        used_ports = set()
        for sibling in siblings:
            if sibling.xmlrpc_port:
                used_ports.add(sibling.xmlrpc_port)
            if sibling.longpolling_port:
                used_ports.add(sibling.longpolling_port)

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
                with self.db_server_id._get_ssh_connection() as db_ssh:
                    db_size_cmd = (
                        'sudo -u postgres psql -At -c '
                        '"SELECT pg_database_size(\'%s\');"'
                    ) % self.subdomain
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

        # -- Total storage = disk + db + backup sizes --
        backup_bytes = sum(
            (b.size_mb or 0) * 1024 * 1024
            for b in self.backup_ids
            if b.state == 'done'
        )
        total_bytes = disk_bytes + db_bytes + backup_bytes
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
        repos, version_repos, all_addons_paths = self._get_all_repo_context()

        # docker-compose.yml
        self._append_log("Writing docker-compose.yml...")
        dc_context = {
            'odoo_image': self.odoo_version_id.docker_image,
            'odoo_version': self.odoo_version_id.docker_image_tag,
            'subdomain': self.subdomain,
            'host_ip': '127.0.0.1',
            'xmlrpc_port': self.xmlrpc_port,
            'longpolling_port': self.longpolling_port,
            'network_name': 'net_%s' % self.subdomain,
            'cpu_limit': self.plan_id.cpu_limit if self.plan_id else 0,
            'ram_limit': self.plan_id.ram_limit if self.plan_id else '',
            'repos': repos,
            'version_repos': version_repos,
        }
        dc_content = self._render_template('docker-compose.yml.jinja', dc_context)
        ssh.write_file('%s/docker-compose.yml' % instance_path, dc_content)
        self._append_log("docker-compose.yml written.")

        # odoo.conf
        self._append_log("Writing odoo.conf...")
        psql_server = self.db_server_id
        db_host = psql_server.private_ip_v4 or psql_server.ip_v4
        conf_context = {
            'master_pass': self.admin_password,
            'db_host': db_host,
            'db_port': psql_server.psql_port or 5432,
            'db_user': self.db_user,
            'db_password': self.db_password,
            'proxy_mode': True,
            'workers': self.plan_id.workers if self.plan_id else 2,
            'extra_config': self._parse_extra_config(),
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
        db_host = psql_server.private_ip_v4 or psql_server.ip_v4
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
            'ODOO_UID=$(docker run --rm --entrypoint id %(image)s -u odoo 2>/dev/null || echo 101) && '
            'mkdir -p %(dst)s && '
            'if [ -d %(src)s ]; then '
            '  cp -a %(src)s/. %(dst)s/; '
            'fi && '
            'chown -R $ODOO_UID:$ODOO_UID %(data)s && '
            'chmod -R 755 %(data)s'
        ) % {
            'image': shlex.quote(odoo_image),
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

        Allowed from ``paid`` and ``failed`` states.  Also allowed from
        ``draft`` when no plan is set (internal / test instances).
        """
        for rec in self:
            if rec.state == 'draft' and rec.plan_id and not rec.is_trial:
                raise UserError(
                    _("Instance '%s' has a plan assigned. "
                      "Please use 'Confirm & Bill' to create a sale order and "
                      "invoice before deploying.") % rec.subdomain
                )
            if rec.state not in ('draft', 'paid', 'failed'):
                raise UserError(
                    _("Cannot deploy instance '%s': must be in Draft (trial/no plan), "
                      "Paid, or Failed state (current: %s).")
                    % (rec.subdomain, rec.state)
                )

            rec._validate_deploy_fields()

            if not rec.db_user:
                rec.db_user = rec._generate_db_user()
            if not rec.db_password:
                rec.db_password = rec._generate_random_password()
            if not rec.admin_password:
                rec.admin_password = rec._generate_random_password()

            rec._auto_assign_ports()
            rec.provisioning_log = ''
            rec.state = 'provisioning'
            rec._append_log("Deployment queued. Running in background...")
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
                'mkdir -p %(path)s/addons '
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
            odoo_image = self.odoo_version_id._get_docker_image()
            perms_cmd = (
                'ODOO_UID=$(docker run --rm --entrypoint id %(image)s -u odoo 2>/dev/null || echo 101) && '
                'chown -R $ODOO_UID:$ODOO_UID %(path)s/data %(path)s/config %(path)s/addons && '
                'chmod -R 755 %(path)s/data %(path)s/config %(path)s/addons'
            ) % {'path': instance_path, 'image': shlex.quote(odoo_image)}
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
            self._provision_nginx(ssh)
            self._append_log("Nginx configured successfully.")

        self.state = 'running'
        self._append_log("Deployment completed successfully. State: running.")
        self._safe_refresh_usage()
        self._send_notification('saas_core.mail_template_saas_deployed')

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

        # 1. Clone any pending instance repos
        pending_repos = self.repo_ids.filtered(lambda r: r.state == 'pending')
        if pending_repos:
            pending_repos._clone_repo()

        # 2. Pull all cloned instance repos
        cloned_repos = self.repo_ids.filtered(lambda r: r.state == 'cloned')
        if cloned_repos:
            with server._get_ssh_connection() as ssh:
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

        # 3. Pull product repos
        with server._get_ssh_connection() as ssh:
            self._pull_product_repos(ssh)

        # 4. Update docker-compose.yml and odoo.conf with current mounts
        self._append_log("Updating configuration...")
        with server._get_ssh_connection() as ssh:
            self._render_and_write_configs(ssh)
        self._append_log("Configuration updated.")

        # 5. Restart the container
        self._restart_container()
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
        for rec in self:
            rec.state = 'cancelled'

    def action_draft(self):
        """Reset to draft state."""
        allowed = ('failed', 'cancelled', 'pending_payment', 'paid')
        for rec in self:
            if rec.state not in allowed:
                raise UserError(
                    _("Can only reset to draft from Failed, Cancelled, "
                      "Pending Payment, or Paid state.")
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
                drop_db_cmd = (
                    "sudo -u postgres psql -tc "
                    "\"SELECT 1 FROM pg_database WHERE datname=%s\" "
                    "| grep -q 1 "
                    "&& sudo -u postgres dropdb %s"
                ) % (shlex.quote("'%s'" % db_name), shlex.quote(db_name))
                ssh.execute(drop_db_cmd)

            if db_user:
                drop_role_cmd = (
                    "sudo -u postgres psql -tc "
                    "\"SELECT 1 FROM pg_roles WHERE rolname=%s\" "
                    "| grep -q 1 "
                    "&& sudo -u postgres dropuser %s"
                ) % (shlex.quote("'%s'" % db_user), shlex.quote(db_user))
                ssh.execute(drop_role_cmd)

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
        """Delete instance (runs in background thread)."""
        self.ensure_one()
        server = self.docker_server_id
        instance_path = self._get_instance_path()

        with server._get_ssh_connection() as ssh:
            down_cmd = 'cd %s && docker compose down -v --remove-orphans 2>&1' % shlex.quote(instance_path)
            exit_code, stdout, stderr = ssh.execute(down_cmd)
            if exit_code != 0:
                _logger.warning(
                    "docker compose down failed for %s: %s", self.subdomain, stderr
                )

            exit_code, stdout, stderr = ssh.execute(
                'rm -rf %s' % shlex.quote(instance_path),
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to remove instance directory '%s':\n%s")
                    % (instance_path, stderr)
                )

            # Remove Nginx config and SSL certificate
            nginx_path = '/etc/nginx/sites-enabled/%s' % self.subdomain
            ssh.execute('rm -f %s' % shlex.quote(nginx_path))
            ssh.execute('systemctl reload nginx 2>&1')
            if self.name:
                ssh.execute(
                    'certbot delete --cert-name %s --non-interactive 2>&1'
                    % shlex.quote(self.name)
                )

        self._drop_postgresql()

        # Delete all backups from cloud storage
        for backup in self.backup_ids.filtered(
            lambda b: b.state == 'done' and b.bucket_path
        ):
            backup._delete_from_bucket()
        self.backup_ids.unlink()

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
        """Handle background operation failure by reverting state."""
        self.state = prev_state
        self._append_log("OPERATION FAILED: %s" % str(exception))

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

    # ========== Module Installation ==========

    def _get_xmlrpc_url(self):
        """Return the XML-RPC URL for the running instance."""
        self.ensure_one()
        server_ip = self.docker_server_id._get_ssh_ip()
        return 'http://%s:%d' % (server_ip, self.xmlrpc_port)

    def action_install_modules(self, module_names):
        """Install one or more Odoo modules on the running instance via XML-RPC.

        Args:
            module_names: list of technical module names (e.g. ['sale', 'purchase'])
        """
        self.ensure_one()
        if self.state != 'running':
            raise UserError(_("Instance must be running to install apps."))
        if not module_names:
            raise UserError(_("No apps specified."))

        # Clean and validate module names
        clean_names = []
        for name in module_names:
            name = name.strip().lower()
            if name and name.replace('_', '').replace('-', '').isalnum():
                clean_names.append(name)
        if not clean_names:
            raise UserError(_("Invalid app names."))

        self._append_log("App installation queued: %s" % ', '.join(clean_names))
        run_in_background(
            self, '_do_install_modules',
            method_args=(clean_names,),
            error_method='_on_module_install_error',
            error_args=(clean_names,),
            thread_name='saas_install_%s' % self.subdomain,
        )
        return True

    def _do_install_modules(self, module_names):
        """Install modules via XML-RPC (runs in background thread)."""
        import xmlrpc.client
        self.ensure_one()

        url = self._get_xmlrpc_url()
        db_name = self.subdomain

        try:
            # Authenticate as admin (uid=2 is default admin in Odoo)
            common = xmlrpc.client.ServerProxy('%s/xmlrpc/2/common' % url, allow_none=True)
            uid = common.authenticate(db_name, 'admin', self.admin_password, {})
            if not uid:
                raise UserError(_("Authentication failed on the instance."))

            models = xmlrpc.client.ServerProxy('%s/xmlrpc/2/object' % url, allow_none=True)

            # Find modules to install
            module_ids = models.execute_kw(
                db_name, uid, self.admin_password,
                'ir.module.module', 'search',
                [[('name', 'in', module_names)]],
            )
            if not module_ids:
                self._append_log(
                    "No matching apps found: %s" % ', '.join(module_names)
                )
                return

            # Trigger installation
            models.execute_kw(
                db_name, uid, self.admin_password,
                'ir.module.module', 'button_immediate_install',
                [module_ids],
            )

            self._append_log(
                "Apps installed successfully: %s" % ', '.join(module_names)
            )
            self.message_post(body=_(
                "Apps installed: %s"
            ) % ', '.join(module_names))

        except xmlrpc.client.Fault as e:
            raise UserError(
                _("Failed to install apps: %s") % e.faultString
            )

    def _on_module_install_error(self, exception, module_names):
        """Handle module installation failure."""
        self.ensure_one()
        self._append_log(
            "App installation failed (%s): %s"
            % (', '.join(module_names), str(exception))
        )



    def _get_nginx_template_name(self):
        """Return the appropriate nginx template based on the Odoo version's nginx_template field."""
        self.ensure_one()
        if self.odoo_version_id.nginx_template == 'old':
            return 'nginx_old_odoo_versions.jinja'
        return 'nginx_new_odoo_versions.jinja'

    def _provision_nginx(self, ssh):
        """Obtain SSL certificate via Certbot and deploy Nginx config on the Docker server."""
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
                            extra_storage_price = float(
                                self.env['ir.config_parameter'].sudo().get_param(
                                    'saas_master.extra_storage_price_per_gb', '0'
                                )
                            )
                            if extra_storage_price > 0:
                                # Extra storage pricing enabled — log overage, don't suspend
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
                            else:
                                # No extra storage pricing — suspend as before
                                try:
                                    instance.action_suspend()
                                    instance._append_log(
                                        "AUTO-SUSPENDED: Storage %.2f GB exceeds plan limit %.2f GB."
                                        % (total_bytes / (1024 ** 3), instance.plan_id.storage_limit)
                                    )
                                    instance.message_post(
                                        body=_(
                                            "Instance automatically suspended: total storage (%(used)s) "
                                            "exceeds plan limit (%(limit).2f GB).",
                                            used=instance.total_storage or '',
                                            limit=instance.plan_id.storage_limit,
                                        ),
                                        message_type='notification',
                                    )
                                    _logger.info(
                                        "Instance %s suspended: storage %.2f GB exceeds %.2f GB limit",
                                        instance.subdomain, total_bytes / (1024 ** 3),
                                        instance.plan_id.storage_limit,
                                    )
                                except Exception:
                                    _logger.exception(
                                        "Failed to suspend instance %s (id=%s)",
                                        instance.subdomain, instance.id,
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
        self.sale_order_id = order
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

        Also sends a warning email when the invoice first becomes overdue.
        """
        today = fields.Date.today()
        instances = self.search([
            ('state', '=', 'running'),
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

    def _check_dunning(self, today):
        """Check if any linked invoices are overdue and act accordingly."""
        self.ensure_one()
        if not self.sale_order_id:
            return

        # Find all unpaid posted invoices linked to this instance's sale orders
        so_domain = [
            ('move_type', '=', 'out_invoice'),
            ('payment_state', 'not in', ('paid', 'in_payment', 'reversed')),
            ('state', '=', 'posted'),
            ('invoice_date_due', '<', today),
            ('partner_id', '=', self.partner_id.id),
        ]
        # Search by sale order link first, fall back to origin
        if self.sale_order_id:
            so_domain.append(('invoice_origin', '=', self.sale_order_id.name))
        else:
            so_domain.append(('invoice_origin', '=', self.name or self.subdomain))
        overdue_invoices = self.env['account.move'].search(so_domain, limit=1)
        if not overdue_invoices:
            return

        grace_days = self.plan_id.grace_period_days if self.plan_id else 7
        oldest_due = overdue_invoices.invoice_date_due
        if not oldest_due:
            return
        days_overdue = (today - oldest_due).days

        if days_overdue > grace_days:
            # Grace period exceeded — suspend
            self.action_suspend()
            self._append_log(
                "AUTO-SUSPENDED: Invoice %s overdue by %d days (grace: %d)."
                % (overdue_invoices.name, days_overdue, grace_days)
            )
            self._send_notification('saas_core.mail_template_saas_suspended')
        elif not self.suspension_warning_sent:
            # Within grace period — send warning
            self.suspension_warning_sent = True
            self._send_notification('saas_core.mail_template_saas_payment_due')
            self._append_log(
                "Payment overdue warning sent. Invoice %s due %s. "
                "Grace period: %d days."
                % (overdue_invoices.name, oldest_due, grace_days)
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
        if (self.saas_product_id and new_plan.saas_product_id
                and new_plan.saas_product_id != self.saas_product_id):
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

    def action_request_plan_change(self, new_plan_id, billing_period=None):
        """Request a plan change from the portal.

        UPGRADE (new price > old price):
          - Calculate remaining value of current plan
          - Charge: new_plan_price - remaining_value (min 0)
          - Applied immediately after payment
          - Billing cycle resets from today

        DOWNGRADE (new price <= old price):
          - NO refund, NO credit, NO proration
          - Blocked if current DB size >= 75% of target plan's db_size_limit
          - Scheduled for end of current billing cycle
          - Client keeps current (higher) plan until then

        Returns:
          - Invoice record (upgrade, needs payment)
          - True (upgrade, zero charge)
          - 'scheduled' (downgrade scheduled)
        """
        self.ensure_one()
        if self.state not in ('running', 'stopped', 'suspended'):
            raise UserError(
                _("Can only change plan on running, stopped, or suspended instances.")
            )
        new_plan = self.env['saas.plan'].browse(int(new_plan_id))
        if not new_plan.exists():
            raise UserError(_("Invalid plan."))
        if new_plan.is_trial_plan:
            raise UserError(_("Cannot switch to a trial plan."))
        if new_plan.id == self.plan_id.id:
            raise UserError(_("Already on this plan."))

        billing_period = billing_period or self.billing_period or 'monthly'
        new_price = new_plan._get_price_for_period(billing_period)
        old_period = self.billing_period or 'monthly'
        old_price = self.plan_id._get_price_for_period(old_period) if self.plan_id else 0

        if new_price > old_price:
            return self._request_upgrade(new_plan, billing_period, new_price, old_price)
        else:
            return self._request_downgrade(new_plan, billing_period)

    # ---------- UPGRADE ----------

    def _request_upgrade(self, new_plan, billing_period, new_price, old_price):
        """Create proration invoice for an upgrade. Applied on payment."""
        self.ensure_one()
        today = fields.Date.today()
        period_label = 'Yearly' if billing_period == 'yearly' else 'Monthly'

        # Calculate remaining value of current subscription
        remaining_value = 0.0
        remaining_info = ''
        if self.next_invoice_date and self.last_invoice_date:
            total_days = (self.next_invoice_date - self.last_invoice_date).days
            remaining_days = (self.next_invoice_date - today).days
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

    def action_change_plan(self, new_plan_id, prorate=True):
        """Change the plan on a running instance.

        Updates resource limits on the running container and optionally
        creates a prorated credit/charge.
        """
        self.ensure_one()
        if self.state not in ('running', 'stopped', 'suspended'):
            raise UserError(
                _("Can only change plan on running, stopped, or suspended instances.")
            )
        new_plan = self.env['saas.plan'].browse(new_plan_id)
        if not new_plan.exists():
            raise UserError(_("Invalid plan."))

        old_plan = self.plan_id

        # Generate prorated invoice if applicable
        if prorate and old_plan and new_plan.price != old_plan.price and self.next_invoice_date:
            self._create_proration_invoice(old_plan, new_plan)

        self.plan_id = new_plan
        self._append_log(
            "Plan changed: %s → %s" % (
                old_plan.name if old_plan else 'None', new_plan.name
            )
        )
        self.message_post(body=_(
            "Plan changed from %s to %s.",
        ) % (old_plan.name if old_plan else '—', new_plan.name))

        # Update resource limits on the live container
        if self.state == 'running':
            try:
                self._update_container_resources()
            except Exception as e:
                _logger.exception(
                    "Failed to update container resources for %s",
                    self.subdomain,
                )
                self._append_log(
                    "WARNING: Plan updated but container resource update failed: %s" % e
                )

    def _create_proration_invoice(self, old_plan, new_plan):
        """Create a prorated charge or credit note for the plan change."""
        self.ensure_one()
        today = fields.Date.today()
        if not self.next_invoice_date or not self.last_invoice_date:
            return

        total_days = (self.next_invoice_date - self.last_invoice_date).days
        if total_days <= 0:
            return
        remaining_days = (self.next_invoice_date - today).days
        if remaining_days <= 0:
            return

        fraction = remaining_days / total_days
        price_diff = new_plan.price - old_plan.price
        proration_amount = price_diff * fraction

        if abs(proration_amount) < 0.01:
            return

        pricelist = self.partner_id.property_product_pricelist
        order_vals = {
            'partner_id': self.partner_id.id,
            'origin': _('Plan change: %s') % (self.name or self.subdomain),
            'order_line': [(0, 0, {
                'product_id': self._get_billing_product().id,
                'name': _('Plan change proration: %s → %s (%d days remaining)')
                        % (old_plan.name, new_plan.name, remaining_days),
                'product_uom_qty': 1,
                'price_unit': abs(proration_amount),
            })],
        }
        if pricelist:
            order_vals['pricelist_id'] = pricelist.id
        order = self.env['sale.order'].create(order_vals)
        order.action_confirm()

        if proration_amount > 0:
            invoice = order._create_invoices()
            invoice.action_post()
            self._append_log(
                "Proration invoice %s: %.2f for plan upgrade."
                % (invoice.name, proration_amount)
            )
        else:
            invoice = order._create_invoices(final=True)
            credit = invoice._reverse_moves(
                default_values_list=[{
                    'ref': _('Proration credit: %s → %s') % (old_plan.name, new_plan.name),
                }],
            )
            credit.action_post()
            self._append_log(
                "Proration credit %s: %.2f for plan downgrade."
                % (credit.name, abs(proration_amount))
            )

    def _update_container_resources(self):
        """Update CPU/RAM limits on a running container via docker update."""
        self.ensure_one()
        if not self.plan_id or self.state != 'running':
            return
        self._ensure_can_ssh()
        container_name = self._get_container_name()
        plan = self.plan_id

        # docker update --cpus=X --memory=Y container
        update_cmd = 'docker update --cpus=%s %s' % (
            shlex.quote(str(plan.cpu_limit)),
            shlex.quote(container_name),
        )
        if plan.ram_limit:
            update_cmd = 'docker update --cpus=%s --memory=%s %s' % (
                shlex.quote(str(plan.cpu_limit)),
                shlex.quote(plan.ram_limit),
                shlex.quote(container_name),
            )

        with self.docker_server_id._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(update_cmd)
            if exit_code != 0:
                raise UserError(
                    _("Failed to update container resources:\n%s") % stderr
                )

        # Also regenerate docker-compose.yml so next restart uses new limits
        with self.docker_server_id._get_ssh_connection() as ssh:
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

    def action_portal_start(self):
        """Start from portal — only allowed for stopped instances."""
        self.ensure_one()
        if self.state != 'stopped':
            raise UserError(_("Instance must be stopped to start."))
        self.action_restart()

