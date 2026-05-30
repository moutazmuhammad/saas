from odoo import api, models

# ----------------------------------------------------------------------
# Pricing engine — the SINGLE source of truth for every price the
# platform quotes (slider preview, configure, checkout, plan creation,
# upgrade/downgrade). See docs/pricing-system-execution-plan.md.
#
# STEP S1 (this file): the engine exists and reproduces the CURRENT
# linear price EXACTLY. It is additive — no caller is repointed yet
# (that is S2). Future capabilities (cost floor, region multiplier,
# add-ons, named tiers) are wired in as no-ops here so that, with their
# config defaults, compute() returns numbers identical to today.
#
# Behaviour-neutral guarantees in S1:
#   * floor rate defaults to 0  -> max(base, 0) == base
#   * region defaults to x1.0   -> no region scaling (no region model yet)
#   * addon total defaults to 0 -> no add-on model referenced yet
# ----------------------------------------------------------------------


class SaasPricingEngine(models.AbstractModel):
    _name = 'saas.pricing.engine'
    _description = 'SaaS Pricing Engine (single source of truth)'

    # ------------------------------------------------------------------
    # Config loading — same keys/defaults the controllers use today, so
    # the engine output matches the existing inline formulas exactly.
    # ``kind`` selects the rate set: 'hosting' or 'services'.
    # ------------------------------------------------------------------
    def _rate_config(self, kind):
        icp = self.env['ir.config_parameter'].sudo()
        get = icp.get_param
        if kind == 'hosting':
            p = 'saas_master.hosting_'
            cfg = {
                'worker_price': float(get('saas_master.hosting_worker_price', '10.0')),
                'storage_price_per_gb': float(get('saas_master.hosting_storage_price_per_gb', '0.3')),
                'min_workers': int(get('saas_master.hosting_min_workers', '2')),
                'max_workers': int(get('saas_master.hosting_max_workers', '8')),
                'min_storage': int(get('saas_master.hosting_min_storage', '5')),
                'max_storage': int(get('saas_master.hosting_max_storage', '200')),
                'yearly_discount_pct': int(get('saas_master.hosting_yearly_discount_pct', '20')),
                # Cost floor (S3 will surface these in Settings). Default 0
                # => no-op in S1, so prices are unchanged.
                'worker_floor': float(get('saas_master.hosting_worker_floor', '0')),
                'storage_floor': float(get('saas_master.hosting_storage_floor', '0')),
            }
        else:  # 'services' (custom plan builder)
            cfg = {
                'worker_price': float(get('saas_master.worker_price', '15.0')),
                'storage_price_per_gb': float(get('saas_master.storage_price_per_gb', '0.5')),
                'min_workers': int(get('saas_master.custom_plan_min_workers', '2')),
                'max_workers': int(get('saas_master.custom_plan_max_workers', '8')),
                'min_storage': int(get('saas_master.custom_plan_min_storage', '5')),
                'max_storage': int(get('saas_master.custom_plan_max_storage', '200')),
                'yearly_discount_pct': int(get('saas_master.custom_plan_yearly_discount_pct', '20')),
                'worker_floor': float(get('saas_master.worker_floor', '0')),
                'storage_floor': float(get('saas_master.storage_floor', '0')),
            }
        cfg['currency'] = self.env.company.currency_id.name or 'USD'
        return cfg

    # ------------------------------------------------------------------
    # No-op hooks for future steps. Implemented here so compute() reads
    # cleanly; they intentionally do nothing in S1.
    # ------------------------------------------------------------------
    def _region_multiplier(self, region):
        """S7: per-region price multiplier. No region model yet -> 1.0."""
        return 1.0

    def _cost_floor(self, cfg, workers, storage):
        """S3/S4: cost-derived price floor. Default rates 0 -> 0.0."""
        return (workers * cfg['worker_floor']) + (storage * cfg['storage_floor'])

    def _addons_total(self, kind, addon_codes):
        """S5: sum configured add-on monthly prices. No add-on model yet
        -> 0.0 (and no caller passes addon_codes in S1)."""
        return 0.0

    @staticmethod
    def _clamp(value, lo, hi):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = lo
        return max(lo, min(value, hi))

    # ------------------------------------------------------------------
    # THE single price computation. Everything must call this.
    # ------------------------------------------------------------------
    @api.model
    def compute(self, kind, workers, storage, billing='monthly',
                addon_codes=(), region=None):
        """Return one fully-resolved price quote.

        Args:
            kind: 'hosting' or 'services' (selects the rate set).
            workers, storage: requested config (clamped to plan limits).
            billing: 'monthly' or 'yearly'.
            addon_codes: iterable of add-on codes (S5; ignored in S1).
            region: region record/id (S7; multiplier is 1.0 in S1).

        Returns a dict (superset of the current ``_price`` shape so
        callers can be repointed in S2 without changing their output):
            workers, storage, billing, monthly, yearly, total,
            monthly_equivalent, yearly_savings, savings_percent,
            currency, region_factor, floored, limits, breakdown.
        """
        cfg = self._rate_config(kind)
        workers = self._clamp(workers, cfg['min_workers'], cfg['max_workers'])
        storage = self._clamp(storage, cfg['min_storage'], cfg['max_storage'])

        base = (workers * cfg['worker_price']) + (storage * cfg['storage_price_per_gb'])
        floor = self._cost_floor(cfg, workers, storage)
        floored = floor > base
        region_factor = self._region_multiplier(region)

        resource_monthly = max(base, floor) * region_factor
        addons_monthly = self._addons_total(kind, addon_codes)
        monthly = resource_monthly + addons_monthly

        discount = cfg['yearly_discount_pct'] / 100.0
        yearly = monthly * 12 * (1 - discount)
        yearly_savings = (monthly * 12) - yearly
        is_yearly = billing == 'yearly'

        return {
            'workers': workers,
            'storage': storage,
            'billing': 'yearly' if is_yearly else 'monthly',
            'monthly': round(monthly, 2),
            'yearly': round(yearly, 2),
            'total': round(yearly if is_yearly else monthly, 2),
            'monthly_equivalent': round(yearly / 12 if is_yearly else monthly, 2),
            'yearly_savings': round(yearly_savings, 2),
            'savings_percent': int(cfg['yearly_discount_pct']),
            'currency': cfg['currency'],
            'region_factor': region_factor,
            'floored': floored,
            'limits': {
                'workers': {'min': cfg['min_workers'], 'max': cfg['max_workers']},
                'storage': {'min': cfg['min_storage'], 'max': cfg['max_storage']},
            },
            'breakdown': {
                'base': round(base, 2),
                'floor': round(floor, 2),
                'resource_monthly': round(resource_monthly, 2),
                'addons_monthly': round(addons_monthly, 2),
            },
        }

    @api.model
    def monthly_price(self, kind, workers, storage, region=None):
        """Convenience: just the monthly figure used when stamping a
        ``saas.plan.price`` at custom-plan creation (S2 will use this)."""
        return self.compute(
            kind, workers, storage, billing='monthly', region=region,
        )['monthly']
