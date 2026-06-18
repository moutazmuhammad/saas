import json
from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests.common import HttpCase, TransactionCase, tagged

from odoo.addons.saas_core.models.saas_instance_repo import (
    assert_safe_git_url, _extract_git_host)


@tagged('post_install', '-at_install')
class TestSsrfGuard(TransactionCase):
    """SSRF: user-supplied Git URLs must never resolve to internal hosts."""

    def test_extract_host_https_and_scp(self):
        self.assertEqual(
            _extract_git_host('https://gitea.example.com/o/r.git'),
            'gitea.example.com')
        self.assertEqual(
            _extract_git_host('git@github.com:o/r.git'), 'github.com')

    def test_loopback_rejected(self):
        for url in ('https://127.0.0.1/o/r.git',
                    'https://localhost/o/r.git',
                    'git@127.0.0.1:o/r.git'):
            with self.assertRaises(UserError):
                assert_safe_git_url(url)

    def test_private_ranges_rejected(self):
        for url in ('https://10.0.0.5/o/r.git',
                    'https://192.168.1.10/o/r.git',
                    'https://172.16.4.4/o/r.git'):
            with self.assertRaises(UserError):
                assert_safe_git_url(url)

    def test_metadata_endpoint_rejected(self):
        # The cloud metadata service is link-local (169.254.0.0/16).
        with self.assertRaises(UserError):
            assert_safe_git_url('https://169.254.169.254/latest/meta-data')

    def test_missing_host_rejected(self):
        with self.assertRaises(UserError):
            assert_safe_git_url('not-a-url')

    def test_public_host_allowed(self):
        # A public IP literal must NOT raise (no DNS needed → offline-safe).
        try:
            assert_safe_git_url('https://8.8.8.8/o/r.git')
        except UserError as e:
            self.fail("public host wrongly rejected: %s" % e)


@tagged('post_install', '-at_install')
class TestRateLimit(TransactionCase):
    """DB-backed fixed-window rate limiter."""

    def test_allows_then_blocks_within_window(self):
        rl = self.env['saas.rate.limit']
        allowed = []
        for _i in range(5):
            ok, _retry = rl._hit('utest', 'k1', 3, 3600)
            allowed.append(ok)
        # First 3 allowed, the rest blocked (same fixed window).
        self.assertEqual(allowed, [True, True, True, False, False])

    def test_independent_keys(self):
        rl = self.env['saas.rate.limit']
        self.assertTrue(rl._hit('utest', 'a', 1, 3600)[0])
        self.assertFalse(rl._hit('utest', 'a', 1, 3600)[0])
        # A different key has its own bucket.
        self.assertTrue(rl._hit('utest', 'b', 1, 3600)[0])

    def test_retry_after_is_positive_when_blocked(self):
        rl = self.env['saas.rate.limit']
        rl._hit('utest', 'c', 1, 3600)
        ok, retry = rl._hit('utest', 'c', 1, 3600)
        self.assertFalse(ok)
        self.assertGreater(retry, 0)


@tagged('post_install', '-at_install')
class TestEnvSlotBilling(TransactionCase):
    """Deleting an extra environment must stop billing its recurring slot."""

    def setUp(self):
        super().setUp()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('saas_master.hosting_worker_price', '10.0')
        icp.set_param('saas_master.hosting_storage_price_per_gb', '0.3')
        icp.set_param('saas_master.env_price_factor', '1.0')
        self.product = self.env['saas.product'].sudo().search(
            [('is_hosting', '=', True)], limit=1) or \
            self.env['saas.product'].sudo().create({
                'name': 'TEST Hosting Sec', 'is_hosting': True,
                'is_published': True})
        self.plan = self.env['saas.plan'].sudo().create({
            'name': 'TEST Sec Plan', 'is_custom': True, 'workers': 4,
            'storage_limit': 50, 'cpu_limit': 2.0, 'ram_limit': '2g',
            'price': 55.0, 'yearly_price': 528.0,
            'currency_id': self.env.company.currency_id.id,
            'saas_product_ids': [(6, 0, [self.product.id])]})
        self.partner = self.env['res.partner'].sudo().create(
            {'name': 'Sec Cust'})
        self.domain = self.env['saas.based.domain'].sudo().search([], limit=1) \
            or self.env['saas.based.domain'].sudo().create(
                {'name': 'sec.example.com'})

    def _mk_prod(self, sub):
        today = date.today()
        return self.env['saas.instance'].sudo().create({
            'subdomain': sub, 'domain_id': self.domain.id,
            'partner_id': self.partner.id, 'saas_product_id': self.product.id,
            'plan_id': self.plan.id, 'billing_period': 'monthly',
            'environment': 'production', 'region_id': False, 'state': 'running',
            'next_invoice_date': today + timedelta(days=15),
            'last_invoice_date': today - timedelta(days=15)})

    def test_delete_environment_releases_slot(self):
        prod = self._mk_prod('secslot')
        prod.write({'staging_slots': 2})
        child = self.env['saas.instance'].sudo().create({
            'subdomain': 'secslot-stg', 'domain_id': self.domain.id,
            'partner_id': self.partner.id, 'saas_product_id': self.product.id,
            'plan_id': self.plan.id, 'billing_period': 'monthly',
            'environment': 'staging', 'parent_id': prod.id,
            'region_id': False, 'state': 'running'})
        # Renewal bills 2 staging slots before deletion.
        self.assertEqual(len(prod._environment_order_lines('monthly')), 2)
        child.action_delete_environment(delete_branch=False)
        prod.invalidate_recordset(['staging_slots'])
        # Slot released → renewal now bills 1, not 2 (no perpetual charge).
        self.assertEqual(prod.staging_slots, 1)
        self.assertEqual(len(prod._environment_order_lines('monthly')), 1)

    def test_delete_slot_floors_at_zero(self):
        prod = self._mk_prod('secfloor')
        prod.write({'staging_slots': 0})
        child = self.env['saas.instance'].sudo().create({
            'subdomain': 'secfloor-stg', 'domain_id': self.domain.id,
            'partner_id': self.partner.id, 'saas_product_id': self.product.id,
            'plan_id': self.plan.id, 'billing_period': 'monthly',
            'environment': 'staging', 'parent_id': prod.id,
            'region_id': False, 'state': 'running'})
        child.action_delete_environment(delete_branch=False)
        prod.invalidate_recordset(['staging_slots'])
        self.assertEqual(prod.staging_slots, 0)


