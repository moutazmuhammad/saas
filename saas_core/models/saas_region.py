from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SaasRegion(models.Model):
    """A hosting region. Server cost varies by region, so each region
    carries a ``price_multiplier`` applied to the compute+storage portion
    of a quote (see ``saas.pricing.engine``). A region groups servers of
    all roles (proxy / docker / db); an instance's three servers must all
    sit in the same region (co-location — enforced in allocation, S7b).
    """
    _name = 'saas.region'
    _description = 'SaaS Region'
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(
        required=True,
        help='Stable technical code, e.g. "eu", "us-east". Do not change once in use.',
    )
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(
        string='Default Region',
        help='Region used when a customer does not pick one. Keep exactly one.',
    )
    price_multiplier = fields.Float(
        string='Price Multiplier', default=1.0,
        help='Multiplies the compute+storage portion of the price for '
             'instances in this region (server cost varies by region). '
             '1.0 = no change. Add-on prices are NOT affected.',
    )
    currency_id = fields.Many2one('res.currency')
    server_ids = fields.One2many('saas.server', 'region_id', string='Servers')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Region code must be unique.'),
    ]

    @api.constrains('is_default')
    def _check_single_default(self):
        if self.search_count([('is_default', '=', True)]) > 1:
            raise ValidationError(_("Only one region may be marked as default."))

    @api.constrains('price_multiplier')
    def _check_multiplier(self):
        for rec in self:
            if rec.price_multiplier <= 0:
                raise ValidationError(_(
                    "Region '%s': price multiplier must be greater than 0."
                ) % rec.name)

    @api.model
    def _get_default(self):
        """The region assigned when the customer doesn't choose one."""
        return self.sudo().search(
            [('active', '=', True), ('is_default', '=', True)], limit=1,
        ) or self.sudo().search(
            [('active', '=', True)], order='sequence, id', limit=1,
        )
