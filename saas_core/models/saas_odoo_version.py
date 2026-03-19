import logging

from odoo import fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class SaasOdooVersion(models.Model):
    _name = 'saas.odoo.version'
    _description = 'Odoo Version'
    _order = 'name'

    name = fields.Char(
        string='Version',
        required=True,
        help='Odoo version identifier (e.g. "18.0", "17.0").',
    )
    docker_image = fields.Char(
        string='Docker Image',
        help='Docker image repository for this Odoo version (e.g. "odoo", "myregistry/odoo").',
    )
    docker_image_tag = fields.Char(
        string='Image Tag',
        help='Docker image tag (e.g. "18.0", "17.0-latest"). '
             'Combined with the image name to form the full image reference.',
    )
    nginx_template = fields.Selection(
        selection=[
            ('new', 'New (16+) — /websocket'),
            ('old', 'Old (≤15) — /longpolling'),
        ],
        string='Nginx Template',
        default='new',
        required=True,
        help='Nginx reverse proxy template to use for instances of this version. '
             'Odoo 16+ uses /websocket, older versions use /longpolling.',
    )
    module_ids = fields.One2many(
        'product.template',
        'saas_odoo_version_id',
        string='Available Modules',
        domain=[('saas_type', '=', 'module')],
        help='Odoo modules available in this version, fetched from the Docker image.',
    )
    product_ids = fields.One2many(
        'product.template',
        'saas_odoo_version_id',
        string='Bundles',
        domain=[('saas_type', '=', 'bundle')],
        help='Module bundles configured for this Odoo version.',
    )
    repo_ids = fields.One2many(
        'saas.version.repo',
        'version_id',
        string='Custom Repositories',
    )
    module_count = fields.Integer(
        string='Modules',
        compute='_compute_module_count',
        help='Total number of modules available in this version.',
    )

    def _compute_module_count(self):
        data = self.env['product.template']._read_group(
            [('saas_odoo_version_id', 'in', self.ids), ('saas_type', '=', 'module')],
            ['saas_odoo_version_id'],
            ['__count'],
        )
        counts = {version.id: count for version, count in data}
        for rec in self:
            rec.module_count = counts.get(rec.id, 0)

    def _get_container_server(self):
        """Return the first available container server or raise."""
        server = self.env['saas.container.physical.server'].search([], limit=1)
        if not server:
            raise UserError(
                _("No Docker host server available to run the Docker image.")
            )
        return server

    def _get_docker_image(self):
        """Return the full docker image:tag string."""
        self.ensure_one()
        if not self.docker_image or not self.docker_image_tag:
            raise ValidationError(
                _("Docker image and tag are required to fetch modules.")
            )
        return '%s:%s' % (self.docker_image, self.docker_image_tag)

    def action_fetch_modules(self):
        """Fetch available standard modules from the Docker image."""
        self.ensure_one()
        image = self._get_docker_image()
        server = self._get_container_server()

        scan_script = (
            "import ast, os, sys\n"
            "paths = ['/usr/lib/python3/dist-packages/odoo/addons', '/mnt/extra-addons']\n"
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
        )

        cmd = "docker run --rm %s python3 -c \"%s\" 2>/dev/null" % (image, scan_script)

        with server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(cmd, timeout=120)
            if exit_code != 0:
                raise UserError(
                    _("Failed to fetch modules from image '%s':\n%s")
                    % (image, stderr)
                )

        # Only touch standard modules — leave custom repo modules untouched
        existing = {
            m.technical_name: m
            for m in self.module_ids.filtered(
                lambda m: m.saas_source != 'custom'
            )
        }
        found_names = set()
        deps_map = {}

        ProductTemplate = self.env['product.template']

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
                deps_map[technical_name] = [d.strip() for d in depends_str.split(',') if d.strip()]

            vals = {
                'name': display_name,
                'description_sale': summary,
                'saas_author': author,
                'saas_source': 'standard',
            }

            if technical_name in existing:
                existing[technical_name].write(vals)
            else:
                vals.update({
                    'technical_name': technical_name,
                    'saas_odoo_version_id': self.id,
                    'saas_type': 'module',
                    'type': 'service',
                })
                ProductTemplate.create(vals)

        # Only remove standard modules that disappeared
        to_remove = self.module_ids.filtered(
            lambda m: m.saas_source != 'custom' and m.technical_name not in found_names
        )
        if to_remove:
            to_remove.unlink()

        # Resolve dependencies
        all_modules = {m.technical_name: m for m in self.module_ids}
        for tech_name, dep_names in deps_map.items():
            if tech_name not in all_modules:
                continue
            dep_records = ProductTemplate.browse()
            for dep_name in dep_names:
                if dep_name in all_modules:
                    dep_records |= all_modules[dep_name]
            all_modules[tech_name].saas_dependency_ids = dep_records

        self._fetch_module_icons(server, image)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Modules Fetched"),
                'message': _("%d standard modules found for %s.") % (len(found_names), image),
                'type': 'success',
                'sticky': False,
            },
        }

    def _fetch_module_icons(self, server, image):
        """Fetch module icons from the Docker image for standard modules without an image."""
        self.ensure_one()
        modules_needing_icons = self.module_ids.filtered(
            lambda m: not m.image_1920 and m.saas_source != 'custom'
        )
        if not modules_needing_icons:
            return

        tech_names = [m.technical_name for m in modules_needing_icons]
        batch_size = 100
        existing_map = {m.technical_name: m for m in modules_needing_icons}

        for i in range(0, len(tech_names), batch_size):
            batch = tech_names[i:i + batch_size]
            self._fetch_icon_batch(server, image, batch, existing_map)

    def _fetch_icon_batch(self, server, image, tech_names, existing_map):
        """Fetch icons for a batch of module technical names."""
        icon_script = (
            "import base64, os, sys; "
            "paths = ['/usr/lib/python3/dist-packages/odoo/addons', '/mnt/extra-addons']; "
            "modules = %r; "
            "["
            "  sys.stdout.write(m + '|||' + base64.b64encode("
            "    open(os.path.join(p, m, 'static', 'description', 'icon.png'), 'rb').read()"
            "  ).decode() + '\\n') "
            "  for p in paths if os.path.isdir(p) "
            "  for m in modules "
            "  if os.path.isfile(os.path.join(p, m, 'static', 'description', 'icon.png'))"
            "]"
        ) % tech_names

        cmd = "docker run --rm %s python3 -c \"%s\" 2>/dev/null" % (image, icon_script)

        with server._get_ssh_connection() as ssh:
            exit_code, stdout, stderr = ssh.execute(cmd, timeout=300)

        if exit_code != 0:
            _logger.warning("Failed to fetch module icons: %s", stderr[:500])
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
                    _logger.warning(
                        "Failed to set icon for module %s", tech_name
                    )
