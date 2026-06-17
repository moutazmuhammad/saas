from unittest.mock import patch, MagicMock

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestComputeDriver(TransactionCase):
    """Phase 1: ComputeDriver seam — driver command-building (mocked SSH) and
    god-model call-site routing (mocked driver). No real SSH/Docker here; the
    real-infra checks run separately against the live test tenant."""

    def setUp(self):
        super().setUp()
        self.product = self.env['saas.product'].sudo().search(
            [('is_hosting', '=', True)], limit=1) or self.env['saas.product'].sudo().create(
            {'name': 'CD Hosting', 'is_hosting': True, 'is_published': True})
        self.plan = self.env['saas.plan'].sudo().create({
            'name': 'CD Plan', 'is_custom': True, 'workers': 2, 'storage_limit': 10,
            'cpu_limit': 1.0, 'ram_limit': '1g', 'price': 50.0, 'yearly_price': 480.0,
            'currency_id': self.env.company.currency_id.id,
            'saas_product_ids': [(6, 0, [self.product.id])]})
        self.partner = self.env['res.partner'].sudo().create({'name': 'CD Cust'})
        self.domain = self.env['saas.based.domain'].sudo().search([], limit=1) \
            or self.env['saas.based.domain'].sudo().create({'name': 'cd.example.com'})

    def _running_instance(self, sub):
        return self.env['saas.instance'].sudo().create({
            'subdomain': sub, 'domain_id': self.domain.id, 'partner_id': self.partner.id,
            'saas_product_id': self.product.id, 'plan_id': self.plan.id,
            'billing_period': 'monthly', 'environment': 'production',
            'region_id': False, 'state': 'running'})

    # -------- driver: builds the right commands over a fake SSH --------
    def test_driver_builds_expected_commands(self):
        from odoo.addons.saas_core.drivers.ssh_docker_driver import SshDockerDriver
        from odoo.addons.saas_core.drivers.base import ComputeHandle
        calls = []

        class FakeSSH:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, cmd, timeout=None):
                calls.append(cmd)
                return (0, 'running|healthy', '')

        server = MagicMock()
        server._get_ssh_connection.return_value = FakeSSH()
        d = SshDockerDriver(server)
        h = ComputeHandle(server_id=1, container_name='odoo_x', instance_path='/srv/x',
                          host='1.2.3.4', http_port=8069)

        d.stop(h)
        self.assertIn('cd /srv/x && docker compose stop', calls[-1])
        d.start(h)
        self.assertIn('docker compose up -d', calls[-1])
        d.destroy(h)
        self.assertIn('docker compose down', calls[-1])
        hs = d.health(h)
        self.assertTrue(hs.running)
        self.assertEqual(hs.detail, 'running|healthy')
        self.assertEqual(d.endpoint(h), ('1.2.3.4', 8069))
        r = d.exec(h, 'echo hi')
        self.assertTrue(r.ok)
        self.assertIn('docker exec', calls[-1])
        self.assertIn('odoo_x', calls[-1])

    def test_driver_health_reports_not_running(self):
        from odoo.addons.saas_core.drivers.ssh_docker_driver import SshDockerDriver
        from odoo.addons.saas_core.drivers.base import ComputeHandle

        class FakeSSH:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, cmd, timeout=None):
                return (0, 'exited|unhealthy', '')

        server = MagicMock()
        server._get_ssh_connection.return_value = FakeSSH()
        d = SshDockerDriver(server)
        h = ComputeHandle(server_id=1, container_name='odoo_x', instance_path='/srv/x')
        self.assertFalse(d.health(h).running)

    # -------- god-model: _do_stop/_do_restart route to the driver --------
    def test_do_stop_routes_to_driver(self):
        inst = self._running_instance('cdstop')
        fake = MagicMock()
        with patch.object(type(inst), '_compute_driver', return_value=fake), \
             patch.object(type(inst), '_compute_handle', return_value='HANDLE'):
            inst._do_stop()
        fake.stop.assert_called_once_with('HANDLE')
        self.assertEqual(inst.state, 'stopped')
        self.assertFalse(inst.pending_operation)

    def test_do_restart_routes_to_driver(self):
        inst = self._running_instance('cdrestart')
        fake = MagicMock()
        with patch.object(type(inst), '_compute_driver', return_value=fake), \
             patch.object(type(inst), '_compute_handle', return_value='HANDLE'):
            inst._do_restart()
        fake.restart.assert_called_once_with('HANDLE')
        self.assertEqual(inst.state, 'running')

    def test_do_stop_wraps_driver_error_as_usererror(self):
        inst = self._running_instance('cderr')
        fake = MagicMock()
        fake.stop.side_effect = RuntimeError('boom')
        with patch.object(type(inst), '_compute_driver', return_value=fake), \
             patch.object(type(inst), '_compute_handle', return_value='H'):
            with self.assertRaises(UserError):
                inst._do_stop()
