from odoo import api, fields, models


class SaasAddon(models.Model):
    """Configurable paid add-on (e.g. Daily Snapshots).

    Add-ons are summed into a quote by the pricing engine
    (`saas.pricing.engine._addons_total`). New add-ons are created as
    records here — no code change. An add-on whose price already lives in
    Settings (Daily Snapshots → `hosting_daily_backup_price`) can point at
    that config key via ``price_config_param`` so there is a single source
    of truth and the existing billing flow is undisturbed.
    """
    _name = 'saas.addon'
    _description = 'SaaS Paid Add-on'
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(
        required=True,
        help='Stable technical code used by the pricing engine / checkout '
             '(e.g. "daily_snapshots"). Do not change once in use.',
    )
    active = fields.Boolean(default=True)
    applies_to = fields.Selection(
        [('hosting', 'Hosting only'),
         ('services', 'Services only'),
         ('both', 'Both')],
        string='Applies To', default='both', required=True,
    )
    monthly_price = fields.Float(
        string='Monthly Price', default=0.0,
        help='Flat monthly price. Ignored when "Price Config Param" is set.',
    )
    price_config_param = fields.Char(
        string='Price Config Param',
        help='Optional: read the price from this ir.config_parameter key '
             'instead of the stored monthly price — keeps a single source '
             'of truth for add-ons whose price already lives in Settings '
             '(e.g. saas_master.hosting_daily_backup_price).',
    )
    description = fields.Text()

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Add-on code must be unique.'),
    ]

    def effective_monthly_price(self):
        self.ensure_one()
        if self.price_config_param:
            try:
                return float(self.env['ir.config_parameter'].sudo().get_param(
                    self.price_config_param, '0') or 0)
            except (TypeError, ValueError):
                return 0.0
        return self.monthly_price or 0.0

    @api.model
    def _sum_prices(self, kind, codes):
        """Total effective monthly price of active add-ons in ``codes``
        that apply to ``kind``."""
        if not codes:
            return 0.0
        addons = self.sudo().search([
            ('code', 'in', list(codes)),
            ('active', '=', True),
        ])
        return sum(
            a.effective_monthly_price()
            for a in addons
            if a.applies_to in (kind, 'both')
        )
