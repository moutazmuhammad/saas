from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPricingEngine(TransactionCase):
    """S2 invariant lock: the pricing engine is the single source of
    truth AND reproduces the legacy linear formula EXACTLY.

    If this passes, repointing the controllers to the engine is
    behaviour-neutral, and S1's no-op guarantees (floor 0, region x1.0,
    add-ons 0) hold. Run with:
        odoo -d <db> -i saas_core --test-enable --stop-after-init
    or  odoo -d <db> -u saas_core --test-enable --stop-after-init
    """

    def setUp(self):
        super().setUp()
        self.engine = self.env['saas.pricing.engine']
        self.icp = self.env['ir.config_parameter'].sudo()
        # Pin known rates so the assertions are deterministic regardless
        # of whatever the live DB has configured.
        self._set({
            'saas_master.hosting_worker_price': '10.0',
            'saas_master.hosting_storage_price_per_gb': '0.3',
            'saas_master.hosting_min_workers': '2',
            'saas_master.hosting_max_workers': '8',
            'saas_master.hosting_min_storage': '5',
            'saas_master.hosting_max_storage': '200',
            'saas_master.hosting_yearly_discount_pct': '20',
            'saas_master.worker_price': '15.0',
            'saas_master.storage_price_per_gb': '0.5',
            'saas_master.custom_plan_min_workers': '2',
            'saas_master.custom_plan_max_workers': '8',
            'saas_master.custom_plan_min_storage': '5',
            'saas_master.custom_plan_max_storage': '200',
            'saas_master.custom_plan_yearly_discount_pct': '20',
            # Floor rates explicitly 0 -> S1 no-op.
            'saas_master.hosting_worker_floor': '0',
            'saas_master.hosting_storage_floor': '0',
            'saas_master.worker_floor': '0',
            'saas_master.storage_floor': '0',
            # Minimum monthly charge explicitly 0 -> P1 no-op (keeps the
            # legacy-formula grid deterministic).
            'saas_master.hosting_minimum_monthly': '0',
            'saas_master.minimum_monthly': '0',
            # Tier soft-floor buffer 0 -> P2 = original hard floor.
            'saas_master.tier_floor_buffer_pct': '0',
        })

    def _set(self, mapping):
        for k, v in mapping.items():
            self.icp.set_param(k, v)

    def _rates(self, kind):
        if kind == 'hosting':
            return 10.0, 0.3, 20
        return 15.0, 0.5, 20

    def _grid(self):
        for kind in ('hosting', 'services'):
            for workers in (2, 4, 8):
                for storage in (5, 50, 200):
                    for billing in ('monthly', 'yearly'):
                        yield kind, workers, storage, billing

    def test_engine_reproduces_legacy_linear_formula(self):
        """Engine monthly/yearly == the exact pre-refactor arithmetic."""
        for kind, workers, storage, billing in self._grid():
            wp, sp, disc = self._rates(kind)
            legacy_monthly = workers * wp + storage * sp
            legacy_yearly = legacy_monthly * 12 * (1 - disc / 100.0)
            q = self.engine.compute(kind, workers, storage, billing)
            self.assertAlmostEqual(
                q['monthly'], round(legacy_monthly, 2), places=2,
                msg='monthly drift %s w%s s%s' % (kind, workers, storage),
            )
            self.assertAlmostEqual(
                q['yearly'], round(legacy_yearly, 2), places=2,
                msg='yearly drift %s w%s s%s' % (kind, workers, storage),
            )
            expected_total = legacy_yearly if billing == 'yearly' else legacy_monthly
            self.assertAlmostEqual(q['total'], round(expected_total, 2), places=2)

    def test_s1_noops(self):
        """Floor, region multiplier and add-ons are no-ops in S1."""
        q = self.engine.compute('hosting', 4, 50, 'monthly',
                                 addon_codes=('snapshots',), region=None)
        self.assertEqual(q['region_factor'], 1.0)
        self.assertFalse(q['floored'])
        self.assertEqual(q['breakdown']['addons_monthly'], 0.0)
        self.assertEqual(q['breakdown']['floor'], 0.0)
        # base == resource_monthly when region x1.0 and floor 0
        self.assertAlmostEqual(
            q['breakdown']['base'], q['breakdown']['resource_monthly'], places=2,
        )

    def test_minimum_monthly_charge(self):
        """P1: the final monthly never drops below the configured minimum;
        default 0 is a no-op; add-ons count toward the minimum, not on top."""
        # Default off -> no-op.
        q0 = self.engine.compute('hosting', 2, 5, 'monthly')
        self.assertFalse(q0['minimum_applied'])
        self.assertAlmostEqual(q0['monthly'], 21.5, places=2)  # 2*10 + 5*0.3
        self.assertAlmostEqual(q0['breakdown']['pre_minimum'], 21.5, places=2)

        # Minimum above the computed price -> bumped up, flag set.
        self._set({'saas_master.hosting_minimum_monthly': '30'})
        q = self.engine.compute('hosting', 2, 5, 'monthly')
        self.assertTrue(q['minimum_applied'])
        self.assertAlmostEqual(q['monthly'], 30.0, places=2)
        self.assertAlmostEqual(q['breakdown']['pre_minimum'], 21.5, places=2)
        self.assertAlmostEqual(q['breakdown']['minimum_monthly'], 30.0, places=2)
        # Yearly applies the discount to the floored monthly.
        self.assertAlmostEqual(q['yearly'], 30.0 * 12 * 0.8, places=2)

        # A config already above the minimum is unaffected.
        big = self.engine.compute('hosting', 8, 200, 'monthly')
        self.assertFalse(big['minimum_applied'])
        self.assertAlmostEqual(big['monthly'], 8 * 10 + 200 * 0.3, places=2)

        # Add-ons count toward the minimum (no double charge): if an add-on
        # pushes pre_minimum above the floor, the floor doesn't apply.
        if self.env['saas.addon'].sudo().search_count(
                [('code', '=', 'daily_snapshots')]):
            self._set({'saas_master.hosting_daily_backup_price': '12'})
            qa = self.engine.compute('hosting', 2, 5, 'monthly',
                                     addon_codes=['daily_snapshots'])
            # 21.5 + 12 = 33.5 > 30 minimum -> not floored.
            self.assertFalse(qa['minimum_applied'])
            self.assertAlmostEqual(qa['monthly'], 33.5, places=2)
        self._set({'saas_master.hosting_minimum_monthly': '0'})

    def test_clamping(self):
        """Out-of-range workers/storage clamp to plan limits."""
        q = self.engine.compute('hosting', 99, 9999, 'monthly')
        self.assertEqual(q['workers'], 8)
        self.assertEqual(q['storage'], 200)
        q = self.engine.compute('hosting', 0, 0, 'monthly')
        self.assertEqual(q['workers'], 2)
        self.assertEqual(q['storage'], 5)

    def test_cost_floor_bites_when_set(self):
        """With floor rates configured, price = max(base, floor)."""
        self._set({
            'saas_master.hosting_worker_floor': '12',
            'saas_master.hosting_storage_floor': '0.5',
        })
        # 2w/5gb: base = 2*10 + 5*0.3 = 21.5 ; floor = 2*12 + 5*0.5 = 26.5
        q = self.engine.compute('hosting', 2, 5, 'monthly')
        self.assertTrue(q['floored'])
        self.assertAlmostEqual(q['monthly'], 26.5, places=2)
        self.assertAlmostEqual(q['breakdown']['cost_floor'], 26.5, places=2)

    def test_plan_price_floor_constraint(self):
        """A plan priced below its cost floor is rejected."""
        from odoo.exceptions import ValidationError
        product = self.env['saas.product'].sudo().search(
            [('is_hosting', '=', True)], limit=1)
        if not product:
            self.skipTest('no hosting product in this DB')
        self._set({
            'saas_master.hosting_worker_floor': '12',
            'saas_master.hosting_storage_floor': '0.5',
        })
        with self.assertRaises(ValidationError):
            self.env['saas.plan'].sudo().create({
                'name': 'TEST below floor',
                'is_public_tier': True,
                'workers': 2, 'storage_limit': 5,
                'cpu_limit': 1.0, 'ram_limit': '1g',
                'price': 10.0,  # below floor 26.5
                'currency_id': self.env.company.currency_id.id,
                'saas_product_ids': [(6, 0, [product.id])],
            })

    def test_tier_floor_blocks_undercut(self):
        """When 'custom >= nearest tier' is on, a custom config that
        contains a tier can't be priced below that tier."""
        product = self.env['saas.product'].sudo().search(
            [('is_hosting', '=', True)], limit=1)
        if not product:
            self.skipTest('no hosting product in this DB')
        self._set({'saas_master.custom_min_is_nearest_tier': 'True'})
        self.env['saas.plan'].sudo().create({
            'name': 'TEST Pro tier', 'is_public_tier': True,
            'workers': 4, 'storage_limit': 50,
            'cpu_limit': 2.0, 'ram_limit': '2g',
            'price': 999.0, 'yearly_price': 9990.0,
            'currency_id': self.env.company.currency_id.id,
            'saas_product_ids': [(6, 0, [product.id])],
        })
        # 8w/200gb contains the 4w/50gb tier -> floor up to 999
        q = self.engine.compute('hosting', 8, 200, 'monthly')
        self.assertEqual(q['breakdown']['tier_floor'], 999.0)
        self.assertGreaterEqual(q['monthly'], 999.0)

    def test_tier_floor_soft_buffer(self):
        """P2: the buffer % lets a custom config sit below the nearest tier
        instead of being pinned to it. 0 = hard floor (unchanged)."""
        product = self.env['saas.product'].sudo().search(
            [('is_hosting', '=', True)], limit=1)
        if not product:
            self.skipTest('no hosting product in this DB')
        self._set({'saas_master.custom_min_is_nearest_tier': 'True'})
        self.env['saas.plan'].sudo().create({
            'name': 'TEST Pro 1000', 'is_public_tier': True,
            'workers': 4, 'storage_limit': 50,
            'cpu_limit': 2.0, 'ram_limit': '2g',
            'price': 1000.0, 'yearly_price': 10000.0,
            'currency_id': self.env.company.currency_id.id,
            'saas_product_ids': [(6, 0, [product.id])],
        })
        # buffer 0 -> hard floor at the full tier price.
        self._set({'saas_master.tier_floor_buffer_pct': '0'})
        q0 = self.engine.compute('hosting', 8, 200, 'monthly')
        self.assertAlmostEqual(q0['breakdown']['tier_floor'], 1000.0, places=2)

        # buffer 10 -> floor relaxes to 90% of the tier (900).
        self._set({'saas_master.tier_floor_buffer_pct': '10'})
        q10 = self.engine.compute('hosting', 8, 200, 'monthly')
        self.assertAlmostEqual(q10['breakdown']['tier_floor'], 900.0, places=2)
        self.assertGreaterEqual(q10['monthly'], 900.0)
        self.assertLess(q10['monthly'], 1000.0)

        # buffer is clamped to 0..100 (a silly 150 can't go negative).
        self._set({'saas_master.tier_floor_buffer_pct': '150'})
        qmax = self.engine.compute('hosting', 8, 200, 'monthly')
        self.assertAlmostEqual(qmax['breakdown']['tier_floor'], 0.0, places=2)
        self._set({'saas_master.tier_floor_buffer_pct': '0',
                   'saas_master.custom_min_is_nearest_tier': 'False'})

    def test_addon_sum(self):
        """The daily_snapshots add-on adds the Settings price to the quote."""
        self._set({'saas_master.hosting_daily_backup_price': '7.0'})
        if not self.env['saas.addon'].sudo().search_count(
                [('code', '=', 'daily_snapshots')]):
            self.skipTest('daily_snapshots add-on not seeded in this DB')
        base = self.engine.compute('hosting', 4, 50, 'monthly')
        withp = self.engine.compute(
            'hosting', 4, 50, 'monthly', addon_codes=['daily_snapshots'])
        self.assertAlmostEqual(
            withp['monthly'] - base['monthly'], 7.0, places=2)
        self.assertAlmostEqual(withp['breakdown']['addons_monthly'], 7.0, places=2)
        # Add-on that doesn't apply to this kind contributes nothing.
        none = self.engine.compute(
            'hosting', 4, 50, 'monthly', addon_codes=['nonexistent_code'])
        self.assertAlmostEqual(none['breakdown']['addons_monthly'], 0.0, places=2)

    def test_addon_storage_aware_pricing(self):
        """P4: an add-on can scale with storage (flat / storage / hybrid)
        billed per block. Flat mode is unchanged."""
        Addon = self.env['saas.addon'].sudo()
        a = Addon.create({
            'name': 'TEST Scaled Backup', 'code': 'test_scaled_backup',
            'applies_to': 'hosting', 'price_mode': 'hybrid',
            'monthly_price': 5.0,        # base fee
            'price_per_block': 1.0, 'block_gb': 10,
        })
        # 50 GB -> ceil(50/10)=5 blocks -> 5 + 5*1 = 10
        self.assertAlmostEqual(a.effective_monthly_price(storage_gb=50), 10.0, places=2)
        # 0 GB -> just the base.
        self.assertAlmostEqual(a.effective_monthly_price(storage_gb=0), 5.0, places=2)
        # 21 GB -> ceil(21/10)=3 blocks -> 5 + 3 = 8
        self.assertAlmostEqual(a.effective_monthly_price(storage_gb=21), 8.0, places=2)
        # storage-only mode: no base.
        a.write({'price_mode': 'storage'})
        self.assertAlmostEqual(a.effective_monthly_price(storage_gb=50), 5.0, places=2)
        # flat mode: storage ignored (back-compat).
        a.write({'price_mode': 'flat'})
        self.assertAlmostEqual(a.effective_monthly_price(storage_gb=999), 5.0, places=2)
        self.assertAlmostEqual(a.effective_monthly_price(), 5.0, places=2)
        # Through the engine: storage flows into the add-on sum.
        a.write({'price_mode': 'hybrid'})
        q = self.engine.compute('hosting', 4, 200, 'monthly',
                                addon_codes=['test_scaled_backup'])
        # 200 GB -> 20 blocks -> 5 + 20 = 25
        self.assertAlmostEqual(q['breakdown']['addons_monthly'], 25.0, places=2)

    def test_storage_overage_per_gb_and_block(self):
        """Overage: legacy per-GB by default; block-based when configured."""
        GB = 1024 ** 3
        self._set({
            'saas_master.extra_storage_price_per_gb': '0.5',
            'saas_master.storage_block_gb': '0',
            'saas_master.storage_block_price': '0',
        })
        # 60GB used over a 50GB limit -> 10GB * 0.5 = 5.0 (per-gb)
        o = self.engine.storage_overage(60 * GB, 50)
        self.assertEqual(o['mode'], 'per_gb')
        self.assertEqual(o['over_gb'], 10)
        self.assertAlmostEqual(o['charge'], 5.0, places=2)
        # Configure blocks: 50GB block @ 9 -> 10GB over = 1 block = 9.0
        self._set({
            'saas_master.storage_block_gb': '50',
            'saas_master.storage_block_price': '9',
        })
        o2 = self.engine.storage_overage(60 * GB, 50)
        self.assertEqual(o2['mode'], 'block')
        self.assertEqual(o2['blocks'], 1)
        self.assertAlmostEqual(o2['charge'], 9.0, places=2)
        # Under the limit -> nothing.
        o3 = self.engine.storage_overage(40 * GB, 50)
        self.assertEqual(o3['mode'], 'none')
        self.assertAlmostEqual(o3['charge'], 0.0, places=2)

    def test_support_plan_flat_not_region_scaled(self):
        """P3: a support plan adds a flat monthly fee, after infra, and is
        NOT scaled by region. No/unknown/default code adds 0."""
        Support = self.env['saas.support.plan'].sudo()
        pro = Support.create({
            'name': 'TEST Pro', 'code': 'test_pro', 'monthly_price': 50.0,
            'response_time': '4h',
        })
        base = self.engine.compute('hosting', 4, 50, 'monthly')
        withs = self.engine.compute('hosting', 4, 50, 'monthly',
                                    support_code='test_pro')
        self.assertAlmostEqual(
            withs['monthly'] - base['monthly'], 50.0, places=2)
        self.assertAlmostEqual(withs['breakdown']['support_monthly'], 50.0, places=2)
        # Unknown / no code -> 0.
        none = self.engine.compute('hosting', 4, 50, 'monthly',
                                   support_code='does_not_exist')
        self.assertAlmostEqual(none['breakdown']['support_monthly'], 0.0, places=2)
        self.assertAlmostEqual(
            self.engine.compute('hosting', 4, 50, 'monthly')
            ['breakdown']['support_monthly'], 0.0, places=2)
        # Region multiplier does NOT scale support.
        region = Support.env['saas.region'].sudo().create({
            'name': 'TEST sx2', 'code': 'test_sx2', 'price_multiplier': 2.0,
        })
        regs = self.engine.compute('hosting', 4, 50, 'monthly',
                                   support_code='test_pro', region=region.id)
        self.assertAlmostEqual(regs['breakdown']['support_monthly'], 50.0, places=2)
        # compute+storage doubled, support flat:
        self.assertAlmostEqual(
            regs['monthly'],
            base['breakdown']['resource_monthly'] * 2 + 50.0, places=2)

    def test_region_multiplier_scales_compute_not_addons(self):
        """Region multiplier scales compute+storage only; add-ons unaffected."""
        region = self.env['saas.region'].sudo().create({
            'name': 'TEST x2', 'code': 'test_x2', 'price_multiplier': 2.0,
        })
        base = self.engine.compute('hosting', 4, 50, 'monthly')
        reg = self.engine.compute('hosting', 4, 50, 'monthly', region=region.id)
        self.assertEqual(reg['region_factor'], 2.0)
        self.assertAlmostEqual(
            reg['breakdown']['resource_monthly'],
            base['breakdown']['resource_monthly'] * 2, places=2)
        # No region -> factor 1.0 (behaviour-neutral).
        self.assertEqual(base['region_factor'], 1.0)
        # Add-ons are NOT scaled by region.
        if self.env['saas.addon'].sudo().search_count(
                [('code', '=', 'daily_snapshots')]):
            self._set({'saas_master.hosting_daily_backup_price': '7.0'})
            rega = self.engine.compute(
                'hosting', 4, 50, 'monthly',
                addon_codes=['daily_snapshots'], region=region.id)
            self.assertAlmostEqual(
                rega['breakdown']['addons_monthly'], 7.0, places=2)

    def test_region_match_domain_treats_null_as_default(self):
        """Null-region servers belong to the default region (behaviour-
        neutral); a non-default region matches only assigned servers."""
        Server = self.env['saas.server'].sudo()
        default = self.env['saas.region']._get_default()
        # No region -> no constraint.
        self.assertEqual(Server._region_match_domain(None), [])
        if default:
            dom = Server._region_match_domain(default)
            # default region includes the region itself OR null
            self.assertIn(('region_id', '=', False), dom)
        other = self.env['saas.region'].sudo().create({
            'name': 'TEST other', 'code': 'test_other', 'price_multiplier': 1.5,
        })
        self.assertEqual(
            Server._region_match_domain(other), [('region_id', '=', other.id)])

    def test_created_plan_price_matches_engine(self):
        """A custom plan stamped from the engine carries the same price
        the engine quotes — i.e. checkout/plan == preview (consistency)."""
        product = self.env['saas.product'].sudo().search([], limit=1)
        if not product:
            self.skipTest('no saas.product available in this DB')
        q = self.engine.compute('hosting', 4, 50, 'monthly')
        plan = self.env['saas.plan'].sudo().create({
            'name': 'TEST Pricing 4W/50GB',
            'is_custom': True,
            'workers': 4,
            'storage_limit': 50,
            'cpu_limit': 2.0,
            'ram_limit': '2g',
            'price': q['monthly'],
            'yearly_price': q['yearly'],
            'currency_id': self.env.company.currency_id.id,
            'saas_product_ids': [(6, 0, [product.id])],
        })
        self.assertAlmostEqual(plan.price, q['monthly'], places=2)
        self.assertAlmostEqual(plan.yearly_price, q['yearly'], places=2)

    def test_support_renewal_line(self):
        """P5: the support plan produces a recurring sale-order line —
        qty 1 on monthly, qty 12 on yearly; the free/$0 plan adds none."""
        Support = self.env['saas.support.plan'].sudo()
        product = self.env['saas.product'].sudo().search([], limit=1)
        if not product:
            self.skipTest('no saas.product available in this DB')
        plan = self.env['saas.plan'].sudo().search([], limit=1)
        partner = self.env['res.partner'].sudo().search([], limit=1)
        pro = Support.create({
            'name': 'TEST Pro Sup', 'code': 'test_pro_sup',
            'monthly_price': 40.0, 'response_time': '4h',
        })
        free = Support.search([('is_default', '=', True)], limit=1)
        inst = self.env['saas.instance'].sudo().create({
            'subdomain': 'zzsup', 'partner_id': partner.id,
            'saas_product_id': product.id, 'plan_id': plan.id,
            'support_plan_id': pro.id, 'billing_period': 'monthly',
        })
        # monthly -> qty 1 @ 40
        line = inst._support_order_line('monthly', 'Monthly')
        self.assertIsNotNone(line)
        self.assertEqual(line[2]['product_uom_qty'], 1)
        self.assertAlmostEqual(line[2]['price_unit'], 40.0, places=2)
        # yearly -> qty 12 @ 40 (support term matches plan term)
        liney = inst._support_order_line('yearly', 'Yearly')
        self.assertEqual(liney[2]['product_uom_qty'], 12)
        # free/$0 plan -> no line.
        if free:
            inst.support_plan_id = free.id
            self.assertIsNone(inst._support_order_line('monthly', 'Monthly'))
