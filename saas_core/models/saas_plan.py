from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaasPlan(models.Model):
    _name = 'saas.plan'
    _description = 'SaaS Plan'
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Plan Name', required=True)
    saas_product_ids = fields.Many2many(
        'saas.product',
        'saas_plan_product_rel',
        'plan_id',
        'product_id',
        string='Services',
        help='Services this plan is available for. '
             'Leave empty to make the plan available for all services.',
    )
    is_trial_plan = fields.Boolean(
        string='Trial Plan',
        default=False,
        help='If checked, this plan is available for free trials only '
             'and will not generate invoices.',
    )
    is_custom = fields.Boolean(
        string='Custom Plan',
        default=False,
        help='Auto-generated plans from the custom plan builder. '
             'These are hidden from the public pricing page.',
    )

    # ========== Public Tier (configurable named plans) ==========
    is_public_tier = fields.Boolean(
        string='Public Tier',
        default=False,
        help='Show this plan as a named tier card (e.g. Starter / Pro / '
             'Business) on the public pricing & configure pages. '
             'Custom (slider-built) plans leave this off.',
    )
    is_recommended = fields.Boolean(
        string='Recommended Tier',
        default=False,
        help='Highlight this tier as the recommended / default choice on '
             'the pricing cards.',
    )
    badge = fields.Char(
        string='Tier Badge',
        help='Optional short badge shown on the tier card '
             '(e.g. "Most popular", "Best value").',
    )

    # ========== Pricing ==========
    # For NAMED tiers the price is derived automatically from the resources
    # (the same linear rate the custom builder uses) minus ``discount_amount``
    # — operators tune the discount, not the raw price. Custom plans get their
    # price from the pricing engine at creation. See ``_auto_price_vals``.
    price = fields.Float(
        string='Monthly Price',
        default=0.0,
        help='Monthly recurring price. For named tiers this is computed '
             'automatically from the resources minus the discount; edit the '
             'discount, not this field.',
    )
    yearly_price = fields.Float(
        string='Yearly Price',
        default=0.0,
        help='Yearly recurring price. Derived from the monthly price and the '
             'global yearly discount for named tiers.',
    )
    discount_amount = fields.Float(
        string='Plan Discount ($/mo)',
        default=0.0,
        help='Fixed amount knocked off this named tier\'s automatic '
             'resource-based monthly price, to make it a "good deal" '
             '(e.g. 5 = $5/mo off). 0 = full resource price. The price is '
             'never allowed below cost. Ignored for custom and trial plans.',
    )
    yearly_discount_pct = fields.Float(
        string='Yearly Discount %',
        compute='_compute_yearly_discount_pct',
        help='Percentage saved when choosing yearly vs monthly billing.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )

    # ========== Resource Limits ==========
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
    workers = fields.Integer(
        string='Odoo Workers',
        default=2,
        help='Number of Odoo worker processes. '
             'Set to 0 for development/testing (threaded mode). '
             'Recommended: 1 per 2 CPU cores.',
    )
    storage_limit = fields.Float(
        string='Storage Limit (GB)',
        default=5.0,
        help='Maximum total storage (container disk + database) in GB. '
             'Instances exceeding this limit will be suspended. '
             'Also used for downgrade eligibility (blocked if current '
             'usage >= 75%% of target plan limit).',
    )
    max_backups = fields.Integer(
        string='Max Backups',
        default=7,
        help='Maximum number of backups to keep per instance. '
             'Older backups are automatically deleted during cleanup. '
             'Set to 0 to disable backups (forced to 0 for trial plans).',
    )
    instance_count = fields.Integer(
        string='Instances',
        compute='_compute_instance_count',
    )
    recommended_users = fields.Integer(
        string='Recommended Users',
        default=0,
        help='Recommended number of internal users for this plan. '
             'Displayed as a guideline on the pricing page. 0 = not shown.',
    )

    # ========== Dunning / Grace ==========
    grace_period_days = fields.Integer(
        string='Grace Period (Days)',
        default=7,
        help='Number of days after invoice due date before the instance '
             'is automatically suspended for non-payment.',
    )

    @api.onchange('is_trial_plan')
    def _onchange_is_trial_plan(self):
        """Reset paid-plan settings when toggling Trial Plan in the form."""
        for rec in self:
            if rec.is_trial_plan:
                rec.price = 0.0
                rec.yearly_price = 0.0
                rec.max_backups = 0

    @api.constrains('is_trial_plan', 'price', 'yearly_price', 'max_backups')
    def _check_trial_plan_zero(self):
        for rec in self:
            if rec.is_trial_plan and (
                rec.price or rec.yearly_price or rec.max_backups
            ):
                raise UserError(_(
                    "Trial plans must have price = 0, yearly_price = 0 and "
                    "max_backups = 0. Plan: %s"
                ) % rec.name)

    @api.constrains('price', 'yearly_price', 'workers', 'storage_limit',
                    'is_trial_plan', 'saas_product_ids')
    def _check_price_floor(self):
        """A plan's price may not fall below the engine's cost-derived
        floor for its resources (margin protection / abuse prevention).

        Checks BOTH the monthly price (>= cost floor) and the yearly
        price (>= 12 months of cost) — a yearly figure below 12× the
        monthly floor would still sell the whole year at a loss even
        though the monthly number looks fine. Skipped for trials and
        when no floor is configured (floor 0 => no constraint, i.e.
        behaviour-neutral by default)."""
        engine = self.env['saas.pricing.engine']
        for rec in self:
            if rec.is_trial_plan or not rec.workers:
                continue
            kind = 'hosting' if any(
                p.is_hosting for p in rec.saas_product_ids
            ) else 'services'
            cfg = engine._rate_config(kind)
            floor = engine._cost_floor(cfg, rec.workers, int(rec.storage_limit or 0))
            if floor <= 0:
                continue
            if rec.price + 0.01 < floor:
                raise ValidationError(_(
                    "Plan '%s': monthly price %.2f is below the cost floor "
                    "%.2f for %d workers / %d GB. Raise the price, or lower "
                    "the cost floor in Settings."
                ) % (rec.name, rec.price, floor, rec.workers,
                     int(rec.storage_limit or 0)))
            if rec.yearly_price and rec.yearly_price + 0.01 < floor * 12:
                raise ValidationError(_(
                    "Plan '%s': yearly price %.2f is below 12 months of "
                    "cost (%.2f) for %d workers / %d GB. Raise the yearly "
                    "price, or lower the cost floor in Settings."
                ) % (rec.name, rec.yearly_price, floor * 12, rec.workers,
                     int(rec.storage_limit or 0)))

    # ========== Automatic resource-based pricing (named tiers) ==========
    def _kind(self):
        """'hosting' or 'services' — selects the rate set for this plan."""
        self.ensure_one()
        return 'hosting' if any(
            p.is_hosting for p in self.saas_product_ids
        ) else 'services'

    def _auto_price_vals(self):
        """The automatic (monthly, yearly) price for a NAMED tier: the linear
        resource rate for its workers/storage MINUS the fixed
        ``discount_amount``, never below the cost floor. Yearly applies the
        global yearly discount on top.

        This is the SINGLE pricing formula — the custom builder prices the
        same linear rate through the engine, and a custom config is capped by
        the cheapest covering tier (``_tier_ceiling``), so the card, the
        configurator and the invoice all agree."""
        self.ensure_one()
        engine = self.env['saas.pricing.engine']
        cfg = engine._rate_config(self._kind())
        storage = int(self.storage_limit or 0)
        linear = (self.workers * cfg['worker_price']) + (
            storage * cfg['storage_price_per_gb'])
        floor = engine._cost_floor(cfg, self.workers, storage)
        price = max(linear - (self.discount_amount or 0.0), floor, 0.0)
        yd = (cfg['yearly_discount_pct'] or 0) / 100.0
        return round(price, 2), round(price * 12 * (1 - yd), 2)

    @api.onchange('workers', 'storage_limit', 'discount_amount',
                  'saas_product_ids', 'is_public_tier')
    def _onchange_auto_price(self):
        """Live-fill a named tier's price from its resources in the form, so
        the operator tunes the discount and sees the resulting price."""
        for rec in self:
            if rec.is_public_tier and not rec.is_trial_plan and rec.workers:
                rec.price, rec.yearly_price = rec._auto_price_vals()

    def _sync_auto_price(self):
        """Enforce the automatic resource-based price on named tiers so the
        STORED price always equals linear - discount (floored at cost),
        regardless of what was written. Custom/trial/manual plans are left
        untouched (custom plans are priced by the engine at creation)."""
        for rec in self:
            if rec.is_public_tier and not rec.is_trial_plan and rec.workers:
                price, yearly = rec._auto_price_vals()
                if (abs(rec.price - price) > 0.005
                        or abs(rec.yearly_price - yearly) > 0.005):
                    rec.with_context(_skip_auto_price=True).write({
                        'price': price, 'yearly_price': yearly,
                    })

    @api.constrains('price', 'yearly_price', 'is_trial_plan')
    def _check_yearly_not_above_monthly_annual(self):
        """The yearly price must never exceed 12 months of the monthly
        price — otherwise the "yearly" option is more expensive than paying
        monthly (a negative discount), which the pricing card would render
        as a negative saving. Equal (= 12x monthly) is allowed (no
        discount). Skipped for trials and unpriced plans."""
        for rec in self:
            if rec.is_trial_plan or not rec.price or not rec.yearly_price:
                continue
            if rec.yearly_price > rec.price * 12 + 0.01:
                raise ValidationError(_(
                    "Plan '%s': yearly price %.2f is higher than 12 months "
                    "of the monthly price (%.2f). Yearly must be at most "
                    "12x the monthly price so it is never a worse deal than "
                    "paying monthly."
                ) % (rec.name, rec.yearly_price, rec.price * 12))

    @api.depends('price', 'yearly_price')
    def _compute_yearly_discount_pct(self):
        for rec in self:
            if rec.price > 0 and rec.yearly_price > 0:
                monthly_annual = rec.price * 12
                rec.yearly_discount_pct = round(
                    (1 - rec.yearly_price / monthly_annual) * 100
                )
            else:
                rec.yearly_discount_pct = 0

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        plans._sync_auto_price()
        return plans

    def write(self, vals):
        res = super().write(vals)
        # Re-derive a named tier's auto price whenever the inputs change — or
        # when the raw price/yearly is written directly (a tier's price is
        # operator-readonly and always overridden by the auto value).
        if not self.env.context.get('_skip_auto_price') and (
            {'workers', 'storage_limit', 'discount_amount', 'is_public_tier',
             'is_trial_plan', 'saas_product_ids', 'price', 'yearly_price'}
            & set(vals)
        ):
            self._sync_auto_price()
        return res

    def _get_price_for_period(self, period):
        """Return the price for the given billing period ('monthly' or 'yearly')."""
        self.ensure_one()
        if period == 'yearly' and self.yearly_price > 0:
            return self.yearly_price
        return self.price

    def _compute_instance_count(self):
        data = self.env['saas.instance']._read_group(
            [('plan_id', 'in', self.ids)],
            ['plan_id'],
            ['__count'],
        )
        counts = {plan.id: count for plan, count in data}
        for rec in self:
            rec.instance_count = counts.get(rec.id, 0)

    def unlink(self):
        # Block deletion if any active instances use this plan
        active_states = (
            'draft', 'pending_payment', 'paid', 'pending_provision',
            'provisioning', 'running', 'stopped', 'suspended',
        )
        for rec in self:
            count = self.env['saas.instance'].search_count([
                ('plan_id', '=', rec.id),
                ('state', 'in', active_states),
            ])
            if count:
                raise UserError(
                    _("Cannot delete plan '%s': %d active instance(s) are "
                      "still using it. Cancel or reassign them first.")
                    % (rec.name, count)
                )
        return super().unlink()

