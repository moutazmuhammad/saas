import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..utils import run_in_background

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    saas_type = fields.Selection(
        selection=[
            ('module', 'Module'),
            ('product', 'Product'),
        ],
        string='SaaS Type',
        help='Identifies this product as part of the SaaS platform. '
             '"Module" represents an individual Odoo module; '
             '"Product" represents a package of modules sold together.',
    )
    technical_name = fields.Char(
        string='Technical Name',
        help='Odoo technical module name as used in the CLI and manifest '
             '(e.g. "sale", "account", "purchase").',
    )
    saas_odoo_version_id = fields.Many2one(
        'saas.odoo.version',
        string='Odoo Version',
        ondelete='cascade',
        help='The Odoo version this module or product belongs to.',
    )
    saas_dependency_ids = fields.Many2many(
        'product.template',
        'saas_product_dependency_rel',
        'product_id',
        'dependency_id',
        string='Dependencies',
        domain="[('saas_type', '=', 'module')]",
        help='Other modules that are automatically installed as dependencies of this module.',
    )
    saas_module_ids = fields.Many2many(
        'product.template',
        'saas_product_module_rel',
        'product_tmpl_id',
        'module_id',
        string='Included Modules',
        domain="[('saas_type', '=', 'module')]",
        help='Modules included in this product. All listed modules will be '
             'installed when a customer purchases this product.',
    )
    saas_source = fields.Selection(
        [
            ('standard', 'Standard'),
            ('custom', 'Custom Repo'),
        ],
        string='Source',
        default='standard',
        help='Where this module was fetched from: '
             'Standard (Docker image) or Custom Repo (GitHub repository).',
    )
    saas_source_repo_id = fields.Many2one(
        'saas.version.repo',
        string='Source Repository',
        ondelete='set null',
    )
    saas_author = fields.Char(
        string='Module Author',
        help='Author of the module as declared in the Odoo manifest file.',
    )
    saas_module_count = fields.Integer(
        string='Module Count',
        compute='_compute_saas_module_count',
        help='Number of modules included in this product.',
    )

    # ========== Repo fields (for products with saas_source='custom') ==========
    repo_url = fields.Char(
        string='Repository URL',
        help='Git clone URL (HTTPS). e.g. https://github.com/user/repo.git',
    )
    repo_branch = fields.Char(
        string='Branch',
        default='main',
    )
    repo_github_token = fields.Char(
        string='GitHub Token',
        help='Personal access token for private repositories.',
        copy=False,
        groups='base.group_system',
    )
    repo_addons_subdir = fields.Char(
        string='Addons Subdirectory',
        help='Subdirectory inside the repo containing addons. '
             'Leave empty if addons are at the root.',
    )
    repo_state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('cloned', 'Cloned'),
            ('error', 'Error'),
        ],
        string='Repo Status',
        readonly=True,
    )
    repo_last_pull = fields.Datetime(
        string='Last Pull',
        readonly=True,
    )
    repo_error = fields.Text(
        string='Repo Error',
        readonly=True,
    )

    _sql_constraints = [
        (
            'unique_technical_name_per_version',
            'UNIQUE(technical_name, saas_odoo_version_id)',
            'Technical name must be unique per Odoo version.',
        ),
    ]

    def unlink(self):
        """When deleting a product, also delete its linked version repo and custom modules."""
        if self.env.context.get('skip_repo_cleanup'):
            return super().unlink()

        repos_to_delete = self.env['saas.version.repo']
        modules_to_delete = self.env['product.template']
        for rec in self:
            if rec.saas_type == 'product' and rec.saas_source_repo_id:
                repo = rec.saas_source_repo_id
                repos_to_delete |= repo
                # Collect custom modules sourced from this repo
                modules_to_delete |= self.env['product.template'].search([
                    ('saas_source_repo_id', '=', repo.id),
                    ('saas_type', '=', 'module'),
                    ('id', 'not in', self.ids),
                ])
        # Delete custom modules first (they reference the repo)
        if modules_to_delete:
            modules_to_delete.with_context(skip_repo_cleanup=True).unlink()
        res = super().unlink()
        # Delete repos (triggers server cleanup + instance restart)
        if repos_to_delete:
            repos_to_delete.unlink()
        return res

    @api.depends('saas_module_ids')
    def _compute_saas_module_count(self):
        for rec in self:
            rec.saas_module_count = len(rec.saas_module_ids)

    # ========== Repo Actions ==========

    def _ensure_repo(self):
        """Ensure a saas.version.repo record exists for this product and sync fields."""
        self.ensure_one()
        if not self.repo_url:
            raise UserError(_("Repository URL is required."))
        if not self.saas_odoo_version_id:
            raise UserError(_("Odoo Version is required."))

        VersionRepo = self.env['saas.version.repo']
        repo = self.saas_source_repo_id

        vals = {
            'version_id': self.saas_odoo_version_id.id,
            'repo_url': self.repo_url,
            'branch': self.repo_branch or 'main',
            'github_token': self.sudo().repo_github_token or False,
            'addons_subdir': self.repo_addons_subdir or False,
        }

        if repo:
            repo.write(vals)
        else:
            vals['product_id'] = self.id
            repo = VersionRepo.create(vals)
            self.saas_source_repo_id = repo

        return repo

    def _sync_from_repo(self, repo):
        """Sync state fields from the repo record back to the product."""
        self.repo_state = repo.state
        self.repo_last_pull = repo.last_pull
        self.repo_error = repo.error_message

    def action_clone_repo(self):
        """Clone the repository on the server (async)."""
        self.ensure_one()
        self.saas_source = 'custom'
        self._ensure_repo()
        run_in_background(
            self, '_do_clone_repo',
            error_method='_on_repo_background_error',
            thread_name='saas_clone_repo_%s' % self.id,
        )

    def _do_clone_repo(self):
        """Clone repo (runs in background thread)."""
        self.ensure_one()
        repo = self.saas_source_repo_id
        if not repo:
            raise UserError(_("No repository linked."))
        repo.action_clone_repo()
        self._sync_from_repo(repo)

    def action_pull_repo(self):
        """Git pull the repository (async)."""
        self.ensure_one()
        repo = self.saas_source_repo_id
        if not repo:
            raise UserError(_("No repository linked to this product."))
        run_in_background(
            self, '_do_pull_repo',
            error_method='_on_repo_background_error',
            thread_name='saas_pull_repo_%s' % self.id,
        )

    def _do_pull_repo(self):
        """Pull repo (runs in background thread)."""
        self.ensure_one()
        repo = self.saas_source_repo_id
        repo.action_pull_repo()
        self._sync_from_repo(repo)

    def _on_repo_background_error(self, exception):
        """Handle background repo operation failure."""
        self.repo_state = 'error'
        self.repo_error = str(exception)

    def action_fetch_repo_modules(self):
        """Scan the cloned repo for modules and populate this product (async)."""
        self.ensure_one()
        repo = self.saas_source_repo_id
        if not repo or repo.state != 'cloned':
            raise UserError(_("Repository must be cloned first."))
        run_in_background(
            self, '_do_fetch_repo_modules',
            error_method='_on_repo_background_error',
            thread_name='saas_fetch_repo_modules_%s' % self.id,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Fetching Modules"),
                'message': _("Module fetch is running in the background. Please refresh to see results."),
                'type': 'info',
                'sticky': False,
            },
        }

    def _do_fetch_repo_modules(self):
        """Scan the cloned repo for modules (runs in background thread)."""
        self.ensure_one()
        repo = self.saas_source_repo_id
        if not repo or repo.state != 'cloned':
            raise UserError(_("Repository must be cloned first."))

        version = self.saas_odoo_version_id
        server = version._get_container_server()
        image = version._get_docker_image()

        host_path = repo._get_remote_repo_path(server)
        mount_path = '/mnt/version-repos/%s' % repo._get_repo_dir_name()
        addons_path = mount_path
        if repo.addons_subdir:
            addons_path = '%s/%s' % (mount_path, repo.addons_subdir.strip('/'))

        volume_args = ' -v %s:%s:ro' % (host_path, mount_path)

        # Scan only the repo path for application modules
        scan_script = (
            "import ast, os, sys\n"
            "paths = ['%(addons_path)s']\n"
            "for p in paths:\n"
            "  if not os.path.isdir(p): continue\n"
            "  for d in sorted(os.listdir(p)):\n"
            "    mf = os.path.join(p, d, '__manifest__.py')\n"
            "    if not os.path.isfile(mf): continue\n"
            "    try:\n"
            "      m = ast.literal_eval(open(mf).read())\n"
            "    except Exception: continue\n"
            "    if not m.get('application'): continue\n"
            "    sys.stdout.write("
            "d + '|||' + m.get('name', d) + '|||' "
            "+ m.get('summary', '').replace('\\\\n', ' ').replace('\\n', ' ') + '|||' "
            "+ m.get('category', '') + '|||' "
            "+ m.get('author', '') + '|||' "
            "+ ','.join(m.get('depends', [])) + '\\n')\n"
        ) % {'addons_path': addons_path}

        cmd = "docker run --rm%s %s python3 -c \"%s\" 2>/dev/null" % (
            volume_args, image, scan_script,
        )

        with server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(cmd, timeout=120)
            if exit_code != 0:
                raise UserError(
                    _("Failed to scan repo modules:\n%s") % stderr
                )

        ProductTemplate = self.env['product.template']
        existing = {
            m.technical_name: m
            for m in ProductTemplate.search([
                ('saas_source_repo_id', '=', repo.id),
                ('saas_type', '=', 'module'),
            ])
        }
        found_names = set()
        deps_map = {}

        for line in stdout.strip().splitlines():
            line = line.strip()
            if not line or '|||' not in line:
                continue
            parts = line.split('|||', 5)
            technical_name = parts[0].strip()
            display_name = parts[1].strip() if len(parts) > 1 else technical_name
            summary = parts[2].strip() if len(parts) > 2 else ''
            category = parts[3].strip() if len(parts) > 3 else ''
            author = parts[4].strip() if len(parts) > 4 else ''
            depends_str = parts[5].strip() if len(parts) > 5 else ''
            found_names.add(technical_name)

            if depends_str:
                deps_map[technical_name] = [
                    d.strip() for d in depends_str.split(',') if d.strip()
                ]

            vals = {
                'name': display_name,
                'description_sale': summary,
                'saas_author': author,
                'saas_source': 'custom',
                'saas_source_repo_id': repo.id,
            }

            if technical_name in existing:
                existing[technical_name].write(vals)
            else:
                vals.update({
                    'technical_name': technical_name,
                    'saas_odoo_version_id': version.id,
                    'saas_type': 'module',
                    'type': 'service',
                })
                ProductTemplate.create(vals)

        # Remove modules from this repo that no longer exist
        to_remove = ProductTemplate.search([
            ('saas_source_repo_id', '=', repo.id),
            ('saas_type', '=', 'module'),
            ('technical_name', 'not in', list(found_names)),
        ])
        if to_remove:
            to_remove.unlink()

        # Update this product's included modules
        repo_modules = ProductTemplate.search([
            ('saas_source_repo_id', '=', repo.id),
            ('saas_type', '=', 'module'),
        ])
        self.saas_module_ids = [(6, 0, repo_modules.ids)]

        # Resolve dependencies among version modules
        all_version_modules = {
            m.technical_name: m
            for m in version.module_ids
        }
        for tech_name, dep_names in deps_map.items():
            if tech_name not in all_version_modules:
                continue
            dep_records = ProductTemplate.browse()
            for dep_name in dep_names:
                if dep_name in all_version_modules:
                    dep_records |= all_version_modules[dep_name]
            all_version_modules[tech_name].saas_dependency_ids = dep_records

        # Fetch icons for new modules
        self._fetch_repo_module_icons(server, image, volume_args, addons_path)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Modules Fetched"),
                'message': _("%d modules found in %s.") % (
                    len(found_names), self.name,
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def _fetch_repo_module_icons(self, server, image, volume_args, addons_path):
        """Fetch icons for modules in this repo that don't have one yet."""
        self.ensure_one()
        modules = self.saas_module_ids.filtered(lambda m: not m.image_1920)
        if not modules:
            return

        tech_names = [m.technical_name for m in modules]
        existing_map = {m.technical_name: m for m in modules}

        icon_script = (
            "import base64, os, sys; "
            "paths = ['%(addons_path)s']; "
            "modules = %(modules)r; "
            "["
            "  sys.stdout.write(m + '|||' + base64.b64encode("
            "    open(os.path.join(p, m, 'static', 'description', 'icon.png'), 'rb').read()"
            "  ).decode() + '\\n') "
            "  for p in paths if os.path.isdir(p) "
            "  for m in modules "
            "  if os.path.isfile(os.path.join(p, m, 'static', 'description', 'icon.png'))"
            "]"
        ) % {'addons_path': addons_path, 'modules': tech_names}

        cmd = "docker run --rm%s %s python3 -c \"%s\" 2>/dev/null" % (
            volume_args, image, icon_script,
        )

        with server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(cmd, timeout=300)

        if exit_code != 0:
            _logger.warning("Failed to fetch repo module icons: %s", stderr[:500])
            return

        for line in stdout.strip().splitlines():
            if '|||' not in line:
                continue
            tech_name, icon_b64 = line.split('|||', 1)
            tech_name = tech_name.strip()
            icon_b64 = icon_b64.strip()
            if tech_name in existing_map and icon_b64:
                try:
                    existing_map[tech_name].image_1920 = icon_b64
                except Exception:
                    _logger.warning("Failed to set icon for module %s", tech_name)
