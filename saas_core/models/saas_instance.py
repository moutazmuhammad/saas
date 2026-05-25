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

# Untranslated technical tokens used as sale.order.origin so the dunning
# and renewal lookups work regardless of UI language. These must never be
# wrapped in _() — they are matched verbatim by _get_all_invoices().
ORIGIN_INITIAL = 'SAAS:INITIAL:%s'
ORIGIN_RENEWAL = 'SAAS:RENEWAL:%s'
ORIGIN_SUBSCRIPTION = 'SAAS:SUBSCRIPTION:%s'
ORIGIN_PLAN_UPGRADE = 'SAAS:UPGRADE:%s'
ORIGIN_DATA_RESTORATION = 'SAAS:RESTORATION:%s'
ORIGIN_BACKUP_ADDON = 'SAAS:BACKUP-ADDON:%s'
# Origins considered "optional" for dunning purposes (won't trigger suspension).
# Daily-backup add-on is opt-in — a missed payment for it shouldn't take down
# the whole instance the customer still uses every day.
OPTIONAL_INVOICE_ORIGIN_PREFIXES = (
    'SAAS:SUBSCRIPTION:', 'SAAS:UPGRADE:', 'SAAS:BACKUP-ADDON:',
)


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
        required=True,
        ondelete='restrict',
        index=True,
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
        ondelete='restrict',
        index=True,
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
        ondelete='restrict',
        index=True,
        help='The service/product this instance provides '
             '(e.g. "Pharmacy Management", "POS").',
    )
    plan_id = fields.Many2one(
        'saas.plan',
        string='Plan',
        tracking=True,
        ondelete='restrict',
        index=True,
        help='Resource plan defining CPU, RAM, and storage limits for this instance.',
    )

    # ========== Infrastructure ==========
    odoo_version_id = fields.Many2one(
        'saas.odoo.version',
        string='Odoo Version',
        tracking=True,
        ondelete='restrict',
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
        ondelete='restrict',
        index=True,
        domain="[('is_docker_host', '=', True)]",
        help='Physical server where the Docker container for this instance runs. '
             'Leave empty for automatic allocation based on server capacity.',
    )
    db_server_id = fields.Many2one(
        'saas.server',
        string='Database Server',
        tracking=True,
        ondelete='restrict',
        index=True,
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
    pre_provisioning_state = fields.Char(
        string='Pre-Provisioning State',
        readonly=True,
        help='State before entering provisioning. Used to recover instances '
             'stuck in provisioning after a server restart.',
    )
    pending_operation = fields.Selection(
        selection=[
            ('deploy', 'Deploy'),
            ('redeploy', 'Redeploy'),
            ('start', 'Start'),
            ('stop', 'Stop'),
            ('restart', 'Restart'),
            ('suspend', 'Suspend'),
            ('restore', 'Restore Backup'),
            ('cancel', 'Cancel'),
            ('delete', 'Delete'),
        ],
        readonly=True,
        help='Operation in progress while state=provisioning. Used by the '
             'recovery cron to decide whether stuck instances can be safely '
             'auto-recovered or whether manual intervention is required '
             '(destructive operations like delete/cancel must NOT be '
             'auto-reverted to a "live" state).',
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
        ondelete='set null',
        index=True,
        help='Sale order linked to this instance.',
    )
    restoration_invoice_id = fields.Many2one(
        'account.move',
        string='Restoration Invoice',
        readonly=True,
        ondelete='set null',
        help='Unpaid restoration fee invoice. Instance is suspended until paid.',
    )
    restore_banner_dismissed = fields.Boolean(
        string='Restore Banner Dismissed',
        default=False,
        help='Client dismissed the data restore suggestion banner.',
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
    package_ids = fields.One2many(
        'saas.instance.package',
        'instance_id',
        string='Python Packages',
        help='Python packages to install via pip on container startup.',
    )

    @api.depends('saas_product_id.is_hosting')
    def _compute_is_hosting(self):
        for rec in self:
            rec.is_hosting = rec.saas_product_id.is_hosting if rec.saas_product_id else False

    # ========== Hosting add-ons ==========
    daily_backup_enabled = fields.Boolean(
        string='Daily Backups',
        default=False,
        tracking=True,
        help='Hosting-only: when enabled, the daily backup cron creates '
             'an incremental, deduplicated snapshot of the entire instance '
             '(databases + filestore + addons + config + docker-compose '
             '+ pip requirements) using restic. Last 7 days are retained. '
             'Billed monthly as an add-on at the rate configured in SaaS '
             'settings.',
    )
    daily_backup_pending_invoice_id = fields.Many2one(
        'account.move',
        string='Daily Backup Pending Invoice',
        tracking=True,
        copy=False,
        ondelete='set null',
        help='Unpaid invoice gating the activation of daily backups. '
             'Set when the customer clicks "Enable Daily Backups" on the '
             'portal; cleared (and daily_backup_enabled flipped to True) '
             'as soon as the invoice transitions to paid / in_payment.',
    )
    daily_backup_pending_state = fields.Selection(
        related='daily_backup_pending_invoice_id.payment_state',
        string='Daily Backup Pending Payment State',
        readonly=True,
    )
    restic_password = fields.Char(
        string='Restic Repository Password',
        readonly=True,
        groups='saas_core.group_saas_manager',
        help='AES-256 password for this instance\'s restic backup '
             'repository. Generated on the first daily backup. NEVER '
             'shared with the customer. Loss of this value renders '
             'all daily snapshots unrecoverable — back up the saas '
             'master database appropriately.',
    )
    daily_backup_monthly_price = fields.Float(
        string='Daily Backup Monthly Price',
        compute='_compute_daily_backup_monthly_price',
        help='Monthly add-on price charged for this instance when daily '
             'backups are enabled. Pulled from SaaS settings at compute time.',
    )
    # Backup billing runs on its own monthly cycle, independent of the
    # main subscription's billing_period. This way a customer on a
    # yearly plan still pays the backup add-on once a month.
    daily_backup_next_invoice_date = fields.Date(
        string='Daily Backup Next Invoice',
        copy=False,
        help='When the next monthly daily-backup invoice is due. Set '
             'on activation payment to first day of next month, then '
             'advanced by one month each renewal.',
    )
    daily_backup_last_invoice_date = fields.Date(
        string='Daily Backup Last Invoice',
        copy=False,
        help='Most recent month the daily-backup add-on was billed for.',
    )

    @api.depends('daily_backup_enabled')
    def _compute_daily_backup_monthly_price(self):
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            price = float(ICP.get_param(
                'saas_master.hosting_daily_backup_price', '0.0',
            ))
        except (TypeError, ValueError):
            price = 0.0
        for rec in self:
            rec.daily_backup_monthly_price = price if rec.daily_backup_enabled else 0.0

    # ========== Free Trial ==========
    is_trial = fields.Boolean(
        string='Free Trial',
        default=False,
        tracking=True,
        index=True,
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
        ondelete='set null',
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
        ondelete='set null',
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
        index=True,
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
        store=True,
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
    last_error = fields.Text(
        string='Last Error',
        readonly=True,
        help='Reason the last background operation failed.',
    )
    last_error_date = fields.Datetime(
        string='Error Date',
        readonly=True,
        help='When the last error occurred.',
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
        ondelete='restrict',
        index=True,
        help='Company that manages this SaaS instance.',
    )

    # ========== Constraints ==========
    def init(self):
        """Create partial unique indexes that exclude cancelled instances."""
        cr = self.env.cr
        cr.execute("""
            SELECT 1 FROM pg_indexes
            WHERE indexname = 'saas_instance_unique_subdomain_per_domain'
              AND indexdef ILIKE '%cancelled%'
        """)
        if not cr.fetchone():
            cr.execute("""
                ALTER TABLE saas_instance
                    DROP CONSTRAINT IF EXISTS saas_instance_unique_subdomain_per_domain;
                DROP INDEX IF EXISTS saas_instance_unique_subdomain_per_domain;
                CREATE UNIQUE INDEX saas_instance_unique_subdomain_per_domain
                    ON saas_instance (subdomain, domain_id)
                    WHERE state NOT IN ('cancelled', 'cancelled_by_client');
            """)
        for col in ('xmlrpc_port', 'longpolling_port'):
            idx = 'saas_instance_unique_%s_per_server' % col
            cr.execute("""
                SELECT 1 FROM pg_indexes
                WHERE indexname = %s AND indexdef ILIKE '%%cancelled%%'
            """, (idx,))
            if cr.fetchone():
                continue
            cr.execute("""
                ALTER TABLE saas_instance
                    DROP CONSTRAINT IF EXISTS %s;
                DROP INDEX IF EXISTS %s;
                CREATE UNIQUE INDEX %s
                    ON saas_instance (docker_server_id, %s)
                    WHERE state NOT IN ('cancelled', 'cancelled_by_client')
                      AND %s IS NOT NULL AND %s > 0;
            """ % (idx, idx, idx, col, col, col))

    # Note: SQL-level uniqueness is enforced by partial indexes in init()
    # (cancelled instances must be allowed to retain their old ports for audit).
    _sql_constraints = []

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
            if rec.pip_packages:
                rec._sync_packages_from_text()
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'pip_packages' in vals and not self.env.context.get('_skip_pip_sync'):
            self._sync_packages_from_text()
        return result

    # Strict PEP 508 / requirement-spec regex. Refuses anything that pip
    # would interpret as an option flag (e.g. `--index-url=...`) or a
    # path/URL — those would let a tenant redirect pip to attacker-
    # controlled packages whose setup.py runs arbitrary code.
    _PIP_PACKAGE_RE = re.compile(
        r'^[A-Za-z0-9][A-Za-z0-9._-]*'           # name
        r'(\[[A-Za-z0-9._,-]+\])?'                # optional [extras]
        r'(\s*(==|!=|<=|>=|<|>|~=)\s*[A-Za-z0-9._*+-]+'  # spec op + version
        r'(\s*,\s*(==|!=|<=|>=|<|>|~=)\s*[A-Za-z0-9._*+-]+)*)?$'
    )

    def _validate_pip_line(self, line):
        if not self._PIP_PACKAGE_RE.match(line):
            raise UserError(_(
                "Invalid pip package spec: %r\n\n"
                "Use the form 'name[==version]' (PEP 508). "
                "Options like '--index-url' or paths/URLs are not allowed."
            ) % line)

    def _sync_packages_from_text(self):
        """Sync ``pip_packages`` text field to ``package_ids`` One2many.

        Parses the text field, deduplicates by package name, and
        creates/updates/removes ``package_ids`` records to match.
        """
        Package = self.env['saas.instance.package']
        for rec in self:
            existing = {}
            for p in rec.package_ids:
                key = p.name.lower().split('=')[0].split('<')[0].split('>')[0].split('!')[0].split('[')[0].strip()
                existing[key] = p

            new_names = []
            if rec.pip_packages:
                for line in rec.pip_packages.splitlines():
                    line = line.strip()
                    if line and not line.startswith('#'):
                        rec._validate_pip_line(line)
                        new_names.append(line)

            new_keys = set()
            to_create = []
            for name in new_names:
                key = name.lower().split('=')[0].split('<')[0].split('>')[0].split('!')[0].split('[')[0].strip()
                if key in new_keys:
                    continue
                new_keys.add(key)
                if key not in existing:
                    to_create.append({'instance_id': rec.id, 'name': name})
                elif existing[key].name != name:
                    existing[key].name = name

            to_remove = rec.package_ids.filtered(
                lambda p: p.name.lower().split('=')[0].split('<')[0].split('>')[0].split('!')[0].split('[')[0].strip() not in new_keys
            )
            to_remove.unlink()
            if to_create:
                Package.create(to_create)

    def _sync_text_from_packages(self):
        """Sync ``package_ids`` One2many back to ``pip_packages`` text field."""
        for rec in self:
            names = rec.package_ids.mapped('name')
            rec.with_context(_skip_pip_sync=True).pip_packages = '\n'.join(names) if names else False

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

    @api.depends('sale_order_id')
    def _compute_sale_order_count(self):
        for rec in self:
            rec.sale_order_count = 1 if rec.sale_order_id else 0

    @api.depends('sale_order_id', 'sale_order_id.invoice_ids', 'partner_id', 'name', 'subdomain')
    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec._get_all_invoices())

    def _instance_origin_tokens(self):
        """Return the list of untranslated origin tokens this instance uses."""
        self.ensure_one()
        ref = self.name or self.subdomain
        if not ref:
            return []
        return [
            ORIGIN_INITIAL % ref,
            ORIGIN_RENEWAL % ref,
            ORIGIN_SUBSCRIPTION % ref,
            ORIGIN_PLAN_UPGRADE % ref,
            ORIGIN_DATA_RESTORATION % ref,
            ORIGIN_BACKUP_ADDON % ref,
        ]

    def _get_all_invoices(self):
        """Return all invoices related to this instance across all sale orders.

        Matches sale orders by exact untranslated origin tokens. Also
        accepts legacy translated origins ("Renewal: …", "Subscription: …"
        in any language) for backwards compatibility with records created
        before token-based origins were introduced.
        """
        self.ensure_one()
        instance_ref = self.name or self.subdomain
        if not instance_ref:
            return self.env['account.move']
        expected_origins = self._instance_origin_tokens() + [instance_ref]
        domain = [
            ('partner_id', '=', self.partner_id.id),
            '|',
            ('origin', 'in', expected_origins),
            ('id', '=', self.sale_order_id.id if self.sale_order_id else 0),
        ]
        sale_orders = self.env['sale.order'].search(domain)
        # Defensive: also pick up legacy SOs where origin contains the
        # instance ref preceded by a known label in any locale.
        if not sale_orders or self.sale_order_id not in sale_orders:
            legacy = self.env['sale.order'].search([
                ('partner_id', '=', self.partner_id.id),
                ('origin', 'ilike', instance_ref),
            ])
            sale_orders |= legacy.filtered(
                lambda s: s.origin and instance_ref in s.origin
            )
        if not sale_orders:
            return self.env['account.move']
        return sale_orders.mapped('invoice_ids')

    # ========== Sales & Invoicing Actions ==========

    def _get_daily_backup_product(self):
        """Return the singleton product.product for the daily-backup add-on.

        Created on first use. Used both in the one-time purchase
        invoice (when the customer enables the feature) and as a
        recurring line on subsequent renewal invoices.
        """
        product = self.env['product.product'].sudo().search(
            [('default_code', '=', 'SAAS-BACKUP-ADDON')], limit=1,
        )
        if not product:
            product = self.env['product.product'].sudo().create({
                'name': 'Daily Backups Add-on',
                'default_code': 'SAAS-BACKUP-ADDON',
                'type': 'service',
                'list_price': 0.0,
                'sale_ok': True,
                'purchase_ok': False,
                'taxes_id': [(5, 0, 0)],
            })
        return product

    def _get_daily_backup_price(self):
        """Monthly price of the backup add-on from SaaS settings."""
        try:
            return float(
                self.env['ir.config_parameter'].sudo().get_param(
                    'saas_master.hosting_daily_backup_price', '0.0',
                )
            )
        except (TypeError, ValueError):
            return 0.0

    def action_purchase_daily_backup(self):
        """Create an unpaid invoice for the backup add-on.

        Sequence:
        1. Sale order with a single ``Daily Backups Add-on`` line at
           the monthly add-on price from settings.
        2. Confirm SO → create + post the invoice.
        3. Store it on ``daily_backup_pending_invoice_id``. Once it
           transitions to ``paid``/``in_payment``, the
           ``account.move.write`` override below flips
           ``daily_backup_enabled`` to True and clears the pointer.

        Caller (portal route) then redirects to our custom checkout
        page where the customer pays.
        """
        self.ensure_one()
        if not self.is_hosting:
            raise UserError(_(
                "Daily backups are a hosting-only feature."
            ))
        if self.is_trial:
            raise UserError(_(
                "Daily backups can't be purchased on a trial plan."
            ))
        if self.daily_backup_enabled:
            raise UserError(_(
                "Daily backups are already enabled on this instance."
            ))
        if self.daily_backup_pending_invoice_id:
            existing = self.daily_backup_pending_invoice_id
            if existing.state == 'posted' and existing.payment_state not in (
                'paid', 'in_payment', 'reversed', 'invoicing_legacy',
            ):
                # An unpaid invoice already exists — return it instead
                # of creating a second one. Portal redirects there.
                return existing
            # Old invoice is paid (shouldn't happen — hook would have
            # cleared this), or cancelled. Clear and re-issue.
            self.daily_backup_pending_invoice_id = False

        monthly_price = self._get_daily_backup_price()
        if monthly_price <= 0:
            raise UserError(_(
                "Daily backup pricing isn't configured. Ask the "
                "platform operator to set the monthly add-on price "
                "in SaaS settings."
            ))

        # Daily-backup billing is ALWAYS monthly, independent of the
        # main subscription's period. Prorate the activation invoice
        # from today to the first day of next month, denominated in
        # this calendar month's length so a same-day enable on (say)
        # Jan 5 charges (days remaining in Jan) / 31. The monthly
        # renewal cron then takes over from that anchor date.
        today = fields.Date.today()
        cycle_end = (today + relativedelta(months=1)).replace(day=1)
        month_start = today.replace(day=1)
        cycle_days = (month_start + relativedelta(months=1) - month_start).days
        remaining_days = max(1, min((cycle_end - today).days, cycle_days))
        prorated_price = round(
            monthly_price * remaining_days / cycle_days, 2,
        )

        product = self._get_daily_backup_product()
        pricelist = self.partner_id.property_product_pricelist
        line_name = _(
            'Daily Backups Add-on (monthly, prorated %(days)s/%(total)s '
            'days through %(end)s) — %(instance)s'
        ) % {
            'days': remaining_days,
            'total': cycle_days,
            'end': cycle_end.strftime('%Y-%m-%d'),
            'instance': self.name or self.subdomain,
        }
        order_vals = {
            'partner_id': self.partner_id.id,
            'origin': ORIGIN_BACKUP_ADDON % (self.name or self.subdomain),
            'order_line': [(0, 0, {
                'product_id': product.id,
                'name': line_name,
                'product_uom_qty': 1,
                'price_unit': prorated_price,
            })],
        }
        if pricelist:
            order_vals['pricelist_id'] = pricelist.id
        order = self.env['sale.order'].sudo().create(order_vals)
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
        self.daily_backup_pending_invoice_id = invoice.id
        self._append_log(
            "Daily-backup add-on activation invoice %s created — "
            "%s/%s days, prorated %.2f (full monthly price %.2f)."
            % (
                invoice.name, remaining_days, cycle_days,
                prorated_price, monthly_price,
            )
        )
        return invoice

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
            'origin': ORIGIN_INITIAL % (self.name or self.subdomain),
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
        # Initialise the recurring billing schedule. Without this the
        # renewal cron never picks up the instance and the customer gets
        # an indefinite free subscription.
        self._set_next_invoice_date()
        self._append_log("Manually marked as paid. Deploying automatically.")
        self.message_post(body=_("Manually marked as paid — deploying now."))
        self.action_deploy()

    def action_view_sale_order(self):
        """Open the linked sale order."""
        self.ensure_one()
        if not self.sale_order_id:
            return False
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
            return False
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

    @staticmethod
    def _sanitize_path_component(value):
        """Strip a string to characters safe inside a remote filesystem path.

        Allows lowercase ASCII alphanumerics, hyphen and underscore.
        Returns '' if no character survives. Used as defence-in-depth
        against path traversal via free-text fields like `partner.ref`
        — never trust caller-controlled values inside `mkdir -p`,
        `rm -rf`, `chown`, `chmod` etc.
        """
        if not value:
            return ''
        cleaned = ''.join(
            c for c in value.strip().lower().replace(' ', '_')
            if c.isascii() and (c.isalnum() or c in '_-')
        )
        # Refuse purely-dot or empty strings (would escape into the parent).
        if not cleaned or cleaned.strip('._-') == '':
            return ''
        return cleaned[:64]

    def _get_partner_code(self):
        """Return a filesystem-safe partner identifier: code_name."""
        self.ensure_one()
        code = self._sanitize_path_component(self.partner_id.ref or '')
        if not code:
            code = str(self.partner_id.id)
        safe_name = self._sanitize_path_component(self.partner_id.name or '')
        return '%s_%s' % (code, safe_name) if safe_name else code

    def _get_instance_path(self):
        """Return the full remote path for this instance."""
        self.ensure_one()
        server = self.docker_server_id
        base = server.docker_base_path.rstrip('/')
        partner = self._get_partner_code()
        # subdomain is regex-validated (SUBDOMAIN_RE) so it can't contain '/'
        # or '..' but re-check defensively before composing the path.
        sub = self.subdomain or ''
        if not SUBDOMAIN_RE.match(sub):
            raise UserError(
                _("Refusing to build instance path: subdomain '%s' is invalid.")
                % sub
            )
        path = '%s/%s/%s' % (base, partner, sub)
        # Final containment check: the realpath must remain under base.
        norm = os.path.normpath(path)
        if not norm.startswith(os.path.normpath(base) + '/'):
            raise UserError(
                _("Refusing to build instance path: '%s' escapes base '%s'.")
                % (norm, base)
            )
        return path

    def _get_container_name(self):
        """Return the Docker container name for this instance."""
        self.ensure_one()
        return 'odoo_%s' % self.subdomain

    def _get_db_host(self):
        """Return the hostname/IP for odoo.conf (used inside the container).

        Same-server: ``host.docker.internal`` (resolved by Docker).
        Different server: DB server's private or public IP.
        """
        self.ensure_one()
        psql_server = self.db_server_id
        if psql_server == self.docker_server_id:
            return 'host.docker.internal'
        return psql_server.private_ip_v4 or psql_server.ip_v4

    def _get_db_host_for_ssh(self):
        """Return the DB hostname/IP for commands run on the host via SSH.

        Same-server: ``localhost`` (psql runs on the same machine).
        Different server: DB server's private or public IP.
        """
        self.ensure_one()
        psql_server = self.db_server_id
        if psql_server == self.docker_server_id:
            return 'localhost'
        return psql_server.private_ip_v4 or psql_server.ip_v4

    def _get_container_uid(self, ssh):
        """Return the UID of the default user inside the Docker image.

        Uses ``--entrypoint`` to bypass the custom entrypoint (which
        requires mounted volumes) and runs a plain ``id -u``.  Falls
        back to 101 (the default in the official Odoo images) if
        detection fails.
        """
        self.ensure_one()
        odoo_image = self.odoo_version_id._get_docker_image()
        exit_code, uid_out, _ = ssh.execute(
            'docker run --rm --entrypoint id %s -u 2>/dev/null'
            % shlex.quote(odoo_image)
        )
        uid = uid_out.strip()
        if exit_code != 0 or not uid.isdigit():
            return '101'
        return uid

    def _ensure_webhooks_registered(self):
        """Verify and register webhooks for all repos that need them.

        Called at the end of deploy/redeploy to guarantee that every repo
        with ``webhook_enabled=True`` and a token actually has a working
        webhook on the Git provider.  Logs the outcome per repo so the
        operator can see exactly what happened.
        """
        self.ensure_one()
        repos = self.repo_ids.filtered(
            lambda r: r.state == 'cloned' and r.webhook_enabled
        )
        if not repos:
            return

        for repo in repos:
            token = repo.sudo().github_token
            if not token:
                self._append_log(
                    "Webhook skipped for %s: no access token. "
                    "Client must provide a token for auto-deploy."
                    % repo.name
                )
                continue

            # Already registered and valid?
            if repo.webhook_provider_id:
                try:
                    if repo._verify_webhook_on_provider():
                        self._append_log(
                            "Webhook verified for %s (provider ID: %s)."
                            % (repo.name, repo.webhook_provider_id)
                        )
                        continue
                except Exception:
                    pass
                # Stale provider ID — clear and re-register
                repo.webhook_provider_id = False

            # Register (or re-register)
            self._append_log(
                "Registering webhook for %s..." % repo.name
            )
            try:
                success = repo._register_webhook_with_retry()
                if not success:
                    self._append_log(
                        "WARNING: Webhook registration failed for %s. "
                        "Auto-deploy will NOT work until this is fixed. "
                        "Check the access token and web.base.url setting."
                        % repo.name
                    )
            except Exception as e:
                _logger.warning(
                    "Webhook registration error for %s: %s", repo.name, e,
                )
                self._append_log(
                    "WARNING: Webhook registration error for %s: %s"
                    % (repo.name, e)
                )

    # Cap the in-DB log to the last ~64 KB so the column does not grow
    # unbounded. Postgres TOAST writes the whole column on every UPDATE,
    # and `_append_log` is called dozens of times per deploy.
    _PROVISIONING_LOG_MAX = 64 * 1024

    def _append_log(self, message):
        """Append a timestamped message to provisioning_log (size-bounded)."""
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = '[%s] %s\n' % (timestamp, message)
        current = self.provisioning_log or ''
        new_log = current + line
        if len(new_log) > self._PROVISIONING_LOG_MAX:
            # Drop the oldest data, but keep complete lines.
            new_log = new_log[-self._PROVISIONING_LOG_MAX:]
            nl = new_log.find('\n')
            if nl >= 0 and nl < len(new_log) - 1:
                new_log = '... [truncated] ...\n' + new_log[nl + 1:]
        self.provisioning_log = new_log

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

    def _provision_postgresql(self, create_db=True):
        """Ensure the PostgreSQL role exists, and optionally the per-instance DB.

        Hosting instances pass ``create_db=False`` — they get an empty
        Odoo container and create databases themselves via the master
        password (or, once portal CRUD ships, via /my/instances).
        The role still gets ``CREATEDB``, which is what makes that work.
        """
        self.ensure_one()
        psql_server = self.db_server_id
        if not psql_server:
            raise UserError(_("No database server configured on this instance."))

        db_user = self.db_user
        db_password = self.db_password

        if not DB_USER_RE.match(db_user):
            raise ValidationError(
                _("Database user '%s' contains unsafe characters.") % db_user
            )

        sql_script = (
            "DO $body$\n"
            "BEGIN\n"
            "  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = %(user_lit)s) THEN\n"
            "    EXECUTE format('CREATE ROLE %%I WITH LOGIN CREATEDB PASSWORD %%L', %(user_lit)s, %(pass_lit)s);\n"
            "  ELSE\n"
            "    EXECUTE format('ALTER ROLE %%I WITH LOGIN CREATEDB PASSWORD %%L', %(user_lit)s, %(pass_lit)s);\n"
            "  END IF;\n"
            "END $body$;\n"
        ) % {
            'user_lit': "$$%s$$" % db_user,
            'pass_lit': "$$%s$$" % db_password.replace("$$", "$ $"),
        }

        ensure_role_cmd = "sudo -u postgres psql <<'SAAS_END_SQL'\n%s\nSAAS_END_SQL" % sql_script

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

            if not create_db:
                self._append_log(
                    "Skipping database creation (hosting instance — "
                    "customer creates DBs themselves)."
                )
                return

            db_name = self.subdomain
            if not SUBDOMAIN_RE.match(db_name):
                raise ValidationError(
                    _("Subdomain '%s' contains unsafe characters for a database name.") % db_name
                )

            create_db_cmd = (
                "sudo -u postgres psql -tc "
                "\"SELECT 1 FROM pg_database WHERE datname='%(db)s'\" "
                "| grep -q 1 "
                "|| sudo -u postgres createdb -O %(user)s %(db)s"
            ) % {'db': db_name, 'user': db_user}

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

            # PG 15+ dropped the default `GRANT ALL ON SCHEMA public TO
            # PUBLIC`, so owning the database isn't enough — we have to
            # explicitly hand the public schema to our role or Odoo's
            # init blows up creating `base_registry_signaling`.
            self._pg_grant_public_schema(ssh, db_name, db_user)

    def _pg_grant_public_schema(self, ssh, db_name, db_user):
        """Give ``db_user`` full control of ``public`` in ``db_name``.

        Always run as ``postgres`` superuser because only the schema
        owner (postgres by default) can re-assign ownership or grant
        on it. Idempotent — re-running is a no-op on PostgreSQL.
        """
        # Defense in depth: callers validate these but we re-check
        # before formatting into raw SQL.
        # Allow a leading underscore so the per-instance template
        # name (``__odoo_template_<sub>``) passes — customer-facing
        # names go through the stricter ``_DB_NAME_RE`` regex earlier.
        if not re.match(r'^[_a-z][a-z0-9_-]{0,62}$', db_name or ''):
            raise UserError(_("Invalid db name %r") % db_name)
        if not DB_USER_RE.match(db_user or ''):
            raise UserError(_("Invalid db user %r") % db_user)
        sql = (
            'ALTER SCHEMA public OWNER TO "%(u)s"; '
            'GRANT ALL ON SCHEMA public TO "%(u)s";'
        ) % {'u': db_user}
        cmd = 'sudo -u postgres psql -d %s -v ON_ERROR_STOP=1 -c %s 2>&1' % (
            shlex.quote(db_name), shlex.quote(sql),
        )
        exit_code, stdout, stderr = ssh.execute(cmd)
        if exit_code != 0:
            raise UserError(
                _("Failed to grant public schema on '%s' to '%s':\n%s")
                % (db_name, db_user, stderr or stdout)
            )

    def _pg_ensure_db_with_grants(self, db_name):
        """Createdb (if needed) and hand the role full schema rights.

        Used by ``hosting_db_create`` for per-DB portal creation, where
        the Odoo CLI would otherwise let the new DB inherit PG 15+'s
        restrictive defaults and fail at init time.
        """
        self.ensure_one()
        psql_server = self.db_server_id
        if not psql_server:
            raise UserError(_("No database server configured on this instance."))
        # Allow a leading underscore so the per-instance template
        # name (``__odoo_template_<sub>``) passes — customer-facing
        # names go through the stricter ``_DB_NAME_RE`` regex earlier.
        if not re.match(r'^[_a-z][a-z0-9_-]{0,62}$', db_name or ''):
            raise UserError(_("Invalid db name %r") % db_name)
        if not DB_USER_RE.match(self.db_user or ''):
            raise UserError(_("Invalid db user %r") % self.db_user)

        db_user = self.db_user
        create_db_cmd = (
            "sudo -u postgres psql -tc "
            "\"SELECT 1 FROM pg_database WHERE datname='%(db)s'\" "
            "| grep -q 1 "
            "|| sudo -u postgres createdb -O %(user)s %(db)s"
        ) % {'db': db_name, 'user': db_user}

        with psql_server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(create_db_cmd)
            if exit_code != 0:
                raise UserError(_(
                    "Failed to create database '%s':\n%s"
                ) % (db_name, stderr or stdout))
            self._pg_grant_public_schema(ssh, db_name, db_user)

    # ------------------------------------------------------------------
    # PG-level template helpers — production path for fast DB creation.
    # The template is initialised once per instance, then every
    # customer-requested DB is a near-instant CREATE DATABASE ...
    # WITH TEMPLATE off it. Avoids the racing-Odoo-worker problems that
    # plagued the per-create-init approach.
    # ------------------------------------------------------------------
    _DB_IDENT_RE = re.compile(r'^[_a-z][a-z0-9_-]{0,62}$')

    def _pg_db_exists(self, db_name):
        """Return True if ``db_name`` exists on the instance's db server."""
        self.ensure_one()
        psql_server = self.db_server_id
        if not psql_server or not db_name:
            return False
        if not self._DB_IDENT_RE.match(db_name):
            raise UserError(_("Invalid db name %r") % db_name)
        safe = db_name.replace("'", "''")
        cmd = (
            "sudo -u postgres psql -tA -c "
            "\"SELECT 1 FROM pg_database WHERE datname='%s'\""
        ) % safe
        with psql_server._get_ssh_connection() as ssh:
            exit_code, stdout, _ = ssh.execute(cmd)
        return exit_code == 0 and stdout.strip() == '1'

    def _pg_clone_db(self, source, target):
        """``CREATE DATABASE target WITH TEMPLATE source OWNER <role>``.

        Postgres copies the data files at the storage layer — typically
        seconds — without running any Odoo init. ``source`` must be
        flagged ``datistemplate=true`` (or have no active connections)
        for the clone to succeed.
        """
        self.ensure_one()
        psql_server = self.db_server_id
        if not psql_server:
            raise UserError(_("No database server configured."))
        for ident in (source, target, self.db_user):
            if not ident or not self._DB_IDENT_RE.match(ident):
                raise UserError(
                    _("Refusing to clone with invalid identifier %r") % ident
                )
        sql = (
            'CREATE DATABASE "%(t)s" WITH TEMPLATE "%(s)s" OWNER "%(u)s"'
        ) % {'t': target, 's': source, 'u': self.db_user}
        cmd = 'sudo -u postgres psql -v ON_ERROR_STOP=1 -c %s 2>&1' % (
            shlex.quote(sql),
        )
        with psql_server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(cmd, timeout=600)
        if exit_code != 0:
            raise UserError(_(
                "Failed to clone database from template:\n%s"
            ) % (stderr or stdout))

    def _pg_mark_template(self, db_name, flag=True):
        """Toggle ``datistemplate`` on a DB.

        Marking as a template:
        * tells Postgres it can be used as a clone source without
          requiring the absence of connections;
        * tells our Odoo workers to skip it (they don't load DBs
          where ``datistemplate=true`` because they aren't customer
          databases).
        """
        self.ensure_one()
        psql_server = self.db_server_id
        if not psql_server or not self._DB_IDENT_RE.match(db_name or ''):
            return
        safe = db_name.replace("'", "''")
        sql = (
            "UPDATE pg_database SET datistemplate=%s "
            "WHERE datname='%s'"
        ) % ('true' if flag else 'false', safe)
        cmd = 'sudo -u postgres psql -v ON_ERROR_STOP=1 -c %s 2>&1' % (
            shlex.quote(sql),
        )
        with psql_server._get_ssh_connection() as ssh:
            ssh.execute(cmd)

    def _pg_drop_db(self, db_name):
        """Drop a database (best-effort). Used to clean up half-built
        templates or failed clones."""
        self.ensure_one()
        psql_server = self.db_server_id
        if not psql_server or not self._DB_IDENT_RE.match(db_name or ''):
            return
        # PG won't drop a database flagged ``datistemplate=true`` even
        # for superuser, so clear the flag first.
        self._pg_mark_template(db_name, flag=False)
        cmd = (
            'sudo -u postgres dropdb --force --if-exists %s 2>&1'
            % shlex.quote(db_name)
        )
        with psql_server._get_ssh_connection() as ssh:
            ssh.execute(cmd, timeout=120)

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

    # PostgreSQL advisory-lock namespace key for per-server port allocation.
    # Arbitrary 32-bit constant; pairs with docker_server_id to form a
    # unique 64-bit key so two servers don't block each other.
    _PORT_ALLOC_LOCK_NAMESPACE = 0x5AA5_0001

    def _auto_assign_ports(self):
        """Auto-assign xmlrpc_port and longpolling_port if not already set.

        Uses a Postgres transaction-scoped advisory lock keyed by
        docker_server_id so concurrent provisioning on the same server
        cannot pick the same port pair. The previous SELECT FOR UPDATE
        only locked rows whose `xmlrpc_port>0` — racing transactions
        with NULL ports skipped each other and both wrote the same port,
        triggering an opaque IntegrityError after every other side-effect
        (DB created, container started) had run.
        """
        self.ensure_one()
        if self.xmlrpc_port and self.longpolling_port:
            return
        server_id = self.docker_server_id.id
        if not server_id:
            raise ValidationError(_(
                "Cannot allocate ports: docker server is not set."
            ))

        starting_port = int(self.env['ir.config_parameter'].sudo().get_param(
            'saas_master.default_instance_starting_port', '32000',
        ))

        # pg_advisory_xact_lock is released automatically at COMMIT/ROLLBACK.
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (self._PORT_ALLOC_LOCK_NAMESPACE, server_id),
        )

        # Now safely scan ALL ports (including ours) — we hold the lock.
        self.env.cr.execute(
            "SELECT xmlrpc_port, longpolling_port FROM saas_instance "
            "WHERE docker_server_id = %s AND id != %s "
            "AND state NOT IN ('cancelled', 'cancelled_by_client')",
            (server_id, self.id or 0),
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
        # Flush so the rest of this transaction sees the assignment and
        # other sessions can see it the moment we commit.
        self.env.cr.execute(
            "UPDATE saas_instance SET xmlrpc_port=%s, longpolling_port=%s "
            "WHERE id=%s",
            (candidate, candidate + 1, self.id),
        )

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

    def _strict_refresh_usage(self):
        """Refresh usage, raising if it cannot be measured.

        Use this from places (downgrade gate, billing) where acting on
        stale or zero data could let a customer move to a plan that
        cannot accommodate them.
        """
        self.ensure_one()
        self._ensure_can_ssh()
        with self.docker_server_id._get_ssh_connection() as ssh:
            self._refresh_usage_with_ssh(ssh)

    @api.model
    def _cron_refresh_usage(self):
        """Cron: refresh resource usage for all running instances.

        Batched: opens ONE SSH per (docker_server, db_server) per pass,
        runs ONE psql query per db_server returning every DB size at
        once. The naive per-instance loop opened 2N fresh paramiko
        handshakes per cron run; this version drops that to ~M (number
        of distinct servers).
        """
        instances = self.search([
            ('state', '=', 'running'),
            ('docker_server_id', '!=', False),
        ])
        if not instances:
            return

        # Pre-fetch all DB sizes from each db_server in one query.
        db_sizes_by_server = {}
        for db_server in instances.mapped('db_server_id'):
            if not db_server:
                continue
            db_names = [
                i.subdomain for i in instances
                if i.db_server_id == db_server
                and i.subdomain
                and SUBDOMAIN_RE.match(i.subdomain)
            ]
            if not db_names:
                continue
            try:
                db_sizes_by_server[db_server.id] = \
                    db_server._fetch_database_sizes(db_names)
            except Exception:
                _logger.exception(
                    "Cron: failed to batch-fetch DB sizes from server %s",
                    db_server.name,
                )
                db_sizes_by_server[db_server.id] = {}

        # Group by docker_server and refresh in one SSH session each.
        for docker_server in instances.mapped('docker_server_id'):
            server_instances = instances.filtered(
                lambda i: i.docker_server_id == docker_server
            )
            try:
                with docker_server._get_ssh_connection() as ssh:
                    for instance in server_instances:
                        try:
                            db_sizes = db_sizes_by_server.get(
                                instance.db_server_id.id, {}
                            )
                            instance._refresh_usage_with_ssh(
                                ssh,
                                precomputed_db_size=db_sizes.get(instance.subdomain),
                            )
                            self.env.cr.commit()
                        except Exception:
                            self.env.cr.rollback()
                            _logger.exception(
                                "Cron: failed to refresh usage for %s",
                                instance.subdomain,
                            )
            except Exception:
                _logger.exception(
                    "Cron: cannot reach docker server %s for usage refresh",
                    docker_server.name,
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

    # Operations that can be safely re-run if interrupted. Anything else
    # (delete, cancel, suspend) must go to a manual-review state because
    # the partial side-effects on the remote server make "resume" unsafe.
    _RECOVERABLE_OPERATIONS = ('deploy', 'redeploy', 'restart', 'start', 'restore')

    def _cron_recover_stuck_provisioning(self):
        """Cron: recover instances stuck in ``provisioning`` after a restart.

        Idempotent operations (deploy/redeploy/restart/start/restore) are
        re-queued. Destructive operations (cancel/delete/suspend) are NOT
        auto-reverted — doing so would mark a half-deleted instance as
        "running" again. They are routed to ``failed`` for manual review.
        """
        threshold = fields.Datetime.now() - datetime.timedelta(minutes=15)
        stuck = self.search([
            ('state', '=', 'provisioning'),
            ('write_date', '<', threshold),
        ])
        if not stuck:
            return
        _logger.info(
            "Cron: recovering %d instance(s) stuck in provisioning.", len(stuck),
        )
        for instance in stuck:
            try:
                op = instance.pending_operation
                prev_state = instance.pre_provisioning_state or 'failed'
                if op and op not in self._RECOVERABLE_OPERATIONS:
                    instance._append_log(
                        "Recovery aborted: operation '%s' was in progress "
                        "and cannot be safely auto-reverted. Marked as failed "
                        "for manual review." % op
                    )
                    instance.write({
                        'state': 'failed',
                        'pre_provisioning_state': False,
                        'pending_operation': False,
                        'last_error': 'Server restarted during %s — manual review required' % op,
                        'last_error_date': fields.Datetime.now(),
                    })
                else:
                    instance._append_log(
                        "Recovered from stuck provisioning state "
                        "(likely caused by a server restart)."
                    )
                    instance._on_background_error(
                        Exception("Server restarted during provisioning"),
                        prev_state,
                    )
                    instance.pending_operation = False
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception(
                    "Cron: recovery failed for stuck instance %s",
                    instance.subdomain,
                )

    def _cron_verify_webhooks(self):
        """Cron: verify and re-register webhooks for all running instances.

        Runs every 6 hours.  For each running instance with repos that
        have ``webhook_enabled=True``, verifies the webhook is still
        active on the Git provider and re-registers if needed.
        """
        instances = self.search([
            ('state', '=', 'running'),
        ])
        if not instances:
            return
        for instance in instances:
            repos_needing_webhook = instance.repo_ids.filtered(
                lambda r: r.state == 'cloned'
                and r.webhook_enabled
                and r.sudo().github_token
                and not r.webhook_provider_id
            )
            if not repos_needing_webhook:
                continue
            try:
                _logger.info(
                    "Cron: re-registering %d webhook(s) for %s",
                    len(repos_needing_webhook), instance.subdomain,
                )
                instance._ensure_webhooks_registered()
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception(
                    "Cron: webhook verification failed for %s",
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

    def _refresh_usage_with_ssh(self, ssh, precomputed_db_size=None):
        """Fetch resource usage relative to plan limits.

        CPU and RAM are reported as percentages of the plan's allocated
        resources (not the physical server), giving the client a clear
        picture of how much of *their* allocation they are consuming.

        When *precomputed_db_size* is provided (in bytes), skip the
        per-instance SSH to the DB server — the caller has already
        batched that query.
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
        # Use the precomputed batched value when the caller (cron) has
        # already done the work; otherwise fall back to a per-instance
        # SSH to the DB host.
        db_bytes = 0
        if precomputed_db_size is not None:
            db_bytes = int(precomputed_db_size)
        elif self.db_server_id and self.subdomain:
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
        extract_cmd = 'python3 -m zipfile -e %s %s 2>&1' % (
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
        db_host = self._get_db_host_for_ssh()
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
            'sudo chmod -R 777 %(data)s'
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

    def _validate_addons_manifests(self, ssh):
        """Check that every ``__manifest__.py`` under the instance addons is valid.

        Scans the instance's ``addons/`` directory on the host (which is
        mounted into the container).  If any manifest cannot be parsed by
        ``ast.literal_eval``, the deploy is aborted with a clear error
        listing the broken modules so the client can fix them.
        """
        self.ensure_one()
        instance_path = self._get_instance_path()
        addons_dir = '%s/addons' % instance_path
        script_path = '%s/_validate_manifests.py' % instance_path
        ssh.write_file(script_path, (
            "import ast, os, sys\n"
            "errors = []\n"
            "addons_dir = sys.argv[1]\n"
            "for root, dirs, files in os.walk(addons_dir):\n"
            "    if '__manifest__.py' in files:\n"
            "        path = os.path.join(root, '__manifest__.py')\n"
            "        try:\n"
            "            with open(path) as f:\n"
            "                ast.literal_eval(f.read())\n"
            "        except Exception as e:\n"
            "            errors.append('%s: %s' % (os.path.basename(root), e))\n"
            "if errors:\n"
            "    for err in errors:\n"
            "        print(err)\n"
            "    sys.exit(1)\n"
        ))
        self._append_log("Validating module manifests...")
        exit_code, stdout, stderr = ssh.execute(
            'python3 %s %s 2>&1' % (
                shlex.quote(script_path), shlex.quote(addons_dir),
            ),
            timeout=120,
        )
        ssh.execute('rm -f %s' % shlex.quote(script_path))
        if exit_code != 0 and stdout.strip():
            raise UserError(
                _("Custom repository contains modules with invalid manifests. "
                  "Please fix the following modules and try again:\n%s")
                % stdout.strip()
            )

    def _clone_product_repos(self, ssh):
        """Clone the product's GitHub repositories into the instance directory."""
        self.ensure_one()
        product = self.saas_product_id
        if not product or not product.repo_ids:
            return

        instance_path = self._get_instance_path()
        container_uid = self._get_container_uid(ssh)

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
            ssh.execute(
                'sudo chown -R %s:%s %s && sudo chmod -R 777 %s'
                % (container_uid, container_uid,
                   shlex.quote(repo_dir), shlex.quote(repo_dir))
            )
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
            rec.pre_provisioning_state = 'failed'
            rec.pending_operation = 'deploy'
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

            # Set ownership so the container user can read/write volumes.
            self._append_log("Setting permissions...")
            container_uid = self._get_container_uid(ssh)
            perms_cmd = (
                'sudo chown -R %(uid)s:%(uid)s %(path)s/data %(path)s/config %(path)s/addons && '
                'sudo chmod -R 777 %(path)s/data %(path)s/config %(path)s/addons'
            ) % {'path': instance_path, 'uid': container_uid}
            exit_code, stdout, stderr = ssh.execute(perms_cmd)
            if exit_code != 0:
                raise UserError(
                    _("Failed to set permissions:\n%s") % stderr
                )
            self._append_log("Permissions set (UID=%s)." % container_uid)

            # Allow git to operate on directories owned by the container
            # user (UID differs from the SSH user running git commands).
            ssh.execute(
                "git config --global --add safe.directory '*' 2>/dev/null || true"
            )
            ssh.execute(
                "sudo git config --system --add safe.directory '*' 2>/dev/null || true"
            )

            # Render and write config files (initial — without custom repos)
            self._render_and_write_configs(ssh)

            # Create PostgreSQL user (and the per-instance DB for service
            # plans). Hosting instances get only the role — with CREATEDB
            # — so the customer can spin up databases themselves via the
            # Odoo database manager.
            if self.is_hosting:
                self._append_log("Creating PostgreSQL role (hosting — no DB)...")
                self._provision_postgresql(create_db=False)
                self._append_log("PostgreSQL role ready.")
            else:
                self._append_log("Creating PostgreSQL role and database...")
                self._provision_postgresql(create_db=True)
                self._append_log("PostgreSQL role and database ready.")

                # Restore pre-built database snapshot (if configured)
                snapshot_restored = self._restore_snapshot(ssh)

                if not snapshot_restored:
                    # No snapshot — initialize database with base modules
                    self._append_log("Initializing database...")
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

            # Re-set permissions after init — docker compose run may
            # have created files as root inside the data directory.
            perms_cmd = (
                'sudo chown -R %(uid)s:%(uid)s %(path)s/data && '
                'sudo chmod -R 777 %(path)s/data'
            ) % {'path': instance_path, 'uid': container_uid}
            ssh.execute(perms_cmd)

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

            # Clone repos AFTER container is running — ensures the instance
            # is functional before adding custom code and webhooks.

            # Clone product repositories
            self._clone_product_repos(ssh)

            # Clone customer instance repos (for hosting instances)
            if self.is_hosting and self.repo_ids:
                for repo in self.repo_ids.filtered(lambda r: r.state == 'pending'):
                    self._append_log("Cloning customer repo: %s (%s)..." % (repo.repo_url, repo.branch))
                    repo._clone_repo()

            # Check if any repos (product or instance) need to be in the
            # addons_path.  If so, re-render config and restart.
            all_addons = self._get_all_addons_paths()
            if all_addons:
                # Validate module manifests to catch broken modules early.
                self._validate_addons_manifests(ssh)
                # Re-render configs to include the addons paths and
                # restart to pick them up.
                self._render_and_write_configs(ssh)
                self._append_log("Restarting container to load custom addons...")
                ssh.execute(
                    'cd %s && docker compose down 2>&1'
                    % shlex.quote(instance_path)
                )
                exit_code, stdout, stderr = ssh.execute(
                    'cd %s && docker compose up -d 2>&1'
                    % shlex.quote(instance_path)
                )
                if exit_code != 0:
                    raise UserError(
                        _("docker compose restart failed:\n%s\n%s")
                        % (stdout, stderr)
                    )
                self._append_log("Container restarted with custom addons.")

            # Ensure webhooks are registered for all repos that need them.
            # _clone_repo attempts registration but may fail silently
            # (e.g. race condition, transient API error).  This final
            # pass catches anything that slipped through.
            self._ensure_webhooks_registered()

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
        self.last_error = False
        self.last_error_date = False
        self.pending_operation = False
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
            rec.pre_provisioning_state = prev_state
            rec.pending_operation = 'stop'
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
        self.pending_operation = False
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
            rec.pre_provisioning_state = prev_state
            rec.pending_operation = 'restart'
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
        self.pending_operation = False
        self._append_log("Instance restarted successfully.")
        self._safe_refresh_usage()

    def action_redeploy(self):
        """Redeploy: clone pending repos, pull cloned repos, update config/mounts,
        install pending modules, and restart the container (async)."""
        for rec in self:
            # Suspended instances must NOT be redeployed via this path —
            # that would silently restore service to a non-paying or
            # trial-expired customer. Use action_reactivate / payment
            # flows instead, which validate billing.
            if rec.state not in ('running', 'stopped'):
                raise UserError(
                    _("Cannot redeploy instance '%s': must be Running or "
                      "Stopped (current: %s). Suspended instances must be "
                      "reactivated through the payment flow first.")
                    % (rec.subdomain, rec.state)
                )
            rec._ensure_can_ssh()
            prev_state = rec.state
            rec.pre_provisioning_state = prev_state
            rec.pending_operation = 'redeploy'
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

        # Ensure webhooks are registered for any new or updated repos
        self._ensure_webhooks_registered()

        # Restore the previous state instead of forcing 'running'.
        # A redeploy on a Stopped instance should leave it Stopped.
        target_state = self.pre_provisioning_state or 'running'
        if target_state not in ('running', 'stopped'):
            target_state = 'running'
        self.state = target_state
        self.pending_operation = False
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
            rec.pre_provisioning_state = prev_state
            rec.pending_operation = 'suspend'
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
        self.pending_operation = False
        self._append_log("Instance suspended successfully.")

    def action_cancel(self):
        """Cancel the instance, cleaning up any infrastructure that was created.

        Handles both fully deployed instances and partially provisioned
        ones (e.g. directories created, database provisioned, but
        container never started).
        """
        for rec in self:
            if rec.docker_server_id:
                # Infrastructure may exist (fully or partially) — clean up
                rec._ensure_can_ssh()
                prev_state = rec.state
                rec.pre_provisioning_state = prev_state
                rec.pending_operation = 'cancel'
                rec.state = 'provisioning'
                rec._append_log("Cancellation queued. Cleaning up infrastructure...")
                run_in_background(
                    rec, '_do_delete_instance',
                    error_method='_on_background_error',
                    error_args=(prev_state,),
                    thread_name='saas_cancel_%s' % rec.subdomain,
                )
            else:
                # No server assigned — nothing to clean up
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
        """Drop ALL databases owned by this instance's role + the role.

        Service instances historically had exactly one DB (= subdomain),
        but hosting instances let the customer create N databases all
        owned by ``db_user``. Listing by owner catches both shapes —
        legacy service single-DB and modern hosting multi-DB — so a
        cancelled instance never leaks a database behind.
        """
        self.ensure_one()
        psql_server = self.db_server_id
        if not psql_server:
            return

        db_user = self.db_user
        if db_user and not DB_USER_RE.match(db_user):
            _logger.error(
                "Refusing to drop role with invalid identifier %r", db_user,
            )
            db_user = None
        if not db_user:
            return  # nothing else we can do safely

        # Per-DB name regex used as a defense-in-depth filter when we
        # iterate the list of owned DBs. Allows a leading underscore
        # so the per-instance Odoo template (``__odoo_template_<sub>``)
        # is included — otherwise it'd leak on cancel.
        owned_name_re = re.compile(r'^[_a-z][a-z0-9_-]{0,62}$')
        safe_user = db_user.replace("'", "''")

        with psql_server._get_ssh_connection() as ssh:
            # 1. Enumerate every database currently owned by our role.
            #    Filtering by owner means we won't accidentally drop a
            #    catalog DB (template0, postgres) which is owned by a
            #    different role. We DO include the per-instance Odoo
            #    template (datistemplate=true, owned by our role) so
            #    a cancelled instance doesn't leak templates either.
            list_sql = (
                "SELECT datname, datistemplate FROM pg_database "
                "WHERE datdba = (SELECT oid FROM pg_roles WHERE rolname='%s') "
                "ORDER BY datname"
            ) % safe_user
            list_cmd = "sudo -u postgres psql -tA -F '|' -c %s" % shlex.quote(list_sql)
            exit_code, stdout, stderr = ssh.execute(list_cmd)
            if exit_code != 0:
                _logger.warning(
                    "Failed to list databases owned by %s: %s",
                    db_user, stderr or stdout,
                )
                owned = []
            else:
                owned = []
                for line in stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split('|', 1)
                    name = parts[0].strip()
                    is_template = (
                        parts[1].strip() == 't' if len(parts) > 1 else False
                    )
                    owned.append((name, is_template))

            # 2. Drop each owned DB. ``--force`` terminates any open
            #    sessions first; ``--if-exists`` swallows a race.
            #    Templates need datistemplate=false first or dropdb
            #    refuses.
            for db_name, is_template in owned:
                if not owned_name_re.match(db_name):
                    _logger.warning(
                        "Skipping drop of suspicious-looking db name %r",
                        db_name,
                    )
                    continue
                if is_template:
                    flag_cmd = (
                        "sudo -u postgres psql -c "
                        "\"UPDATE pg_database SET datistemplate=false "
                        "WHERE datname='%s'\""
                    ) % db_name.replace("'", "''")
                    ssh.execute(flag_cmd)
                drop_cmd = (
                    'sudo -u postgres dropdb --force --if-exists %s'
                    % shlex.quote(db_name)
                )
                ec, out, err = ssh.execute(drop_cmd)
                if ec != 0:
                    _logger.warning(
                        "Failed to drop database %s: %s",
                        db_name, err or out,
                    )
                else:
                    self._append_log("Dropped database '%s'." % db_name)

            # 3. Drop the role last (after all its DBs are gone).
            drop_role_cmd = (
                "sudo -u postgres psql -tc "
                "\"SELECT 1 FROM pg_roles WHERE rolname='%s'\" "
                "| grep -q 1 "
                "&& sudo -u postgres dropuser %s"
            ) % (safe_user, shlex.quote(db_user))
            ec, out, err = ssh.execute(drop_role_cmd)
            if ec != 0:
                _logger.warning(
                    "Failed to drop role %s: %s", db_user, err or out,
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
            rec.pre_provisioning_state = prev_state
            rec.pending_operation = 'delete'
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
        #    Only attempt if the instance was actually deployed (had a
        #    running container and database at some point).
        #    Note: state is 'provisioning' here (set by action_cancel),
        #    so check pre_provisioning_state for the real previous state.
        retained_path = False
        prev = self.pre_provisioning_state or self.state
        was_deployed = prev in ('running', 'stopped', 'suspended', 'failed')
        if was_deployed:
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
        else:
            self._append_log(
                "Skipping backup — instance was not fully deployed."
            )

        # 2. Unregister webhooks from Git providers
        for repo in self.repo_ids.filtered(lambda r: r.webhook_provider_id):
            try:
                self._append_log("Removing webhook for %s..." % repo.name)
                repo._unregister_webhook_from_provider()
                repo.webhook_provider_id = False
                self._append_log("Webhook removed for %s." % repo.name)
            except Exception as e:
                self._append_log(
                    "WARNING: Failed to remove webhook for %s: %s"
                    % (repo.name, e)
                )

        # 3. Tear down infrastructure (tolerant of partial state)
        with server._get_ssh_connection() as ssh:
            # Stop container if it exists
            down_cmd = (
                'cd %s && docker compose down -v --remove-orphans 2>&1'
                % shlex.quote(instance_path)
            )
            exit_code, stdout, stderr = ssh.execute(down_cmd)
            if exit_code != 0:
                self._append_log(
                    "docker compose down: %s (may not exist yet)"
                    % (stderr.strip() or stdout.strip())
                )

            # Remove instance directory if it exists
            exit_code, stdout, stderr = ssh.execute(
                'sudo rm -rf %s' % shlex.quote(instance_path),
            )
            if exit_code != 0:
                self._append_log(
                    "WARNING: Failed to remove directory: %s" % stderr
                )
                _logger.warning(
                    "Failed to remove instance dir %s: %s",
                    instance_path, stderr,
                )

            # Remove Nginx config and SSL certificate (if configured)
            try:
                proxy_server = self.domain_id.proxy_server_id
                if proxy_server and proxy_server != self.docker_server_id:
                    with proxy_server._get_ssh_connection() as proxy_ssh:
                        self._remove_nginx(proxy_ssh)
                else:
                    self._remove_nginx(ssh)
            except Exception:
                self._append_log(
                    "WARNING: Nginx cleanup failed (may not have been configured)."
                )

        # Drop database and role (safe if they don't exist)
        try:
            self._drop_postgresql()
        except Exception:
            self._append_log(
                "WARNING: PostgreSQL cleanup failed (may not have been provisioned)."
            )

        # 4. Delete ALL client backups from cloud storage — both regular
        #    backups and old cancelled_backups/ from prior cancellations.
        #    Only keep the new final backup we just created.
        all_backups = Backup.search([('instance_id', '=', self.id)])
        for backup in all_backups:
            if backup.bucket_path and backup.bucket_path != retained_path:
                try:
                    backup._delete_from_bucket()
                except Exception:
                    _logger.warning(
                        "Failed to delete old backup %s for %s",
                        backup.bucket_path, self.subdomain,
                    )

        # Also delete any old retained backup from a prior cancellation
        if self.retained_backup_path and self.retained_backup_path != retained_path:
            try:
                old_temp = Backup.new({
                    'instance_id': self.id,
                    'bucket_path': self.retained_backup_path,
                })
                old_temp._delete_from_bucket()
                self._append_log(
                    "Deleted old retained backup: %s" % self.retained_backup_path
                )
            except Exception:
                _logger.warning(
                    "Failed to delete old retained backup %s for %s",
                    self.retained_backup_path, self.subdomain,
                )

        # 5. Clean up and finalize
        all_backups.unlink()
        self.retained_backup_path = retained_path

        # Reset repo statuses — infrastructure no longer exists
        for repo in self.repo_ids:
            repo.write({
                'state': 'pending',
                'webhook_enabled': False,
                'webhook_provider_id': False,
                'last_pull': False,
                'error_message': False,
            })

        self.state = 'cancelled'
        self.pending_operation = False
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
        error_msg = str(exception)
        self._append_log("OPERATION FAILED: %s" % error_msg)
        self.last_error = error_msg
        self.last_error_date = fields.Datetime.now()
        self.pre_provisioning_state = False
        self.pending_operation = False

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

    def _do_retained_restore(self, source_id, prev_state, delete_after):
        """Restore the retained backup of *source_id* into this instance.

        Runs in a background thread (queued by the wizard). On failure
        the standard `_on_background_error` handler is invoked which
        restores `prev_state`.
        """
        self.ensure_one()
        source = self.env['saas.instance'].browse(source_id)
        if not source.exists() or not source.retained_backup_path:
            raise UserError(
                _("Source instance %s no longer has a retained backup.")
                % (source.name or source_id)
            )

        Backup = self.env['saas.instance.backup']
        backup = Backup.create({
            'instance_id': self.id,
            'name': 'restored_from_%s' % (source.subdomain or source.id),
            'bucket_path': source.retained_backup_path,
            'state': 'done',
        })

        self._append_log("Restoring retained backup '%s'..." % backup.name)
        try:
            self._pre_restore_setup()
            self._do_restore_backup(backup.id)
        finally:
            backup.unlink()

        try:
            self._ensure_webhooks_registered()
        except Exception as exc:
            _logger.warning(
                "Post-restore webhook setup failed for %s: %s",
                self.subdomain, exc,
            )

        if delete_after and source.retained_backup_path:
            try:
                Backup._delete_bucket_path(source.retained_backup_path)
                source.retained_backup_path = False
            except Exception:
                _logger.exception(
                    "Failed to delete retained backup from cloud for %s",
                    source.name,
                )

    def action_create_backup(self):
        """Create a backup in the background."""
        self.ensure_one()

        # Block backups for trial plans
        if self.plan_id and self.plan_id.is_trial_plan:
            raise UserError(_("Backups are not available on trial plans. Please upgrade to a paid plan."))

        # Lock the instance row for the duration of the backup-create check
        # so two concurrent portal clicks cannot both pass the "no running
        # backup" guard and both spawn a thread.
        self.env.cr.execute(
            "SELECT id FROM saas_instance WHERE id = %s FOR UPDATE",
            (self.id,),
        )

        # Block if a backup is already running (re-read after the row lock)
        Backup = self.env['saas.instance.backup']
        running = Backup.search_count([
            ('instance_id', '=', self.id),
            ('state', '=', 'running'),
        ])
        if running:
            raise UserError(_("A backup is already in progress. Please wait for it to finish."))

        # Create the running record FIRST so concurrent clicks see it.
        now_str = fields.Datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup = Backup.create({
            'instance_id': self.id,
            'name': 'backup_%s' % now_str,
            'state': 'running',
        })

        # Auto-rotate AFTER creating the new record: if we're now at plan
        # limit + 1, delete the oldest. Doing this before creation could
        # leave the customer with one fewer backup if creation fails.
        if self.plan_id and self.plan_id.max_backups > 0:
            done_backups = Backup.search([
                ('instance_id', '=', self.id),
                ('state', '=', 'done'),
            ], order='create_date asc')
            while len(done_backups) >= self.plan_id.max_backups:
                oldest = done_backups[0]
                self._append_log(
                    "Auto-removing oldest backup '%s' (limit: %d)."
                    % (oldest.name, self.plan_id.max_backups)
                )
                oldest._delete_from_bucket()
                oldest.unlink()
                done_backups -= oldest

        self._append_log("Backup queued. Running in background...")
        run_in_background(
            backup, '_run_portal_backup',
            thread_name='saas_backup_%s' % self.subdomain,
        )
        return True

    # TEST-BUTTON-REMOVE-ME — manual trigger for the daily-restic flow,
    # so QA can exercise the cron path without waiting for 03:00 UTC.
    # Delete this method (and the matching button in
    # saas_instance_views.xml) once snapshot testing is signed off.
    def action_test_run_daily_backup(self):
        """Fire ``_perform_full_instance_backup`` in a background thread.

        Same code path the daily cron uses. Returns immediately so the
        HTTP transaction doesn't hold a row-level write while restic is
        uploading — the cron itself runs in a fresh cursor for the same
        reason. Watch progress in the instance log stream.
        """
        self.ensure_one()
        if not self.is_hosting:
            raise UserError(_("Test button is for hosting instances only."))
        if not self.daily_backup_enabled:
            raise UserError(_(
                "Daily backups must be enabled before triggering a test run."
            ))
        if self.state != 'running':
            raise UserError(_("Instance must be Running to back it up."))

        Backup = self.env['saas.instance.backup'].sudo()
        running = Backup.search_count([
            ('instance_id', '=', self.id),
            ('state', '=', 'running'),
            ('is_full_instance', '=', True),
        ])
        if running:
            raise UserError(_(
                "A full-instance backup is already running on this "
                "instance. Wait for it to finish before triggering "
                "another test."
            ))

        self._append_log("TEST: manual daily-snapshot trigger queued.")
        run_in_background(
            Backup, '_perform_full_instance_backup_in_new_cursor',
            method_args=(self.id,),
            thread_name='saas_test_snapshot_%s' % self.subdomain,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Snapshot started"),
                'message': _(
                    "Full-instance snapshot is running in the "
                    "background. Watch the instance log or the "
                    "Snapshots page — the new saas.instance.backup "
                    "row will flip to 'done' when restic finishes."
                ),
                'type': 'success',
                'sticky': False,
            },
        }

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
        if backup.is_full_instance:
            raise UserError(_(
                "This is a full-instance restic snapshot — use "
                "action_restore_full_instance, not action_restore_backup. "
                "The backend Restore button now dispatches automatically; "
                "if you're seeing this, a stale code path is still calling "
                "the zip restore on a restic backup."
            ))
        if not backup.backup_path:
            raise UserError(_(
                "Backup record has no cloud object path — nothing to "
                "download. This row is probably a failed or partial "
                "backup; delete it and create a fresh one."
            ))

        self._ensure_can_ssh()
        # Lock the row + refuse if another restore is already in flight.
        # Concurrent restores would both run dropdb/createdb/psql -f
        # against the same DB and corrupt it.
        self.env.cr.execute(
            "SELECT id FROM saas_instance WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        if self.pending_operation == 'restore' or self.state == 'provisioning':
            raise UserError(_("A restore is already in progress for this instance."))

        prev_state = self.state
        self.pre_provisioning_state = prev_state
        self.pending_operation = 'restore'
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

    def action_restore_full_instance(self, backup_id):
        """Restore an entire hosting instance from a full-instance backup.

        Brings back every database, the filestore, custom addons,
        configuration files, docker-compose, and pip requirements at
        the exact point in time the backup was taken. Other databases
        currently on the instance are dropped — this is a full state
        replacement, not a merge.

        Before destroying anything, ``_do_restore_full_instance`` takes
        a fresh full-instance "pre-restore" snapshot. If that fails,
        the restore aborts and the current state is untouched.
        """
        self.ensure_one()
        if not self.is_hosting:
            raise UserError(_(
                "Full-instance restore is only available for hosting instances."
            ))
        if self.state not in ('running', 'stopped'):
            raise UserError(
                _("Instance must be Running or Stopped to restore.")
            )

        backup = self.env['saas.instance.backup'].browse(backup_id)
        if not backup.exists() or backup.instance_id != self:
            raise UserError(_("Invalid backup."))
        if backup.state != 'done':
            raise UserError(_("Only completed backups can be restored."))
        if not backup.is_full_instance:
            raise UserError(_(
                "This backup is per-database. Use the per-DB restore button."
            ))

        self._ensure_can_ssh()
        self.env.cr.execute(
            "SELECT id FROM saas_instance WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        if self.pending_operation == 'restore' or self.state == 'provisioning':
            raise UserError(_("A restore is already in progress for this instance."))

        prev_state = self.state
        self.pre_provisioning_state = prev_state
        self.pending_operation = 'restore'
        self.state = 'provisioning'
        self._append_log("Full-instance restore from '%s' queued..." % backup.name)
        run_in_background(
            self, '_do_restore_full_instance',
            method_args=(backup.id,),
            error_method='_on_background_error',
            error_args=(prev_state,),
            thread_name='saas_restore_full_%s' % self.subdomain,
        )
        return True

    def _do_restore_full_instance(self, backup_id):
        """Background worker: replace the entire instance from a snapshot.

        Dispatches by ``backup.format``:
        - ``restic`` → restic-based restore (new format, deduplicated).
        - ``zip``    → legacy single-zip flow, kept for backups taken
          before the restic switch.

        In both cases a pre-restore safety snapshot is taken first so a
        failed restore can be rolled forward.
        """
        self.ensure_one()
        backup = self.env['saas.instance.backup'].browse(backup_id)
        if backup.format == 'restic':
            return self._do_restore_full_instance_restic(backup_id)
        return self._do_restore_full_instance_zip(backup_id)

    def _do_restore_full_instance_zip(self, backup_id):
        """Legacy single-zip full-instance restore."""
        self.ensure_one()
        backup = self.env['saas.instance.backup'].browse(backup_id)
        server = self.docker_server_id
        container_name = self._get_container_name()
        instance_path = self._get_instance_path()
        psql_server = self.db_server_id
        db_host = self._get_db_host_for_ssh()
        db_port = psql_server.psql_port or 5432

        if not DB_USER_RE.match(self.db_user or ''):
            raise UserError(
                _("Refusing to restore: invalid db user %r") % self.db_user
            )

        # 0. Pre-restore safety snapshot. Anything that's currently on
        # the instance gets captured under a `pre_restore_<ts>` name so
        # an operator can roll forward again if this restore goes wrong.
        try:
            self._append_log("Taking pre-restore safety snapshot...")
            self.env['saas.instance.backup'].sudo()\
                ._perform_full_instance_backup(self)
            self._append_log("Pre-restore snapshot complete.")
        except Exception as e:
            raise UserError(_(
                "Pre-restore snapshot failed — aborting before destroying "
                "anything:\n%s"
            ) % e)

        # Compatibility check — refuse to restore across Odoo major
        # versions, otherwise schema migrations corrupt silently.
        manifest_version = None
        try:
            manifest = backup._read_manifest_safe() \
                if hasattr(backup, '_read_manifest_safe') else None
            if isinstance(manifest, dict):
                manifest_version = manifest.get('odoo_version')
        except Exception:
            pass
        if manifest_version and self.odoo_version_id \
                and manifest_version != self.odoo_version_id.name:
            raise UserError(_(
                "Backup was taken on Odoo %s but this instance now runs %s. "
                "Aborting to avoid silent schema corruption."
            ) % (manifest_version, self.odoo_version_id.name))

        with server._get_ssh_connection() as ssh:
            # 1. Stop the container — full restore replaces /data, so no
            # connections can be left open.
            self._append_log("Stopping container...")
            exit_code, stdout, stderr = ssh.execute(
                'cd %s && docker compose down 2>&1' % shlex.quote(instance_path)
            )
            if exit_code != 0 and 'No such container' not in (stdout + stderr):
                raise UserError(_(
                    "Failed to stop container before restore:\n%s\n%s"
                ) % (stdout, stderr))

            # 2. Download + extract the backup zip
            self._append_log("Downloading backup...")
            download_url = backup._generate_presigned_url()
            tmp_zip = '/tmp/saas_full_restore_%s.zip' % self.subdomain
            extract_dir = '/tmp/saas_full_restore_%s' % self.subdomain

            dl_cmd = 'curl -fsSL -o %s %s 2>&1' % (
                shlex.quote(tmp_zip), shlex.quote(download_url),
            )
            exit_code, stdout, stderr = ssh.execute(dl_cmd, timeout=1800)
            if exit_code != 0:
                raise UserError(
                    _("Failed to download backup:\n%s\n%s") % (stdout, stderr)
                )

            self._append_log("Extracting...")
            ssh.execute('rm -rf %s && mkdir -p %s' % (
                shlex.quote(extract_dir), shlex.quote(extract_dir),
            ))
            # Use Python's zipfile module instead of the `unzip` binary
            # so we don't fail on docker hosts that don't ship it.
            exit_code, stdout, stderr = ssh.execute(
                'python3 -m zipfile -e %s %s 2>&1' % (
                    shlex.quote(tmp_zip), shlex.quote(extract_dir),
                ),
                timeout=1800,
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to extract backup:\n%s\n%s") % (stdout, stderr)
                )

            # 3. Restore the on-disk instance files (data, addons,
            # config, compose / requirements / pip script). We blow
            # away the target subdirs first — leaving stale files would
            # interleave with the snapshot.
            self._append_log("Restoring instance files...")
            container_uid = self._get_container_uid(ssh)
            wipe_and_copy_cmd = (
                # Wipe targets
                'sudo rm -rf %(ip)s/data %(ip)s/addons %(ip)s/config && '
                # Copy back from extraction (whichever subdirs the
                # backup contained)
                'for d in data addons config; do '
                '  if [ -d %(ed)s/$d ]; then '
                '    sudo cp -a %(ed)s/$d %(ip)s/$d; '
                '  fi; '
                'done && '
                # Top-level files
                'for f in docker-compose.yml requirements.txt pip_install.sh; do '
                '  if [ -f %(ed)s/$f ]; then '
                '    sudo cp -a %(ed)s/$f %(ip)s/$f; '
                '  fi; '
                'done && '
                # Re-apply container-friendly ownership/perms
                'sudo chown -R %(uid)s:%(uid)s %(ip)s/data %(ip)s/config %(ip)s/addons 2>/dev/null || true && '
                'sudo chmod -R 777 %(ip)s/data %(ip)s/config %(ip)s/addons 2>/dev/null || true'
            ) % {
                'ip': shlex.quote(instance_path),
                'ed': shlex.quote(extract_dir),
                'uid': container_uid,
            }
            exit_code, stdout, stderr = ssh.execute(wipe_and_copy_cmd, timeout=1800)
            if exit_code != 0:
                raise UserError(_(
                    "Failed to restore instance files:\n%s\n%s"
                ) % (stdout, stderr))

            # 4. Restore every DB dump. We do this before bringing the
            # container back up so Odoo doesn't autocreate empty schemas.
            dumps_dir = '%s/dumps' % extract_dir
            list_cmd = 'ls %s 2>/dev/null || true' % shlex.quote(dumps_dir)
            exit_code, listing, _ = ssh.execute(list_cmd)
            dump_files = [f for f in (listing or '').splitlines()
                          if f.strip().endswith('.sql')]
            for dump_file in dump_files:
                db = dump_file[:-4]  # strip .sql
                if not re.match(r'^[a-z][a-z0-9_-]{0,62}$', db):
                    self._append_log(
                        "Skipping suspicious dump filename: %r" % dump_file
                    )
                    continue
                self._append_log("Restoring database '%s'..." % db)
                self._restore_one_db_from_dump(
                    ssh, db, '%s/%s' % (dumps_dir, dump_file),
                    db_host=db_host, db_port=db_port,
                    psql_server=psql_server,
                )

            # 5. Cleanup temp files (before bringing container up, so a
            # subsequent failure doesn't leave the zip lying around).
            ssh.execute('rm -rf %s %s' % (
                shlex.quote(tmp_zip), shlex.quote(extract_dir),
            ))

            # 6. Start the container
            self._append_log("Starting container...")
            start_cmd = 'cd %s && docker compose up -d 2>&1' % shlex.quote(instance_path)
            exit_code, stdout, stderr = ssh.execute(start_cmd, timeout=300)
            if exit_code != 0:
                raise UserError(
                    _("Failed to start container after restore:\n%s") % stderr
                )

        self.state = 'running'
        self.pending_operation = False
        self._append_log("Full-instance restore from '%s' complete." % backup.name)
        self._safe_refresh_usage()

    def _do_restore_full_instance_restic(self, backup_id):
        """Restic-based full-instance restore.

        Looks up the snapshots tagged ``run=<backup.restic_run_tag>``
        in this instance's repo. Restores the filesystem snapshot
        in place (after stopping the container), then for each DB
        snapshot drops/recreates the target DB and pipes ``restic
        dump`` into ``psql``.
        """
        import json as _json
        self.ensure_one()
        Backup = self.env['saas.instance.backup'].sudo()
        backup = Backup.browse(backup_id)
        server = self.docker_server_id
        instance_path = self._get_instance_path()
        container_name = self._get_container_name()
        psql_server = self.db_server_id
        db_host = self._get_db_host_for_ssh()
        db_port = psql_server.psql_port or 5432

        if not DB_USER_RE.match(self.db_user or ''):
            raise UserError(
                _("Refusing to restore: invalid db user %r") % self.db_user
            )
        if not backup.restic_run_tag:
            raise UserError(_("Backup has no restic_run_tag — cannot restore."))

        # 0. Pre-restore safety snapshot in the same restic repo.
        try:
            self._append_log("Taking pre-restore safety snapshot...")
            Backup._perform_full_instance_backup(self)
            self._append_log("Pre-restore snapshot complete.")
        except Exception as e:
            raise UserError(_(
                "Pre-restore snapshot failed — aborting:\n%s"
            ) % e)

        gcs_path = None
        try:
            with server._get_ssh_connection() as ssh:
                Backup._ensure_restic_installed(ssh, server.name)
                gcs_path = Backup._stage_gcs_credentials(ssh, self)
                env = Backup._restic_env_vars(self, gcs_path)

                # 1. Look up snapshot IDs by tag. JSON output is the
                # stable interface — text format changes across versions.
                list_cmd = Backup._restic_cmd(
                    env,
                    ['snapshots', '--tag', 'run=' + backup.restic_run_tag,
                     '--host', shlex.quote(self.subdomain),
                     '--json'],
                )
                exit_code, stdout, stderr = ssh.execute(list_cmd, timeout=120)
                if exit_code != 0:
                    raise UserError(_(
                        "Could not list restic snapshots:\n%s"
                    ) % stderr or stdout)
                try:
                    snapshots = _json.loads(stdout.strip() or '[]')
                except Exception:
                    raise UserError(_(
                        "restic returned non-JSON snapshot list:\n%s"
                    ) % stdout[:500])
                if not snapshots:
                    raise UserError(_(
                        "No restic snapshots found for run %s."
                    ) % backup.restic_run_tag)

                fs_snap = None
                db_snaps = []  # list of (db_name, snapshot_id)
                for s in snapshots:
                    tags = s.get('tags', []) or []
                    if 'fs' in tags:
                        fs_snap = s['id']
                    elif 'db' in tags:
                        # tags include "db=<name>" so we recover the DB
                        db_name = None
                        for t in tags:
                            if t.startswith('db=') and len(t) > 3:
                                db_name = t[3:]
                                break
                        if not db_name:
                            # Fall back to the original stdin filename
                            paths = s.get('paths') or []
                            if paths:
                                base = paths[-1].rsplit('/', 1)[-1]
                                if base.endswith('.sql'):
                                    db_name = base[:-4]
                        if db_name and re.match(
                            r'^[a-z][a-z0-9_-]{0,62}$', db_name,
                        ):
                            db_snaps.append((db_name, s['id']))
                if not fs_snap:
                    raise UserError(_(
                        "Restic run %s has no filesystem snapshot."
                    ) % backup.restic_run_tag)

                # 2. Stop container before mutating files.
                self._append_log("Stopping container...")
                exit_code, stdout, stderr = ssh.execute(
                    'cd %s && docker compose down 2>&1'
                    % shlex.quote(instance_path),
                )
                if exit_code != 0 and 'No such' not in (stdout + stderr):
                    raise UserError(_(
                        "Failed to stop container:\n%s"
                    ) % stderr or stdout)

                # 3. Wipe the targets and restore the filesystem snapshot.
                # restic restore writes paths back to their original
                # absolute locations when --target /. We delete first to
                # avoid stale files left from the current state.
                container_uid = self._get_container_uid(ssh)
                self._append_log("Wiping current instance files...")
                wipe_cmd = (
                    'sudo rm -rf %(ip)s/data %(ip)s/addons %(ip)s/config '
                    '%(ip)s/docker-compose.yml %(ip)s/requirements.txt '
                    '%(ip)s/pip_install.sh'
                ) % {'ip': shlex.quote(instance_path)}
                ssh.execute(wipe_cmd, timeout=600)

                self._append_log("Restoring filesystem from restic...")
                # Sudo so we can rewrite files owned by the container UID.
                # restic itself runs unprivileged; sudo wraps only the
                # write portion. To avoid editing /etc, we set --target /.
                #
                # The KEY=val prefix that ``_restic_cmd`` emits only acts
                # as an environment assignment when it's at the start of
                # a simple command. Once we prepend ``sudo``, those
                # tokens become positional args to sudo — which sudo
                # treats as "set var" syntax and refuses by default
                # (you'd see "sorry, you are not allowed to set the
                # following environment variables: RESTIC_REPOSITORY").
                # Wrap with ``sudo -E env`` so the assignments go to the
                # real ``env`` binary, which sets them and execs restic.
                restore_cmd = (
                    'sudo -E env ' +
                    Backup._restic_cmd(
                        env,
                        ['restore', fs_snap, '--target', '/', '--quiet'],
                    )
                )
                exit_code, stdout, stderr = ssh.execute(
                    restore_cmd, timeout=7200,
                )
                if exit_code != 0:
                    # Surface the full output to the instance log — a
                    # 500-char tail is often not enough for restic
                    # errors that put context earlier.
                    self._append_log(
                        "restic restore (fs) failed. Full output:\n%s\n%s"
                        % (stdout, stderr)
                    )
                    raise UserError(_(
                        "restic restore (fs) failed:\n%s\n%s"
                    ) % (stdout[-1500:], stderr[-1500:]))

                # Re-apply container ownership/perms.
                ssh.execute(
                    'sudo chown -R %(uid)s:%(uid)s %(ip)s/data %(ip)s/config '
                    '%(ip)s/addons 2>/dev/null || true && '
                    'sudo chmod -R 777 %(ip)s/data %(ip)s/config %(ip)s/addons '
                    '2>/dev/null || true' % {
                        'ip': shlex.quote(instance_path),
                        'uid': container_uid,
                    },
                    timeout=300,
                )

                # 4. Per-DB restore: dump from restic stdin into psql.
                for db, snap_id in db_snaps:
                    self._append_log("Restoring database '%s'..." % db)
                    self._restic_restore_one_db(
                        ssh, Backup, env, snap_id, db,
                        db_host=db_host, db_port=db_port,
                        psql_server=psql_server,
                    )

                # 5. Bring container back up.
                self._append_log("Starting container...")
                exit_code, stdout, stderr = ssh.execute(
                    'cd %s && docker compose up -d 2>&1'
                    % shlex.quote(instance_path),
                    timeout=300,
                )
                if exit_code != 0:
                    raise UserError(_(
                        "Failed to start container:\n%s"
                    ) % stderr)
        finally:
            if gcs_path:
                try:
                    with server._get_ssh_connection() as ssh2:
                        Backup._unstage_gcs_credentials(ssh2, gcs_path)
                except Exception:
                    pass

        self.state = 'running'
        self.pending_operation = False
        self._append_log("Restic restore from '%s' complete." % backup.name)
        self._safe_refresh_usage()

    def _restic_restore_one_db(self, ssh, Backup, env, snap_id, db,
                               db_host, db_port, psql_server):
        """Drop+recreate ``db`` then pipe ``restic dump`` to psql.

        Mirrors ``_restore_one_db_from_dump`` (the zip path) but the
        SQL bytes come from ``restic dump`` instead of an extracted
        file. Keeping them separate avoids smuggling restic env vars
        through the simpler helper.
        """
        if not re.match(r'^[a-z][a-z0-9_-]{0,62}$', db):
            raise UserError(_("Refusing to restore bogus db name %r") % db)

        def _run_on_db_server(cmd):
            if psql_server == self.docker_server_id:
                return ssh.execute(cmd)
            with psql_server._get_ssh_connection() as db_ssh:
                return db_ssh.execute(cmd)

        _run_on_db_server(
            "sudo -u postgres psql -c "
            "\"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname='%s' AND pid <> pg_backend_pid();\" 2>&1"
            % db.replace("'", "''")
        )
        exit_code, stdout, stderr = _run_on_db_server(
            'sudo -u postgres dropdb --force --if-exists %s 2>&1'
            % shlex.quote(db)
        )
        if exit_code != 0:
            raise UserError(_(
                "dropdb %s failed:\n%s\n%s"
            ) % (db, stdout, stderr))
        exit_code, stdout, stderr = _run_on_db_server(
            'sudo -u postgres createdb -O %s %s 2>&1'
            % (shlex.quote(self.db_user), shlex.quote(db))
        )
        if exit_code != 0:
            raise UserError(_(
                "createdb %s failed:\n%s\n%s"
            ) % (db, stdout, stderr))

        # Pipe restic dump → sed → psql on the docker host (it has the
        # network path to the db server already).
        #
        # The sed filter strips ``SET`` statements that the newer
        # pg_dump (PG 17+) shipped in our containers emits but older
        # PG servers don't understand. ``transaction_timeout`` is the
        # one that bit us in the field; we keep the pattern open-ended
        # so future PG-17/18-only knobs in the dump prologue won't
        # break restores against PG 15/16 servers. Real data lines
        # (``COPY``, ``INSERT``) are unaffected — the offending
        # statements are always single ``SET <name> = <value>;`` lines.
        dump_cmd = Backup._restic_cmd(
            env,
            ['dump', snap_id, shlex.quote('/%s.sql' % db)],
        )
        sed_filter = "sed -E '/^SET (transaction_timeout)\\s*=/d'"
        psql_cmd = (
            'PGPASSWORD=%s psql -h %s -p %d -U %s -d %s -q -v ON_ERROR_STOP=1'
        ) % (
            shlex.quote(self.db_password),
            shlex.quote(db_host),
            db_port,
            shlex.quote(self.db_user),
            shlex.quote(db),
        )
        pipeline = 'set -o pipefail; %s | %s | %s' % (
            dump_cmd, sed_filter, psql_cmd,
        )
        exit_code, stdout, stderr = ssh.execute(pipeline, timeout=7200)
        if exit_code != 0:
            self._append_log(
                "restic dump | psql last 1k chars for %s:\n%s"
                % (db, (stdout + stderr)[-1000:])
            )
            raise UserError(_(
                "Restore of '%s' failed:\n%s"
            ) % (db, (stderr or stdout)[-500:]))

    def _restore_one_db_from_dump(self, ssh, db, dump_path,
                                  db_host, db_port, psql_server):
        """Drop + recreate ``db`` then psql -f the dump in.

        Helper for ``_do_restore_full_instance``. Runs SQL on the db
        server via the ssh-connected docker host; falls back to a
        direct connection if the docker host is also the db server.
        """
        if not re.match(r'^[a-z][a-z0-9_-]{0,62}$', db):
            raise UserError(_("Refusing to restore bogus db name %r") % db)

        def _run_on_db_server(cmd):
            if psql_server == self.docker_server_id:
                return ssh.execute(cmd)
            with psql_server._get_ssh_connection() as db_ssh:
                return db_ssh.execute(cmd)

        # Terminate any leftover sessions first.
        _run_on_db_server(
            "sudo -u postgres psql -c "
            "\"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname='%s' AND pid <> pg_backend_pid();\" 2>&1"
            % db.replace("'", "''")
        )
        exit_code, stdout, stderr = _run_on_db_server(
            'sudo -u postgres dropdb --force --if-exists %s 2>&1'
            % shlex.quote(db)
        )
        if exit_code != 0:
            raise UserError(_(
                "dropdb failed for %s — aborting restore:\n%s\n%s"
            ) % (db, stdout, stderr))
        exit_code, stdout, stderr = _run_on_db_server(
            'sudo -u postgres createdb -O %s %s 2>&1'
            % (shlex.quote(self.db_user), shlex.quote(db))
        )
        if exit_code != 0:
            raise UserError(_(
                "createdb failed for %s — aborting restore:\n%s\n%s"
            ) % (db, stdout, stderr))

        # Apply the dump from the docker host (it has psql + network
        # to the db server already). Same PG-17→older-server filter as
        # the restic path; ``cat | sed | psql`` instead of ``psql -f``
        # so we can drop the offending SET line in-stream.
        restore_cmd = (
            "set -o pipefail; cat %s "
            "| sed -E '/^SET (transaction_timeout)\\s*=/d' "
            "| PGPASSWORD=%s psql -h %s -p %d -U %s -d %s 2>&1"
        ) % (
            shlex.quote(dump_path),
            shlex.quote(self.db_password),
            shlex.quote(db_host),
            db_port,
            shlex.quote(self.db_user),
            shlex.quote(db),
        )
        exit_code, stdout, stderr = ssh.execute(restore_cmd, timeout=3600)
        if exit_code != 0:
            self._append_log(
                "psql restore of %s last 1k chars:\n%s" % (db, stdout[-1000:])
            )
            raise UserError(_(
                "Restore of '%s' failed:\n%s"
            ) % (db, stderr[-500:]))

    def _do_restore_backup(self, backup_id):
        """Restore a backup — replace target DB and filestore (background).

        For service instances, the target DB is always ``self.subdomain``.
        For hosting instances, the target is ``backup.db_name`` (which can
        be one of many DBs on the container) so other databases on the
        same instance stay online during the restore.
        """
        self.ensure_one()
        backup = self.env['saas.instance.backup'].browse(backup_id)
        server = self.docker_server_id
        container_name = self._get_container_name()
        instance_path = self._get_instance_path()
        # Restore target = the database the backup was taken from. Falls
        # back to subdomain for legacy backups recorded before db_name.
        db_name = backup.db_name or self.subdomain
        psql_server = self.db_server_id
        db_host = self._get_db_host_for_ssh()
        db_port = psql_server.psql_port or 5432

        # Validate identifiers before any shell execution.
        # Hosting DB names are slightly more permissive than subdomains
        # (underscores allowed), so apply the right regex per case.
        name_re = (
            re.compile(r'^[a-z][a-z0-9_-]{0,62}$')
            if self.is_hosting else SUBDOMAIN_RE
        )
        if not name_re.match(db_name or ''):
            raise UserError(
                _("Refusing to restore: invalid db name %r") % db_name
            )
        if not DB_USER_RE.match(self.db_user or ''):
            raise UserError(
                _("Refusing to restore: invalid db user %r") % self.db_user
            )

        # Snapshot/backup version compatibility check (B7).
        manifest = backup._read_manifest_safe() if hasattr(backup, '_read_manifest_safe') else None
        backup_version = (manifest or {}).get('odoo_version') if isinstance(manifest, dict) else None
        if backup_version and self.odoo_version_id and \
                backup_version != self.odoo_version_id.name:
            raise UserError(_(
                "Backup was taken on Odoo version %s but this instance "
                "runs %s. Aborting to avoid silent schema corruption."
            ) % (backup_version, self.odoo_version_id.name))

        with server._get_ssh_connection() as ssh:
            # 1. Make sure no Odoo workers are holding the target DB open.
            # Service instances: stop the whole container (it only serves
            # this one DB anyway).
            # Hosting instances: ask Odoo to release just this DB so other
            # databases on the same container keep serving traffic.
            if self.is_hosting:
                self._append_log(
                    "Releasing connections to database '%s'..." % db_name
                )
                release_script = (
                    "from odoo.service import db\n"
                    "try:\n"
                    "    db._drop_conn(None, os.environ['SAAS_DB_NAME'])\n"
                    "except Exception as e:\n"
                    "    print('release-error:', e)\n"
                    "print('OK')\n"
                )
                # Best-effort: don't fail the restore if release errors.
                # The dropdb --force below still terminates any leftover
                # backends.
                try:
                    self._docker_exec_python(
                        ssh, release_script,
                        env={'SAAS_DB_NAME': db_name},
                        timeout=60,
                    )
                except Exception as e:
                    self._append_log(
                        "Note: _drop_conn failed (%s); continuing." % e
                    )
            else:
                self._append_log("Stopping container...")
                exit_code, stdout, stderr = ssh.execute(
                    'docker stop %s 2>&1' % shlex.quote(container_name)
                )
                if exit_code != 0 and 'No such container' not in (stdout + stderr):
                    raise UserError(_(
                        "Failed to stop container '%s' before restore — refusing "
                        "to drop the database while connections may still be open:\n%s\n%s"
                    ) % (container_name, stdout, stderr))

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
                'python3 -m zipfile -e %s %s 2>&1' % (
                    shlex.quote(tmp_zip), shlex.quote(extract_dir),
                ),
                timeout=300,
            )
            if exit_code != 0:
                raise UserError(
                    _("Failed to extract backup:\n%s\n%s") % (stdout, stderr)
                )

            # 4. Drop current DB and recreate empty.
            # Both commands MUST succeed — otherwise psql -f below would
            # restore into the existing (non-empty) DB and produce a
            # silently corrupted half-merged database.
            self._append_log("Dropping current database...")
            def _run_on_db_server(cmd):
                if psql_server == server:
                    return ssh.execute(cmd)
                with psql_server._get_ssh_connection() as db_ssh:
                    return db_ssh.execute(cmd)

            # Terminate any lingering backends first (older PG ignores --force).
            _run_on_db_server(
                "sudo -u postgres psql -c "
                "\"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname='%s' AND pid <> pg_backend_pid();\" 2>&1"
                % db_name.replace("'", "''")
            )
            exit_code, stdout, stderr = _run_on_db_server(
                'sudo -u postgres dropdb --force --if-exists %s 2>&1'
                % shlex.quote(db_name)
            )
            if exit_code != 0:
                raise UserError(_(
                    "dropdb failed for %s — aborting restore:\n%s\n%s"
                ) % (db_name, stdout, stderr))
            exit_code, stdout, stderr = _run_on_db_server(
                'sudo -u postgres createdb -O %s %s 2>&1'
                % (shlex.quote(self.db_user), shlex.quote(db_name))
            )
            if exit_code != 0:
                raise UserError(_(
                    "createdb failed for %s — aborting restore:\n%s\n%s"
                ) % (db_name, stdout, stderr))

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
                'sudo chmod -R 777 %(data)s'
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

            # 8. Restart the container — service only. Hosting kept it
            # running so other databases stayed online; nothing to start.
            if not self.is_hosting:
                self._append_log("Starting container...")
                start_cmd = 'cd %s && docker compose up -d 2>&1' % shlex.quote(instance_path)
                exit_code, stdout, stderr = ssh.execute(start_cmd)
                if exit_code != 0:
                    raise UserError(
                        _("Failed to start container:\n%s") % stderr
                    )

        self.state = 'running'
        self.pending_operation = False
        self._append_log("Backup '%s' restored successfully." % backup.name)
        self._safe_refresh_usage()

    def _pre_restore_setup(self):
        """Set up repos, configs, and pip packages before a DB restore.

        Ensures the restored database will find all custom modules and
        Python packages it depends on.  Called by both the paid-restore
        flow and the admin wizard.
        """
        self.ensure_one()
        self._append_log("Pre-restore: setting up repos and packages...")

        # Re-enable webhooks for repos that have a token
        for repo in self.repo_ids:
            if repo.sudo().github_token and not repo.webhook_enabled:
                repo.webhook_enabled = True

        # Clone pending customer repos
        for repo in self.repo_ids.filtered(lambda r: r.state == 'pending'):
            self._append_log("Cloning repo %s (%s)..." % (repo.repo_url, repo.branch))
            try:
                repo._clone_repo()
            except Exception as e:
                self._append_log("WARNING: Failed to clone %s: %s" % (repo.name, e))

        # Clone product repos
        if self.saas_product_id and self.saas_product_id.repo_ids:
            self._ensure_can_ssh()
            with self.docker_server_id._get_ssh_connection() as ssh:
                self._clone_product_repos(ssh)

        # Re-render configs with all addons paths
        self._ensure_can_ssh()
        with self.docker_server_id._get_ssh_connection() as ssh:
            self._render_and_write_configs(ssh)

        # Install pip packages
        if self.pip_packages:
            self._append_log("Installing pip packages...")
            try:
                container = 'odoo_%s' % self.subdomain
                pkgs = [
                    p.strip() for p in self.pip_packages.splitlines()
                    if p.strip() and not p.strip().startswith('#')
                ]
                if pkgs:
                    self._ensure_can_ssh()
                    with self.docker_server_id._get_ssh_connection() as ssh:
                        install_cmd = (
                            'docker exec %s bash -c "'
                            'mkdir -p /var/lib/odoo/pip_packages && '
                            'pip3 install --target=/var/lib/odoo/pip_packages '
                            '--upgrade --no-warn-script-location %s'
                            '" 2>&1'
                        ) % (shlex.quote(container), ' '.join(
                            shlex.quote(p) for p in pkgs
                        ))
                        exit_code, stdout, stderr = ssh.execute(
                            install_cmd, timeout=300,
                        )
                        if exit_code == 0:
                            self._append_log(
                                "Pip packages installed: %s" % ', '.join(pkgs)
                            )
                        else:
                            self._append_log(
                                "WARNING: pip install issues:\n%s"
                                % (stdout or stderr)[:500]
                            )
            except Exception as e:
                self._append_log("WARNING: pip install failed: %s" % e)

        self._append_log("Pre-restore setup complete.")

    def _do_paid_restore(self):
        """Restore retained backup after the restoration invoice is paid.

        Called in a background thread by the payment handler.
        """
        self.ensure_one()
        if not self.retained_backup_path:
            self._append_log("ERROR: No retained backup path — cannot restore.")
            self.restoration_invoice_id = False
            return

        # Set state so client sees "provisioning" instead of "running"
        self.state = 'provisioning'
        self._append_log("Restoring data from retained backup (paid)...")
        self.env.cr.commit()

        Backup = self.env['saas.instance.backup']
        backup = Backup.create({
            'instance_id': self.id,
            'name': 'restored_paid_%s' % fields.Datetime.now().strftime('%Y%m%d_%H%M%S'),
            'bucket_path': self.retained_backup_path,
            'state': 'done',
        })

        # Set up all repos, configs, and pip packages BEFORE restore
        self._pre_restore_setup()

        # Restore the backup (sets state back to 'running' on success)
        self._do_restore_backup(backup.id)
        backup.unlink()

        # Re-register webhooks
        try:
            self._ensure_webhooks_registered()
        except Exception:
            pass

        # Delete the retained backup from cloud storage
        retained_path = self.retained_backup_path
        if retained_path:
            try:
                temp = Backup.new({
                    'instance_id': self.id,
                    'bucket_path': retained_path,
                })
                temp._delete_from_bucket()
                self._append_log(
                    "Retained backup deleted from cloud: %s" % retained_path
                )
            except Exception:
                _logger.exception(
                    "Failed to delete retained backup from cloud for %s",
                    self.subdomain,
                )

        # Clear restoration references and dismiss banner
        self.write({
            'restoration_invoice_id': False,
            'retained_backup_path': False,
            'restore_banner_dismissed': True,
        })
        self._append_log("Data restoration completed successfully.")



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

        # Pre-fetch DB sizes per db_server in a single batched query.
        db_sizes_by_server = {}
        for db_server in instances.mapped('db_server_id'):
            if not db_server:
                continue
            db_names = [
                i.subdomain for i in instances
                if i.db_server_id == db_server
                and i.subdomain
                and SUBDOMAIN_RE.match(i.subdomain)
            ]
            if not db_names:
                continue
            try:
                db_sizes_by_server[db_server.id] = \
                    db_server._fetch_database_sizes(db_names)
            except Exception:
                _logger.exception(
                    "Storage cron: failed to batch-fetch sizes from %s",
                    db_server.name,
                )
                db_sizes_by_server[db_server.id] = {}

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
                            db_sizes = db_sizes_by_server.get(
                                instance.db_server_id.id, {}
                            )
                            instance._refresh_usage_with_ssh(
                                ssh,
                                precomputed_db_size=db_sizes.get(instance.subdomain),
                            )
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
        """Suspend running trial instances whose client trial period has expired.

        A partner is considered expired only when their trial end date is
        set AND in the past AND at least one trial flag is True. The
        previous predicate broke the OR/AND grouping and would match any
        partner with a flag regardless of date, mass-suspending paying
        customers.
        """
        today = fields.Date.today()
        expired_partners = self.env['res.partner'].search([
            ('saas_trial_end_date', '!=', False),
            ('saas_trial_end_date', '<=', today),
            '|',
            ('saas_trial_used', '=', True),
            ('saas_hosting_trial_used', '=', True),
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
                # Clear any pending upgrade that was never paid (capture
                # the plan name BEFORE clearing — otherwise the log entry
                # below would dereference a False record).
                if instance.pending_plan_id:
                    pending_name = instance.pending_plan_id.name
                    instance.write({
                        'pending_plan_id': False,
                        'pending_billing_period': False,
                    })
                    instance._append_log(
                        "Pending upgrade to %s cleared (trial expired)."
                        % pending_name
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

    @api.model
    def _cron_renew_daily_backup_addons(self):
        """Generate monthly renewal invoices for the daily-backup add-on.

        Independent of the main subscription cycle so a customer on a
        yearly plan still pays for the backup add-on once a month at
        the monthly rate. Skips trials and instances whose backup flag
        was turned off (which only happens via admin since the portal
        disable path is blocked).
        """
        today = fields.Date.today()
        instances = self.search([
            ('state', '=', 'running'),
            ('is_trial', '=', False),
            ('daily_backup_enabled', '=', True),
            ('daily_backup_next_invoice_date', '!=', False),
            ('daily_backup_next_invoice_date', '<=', today),
        ])
        for instance in instances:
            try:
                instance._generate_daily_backup_renewal_invoice()
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception(
                    "Failed to generate daily-backup renewal invoice for %s",
                    instance.subdomain,
                )

    def _generate_daily_backup_renewal_invoice(self):
        """Issue a single monthly invoice for the daily-backup add-on.

        Advances ``daily_backup_next_invoice_date`` by one month BEFORE
        posting the invoice so a failure later in the post step doesn't
        leave the cron re-issuing the same charge tomorrow.
        """
        self.ensure_one()
        if not (self.is_hosting and self.daily_backup_enabled):
            return
        monthly_price = self._get_daily_backup_price()
        if monthly_price <= 0:
            _logger.warning(
                "Skipping daily-backup renewal for %s: monthly price is "
                "not configured (saas_master.hosting_daily_backup_price).",
                self.subdomain,
            )
            return

        today = fields.Date.today()
        line_name = _(
            'Daily Backups Add-on (monthly) — %s'
        ) % (self.name or self.subdomain)
        product = self._get_daily_backup_product()
        pricelist = self.partner_id.property_product_pricelist
        order_vals = {
            'partner_id': self.partner_id.id,
            'origin': ORIGIN_BACKUP_ADDON % (self.name or self.subdomain),
            'order_line': [(0, 0, {
                'product_id': product.id,
                'name': line_name,
                'product_uom_qty': 1,
                'price_unit': monthly_price,
            })],
        }
        if pricelist:
            order_vals['pricelist_id'] = pricelist.id
        order = self.env['sale.order'].sudo().create(order_vals)
        order.action_confirm()
        invoice = order._create_invoices()

        # Advance the cycle BEFORE posting (see ``_generate_renewal_invoice``
        # for the same pattern + reasoning).
        self.write({
            'daily_backup_last_invoice_date': today,
            'daily_backup_next_invoice_date': (
                self.daily_backup_next_invoice_date + relativedelta(months=1)
                if self.daily_backup_next_invoice_date
                else (today + relativedelta(months=1)).replace(day=1)
            ),
        })
        invoice.action_post()
        self._append_log(
            "Daily-backup monthly renewal invoice %s issued (%.2f). "
            "Next invoice: %s." % (
                invoice.name, monthly_price,
                self.daily_backup_next_invoice_date,
            )
        )
        return invoice

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

        # NB: the daily-backup add-on is NOT billed here. It has its
        # own monthly cycle driven by ``_cron_renew_daily_backup_addons``
        # so a customer on a yearly plan still pays for backups once a
        # month — see ``_generate_daily_backup_renewal_invoice``.

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
            'origin': ORIGIN_RENEWAL % (self.name or self.subdomain),
            'order_line': order_lines,
        }
        if pricelist:
            order_vals['pricelist_id'] = pricelist.id
        order = self.env['sale.order'].create(order_vals)
        order.action_confirm()
        # Keep sale_order_id pointing to the original SO for payment detection;
        # renewal invoices are tracked via partner + origin for dunning.
        invoice = order._create_invoices()

        # Advance the billing cycle *before* posting the invoice. account.move
        # post commits the move at the accounting layer; if we advanced the
        # date afterwards and any later step failed (mail, write), the cron
        # would re-post a duplicate renewal tomorrow.
        if period == 'yearly':
            interval = relativedelta(years=1)
        else:
            interval = relativedelta(months=1)
        self.write({
            'next_invoice_date': self.next_invoice_date + interval,
            'last_invoice_date': fields.Date.today(),
            'suspension_warning_sent': False,
        })
        invoice.action_post()
        self._append_log(
            "Renewal invoice %s created for %s period."
            % (invoice.name, period_label)
        )
        self.message_post(body=_(
            "Renewal invoice %s created (%s). Payment due.",
        ) % (invoice.name, period_label))

        # Send payment-due notification (best-effort: never roll back the
        # renewal if mail delivery fails).
        try:
            self._send_notification('saas_core.mail_template_saas_payment_due')
        except Exception:
            _logger.exception(
                "Failed to send payment-due notification for renewal of %s",
                self.subdomain,
            )

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

    def _is_optional_invoice(self, invoice):
        """Return True if the invoice is for an optional upgrade that
        the client can back out of without losing their current service."""
        so_origins = invoice.line_ids.sale_line_ids.order_id.mapped('origin')
        return any(
            origin and any(
                origin.startswith(prefix)
                for prefix in OPTIONAL_INVOICE_ORIGIN_PREFIXES
            )
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
            'origin': ORIGIN_SUBSCRIPTION % (self.name or self.subdomain),
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
        was_suspended = self.state == 'suspended'
        was_trial = self.is_trial
        billing_period = self.pending_billing_period or 'monthly'

        # Reactivate FIRST if suspended. If the restart fails we don't
        # want to have already flipped is_trial=False — that would leave
        # the customer charged but with a permanently unreachable instance
        # and no way to retry.
        if was_suspended:
            self._append_log("Reactivating instance after paid subscription.")
            try:
                # Use _do_restart synchronously here (we're already inside
                # the background payment thread). action_restart would
                # spawn another bg thread and decouple error reporting.
                self._do_restart()
            except Exception as e:
                # Leave plan/trial unchanged so the customer can retry.
                _logger.exception(
                    "Restart failed during paid-upgrade for %s — aborting "
                    "plan switch so the customer is not charged for an "
                    "unreachable instance.", self.subdomain,
                )
                self._append_log(
                    "ERROR: restart failed during paid-upgrade — plan "
                    "switch deferred. %s" % e
                )
                raise

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
            "Payment confirmed. Upgraded from %s to paid plan: %s."
        ) % ('trial' if was_trial else (old_plan.name if old_plan else 'plan'),
             new_plan.name))

        # Update container resources / regenerate configs (best effort —
        # the customer is already paid and reactivated, don't roll back
        # the upgrade if these fail; they can be retried by Redeploy).
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
            try:
                with self.docker_server_id._get_ssh_connection() as ssh:
                    self._render_and_write_configs(ssh)
            except Exception:
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
        """Cancel the current pending upgrade and ALL of its unpaid invoices.

        Called automatically when the client selects a different plan
        while an upgrade is still awaiting payment. Cancels every unpaid
        invoice tied to either an upgrade SO or a subscription SO for
        this instance — using only `sale_order_id` would miss invoices
        from earlier upgrade rounds whose SO has already been replaced.
        """
        self.ensure_one()
        old_plan_name = (
            self.pending_plan_id.name if self.pending_plan_id else 'Unknown'
        )

        # Find any unpaid posted invoice originating from an upgrade
        # or subscription SO (both are "optional" — the client may back
        # out of paying without losing their current plan).
        invoices = self._get_all_invoices().filtered(
            lambda inv: (
                inv.state == 'posted'
                and inv.payment_state not in ('paid', 'in_payment')
                and inv.amount_residual > 0
                and self._is_optional_invoice(inv)
            )
        )
        for inv in invoices:
            try:
                inv.button_cancel()
            except Exception:
                _logger.exception(
                    "Failed to cancel optional invoice %s for instance %s",
                    inv.name, self.subdomain,
                )

        self._append_log(
            "Auto-cancelled pending upgrade to %s and %d unpaid invoice(s) "
            "(client selected a different plan)."
            % (old_plan_name, len(invoices))
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
            'origin': ORIGIN_PLAN_UPGRADE % (self.name or self.subdomain),
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

        # Refresh storage usage before checking threshold. Use the
        # strict variant — if we can't measure usage we MUST refuse the
        # downgrade rather than greenlight it on a stale/zero value
        # (the customer could otherwise be charged for a plan that can
        # never serve their data).
        try:
            self._strict_refresh_usage()
        except Exception as exc:
            raise UserError(_(
                "Cannot verify current storage usage — refusing the "
                "downgrade until usage can be measured. Please try again "
                "in a few minutes.\n\nDetails: %s"
            ) % exc)

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

    # ========== Hosting: customer-facing DB management ==========
    # Run on the docker host via SSH + ``docker compose exec`` against
    # the running Odoo container. We use Odoo's own
    # ``odoo.service.db.exp_*`` functions for create / duplicate / drop
    # so passwords are hashed correctly and ``base`` is initialised the
    # same way the official /web/database/manager UI would.
    # Plain ``psql`` is enough for the list query.

    # PostgreSQL identifier rules: starts with a letter, [a-z0-9_-],
    # max 63 bytes. Reject the catalog DBs explicitly.
    _DB_NAME_RE = re.compile(r'^[a-z][a-z0-9_-]{0,62}$')
    # Reserved DB names — PostgreSQL system catalogs and Odoo defaults.
    _DB_RESERVED = frozenset([
        'postgres', 'template0', 'template1', 'odoo',
    ])
    # Hard floor for customer-typed suffixes. Anything shorter is
    # almost certainly a slip; reject before we waste a CLI init.
    _DB_NAME_MIN_LENGTH = 3

    def _hosting_db_prefix(self):
        """Prefix every customer-created DB with the instance subdomain.

        Two reasons:
        * Tenant safety — two customers can both pick "prod"; only
          ``acme_prod`` and ``zen_prod`` ever exist on the cluster.
        * Listing — the portal can show only DBs that match the
          prefix, so the cron / drop / duplicate paths never see a
          stranger's data.
        """
        sub = (self.subdomain or '').strip().lower()
        # Underscore is the natural separator; subdomains use hyphens
        # so the boundary is unambiguous (``acme-prod`` + `_` + name).
        return '%s_' % sub if sub else ''

    def _validate_db_name(self, name):
        """Validate a raw customer-typed DB name.

        ``name`` is the bare value the customer entered, **without**
        the subdomain prefix. Returns the normalized (stripped +
        lower-cased) name on success, raises ``UserError`` with a
        specific message otherwise.

        Each branch surfaces a distinct error so the customer knows
        *why* their input was rejected, not just that it was.
        """
        # Strip + normalize. Doing this first lets us tell "empty"
        # apart from "wrong chars".
        raw = (name or '').strip()
        if not raw:
            raise UserError(_("Database name is required."))

        # Reject inputs that change after lower-casing — better to
        # be explicit than silently accept and produce something the
        # customer didn't type.
        if raw != raw.lower():
            raise UserError(_(
                "Database name must be lowercase. '%s' contains uppercase letters."
            ) % raw)
        name = raw

        if len(name) < self._DB_NAME_MIN_LENGTH:
            raise UserError(_(
                "Database name must be at least %d characters long."
            ) % self._DB_NAME_MIN_LENGTH)
        if len(name) > 63:
            raise UserError(_(
                "Database name is too long: %d characters (max 63)."
            ) % len(name))

        # Catch the most common mistakes with specific messages
        # before falling through to the generic regex check.
        if not name[0].isalpha():
            raise UserError(_(
                "Database name must start with a letter (got '%s')."
            ) % name[0])
        bad_chars = [c for c in name if not (c.isalnum() or c in '_-')]
        if bad_chars:
            raise UserError(_(
                "Database name contains characters that aren't allowed: %s. "
                "Use only letters, digits, underscores, and hyphens."
            ) % ', '.join("'%s'" % c for c in sorted(set(bad_chars))))
        if name.endswith('-') or name.endswith('_'):
            raise UserError(_(
                "Database name can't end with a hyphen or underscore."
            ))
        if '--' in name or '__' in name:
            raise UserError(_(
                "Database name can't contain consecutive underscores or hyphens."
            ))

        # Final regex check — catches anything the messages above
        # missed (shouldn't be reachable, but defensive).
        if not self._DB_NAME_RE.match(name):
            raise UserError(_(
                "Database name '%s' is not a valid PostgreSQL identifier."
            ) % name)

        if name in self._DB_RESERVED:
            raise UserError(_(
                "'%s' is reserved and can't be used as a database name."
            ) % name)
        return name

    def _hosting_db_full_name(self, name):
        """Combine the instance prefix and the customer-typed suffix.

        Strips an already-applied prefix if the customer pastes the
        full name back (so re-entering ``acme_test`` doesn't produce
        ``acme_acme_test``). Enforces the 63-byte PG identifier limit
        on the FINAL name.
        """
        self.ensure_one()
        prefix = self._hosting_db_prefix()
        raw = (name or '').strip().lower()
        if prefix and raw.startswith(prefix):
            raw = raw[len(prefix):]
        suffix = self._validate_db_name(raw)
        full = '%s%s' % (prefix, suffix)
        if len(full) > 63:
            raise UserError(_(
                "Database name '%s' is too long (max 63 characters, "
                "including the '%s' prefix)."
            ) % (full, prefix))
        return full

    def _ensure_hosting_for_db_ops(self):
        self.ensure_one()
        if not self.is_hosting:
            raise UserError(_(
                "Database management is only available for hosting instances."
            ))
        # ``provisioning`` is normally off-limits, but a restore-in-progress
        # legitimately needs to list databases for the pre-restore safety
        # snapshot (the container is still up at that point — we haven't
        # docker-compose-down'd yet). Allow only that specific transition.
        allowed = self.state == 'running' or (
            self.state == 'provisioning'
            and self.pending_operation == 'restore'
        )
        if not allowed:
            raise UserError(_(
                "Instance must be running to manage databases (current: %s)."
            ) % self.state)
        if not self.docker_server_id:
            raise UserError(_("No Docker server assigned to this instance."))

    def _docker_exec_python(self, ssh, py_script, env=None, timeout=600):
        """Run ``py_script`` inside the instance's Odoo container.

        Values that need to reach the script (db names, passwords) go
        via env vars so shell-quoting can't bite us. ``odoo.tools.config``
        is preloaded so the script can call into ``odoo.service.db``
        functions immediately.

        Returns ``(exit_code, stdout, stderr)``.
        """
        instance_path = self._get_instance_path()
        env_flags = ''
        if env:
            env_flags = ' '.join(
                '-e %s=%s' % (k, shlex.quote(str(v)))
                for k, v in env.items()
            )
        prelude = (
            "import os, sys\n"
            "import odoo\n"
            "odoo.tools.config.parse_config(['-c','/etc/odoo/odoo.conf'])\n"
        )
        full_script = prelude + py_script
        cmd = (
            "cd %s && docker compose exec -T %s odoo python3 - <<'SAAS_DBOPS_EOF'\n"
            "%s\n"
            "SAAS_DBOPS_EOF"
        ) % (shlex.quote(instance_path), env_flags, full_script)
        return ssh.execute(cmd, timeout=timeout)

    def _docker_exec_sql(self, ssh, sql, db='postgres', timeout=60):
        """Run a single SQL via psql inside the container.

        ``db_password`` is passed via PGPASSWORD env so it doesn't show
        up in process listings.
        """
        instance_path = self._get_instance_path()
        psql_server = self.db_server_id
        env_flags = (
            '-e PGPASSWORD=%s' % shlex.quote(self.sudo().db_password or '')
        )
        cmd = (
            "cd %s && docker compose exec -T %s odoo psql "
            "-h %s -p %s -U %s -d %s -tA -c %s"
        ) % (
            shlex.quote(instance_path),
            env_flags,
            shlex.quote(self._get_db_host()),
            shlex.quote(str(psql_server.psql_port or 5432)),
            shlex.quote(self.sudo().db_user or ''),
            shlex.quote(db),
            shlex.quote(sql),
        )
        return ssh.execute(cmd, timeout=timeout)

    def hosting_db_list(self):
        """List databases this instance's customer owns.

        Calls ``odoo.service.db.list_dbs(force=True)`` inside the
        container — that's the exact function ``/web/database/list``
        backs onto, and it already filters by the PG role owner from
        ``odoo.conf``. We additionally filter by the instance prefix
        in Python so a customer can never see (or operate on) another
        tenant's database, even if PG visibility somehow leaked.

        Going through Odoo's own helper instead of building raw SQL
        sidesteps three layers of quoting (Python -> shell -> psql)
        and the ``LIKE ... ESCAPE`` parser strictness that bit us in
        production.

        Returns a list of dicts: ``{'name': str}``.
        """
        self._ensure_hosting_for_db_ops()
        prefix = self._hosting_db_prefix()
        # Marker prefix/suffix so we can recover the list even if Odoo
        # logs decide to print something to stdout during init.
        script = (
            "from odoo.service.db import list_dbs\n"
            "prefix = os.environ.get('SAAS_DB_PREFIX', '')\n"
            "names = [d for d in list_dbs(force=True) if d.startswith(prefix)]\n"
            "print('---SAAS_DB_LIST_BEGIN---')\n"
            "for n in names:\n"
            "    print(n)\n"
            "print('---SAAS_DB_LIST_END---')\n"
        )
        with self.docker_server_id._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = self._docker_exec_python(
                ssh, script,
                env={'SAAS_DB_PREFIX': prefix},
                timeout=60,
            )
        if exit_code != 0:
            raise UserError(
                _("Could not list databases: %s") % (stderr or stdout)
            )
        # Pull the names out from between the markers; any unrelated
        # log lines Odoo may have emitted are ignored.
        names = []
        capturing = False
        for line in stdout.splitlines():
            line = line.strip()
            if line == '---SAAS_DB_LIST_BEGIN---':
                capturing = True
                continue
            if line == '---SAAS_DB_LIST_END---':
                break
            if capturing and line:
                names.append(line)
        return [{'name': n} for n in names]

    # ------------------------------------------------------------------
    # Customer DB management via XML-RPC to the instance's own ``db``
    # service. This is the same endpoint Odoo's /web/database/manager
    # uses — the request is handled by the LIVE Odoo worker process,
    # which means:
    #   * Registry.new(update_module=True) runs in the worker that's
    #     already fully initialised — no fresh-interpreter setup
    #     gotchas like our earlier ``docker exec python3 -`` attempts.
    #   * No racing init container vs running workers — there's only
    #     one process touching the DB.
    #   * No memory doubling.
    # The master password (`saas.instance.admin_password`) flows over
    # HTTPS in the request body; the customer never sees it.
    # ------------------------------------------------------------------
    def _hosting_xmlrpc_db_proxy(self):
        """Return an XML-RPC proxy for this instance's ``db`` service."""
        import xmlrpc.client
        import ssl

        if not self.url:
            raise UserError(_(
                "Instance has no URL yet — is it deployed?"
            ))
        # Some customer instances haven't issued a Let's Encrypt cert
        # yet (e.g. brand-new deploys). We trust our own infra so we
        # disable verification for these server-to-server calls.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        url = '%s/xmlrpc/2/db' % self.url.rstrip('/')
        return xmlrpc.client.ServerProxy(url, context=ctx, allow_none=True)

    # Modules that ``db.create_database`` doesn't pull in via the
    # auto-install graph but that we consider essential for a usable
    # Odoo (the customer's /web/login fails without ``web`` for
    # instance). Installed via a follow-up XML-RPC call after the
    # database is created. Add ``web_editor``, ``mail`` etc. here if
    # you discover something else is missing.
    _HOSTING_ESSENTIAL_MODULES = ['web', 'base_setup']

    def hosting_db_create(self, name, login, password, lang='en_US',
                          country_code=None):
        """Create a new Odoo database via the instance's XML-RPC db service.

        Two steps:

        1. ``db.create_database(master_pwd, …)`` — the customer's live
           Odoo creates the empty PG database, installs ``base``, sets
           the admin user, creates the filestore.

        2. ``_hosting_install_essentials`` — authenticate as the new
           admin user and install ``web`` + ``base_setup``. Odoo's
           ``create_database`` only installs ``base`` and modules
           flagged ``auto_install=True``; in the standard Docker
           image ``web`` isn't auto-installed, so without this step
           the very first ``/web/login`` request blows up with
           ``External ID not found in the system: web.login``.

        If step 2 fails we drop the DB so a retry starts clean.
        """
        self._ensure_hosting_for_db_ops()
        name = self._hosting_db_full_name(name)
        login = (login or 'admin').strip()
        if not password:
            raise UserError(_("Initial admin password is required."))

        existing = {r['name'] for r in self.hosting_db_list()}
        if name in existing:
            raise UserError(_("Database '%s' already exists.") % name)

        import xmlrpc.client
        proxy = self._hosting_xmlrpc_db_proxy()
        master_pwd = self.sudo().admin_password
        try:
            proxy.create_database(
                master_pwd,
                name,
                False,           # demo
                lang or 'en_US',
                password,        # admin password
                login,           # admin login
                country_code,    # country
                None,            # phone
            )
        except xmlrpc.client.Fault as e:
            msg = (e.faultString or '').strip() or str(e)
            raise UserError(_(
                "Database create failed: %s"
            ) % msg)
        except Exception as e:
            raise UserError(_(
                "Could not reach instance at %s: %s"
            ) % (self.url, e))

        # Step 2 — install essentials. Best-effort: the DB itself is
        # already complete and login-capable, so a failure here
        # (commonly the registry-reload after install severing the
        # XML-RPC connection mid-response) shouldn't trash the DB the
        # customer just paid the bootstrap time for. We log loudly so
        # it's still visible; in practice ``web`` is ``auto_install``
        # in upstream Odoo and gets pulled in by ``base`` anyway.
        try:
            self._hosting_install_essentials(name, login, password)
        except Exception as e:
            _logger.warning(
                "Essentials install on '%s' did not complete cleanly: "
                "%s. DB is kept — customer can log in and finish any "
                "module install via /web.",
                name, e,
            )
        return name

    def _hosting_install_essentials(self, db_name, login, user_password):
        """Authenticate as the new admin and install ``web`` etc.

        Called from ``hosting_db_create`` straight after the live
        Odoo's ``db.create_database`` returns. Uses ORM XML-RPC
        (``/xmlrpc/2/common`` + ``/xmlrpc/2/object``) so the running
        Odoo handles dependency resolution, transactions, and
        registry refresh itself — same path the customer would take
        if they installed a module from Apps.

        Authentication is retried with backoff: ``create_database``
        and the follow-up ``authenticate`` may land on different
        workers in a multi-worker deployment, and the worker handling
        the auth call sometimes hasn't yet seen the freshly-committed
        ``res_users`` row (registry / connection-pool caching). A
        couple of seconds is usually enough for the new row to become
        visible.
        """
        import xmlrpc.client
        import ssl
        import time

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        base_url = self.url.rstrip('/')

        common = xmlrpc.client.ServerProxy(
            '%s/xmlrpc/2/common' % base_url, context=ctx, allow_none=True,
        )
        uid = None
        last_error = None
        for attempt in range(5):
            try:
                uid = common.authenticate(
                    db_name, login, user_password, {},
                )
            except Exception as e:
                last_error = e
                uid = None
            if uid:
                break
            time.sleep(2)
        if not uid:
            # Don't roll back the DB — it's perfectly usable, the
            # customer can log in via /web/login and Odoo will resolve
            # the auto-install graph (web is normally auto_install=True
            # in upstream). Surface a warning so we still notice if
            # this becomes systemic.
            _logger.warning(
                "Could not authenticate as '%s' on freshly-created DB "
                "'%s' after retries (last error: %s). Skipping the "
                "essentials install step — DB is otherwise ready.",
                login, db_name, last_error,
            )
            return

        obj = xmlrpc.client.ServerProxy(
            '%s/xmlrpc/2/object' % base_url, context=ctx, allow_none=True,
        )
        # Look up only the modules that aren't already installed
        # (in case a future Odoo version flips ``web.auto_install`` on
        # and this call becomes a no-op).
        module_ids = obj.execute_kw(
            db_name, uid, user_password,
            'ir.module.module', 'search',
            [[
                ['name', 'in', self._HOSTING_ESSENTIAL_MODULES],
                ['state', '=', 'uninstalled'],
            ]],
        )
        if not module_ids:
            return
        obj.execute_kw(
            db_name, uid, user_password,
            'ir.module.module', 'button_immediate_install',
            [module_ids],
        )

    def hosting_db_duplicate(self, source, new_name):
        """Duplicate a database via the instance's XML-RPC db service."""
        self._ensure_hosting_for_db_ops()
        source = self._hosting_db_full_name(source)
        new_name = self._hosting_db_full_name(new_name)
        existing = {r['name'] for r in self.hosting_db_list()}
        if source not in existing:
            raise UserError(
                _("Source database '%s' does not exist.") % source
            )
        if new_name in existing:
            raise UserError(
                _("Target database '%s' already exists.") % new_name
            )

        import xmlrpc.client
        proxy = self._hosting_xmlrpc_db_proxy()
        master_pwd = self.sudo().admin_password
        try:
            proxy.duplicate_database(master_pwd, source, new_name)
        except xmlrpc.client.Fault as e:
            msg = (e.faultString or '').strip() or str(e)
            raise UserError(_(
                "Database duplicate failed: %s"
            ) % msg)
        except Exception as e:
            raise UserError(_(
                "Could not reach instance: %s"
            ) % e)
        return new_name

    def hosting_db_drop(self, name):
        """Drop a database via the instance's XML-RPC db service.

        The customer can only target DBs in the instance's prefix
        namespace — ``_hosting_db_full_name`` enforces that even if a
        crafted POST tried to drop e.g. ``postgres``.
        """
        self._ensure_hosting_for_db_ops()
        name = self._hosting_db_full_name(name)
        if name not in {r['name'] for r in self.hosting_db_list()}:
            raise UserError(
                _("Database '%s' does not belong to this instance.") % name
            )

        import xmlrpc.client
        proxy = self._hosting_xmlrpc_db_proxy()
        master_pwd = self.sudo().admin_password
        try:
            proxy.drop(master_pwd, name)
        except xmlrpc.client.Fault as e:
            msg = (e.faultString or '').strip() or str(e)
            raise UserError(_("Database drop failed: %s") % msg)
        except Exception as e:
            raise UserError(_(
                "Could not reach instance: %s"
            ) % e)
        return name

    def _hosting_template_db_name(self):
        """Per-instance template DB name.

        Lives outside the customer's prefix namespace so:
        * ``hosting_db_list`` (which filters by ``<sub>_``) won't show it;
        * ``_DB_NAME_RE`` rejects names starting with ``_``, so a
          customer can't accidentally target it via the portal.
        """
        self.ensure_one()
        # Strip hyphens; PG identifiers are happier with underscores.
        safe = (self.subdomain or '').replace('-', '_').lower()
        return '__odoo_template_%s' % safe

    def _hosting_ensure_template_db(self):
        """Create the per-instance template DB if it doesn't exist.

        The template is a fully-initialised Odoo database (``base`` +
        every auto-installable module). It's created once via the
        slow ``odoo -i base`` path, then ``datistemplate=true`` flags
        it as a Postgres template so subsequent customer DB creates
        are near-instant ``CREATE DATABASE WITH TEMPLATE`` clones
        instead of repeating the slow init.

        Container is stopped for the duration of the init (~60-90s)
        — there's no way to run init alongside live Odoo workers
        without one of them caching a half-initialised registry. We
        accept the brief downtime on FIRST DB create only.

        Idempotent and concurrency-safe: if the template already
        exists, this is a single ``SELECT`` and returns. If two
        creates race the bootstrap, the second's
        ``_pg_ensure_db_with_grants`` will fail on "database already
        exists" — caller handles.
        """
        self.ensure_one()
        template = self._hosting_template_db_name()
        if self._pg_db_exists(template):
            return template

        self._append_log(
            "Bootstrapping per-instance template DB '%s' (one-time, "
            "~60s)..." % template
        )
        self._pg_ensure_db_with_grants(template)

        instance_path = self._get_instance_path()
        with self.docker_server_id._get_ssh_connection() as ssh:
            self._hosting_db_pause_container(ssh, instance_path)

            init_cmd = (
                'cd %s && docker compose run --rm -T odoo '
                'odoo -d %s '
                '-i base '
                '--without-demo=all '
                '--stop-after-init '
                '--no-http '
                '--workers=0 '
                '--log-level=info 2>&1'
            ) % (
                shlex.quote(instance_path),
                shlex.quote(template),
            )
            init_exit = 0
            init_output = ''
            try:
                init_exit, stdout, stderr = ssh.execute(
                    init_cmd, timeout=1200,
                )
                init_output = (stdout or '') + (stderr or '')
            finally:
                self._hosting_db_resume_container(ssh, instance_path)

            def _cleanup_template():
                # Drop the half-built template + its filestore so a
                # retry starts from a fully-clean slate.
                try:
                    self._pg_drop_db(template)
                except Exception:
                    pass
                try:
                    self._hosting_drop_filestore(template)
                except Exception:
                    pass

            if init_exit != 0:
                _cleanup_template()
                raise UserError(_(
                    "Template DB init failed (exit %s):\n\n%s"
                ) % (init_exit, init_output[-8000:]))

            if not self._hosting_db_is_initialized(ssh, template):
                _cleanup_template()
                raise UserError(_(
                    "Template DB init exited cleanly but left an "
                    "incomplete schema. Last 8KB of init output:\n\n%s"
                ) % init_output[-8000:])

        # Flip ``datistemplate=true``. Two effects:
        # 1. ``CREATE DATABASE x WITH TEMPLATE __odoo_template_X``
        #    works without disconnecting whoever's connected.
        # 2. Our Odoo workers never auto-load it (they filter out
        #    ``datistemplate`` databases at the registry level).
        self._pg_mark_template(template, flag=True)
        self._append_log("Template DB ready.")
        return template

    def _DEPRECATED_hosting_db_create_template_clone(self, name, login, password, lang='en_US',
                          country_code=None):
        """[DEPRECATED — kept for reference] Create a customer DB via
        PG template cloning.

        Replaced by the XML-RPC-based ``hosting_db_create`` above —
        the live Odoo handles registry plumbing properly there, and
        template-clone added too much moving infrastructure (per-
        instance template bootstrap, filestore cp, datistemplate flag
        management) that bit us in production. This body kept only so
        the design intent is documented.

        1. Validate the customer's name.
        2. Ensure the per-instance template exists (slow on first
           call, instant after — runs only when the template's
           genuinely missing).
        3. ``CREATE DATABASE <new> WITH TEMPLATE <template> OWNER
           <role>`` on the db server. Postgres copies data files at
           the storage layer — typically seconds, no Odoo init runs.
        4. ``docker compose exec`` a short ORM patch to update the
           admin user's login / password / lang (the cloned DB has
           the template's ``admin / admin`` placeholders) and set
           the company country if supplied.

        No container restart. No racing workers. The new DB is
        always either fully present or fully absent — half-built
        states are impossible because Postgres' ``CREATE DATABASE
        WITH TEMPLATE`` is atomic.
        """
        self._ensure_hosting_for_db_ops()
        name = self._hosting_db_full_name(name)
        login = (login or 'admin').strip()
        if not password:
            raise UserError(_("Initial admin password is required."))

        existing = {r['name'] for r in self.hosting_db_list()}
        if name in existing:
            raise UserError(_("Database '%s' already exists.") % name)

        # 1. Make sure the template exists. First call: slow (~60-90s
        # init, container down). Subsequent calls: a single SELECT.
        template = self._hosting_ensure_template_db()

        # 2. Clone the PG database from the template. Fast (atomic).
        self._append_log(
            "Cloning '%s' from template '%s'..." % (name, template)
        )
        self._pg_clone_db(template, name)

        # 3. Clone the filestore directory. An Odoo DB is two things:
        # the psql database (cloned in step 2) AND a per-DB filestore
        # directory at /var/lib/odoo/filestore/<name>. ``CREATE
        # DATABASE WITH TEMPLATE`` only covers the first. Without
        # this step, the new DB's first request would 500 on missing
        # attachments / icons that the cloned ir_attachment rows
        # point at.
        try:
            self._hosting_clone_filestore(template, name)
        except Exception as e:
            self._pg_drop_db(name)
            raise UserError(_(
                "Database '%s' was cloned but filestore copy failed; "
                "rolled back:\n%s"
            ) % (name, e))

        # 4. Patch admin credentials via a short ORM script. The
        # cloned DB inherits the template's admin user; we replace
        # the placeholder login/password with what the customer
        # entered. On failure we drop both the DB and its filestore
        # so a retry starts clean.
        try:
            self._hosting_patch_admin_creds(
                db_name=name, login=login, password=password,
                lang=lang or 'en_US', country_code=country_code,
            )
        except Exception as e:
            try:
                self._hosting_drop_filestore(name)
            except Exception:
                pass
            self._pg_drop_db(name)
            raise UserError(_(
                "Database '%s' cloned but admin credential patch "
                "failed; rolled back:\n%s"
            ) % (name, e))

        self._append_log("Database '%s' ready." % name)
        return name

    def _hosting_filestore_path(self, db_name):
        """Return the host-side path to a DB's Odoo filestore.

        The compose volume mounts ``./data/odoo`` →
        ``/var/lib/odoo`` inside the container, so the host path is
        ``<instance_path>/data/odoo/filestore/<db>``. Used to copy /
        delete filestores without entering the container.
        """
        return '%s/data/odoo/filestore/%s' % (
            self._get_instance_path(), db_name,
        )

    def _hosting_clone_filestore(self, source_db, target_db):
        """Copy the template's filestore directory to the new DB's path.

        Runs ``cp -a`` on the docker host (sudo so we can read the
        container-owned source even when our SSH user can't), then
        fixes ownership so the running container can write to it.
        If the template never had a filestore directory (no modules
        wrote any files), we just create an empty target.
        """
        self.ensure_one()
        src = self._hosting_filestore_path(source_db)
        dst = self._hosting_filestore_path(target_db)
        instance_path = self._get_instance_path()

        with self.docker_server_id._get_ssh_connection() as ssh:
            container_uid = self._get_container_uid(ssh)
            cmd = (
                # Idempotent: if dst already exists from a previous
                # half-run, blow it away first.
                'sudo rm -rf %(dst)s && '
                # Copy or create empty. The template's filestore may
                # legitimately not exist if no module wrote anything
                # to disk; cover that case so we don't error out.
                'if [ -d %(src)s ]; then '
                '  sudo cp -a %(src)s %(dst)s; '
                'else '
                '  sudo mkdir -p %(dst)s; '
                'fi && '
                'sudo chown -R %(uid)s:%(uid)s %(dst)s && '
                'sudo chmod -R 755 %(dst)s'
            ) % {
                'src': shlex.quote(src),
                'dst': shlex.quote(dst),
                'uid': container_uid,
            }
            exit_code, stdout, stderr = ssh.execute(cmd, timeout=600)
            if exit_code != 0:
                raise UserError(_(
                    "Failed to clone filestore:\n%s"
                ) % (stderr or stdout))

    def _hosting_drop_filestore(self, db_name):
        """Remove a DB's filestore directory. Best-effort.

        Called from rollback paths and from instance deletion. We
        guard the name regex one more time before passing to the
        shell — defense in depth even though callers already validate.
        """
        self.ensure_one()
        if not self._DB_IDENT_RE.match(db_name or ''):
            return
        path = self._hosting_filestore_path(db_name)
        with self.docker_server_id._get_ssh_connection() as ssh:
            ssh.execute(
                'sudo rm -rf %s' % shlex.quote(path), timeout=120,
            )

    def _hosting_patch_admin_creds(self, db_name, login, password,
                                   lang, country_code):
        """Set admin login / password / lang on a freshly-cloned DB.

        Goes through ``docker compose exec python3 -`` so Odoo's
        password hashing runs (we never see or store the plaintext
        in PG). The script writes directly via the ORM — short, no
        registry preload contention because the DB was just cloned
        and no worker has touched it yet.
        """
        script = (
            "from contextlib import closing\n"
            "import odoo\n"
            "from odoo import api, SUPERUSER_ID\n"
            "from odoo.modules.registry import Registry\n"
            "registry = Registry(os.environ['SAAS_DB_NAME'])\n"
            "with closing(registry.cursor()) as cr:\n"
            "    env = api.Environment(cr, SUPERUSER_ID, {})\n"
            "    admin = env.ref('base.user_admin')\n"
            "    vals = {\n"
            "        'login': os.environ['SAAS_DB_LOGIN'],\n"
            "        'password': os.environ['SAAS_DB_PWD'],\n"
            "        'lang': os.environ['SAAS_DB_LANG'],\n"
            "    }\n"
            "    if '@' in os.environ['SAAS_DB_LOGIN']:\n"
            "        vals['email'] = os.environ['SAAS_DB_LOGIN']\n"
            "    admin.write(vals)\n"
            "    cc = os.environ.get('SAAS_DB_CC') or ''\n"
            "    if cc:\n"
            "        country = env['res.country'].search("
            "            [('code', 'ilike', cc)], limit=1)\n"
            "        if country:\n"
            "            env['res.company'].browse(1).write({\n"
            "                'country_id': country.id,\n"
            "                'currency_id': country.currency_id.id,\n"
            "            })\n"
            "    cr.commit()\n"
            "print('OK')\n"
        )
        env = {
            'SAAS_DB_NAME': db_name,
            'SAAS_DB_LANG': lang,
            'SAAS_DB_PWD': password,
            'SAAS_DB_LOGIN': login,
            'SAAS_DB_CC': country_code or '',
        }
        with self.docker_server_id._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = self._docker_exec_python(
                ssh, script, env=env, timeout=120,
            )
        if exit_code != 0 or 'OK' not in (stdout or ''):
            raise UserError(_(
                "Could not patch admin credentials:\n%s\n%s"
            ) % ((stdout or '')[-1000:], (stderr or '')[-500:]))

    def _hosting_db_pause_container(self, ssh, instance_path):
        """Stop the customer's Odoo container so it doesn't race the
        init we're about to run on a new database.

        Why ``docker compose down`` rather than ``docker stop``: we
        also want the container removed so the ephemeral
        ``docker compose run --rm`` below can reuse the service slot
        cleanly without name conflicts. The volumes are preserved
        because we don't pass ``-v``.
        """
        self._append_log(
            "Pausing instance container during DB init..."
        )
        ssh.execute(
            'cd %s && docker compose down 2>&1'
            % shlex.quote(instance_path),
            timeout=120,
        )

    def _hosting_db_resume_container(self, ssh, instance_path):
        """Bring the instance container back up after a DB init.

        Best-effort: if this fails we log it but don't raise — the
        operator can also bring it back manually. Raising here would
        mask the original (init) failure from the caller.
        """
        self._append_log("Resuming instance container...")
        ec, out, err = ssh.execute(
            'cd %s && docker compose up -d 2>&1'
            % shlex.quote(instance_path),
            timeout=300,
        )
        if ec != 0:
            self._append_log(
                "WARNING: container resume returned exit %s — manual "
                "intervention may be needed.\n%s"
                % (ec, (err or out or '')[-1000:])
            )

    def _hosting_db_is_initialized(self, ssh, name):
        """Return True iff ``base`` is fully installed in ``name``.

        Used as a post-init verification so we don't claim success on
        a half-built database. We check via plain psql so the answer
        doesn't depend on the registry's loaded state — we want the
        ground truth from PG.
        """
        sql = (
            "SELECT 1 FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname='public' AND c.relname='ir_module_module' "
            "AND EXISTS ("
            "  SELECT 1 FROM ir_module_module "
            "  WHERE name='base' AND state='installed'"
            ")"
        )
        # ``-d <name>`` here is the DB we just initialized, not the
        # subdomain DB the container normally talks to.
        instance_path = self._get_instance_path()
        psql_server = self.db_server_id
        env_flags = (
            '-e PGPASSWORD=%s' % shlex.quote(self.sudo().db_password or '')
        )
        cmd = (
            "cd %s && docker compose exec -T %s odoo psql "
            "-h %s -p %s -U %s -d %s -tA -c %s 2>&1"
        ) % (
            shlex.quote(instance_path),
            env_flags,
            shlex.quote(self._get_db_host()),
            shlex.quote(str(psql_server.psql_port or 5432)),
            shlex.quote(self.sudo().db_user or ''),
            shlex.quote(name),
            shlex.quote(sql),
        )
        exit_code, stdout, _ = ssh.execute(cmd, timeout=60)
        # The query returns either '1' (initialised) or empty/no rows.
        return exit_code == 0 and stdout.strip() == '1'

    def _hosting_db_rollback(self, ssh, name):
        """Best-effort drop a half-built database after a failed init.

        Runs ``docker compose exec`` against the running container so
        we don't need a fresh ephemeral container just to clean up.
        Errors are swallowed — the original init failure is more
        important to surface than a cleanup hiccup.
        """
        script = (
            "from odoo.service import db\n"
            "try:\n"
            "    db.exp_drop(os.environ['SAAS_DB_NAME'])\n"
            "except Exception:\n"
            "    pass\n"
            "print('OK')\n"
        )
        try:
            self._docker_exec_python(
                ssh, script,
                env={'SAAS_DB_NAME': name}, timeout=60,
            )
        except Exception:
            _logger = __import__('logging').getLogger(__name__)
            _logger.warning(
                "Best-effort rollback of %s failed", name,
            )

    def hosting_db_create_async(self, name, login, password,
                                lang='en_US', country_code=None):
        """Queue a database create and return the tracking record.

        The actual create runs in a background thread so the HTTP
        request returns within ~200 ms — far below nginx's
        ``proxy_read_timeout`` and without tying up a worker for the
        30-90 s the CLI init takes.
        """
        self._ensure_hosting_for_db_ops()
        # Validate upfront so the customer gets a synchronous error
        # for bad names instead of a "failed" record they have to
        # discover on refresh.
        full_name = self._hosting_db_full_name(name)
        if not password:
            raise UserError(_("Initial admin password is required."))
        existing = {r['name'] for r in self.hosting_db_list()}
        if full_name in existing:
            raise UserError(_("Database '%s' already exists.") % full_name)
        # Don't queue a second create for the same target name while
        # the first is still running.
        Op = self.env['saas.instance.db.operation']
        if Op.search_count([
            ('instance_id', '=', self.id),
            ('db_name', '=', full_name),
            ('state', '=', 'running'),
        ]):
            raise UserError(
                _("A create for '%s' is already in progress.") % full_name
            )

        op = Op.create({
            'instance_id': self.id,
            'db_name': full_name,
            'operation': 'create',
        })
        run_in_background(
            op, '_run_create',
            method_args=(
                login, password, lang or 'en_US', country_code or None,
            ),
            thread_name='saas_db_create_%s' % full_name,
        )
        return op

    def hosting_db_duplicate_async(self, source, new_name):
        """Queue a database duplicate and return the tracking record."""
        self._ensure_hosting_for_db_ops()
        source_full = self._hosting_db_full_name(source)
        new_full = self._hosting_db_full_name(new_name)
        existing = {r['name'] for r in self.hosting_db_list()}
        if source_full not in existing:
            raise UserError(_("Source database '%s' does not exist.") % source_full)
        if new_full in existing:
            raise UserError(_("Target database '%s' already exists.") % new_full)
        Op = self.env['saas.instance.db.operation']
        if Op.search_count([
            ('instance_id', '=', self.id),
            ('db_name', '=', new_full),
            ('state', '=', 'running'),
        ]):
            raise UserError(
                _("A duplicate to '%s' is already in progress.") % new_full
            )
        op = Op.create({
            'instance_id': self.id,
            'db_name': new_full,
            'source_db': source_full,
            'operation': 'duplicate',
        })
        run_in_background(
            op, '_run_duplicate',
            thread_name='saas_db_dup_%s' % new_full,
        )
        return op

    def hosting_db_drop_async(self, name):
        """Queue a database drop and return the tracking record.

        Drop is fast (a single ``DROP DATABASE``) but still goes async
        so the experience matches create / duplicate and the customer
        sees the same in-flight indicator.
        """
        self._ensure_hosting_for_db_ops()
        full_name = self._hosting_db_full_name(name)
        Op = self.env['saas.instance.db.operation']
        if Op.search_count([
            ('instance_id', '=', self.id),
            ('db_name', '=', full_name),
            ('state', '=', 'running'),
        ]):
            raise UserError(
                _("A drop of '%s' is already in progress.") % full_name
            )
        op = Op.create({
            'instance_id': self.id,
            'db_name': full_name,
            'operation': 'drop',
        })
        run_in_background(
            op, '_run_drop',
            thread_name='saas_db_drop_%s' % full_name,
        )
        return op

    def _DEPRECATED_hosting_db_duplicate_dockerexec(self, source, new_name):
        """[DEPRECATED] Pre-XML-RPC duplicate path via docker exec.

        Replaced by the XML-RPC ``hosting_db_duplicate`` above.
        """
        self._ensure_hosting_for_db_ops()
        # Both source and target live under the instance prefix.
        # _hosting_db_full_name strips a re-pasted prefix so the
        # customer can hand us either the bare name or the full one.
        source = self._hosting_db_full_name(source)
        new_name = self._hosting_db_full_name(new_name)
        existing = {r['name'] for r in self.hosting_db_list()}
        if source not in existing:
            raise UserError(
                _("Source database '%s' does not exist.") % source
            )
        if new_name in existing:
            raise UserError(
                _("Target database '%s' already exists.") % new_name
            )
        script = (
            "from odoo.service import db\n"
            "db.exp_duplicate_database(\n"
            "  os.environ['SAAS_DB_SRC'],\n"
            "  os.environ['SAAS_DB_DST'],\n"
            ")\n"
            "print('OK')\n"
        )
        env = {'SAAS_DB_SRC': source, 'SAAS_DB_DST': new_name}
        with self.docker_server_id._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = self._docker_exec_python(
                ssh, script, env=env, timeout=600,
            )
        if exit_code != 0 or 'OK' not in stdout:
            raise UserError(_(
                "Database duplicate failed:\n%s\n%s"
            ) % (stdout[-1000:], stderr[-500:]))
        return new_name

    def _DEPRECATED_hosting_db_drop_dockerexec(self, name):
        """[DEPRECATED] Pre-XML-RPC drop path via docker exec.

        Replaced by the XML-RPC ``hosting_db_drop`` above.
        """
        self._ensure_hosting_for_db_ops()
        name = self._hosting_db_full_name(name)
        # Belt and braces: confirm the DB really is one of ours before
        # talking to PG. ``hosting_db_list`` already filters by prefix.
        if name not in {r['name'] for r in self.hosting_db_list()}:
            raise UserError(
                _("Database '%s' does not belong to this instance.") % name
            )
        script = (
            "from odoo.service import db\n"
            "db.exp_drop(os.environ['SAAS_DB_NAME'])\n"
            "print('OK')\n"
        )
        with self.docker_server_id._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = self._docker_exec_python(
                ssh, script, env={'SAAS_DB_NAME': name}, timeout=120,
            )
        if exit_code != 0 or 'OK' not in stdout:
            raise UserError(_(
                "Database drop failed:\n%s\n%s"
            ) % (stdout[-1000:], stderr[-500:]))
        return name

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
            'backup_running': bool(self.backup_ids.filtered(lambda b: b.state == 'running')),
            'restoration_pending': bool(self.restoration_invoice_id),
            'db_ops_running': bool(self._hosting_reconcile_db_ops()),
        }

    # Skip the expensive ``hosting_db_list`` reconcile for the first
    # ~90 s of an op's lifetime — that's the normal completion window
    # for create (clone + bootstrap) and duplicate. Reconciling sooner
    # would SSH into the docker host on every 5-second poll for no
    # reason; the happy path is just ``search_count`` on the state.
    _DB_OP_RECONCILE_GRACE_SECONDS = 90

    def _hosting_reconcile_db_ops(self):
        """Self-heal stuck DB-op tracking rows and return the live set.

        The background worker normally flips ``state`` to ``done`` /
        ``failed`` itself — but that flip can be missed when the
        XML-RPC call to the customer's instance hangs (no socket
        timeout in ``xmlrpc.client``), when the HTTP worker is
        recycled by ``--limit-time-real`` mid-thread, or when a
        registry reload after module install severs the connection.
        Reality (the actual list of databases) is the source of
        truth, so we reconcile against it whenever an op has been
        running longer than the typical completion window. Returns
        the recordset of ops still running so callers can decide
        whether to keep polling.
        """
        self.ensure_one()
        Op = self.env['saas.instance.db.operation'].sudo()
        stuck = Op.search([
            ('instance_id', '=', self.id),
            ('state', '=', 'running'),
        ])
        if not stuck:
            return stuck
        # Listing requires a reachable hosting instance with a docker
        # server — otherwise we'd surface the listing error as a
        # "stuck" status check.
        if not (self.is_hosting and self.state in ('running', 'provisioning')
                and self.docker_server_id):
            return stuck
        # Only reconcile against the live DB list once the youngest op
        # is past the typical completion window. Keeps the happy-path
        # poll a cheap ``search_count`` instead of an SSH round trip.
        cutoff = fields.Datetime.now() - datetime.timedelta(
            seconds=self._DB_OP_RECONCILE_GRACE_SECONDS,
        )
        if not any(op.create_date and op.create_date < cutoff for op in stuck):
            return stuck
        try:
            db_names = {r['name'] for r in self.hosting_db_list()}
        except Exception:
            return stuck
        still_running = self.env['saas.instance.db.operation']
        for op in stuck:
            if op.operation in ('create', 'duplicate'):
                if op.db_name in db_names:
                    op.state = 'done'
                    continue
            elif op.operation == 'drop':
                if op.db_name not in db_names:
                    op.state = 'done'
                    continue
            still_running |= op
        return still_running

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
            # Reset restore banner so client sees the option again
            'restore_banner_dismissed': False,
            'restoration_invoice_id': False,
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

