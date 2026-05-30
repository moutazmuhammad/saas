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
