from odoo import fields, models


class SaasInstanceModuleLine(models.Model):
    _name = 'saas.instance.module.line'
    _description = 'Instance Module Installation Line'
    _order = 'sequence, id'

    sequence = fields.Integer(
        default=10,
        help='Controls the order in which modules are installed.',
    )
    instance_id = fields.Many2one(
        'saas.instance',
        string='Instance',
        required=True,
        ondelete='cascade',
        help='The SaaS instance this installation line belongs to.',
    )
    odoo_version_id = fields.Many2one(
        related='instance_id.odoo_version_id',
        store=True,
        help='Odoo version of the parent instance (used for domain filtering).',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        domain="[('saas_type', '=', 'product'), ('saas_odoo_version_id', '=', odoo_version_id)]",
        help='Product to install. All modules in the product will be installed together.',
    )
    module_id = fields.Many2one(
        'product.product',
        string='Module',
        domain="[('saas_type', '=', 'module'), ('saas_odoo_version_id', '=', odoo_version_id)]",
        help='Individual module to install on the instance.',
    )
    product_image = fields.Image(
        related='product_id.image_128',
        string='Product Image',
    )
    module_image = fields.Image(
        related='module_id.image_128',
        string='Module Image',
    )
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('installed', 'Installed'),
            ('failed', 'Failed'),
        ],
        string='Status',
        default='pending',
        readonly=True,
        help='Current installation status: Pending (queued), Installed (success), or Failed.',
    )
    module_source = fields.Selection(
        related='module_id.saas_source',
        string='Source',
        readonly=True,
    )
    log = fields.Text(
        string='Log',
        readonly=True,
        help='Detailed output captured during the installation attempt (populated on failure).',
    )

    def _get_all_technical_names(self):
        """Return a set of all technical module names for this line including dependencies."""
        self.ensure_one()
        names = set()

        if self.product_id:
            for mod in self.product_id.product_tmpl_id.saas_module_ids:
                names.add(mod.technical_name)
                for dep in mod.saas_dependency_ids:
                    names.add(dep.technical_name)
        elif self.module_id:
            tmpl = self.module_id.product_tmpl_id
            names.add(tmpl.technical_name)
            for dep in tmpl.saas_dependency_ids:
                names.add(dep.technical_name)

        return names
