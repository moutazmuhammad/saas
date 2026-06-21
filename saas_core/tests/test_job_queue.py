import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestJobQueue(TransactionCase):
    """ARCH-004 Phase 0: durable job engine — enqueue/idempotency, claim,
    success, retry/back-off, terminal failure, run_after gating, per-resource
    lock, and reaper recovery."""

    def setUp(self):
        super().setUp()
        self.Job = self.env['saas.job']
        self.partner = self.env['res.partner'].sudo().create({'name': 'Job Target'})

        def _job_ok(rec, *a):
            return {'ran': True, 'args': list(a)}

        def _job_boom(rec, *a):
            raise ValueError('boom')

        for name, fn in (('_job_ok', _job_ok), ('_job_boom', _job_boom)):
            p = patch.object(type(self.partner), name, fn, create=True)
            p.start()
            self.addCleanup(p.stop)
        # Suppress the immediate worker thread so execution is driven
        # deterministically via _cron_run_jobs / _run_one in the tests (and so
        # _enqueue doesn't commit the test cursor).
        wp = patch.object(type(self.Job), '_spawn_worker', lambda self: None)
        wp.start()
        self.addCleanup(wp.stop)

    def _no_commit(self):
        # _cron_run_jobs / _execute / reaper commit per item; the test cursor
        # forbids commit/rollback, so neutralise them for the call.
        for op in ('commit', 'rollback'):
            p = patch.object(self.env.cr, op)
            p.start()
            self.addCleanup(p.stop)

    # ---- enqueue / idempotency ----
    def test_enqueue_creates_pending(self):
        job = self.Job._enqueue(self.partner, '_job_ok', args=(1, 2))
        self.assertEqual(job.state, 'pending')
        self.assertEqual(job.model, 'res.partner')
        self.assertEqual(job.res_id, self.partner.id)
        self.assertEqual(json.loads(job.args_json), [1, 2])

    def test_enqueue_idempotent(self):
        j1 = self.Job._enqueue(self.partner, '_job_ok', idempotency_key='k1')
        j2 = self.Job._enqueue(self.partner, '_job_ok', idempotency_key='k1')
        self.assertEqual(j1, j2, "same idempotency key must not create a 2nd job")

    # ---- run ----
    def test_run_success_stores_result(self):
        self._no_commit()
        job = self.Job._enqueue(self.partner, '_job_ok', args=(1, 2))
        self.Job._cron_run_jobs()
        self.assertEqual(job.state, 'done')
        self.assertEqual(job.attempts, 1)
        self.assertEqual(json.loads(job.result_json), {'ran': True, 'args': [1, 2]})

    def test_run_with_lock_key(self):
        self._no_commit()
        job = self.Job._enqueue(self.partner, '_job_ok',
                                lock_key='res:%s' % self.partner.id)
        self.Job._cron_run_jobs()
        self.assertEqual(job.state, 'done')

    # ---- failure: retry then terminal ----
    def test_failure_requeues_with_backoff(self):
        self._no_commit()
        job = self.Job._enqueue(self.partner, '_job_boom', max_attempts=3)
        self.Job._cron_run_jobs()
        self.assertEqual(job.state, 'pending', "retries remain -> requeued")
        self.assertEqual(job.attempts, 1)
        self.assertIn('boom', job.error)
        self.assertGreater(job.run_after, fields.Datetime.now(),
                           "requeue is delayed by back-off")

    def test_failure_terminal_alerts(self):
        self._no_commit()
        job = self.Job._enqueue(self.partner, '_job_boom', max_attempts=1)
        self.Job._cron_run_jobs()
        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.attempts, 1)
        self.assertIn('boom', job.error)

    # ---- claim gating ----
    def test_future_job_not_claimed(self):
        self._no_commit()
        job = self.Job._enqueue(self.partner, '_job_ok',
                                eta=fields.Datetime.now() + timedelta(hours=1))
        self.Job._cron_run_jobs()
        self.assertEqual(job.state, 'pending')
        self.assertEqual(job.attempts, 0, "a not-yet-due job must not be claimed")

    # ---- reaper ----
    def test_reaper_requeues_idempotent(self):
        self._no_commit()
        job = self.Job._enqueue(self.partner, '_job_ok', idempotent=True)
        job.write({'state': 'running', 'attempts': 1,
                   'last_heartbeat': fields.Datetime.now() - timedelta(minutes=30)})
        self.Job._cron_reap_jobs()
        self.assertEqual(job.state, 'pending', "dead idempotent job is requeued")

    def test_reaper_fails_non_idempotent(self):
        self._no_commit()
        job = self.Job._enqueue(self.partner, '_job_ok', idempotent=False)
        job.write({'state': 'running', 'attempts': 1,
                   'last_heartbeat': fields.Datetime.now() - timedelta(minutes=30)})
        self.Job._cron_reap_jobs()
        self.assertEqual(job.state, 'failed',
                         "dead non-idempotent job is failed for review")

    def test_reaper_leaves_fresh_running(self):
        self._no_commit()
        job = self.Job._enqueue(self.partner, '_job_ok', idempotent=True)
        job.write({'state': 'running', 'attempts': 1,
                   'last_heartbeat': fields.Datetime.now()})
        self.Job._cron_reap_jobs()
        self.assertEqual(job.state, 'running', "a freshly-beating job is left alone")


@tagged('post_install', '-at_install')
class TestBackupViaQueue(TransactionCase):
    """ARCH-004 Phase 1: portal backups are routed through the durable queue."""

    def setUp(self):
        super().setUp()
        product = self.env['saas.product'].sudo().search(
            [('is_hosting', '=', True)], limit=1) or \
            self.env['saas.product'].sudo().create(
                {'name': 'BQ Hosting', 'is_hosting': True, 'is_published': True})
        plan = self.env['saas.plan'].sudo().create({
            'name': 'BQ Plan', 'is_custom': True, 'workers': 1, 'storage_limit': 5,
            'cpu_limit': 1.0, 'ram_limit': '1g', 'price': 20.0, 'yearly_price': 192.0,
            'currency_id': self.env.company.currency_id.id,
            'saas_product_ids': [(6, 0, [product.id])]})
        domain = self.env['saas.based.domain'].sudo().search([], limit=1) or \
            self.env['saas.based.domain'].sudo().create({'name': 'bq.example.com'})
        partner = self.env['res.partner'].sudo().create({'name': 'BQ Cust'})
        self.instance = self.env['saas.instance'].sudo().create({
            'subdomain': 'bqinst', 'domain_id': domain.id, 'partner_id': partner.id,
            'saas_product_id': product.id, 'plan_id': plan.id,
            'billing_period': 'monthly', 'environment': 'production',
            'region_id': False, 'state': 'running', 'is_hosting': True})

    def test_action_create_backup_enqueues_durable_job(self):
        # Suppress the immediate worker thread so no real backup runs.
        with patch.object(type(self.env['saas.job']), '_spawn_worker',
                          lambda self: None):
            self.instance.action_create_backup()
        backup = self.env['saas.instance.backup'].sudo().search(
            [('instance_id', '=', self.instance.id)], limit=1)
        self.assertEqual(backup.state, 'running',
                         "the backup record is created up-front")
        job = self.env['saas.job'].sudo().search([
            ('model', '=', 'saas.instance.backup'),
            ('res_id', '=', backup.id)], limit=1)
        self.assertTrue(job, "a durable job must be enqueued for the backup")
        self.assertEqual(job.method, '_run_portal_backup')
        self.assertEqual(job.channel, 'backup')
        self.assertEqual(job.lock_key, 'instance:%s' % self.instance.id)
        self.assertEqual(job.state, 'pending')
