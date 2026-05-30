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
                # Minimum monthly charge (P1). Floor on the FINAL monthly
                # total so a tiny config still covers fixed business costs
                # (payment fees, support, CAC). Default 0 => no-op.
                'minimum_monthly': float(get('saas_master.hosting_minimum_monthly', '0')),
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
                'minimum_monthly': float(get('saas_master.minimum_monthly', '0')),
            }
        cfg['currency'] = self.env.company.currency_id.name or 'USD'
        return cfg

    # ------------------------------------------------------------------
    # No-op hooks for future steps. Implemented here so compute() reads
    # cleanly; they intentionally do nothing in S1.
    # ------------------------------------------------------------------
    def _region_multiplier(self, region):
        """Per-region price multiplier for the compute+storage portion.
        ``region`` may be a saas.region record, an id, or falsy. Unknown /
        falsy -> 1.0 (behaviour-neutral; legacy instances have no region)."""
        if not region:
            return 1.0
        try:
            if isinstance(region, int):
                region = self.env['saas.region'].sudo().browse(region)
            if region and region.exists() and region.price_multiplier:
                return region.price_multiplier
        except Exception:
            return 1.0
        return 1.0

    def _cost_floor(self, cfg, workers, storage):
        """S3/S4: cost-derived price floor. Default rates 0 -> 0.0."""
        return (workers * cfg['worker_floor']) + (storage * cfg['storage_floor'])

    def _tier_floor(self, kind, workers, storage):
        """Tier protection (S4 + P2 soft floor): when the 'custom >= nearest
        tier' policy is ON, a custom config may not be priced below the
        highest public-tier monthly price whose resources it fully contains
        (workers AND storage both >= the tier's) — minus a configurable
        buffer.

        ``tier_floor_buffer_pct`` (default 0 = the original hard floor)
        lets a custom config sit up to N% under the nearest tier, so e.g.
        a 3w/95GB config can be a bit cheaper than the 4w/100GB Pro tier
        instead of pinned to it (which felt rigged). The tier is still the
        better value per resource. Returns 0.0 when the policy is OFF
        (default) or no tier qualifies -> no-op."""
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param('saas_master.custom_min_is_nearest_tier', 'False') != 'True':
            return 0.0
        tiers = self.env['saas.plan'].sudo().search([
            ('is_public_tier', '=', True),
            ('workers', '<=', workers),
            ('storage_limit', '<=', storage),
        ])
        best = 0.0
        for t in tiers:
            t_kind = 'hosting' if any(
                p.is_hosting for p in t.saas_product_ids
            ) else 'services'
            if t_kind == kind and t.price > best:
                best = t.price
        if not best:
            return 0.0
        try:
            buffer_pct = float(icp.get_param(
                'saas_master.tier_floor_buffer_pct', '0') or 0)
        except (TypeError, ValueError):
            buffer_pct = 0.0
        # Clamp to a sane 0..100 range; the floor is the tier price less
        # the allowed buffer.
        buffer_pct = min(max(buffer_pct, 0.0), 100.0)
        return best * (1.0 - buffer_pct / 100.0)

    def _addons_total(self, kind, addon_codes):
        """Sum effective monthly prices of the given add-on codes that
        apply to ``kind``. Empty/none -> 0.0 (behaviour-neutral)."""
        if not addon_codes:
            return 0.0
        return self.env['saas.addon']._sum_prices(kind, addon_codes)

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
                addon_codes=(), region=None, support_code=None):
        """Return one fully-resolved price quote.

        Args:
            kind: 'hosting' or 'services' (selects the rate set).
            workers, storage: requested config (clamped to plan limits).
            billing: 'monthly' or 'yearly'.
            addon_codes: iterable of add-on codes (S5; ignored in S1).
            region: region record/id (S7; multiplier is 1.0 in S1).
            support_code: optional saas.support.plan code (P3). A flat
                monthly fee added after infra/region; 0 if None/unknown.

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
        cost_floor = self._cost_floor(cfg, workers, storage)
        tier_floor = self._tier_floor(kind, workers, storage)
        floor = max(cost_floor, tier_floor)
        floored = floor > base
        region_factor = self._region_multiplier(region)

        resource_monthly = max(base, floor) * region_factor
        addons_monthly = self._addons_total(kind, addon_codes)
        # Support plan (P3): flat monthly fee, NOT scaled by region, added
        # after infra. 0 when no plan / the free default / unknown code.
        support_monthly = self.env['saas.support.plan']._price_for_code(support_code)
        pre_minimum = resource_monthly + addons_monthly + support_monthly

        # Minimum monthly charge (P1): the final total never drops below
        # the configured floor — small configs still cover fixed business
        # costs. Applied AFTER add-ons (so add-ons count toward the
        # minimum, never on top of it). Default 0 => no-op.
        minimum_monthly = cfg.get('minimum_monthly', 0.0) or 0.0
        monthly = max(pre_minimum, minimum_monthly)
        minimum_applied = minimum_monthly > pre_minimum

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
            'minimum_applied': minimum_applied,
            'limits': {
                'workers': {'min': cfg['min_workers'], 'max': cfg['max_workers']},
                'storage': {'min': cfg['min_storage'], 'max': cfg['max_storage']},
            },
            'breakdown': {
                'base': round(base, 2),
                'floor': round(floor, 2),
                'cost_floor': round(cost_floor, 2),
                'tier_floor': round(tier_floor, 2),
                'resource_monthly': round(resource_monthly, 2),
                'addons_monthly': round(addons_monthly, 2),
                # P3: flat support-plan fee (not region-scaled).
                'support_monthly': round(support_monthly, 2),
                # P1: the total before the minimum-monthly floor, and the
                # minimum that was enforced (0 = off). monthly == max of
                # these two.
                'pre_minimum': round(pre_minimum, 2),
                'minimum_monthly': round(minimum_monthly, 2),
                # Per-resource split (pre-floor, pre-region) — kept so the
                # legacy display routes can show the same breakdown they
                # do today. Frontend will stop surfacing these in S8.
                'workers_cost': round(workers * cfg['worker_price'], 2),
                'storage_cost': round(storage * cfg['storage_price_per_gb'], 2),
            },
        }

    @api.model
    def storage_overage(self, total_bytes, plan_storage_limit_gb):
        """Monthly charge for storage above the plan allowance.

        Block-based when configured (storage_block_gb>0 AND
        storage_block_price>0) — storage above the limit is billed in
        whole blocks. Otherwise falls back to the legacy per-GB rate
        (``extra_storage_price_per_gb``), so this is behaviour-neutral
        until a block price is set. Returns
        ``{mode, over_gb, blocks?, charge}``.
        """
        import math
        icp = self.env['ir.config_parameter'].sudo()
        limit_gb = plan_storage_limit_gb or 0
        if limit_gb <= 0:
            return {'mode': 'none', 'over_gb': 0, 'charge': 0.0}
        limit_bytes = int(round(limit_gb * (1024 ** 3)))
        if (total_bytes or 0) <= limit_bytes:
            return {'mode': 'none', 'over_gb': 0, 'charge': 0.0}
        over_gb = math.ceil((total_bytes - limit_bytes) / (1024 ** 3))
        block_gb = int(icp.get_param('saas_master.storage_block_gb', '0') or 0)
        block_price = float(icp.get_param('saas_master.storage_block_price', '0') or 0)
        if block_gb > 0 and block_price > 0:
            blocks = math.ceil(over_gb / block_gb)
            return {'mode': 'block', 'over_gb': over_gb, 'blocks': blocks,
                    'charge': round(blocks * block_price, 2)}
        per_gb = float(icp.get_param('saas_master.extra_storage_price_per_gb', '0') or 0)
        return {'mode': 'per_gb', 'over_gb': over_gb,
                'charge': round(over_gb * per_gb, 2)}

    @api.model
    def monthly_price(self, kind, workers, storage, region=None):
        """Convenience: just the monthly figure used when stamping a
        ``saas.plan.price`` at custom-plan creation (S2 will use this)."""
        return self.compute(
            kind, workers, storage, billing='monthly', region=region,
        )['monthly']
