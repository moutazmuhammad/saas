import datetime
import logging
import os
import re
import secrets
import shlex
import string
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

    # ========== Plan ==========
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

    # ========== Modules ==========
    module_line_ids = fields.One2many(
        'saas.instance.module.line',
        'instance_id',
        string='Installation Lines',
        help='All module and product installation requests for this instance.',
    )
    product_line_ids = fields.One2many(
        'saas.instance.module.line',
        'instance_id',
        string='Products to Install',
        domain=[('product_id', '!=', False)],
        help='Installation lines that reference a product.',
    )
    single_module_line_ids = fields.One2many(
        'saas.instance.module.line',
        'instance_id',
        string='Modules to Install',
        domain=[('module_id', '!=', False)],
        help='Installation lines that reference an individual module.',
    )
    installed_module_ids = fields.Many2many(
        'product.product',
        'saas_instance_installed_product_rel',
        'instance_id',
        'product_id',
        string='Installed Modules',
        readonly=True,
        help='Module products that have been successfully installed on this instance.',
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
        help='Current CPU usage percentage of the Docker container.',
    )
    ram_usage = fields.Char(
        string='RAM Usage',
        readonly=True,
        help='Current RAM usage of the Docker container (used / limit).',
    )
    ram_percent = fields.Char(
        string='RAM %',
        readonly=True,
        help='Current RAM usage percentage of the Docker container.',
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
            ('provisioning', 'Provisioning'),
            ('running', 'Running'),
            ('stopped', 'Stopped'),
            ('failed', 'Failed'),
            ('suspended', 'Suspended'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        tracking=True,
        required=True,
        index=True,
        help='Current lifecycle state of the instance.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        help='Company that manages this SaaS instance.',
    )

    # ========== Constraints ==========
    _sql_constraints = [
        (
            'unique_subdomain_per_domain',
            'UNIQUE(subdomain, domain_id)',
            'Subdomain must be unique per domain.',
        ),
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
        return records

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

        Combines instance-level repos and version-level repos.
        Only includes version repos that are needed by the instance's
        selected products or modules (via saas_source_repo_id).
        """
        self.ensure_one()
        server = self.docker_server_id

        # Instance-level repos (absolute mount from custom_repos/)
        instance_repos = self.repo_ids.filtered(lambda r: r.state == 'cloned')
        repos = [{
            'dir_name': r._get_repo_dir_name(),
            'host_path': r._get_remote_repo_path(),
        } for r in instance_repos]
        addons_paths = [r._get_container_addons_path() for r in instance_repos]

        # Determine which version repos are needed by selected products/modules
        needed_version_repo_ids = set()
        for line in self.module_line_ids:
            # Check product's source repo
            if line.product_id:
                tmpl = line.product_id.product_tmpl_id
                if tmpl.saas_source_repo_id:
                    needed_version_repo_ids.add(tmpl.saas_source_repo_id.id)
                # Also check individual modules inside the product
                for mod in tmpl.saas_module_ids:
                    if mod.saas_source_repo_id:
                        needed_version_repo_ids.add(mod.saas_source_repo_id.id)
            # Check individual module's source repo
            if line.module_id:
                tmpl = line.module_id.product_tmpl_id
                if tmpl.saas_source_repo_id:
                    needed_version_repo_ids.add(tmpl.saas_source_repo_id.id)

        # Version-level repos (absolute mount) — only those needed
        version_repos = []
        if self.odoo_version_id and needed_version_repo_ids:
            for vr in self.odoo_version_id.repo_ids.filtered(
                lambda r: r.state == 'cloned' and r.id in needed_version_repo_ids
            ):
                version_repos.append({
                    'dir_name': vr._get_repo_dir_name(),
                    'host_path': vr._get_remote_repo_path(server),
                })
                addons_paths.append(vr._get_container_addons_path())

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

    def _refresh_usage_with_ssh(self, ssh):
        """Fetch resource usage using an existing SSH connection to the docker server."""
        self.ensure_one()
        container_name = self._get_container_name()
        instance_path = self._get_instance_path()

        # Fetch container CPU & RAM via docker stats table output
        stats_cmd = 'docker stats --no-stream %s' % shlex.quote(container_name)
        exit_code, stdout, stderr = ssh.execute(stats_cmd)
        if exit_code == 0 and stdout.strip():
            lines = stdout.strip().splitlines()
            if len(lines) >= 2:
                values = lines[1].split()
                for i, val in enumerate(values):
                    if '%' in val:
                        self.cpu_usage = val
                        remaining = values[i+1:]
                        if len(remaining) >= 3:
                            self.ram_usage = '%s %s %s' % (
                                remaining[0], remaining[1], remaining[2],
                            )
                        if len(remaining) >= 4 and '%' in remaining[3]:
                            self.ram_percent = remaining[3]
                        break

        # Fetch disk usage of the instance folder (in bytes)
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

        # Fetch database size from PostgreSQL server (in bytes)
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

        total_bytes = disk_bytes + db_bytes
        self.total_storage = self._format_bytes(total_bytes) if total_bytes else ''
        self.total_storage_bytes = total_bytes
        self.usage_last_updated = fields.Datetime.now()

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
            'extra_config': self._parse_extra_config(),
            'repo_addons_paths': all_addons_paths,
        }
        conf_content = self._render_template('odoo.conf.jinja', conf_context)
        ssh.write_file('%s/config/odoo.conf' % instance_path, conf_content)
        self._append_log("odoo.conf written.")

    # ========== Module Installation Helper ==========

    def _install_pending_modules(self, ssh):
        """Install pending module lines via docker compose run. Returns True if modules were installed."""
        self.ensure_one()
        instance_path = self._get_instance_path()

        pending_lines = self.module_line_ids.filtered(
            lambda l: l.state == 'pending'
        ).sorted('sequence')

        if not pending_lines:
            return False

        all_module_names = []
        for line in pending_lines:
            names = line._get_all_technical_names()
            names.discard('base')
            for n in sorted(names):
                if n not in all_module_names:
                    all_module_names.append(n)

        if not all_module_names:
            return False

        modules_to_install = ','.join(all_module_names)

        # Log what each line contributes
        for line in pending_lines:
            names = line._get_all_technical_names()
            names.discard('base')
            label = line.product_id.name if line.product_id else (
                line.module_id.name if line.module_id else ','.join(sorted(names))
            )
            self._append_log(
                "Line [%d] %s: %s" % (line.sequence, label, ','.join(sorted(names)))
            )

        self._append_log("Installing modules: %s" % modules_to_install)
        install_cmd = (
            'cd %s && docker compose run --rm -T odoo '
            'odoo -d %s '
            '-i %s '
            '--without-demo=all '
            '--stop-after-init '
            '--no-http 2>&1'
        ) % (
            shlex.quote(instance_path),
            shlex.quote(self.subdomain),
            shlex.quote(modules_to_install),
        )
        exit_code, stdout, stderr = ssh.execute(install_cmd, timeout=600)
        self._append_log(
            "Install output (last 1000 chars):\n%s" % stdout[-1000:]
        )
        if exit_code != 0:
            for line in pending_lines:
                line.state = 'failed'
                line.log = stdout[-2000:] + '\n' + stderr[-500:]
            raise UserError(
                _("Module installation failed:\n%s\n%s")
                % (stdout[-500:], stderr[-500:])
            )

        self._append_log("All modules installed successfully.")

        # Mark all lines as installed and track products
        all_products = self.env['product.product']
        for line in pending_lines:
            line.state = 'installed'
            line.log = ''
            if line.product_id:
                module_tmpls = line.product_id.product_tmpl_id.saas_module_ids
                all_products |= module_tmpls.mapped('product_variant_id')
            elif line.module_id:
                all_products |= line.module_id
        if all_products:
            self.installed_module_ids = [(4, p.id) for p in all_products]

        return True

    # ========== Deploy Flow ==========

    def action_deploy(self):
        """Full deployment flow: provision Docker container over SSH (async)."""
        for rec in self:
            if rec.state not in ('draft', 'failed'):
                raise UserError(
                    _("Cannot deploy instance '%s': must be in Draft or Failed state (current: %s).")
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

            # Set permissions
            self._append_log("Setting permissions...")
            perms_cmd = (
                'chown -R 1000:1000 %(path)s/data/odoo %(path)s/config %(path)s/addons && '
                'chmod -R 777 %(path)s/data/odoo %(path)s/config %(path)s/addons'
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

            # Install modules — for initial deploy, include 'base'
            pending_lines = self.module_line_ids.filtered(
                lambda l: l.state == 'pending'
            ).sorted('sequence')

            all_module_names = []
            for line in pending_lines:
                names = line._get_all_technical_names()
                names.discard('base')
                for n in sorted(names):
                    if n not in all_module_names:
                        all_module_names.append(n)

            modules_to_install = 'base'
            if all_module_names:
                modules_to_install = 'base,%s' % ','.join(all_module_names)

            for line in pending_lines:
                names = line._get_all_technical_names()
                names.discard('base')
                label = line.product_id.name if line.product_id else (
                    line.module_id.name if line.module_id else ','.join(sorted(names))
                )
                self._append_log(
                    "Line [%d] %s: %s" % (line.sequence, label, ','.join(sorted(names)))
                )

            self._append_log(
                "Initializing database with modules: %s" % modules_to_install
            )
            init_cmd = (
                'cd %s && docker compose run --rm -T odoo '
                'odoo -d %s '
                '-i %s '
                '--without-demo=all '
                '--stop-after-init '
                '--no-http 2>&1'
            ) % (
                shlex.quote(instance_path),
                shlex.quote(self.subdomain),
                shlex.quote(modules_to_install),
            )
            exit_code, stdout, stderr = ssh.execute(init_cmd, timeout=600)
            self._append_log(
                "Install output (last 1000 chars):\n%s" % stdout[-1000:]
            )
            if exit_code != 0:
                for line in pending_lines:
                    line.state = 'failed'
                    line.log = stdout[-2000:] + '\n' + stderr[-500:]
                raise UserError(
                    _("Module installation failed:\n%s\n%s")
                    % (stdout[-500:], stderr[-500:])
                )
            self._append_log("All modules installed successfully.")

            # Mark all lines as installed and track products
            all_products = self.env['product.product']
            for line in pending_lines:
                line.state = 'installed'
                line.log = ''
                if line.product_id:
                    module_tmpls = line.product_id.product_tmpl_id.saas_module_ids
                    all_products |= module_tmpls.mapped('product_variant_id')
                elif line.module_id:
                    all_products |= line.module_id
            if all_products:
                self.installed_module_ids = [(4, p.id) for p in all_products]

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

        # 3. Clone any pending version repos needed by module lines
        needed_version_repo_ids = set()
        for line in self.module_line_ids:
            if line.product_id:
                tmpl = line.product_id.product_tmpl_id
                if tmpl.saas_source_repo_id:
                    needed_version_repo_ids.add(tmpl.saas_source_repo_id.id)
                for mod in tmpl.saas_module_ids:
                    if mod.saas_source_repo_id:
                        needed_version_repo_ids.add(mod.saas_source_repo_id.id)
            if line.module_id:
                tmpl = line.module_id.product_tmpl_id
                if tmpl.saas_source_repo_id:
                    needed_version_repo_ids.add(tmpl.saas_source_repo_id.id)
        if self.odoo_version_id and needed_version_repo_ids:
            pending_vrepos = self.odoo_version_id.repo_ids.filtered(
                lambda r: r.state == 'pending' and r.id in needed_version_repo_ids
            )
            for vrepo in pending_vrepos:
                self._append_log("Cloning pending version repo %s..." % vrepo.repo_url)
                vrepo.action_clone_repo()

        # 4. Update docker-compose.yml and odoo.conf with current mounts
        self._append_log("Updating configuration...")
        with server._get_ssh_connection() as ssh:
            self._render_and_write_configs(ssh)
        self._append_log("Configuration updated.")

        # 5. Install pending modules (if any)
        with server._get_ssh_connection() as ssh:
            self._install_pending_modules(ssh)

        # 6. Restart the container
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
        """Reset to draft state (only from failed or cancelled)."""
        for rec in self:
            if rec.state not in ('failed', 'cancelled'):
                raise UserError(
                    _("Can only reset to draft from 'Failed' or 'Cancelled' state.")
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

        # Reset module/product lines and clear installed modules
        self.module_line_ids.write({'state': 'pending'})
        self.installed_module_ids = [(5,)]

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
        self._append_log("Backup queued. Running in background...")
        run_in_background(
            self, '_do_create_backup',
            thread_name='saas_backup_%s' % self.subdomain,
        )
        return True

    def _do_create_backup(self):
        """Create backup (runs in background thread)."""
        self.ensure_one()
        self.env['saas.instance.backup']._perform_backup(self)
        self._append_log("Backup completed successfully.")



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
                        limit_bytes = instance.plan_id.storage_limit * (1024 ** 3)
                        if total_bytes > limit_bytes:
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


