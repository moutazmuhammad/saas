from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class SaasPlan(models.Model):
    _name = 'saas.plan'
    _description = 'SaaS Plan'
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Plan Name', required=True)
    is_trial_plan = fields.Boolean(
        string='Trial Plan',
        default=False,
        help='If checked, this plan is available for free trials only '
             'and will not generate invoices.',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        help='Sellable product linked to this plan. '
             'The product price is used when creating sale orders.',
    )
    price = fields.Float(
        string='Price',
        compute='_compute_price',
        inverse='_inverse_price',
        help='Sale price from the linked product.',
    )
    currency_id = fields.Many2one(
        related='product_id.currency_id',
        string='Currency',
    )
    billing_period = fields.Selection(
        [
            ('monthly', 'Monthly'),
            ('yearly', 'Yearly'),
        ],
        string='Billing Period',
        default='monthly',
        help='How often the customer is invoiced for this plan.',
    )
    cpu_limit = fields.Float(
        string='CPU Limit',
        default=1.0,
        help='CPU limit for the Docker container (e.g. 0.5 = half a core, 2.0 = two cores).',
    )
    ram_limit = fields.Char(
        string='RAM Limit',
        default='1g',
        help='RAM limit for the Docker container (e.g. 512m, 1g, 2g).',
    )
    storage_limit = fields.Float(
        string='Storage Limit (GB)',
        default=5.0,
        help='Maximum total storage (container disk + database) in GB. '
             'Instances exceeding this limit will be suspended.',
    )
    max_backups = fields.Integer(
        string='Max Backups',
        default=7,
        help='Maximum number of backups to keep per instance. '
             'Older backups are automatically deleted during cleanup.',
    )
    instance_count = fields.Integer(
        string='Instances',
        compute='_compute_instance_count',
    )

    # ========== Feature Flags ==========
    feature_api_access = fields.Boolean(
        string='API / XML-RPC Access',
        default=False,
        help='Allow external API access to the Odoo instance.',
    )
    feature_custom_domain = fields.Boolean(
        string='Custom Domain',
        default=False,
        help='Allow mapping a custom domain to the instance.',
    )
    feature_custom_modules = fields.Boolean(
        string='Custom Modules',
        default=False,
        help='Allow installing custom Git repositories on the instance.',
    )
    max_users = fields.Integer(
        string='Max Users',
        default=0,
        help='Maximum number of internal users allowed. 0 = unlimited.',
    )

    # ========== Dunning / Grace ==========
    grace_period_days = fields.Integer(
        string='Grace Period (Days)',
        default=7,
        help='Number of days after invoice due date before the instance '
             'is automatically suspended for non-payment.',
    )

    @api.depends('product_id', 'product_id.list_price')
    def _compute_price(self):
        for rec in self:
            rec.price = rec.product_id.list_price if rec.product_id else 0.0

    def _inverse_price(self):
        for rec in self:
            if rec.product_id:
                rec.product_id.list_price = rec.price

    def _compute_instance_count(self):
        data = self.env['saas.instance']._read_group(
            [('plan_id', 'in', self.ids)],
            ['plan_id'],
            ['__count'],
        )
        counts = {plan.id: count for plan, count in data}
        for rec in self:
            rec.instance_count = counts.get(rec.id, 0)

    def _get_billing_interval(self):
        """Return a relativedelta for the billing period."""
        self.ensure_one()
        if self.billing_period == 'yearly':
            return relativedelta(years=1)
        return relativedelta(months=1)