@tagged('post_install', '-at_install')
class TestApiSecurityHttp(HttpCase):
    """End-to-end checks against the live JSON routes: brute-force throttling
    and the access-token's read-only scope."""

    def setUp(self):
        super().setUp()
        self.product = self.env['saas.product'].sudo().search(
            [('is_hosting', '=', True)], limit=1) or \
            self.env['saas.product'].sudo().create({
                'name': 'HTTP Hosting', 'is_hosting': True,
                'is_published': True})
        self.plan = self.env['saas.plan'].sudo().create({
            'name': 'HTTP Plan', 'is_custom': True, 'workers': 2,
            'storage_limit': 5, 'cpu_limit': 1.0, 'ram_limit': '1g',
            'price': 20.0, 'yearly_price': 192.0,
            'currency_id': self.env.company.currency_id.id,
            'saas_product_ids': [(6, 0, [self.product.id])]})
        self.domain = self.env['saas.based.domain'].sudo().search([], limit=1) \
            or self.env['saas.based.domain'].sudo().create(
                {'name': 'http.example.com'})
        self.partner = self.env['res.partner'].sudo().create(
            {'name': 'HTTP Cust', 'email': 'httpcust@example.com'})

    def _call(self, route, params):
        resp = self.url_open(
            route,
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call',
                             'params': params}),
            headers={'Content-Type': 'application/json'})
        return resp.json().get('result')

    def test_login_is_rate_limited(self):
        # Hammer with wrong credentials; the per-account window is 7/300s, so
        # the throttle must kick in well before the 12th try.
        codes = []
        for _i in range(12):
            res = self._call('/saas/api/v1/auth/login',
                             {'login': 'nobody@example.com',
                              'password': 'wrong'})
            codes.append((res or {}).get('code'))
        self.assertIn('rate_limited', codes,
                      "login endpoint was never throttled: %s" % codes)

    def test_access_token_is_read_only(self):
        inst = self.env['saas.instance'].sudo().create({
            'subdomain': 'httptok', 'domain_id': self.domain.id,
            'partner_id': self.partner.id, 'saas_product_id': self.product.id,
            'plan_id': self.plan.id, 'billing_period': 'monthly',
            'environment': 'production', 'region_id': False, 'state': 'running',
            'is_hosting': True})
        token = inst._portal_ensure_token()
        # READ with the token works (share-link semantics preserved).
        read = self._call('/saas/api/v1/instances/%s' % inst.id,
                          {'access_token': token})
        self.assertTrue(read and read.get('ok'),
                        "token read should succeed: %s" % read)
        # WRITE with the SAME token is refused — destructive ops need the
        # authenticated owner, not a bearer token.
        write = self._call('/saas/api/v1/instances/%s/action' % inst.id,
                           {'access_token': token, 'action': 'restart'})
        self.assertFalse(write.get('ok'),
                         "token must NOT authorize a write: %s" % write)
        self.assertEqual(write.get('code'), 'not_found')
        # And the token must no longer be echoed back in the read payload.
        self.assertNotIn('access_token', read.get('data', {}))

    def test_environments_payload_exposes_scaling(self):
        # The workspace needs the Production server's resources + slot usage to
        # offer "Scale resources" and "add test environment" CTAs.
        prod = self.env['saas.instance'].sudo().create({
            'subdomain': 'httpscale', 'domain_id': self.domain.id,
            'partner_id': self.partner.id, 'saas_product_id': self.product.id,
            'plan_id': self.plan.id, 'billing_period': 'monthly',
            'environment': 'production', 'region_id': False, 'state': 'running',
            'is_hosting': True, 'staging_slots': 2})
        token = prod._portal_ensure_token()
        res = self._call('/saas/api/v1/instances/%s/environments' % prod.id,
                         {'access_token': token})
        self.assertTrue(res.get('ok'), res)
        data = res['data']
        self.assertEqual(data['production_plan']['workers'], self.plan.workers)
        self.assertEqual(data['production_plan']['storage_gb'],
                         int(self.plan.storage_limit))
        self.assertFalse(data['production_plan']['is_trial'])
        self.assertEqual(data['slots']['staging']['total'], 2)
        self.assertEqual(data['slots']['staging']['used'], 0)
