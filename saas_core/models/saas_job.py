"""Durable job queue (ARCH-004, Phase 0).

A DB-backed queue: ``_enqueue`` persists a job row; ``_cron_run_jobs`` claims due
jobs with ``FOR UPDATE SKIP LOCKED`` and runs them; ``_cron_reap_jobs`` requeues
(idempotent) or fails (non-idempotent) jobs whose worker died (stale heartbeat).
Retries use exponential back-off; a per-resource advisory ``lock_key``
serialises same-resource jobs; ``idempotency_key`` dedupes enqueues. Reuses the
heartbeat/reaper (PROV-001), alert (SEC-009) and audit (SEC-010) patterns.

Phase 0 ships the engine with NO callers — pure addition, zero behaviour change.
See docs/reviews/ARCH-004-JOB-QUEUE-DESIGN.md.
"""
import datetime
import hashlib
import json
import logging
import random
import threading

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaasJob(models.Model):
    _name = 'saas.job'
    _description = 'SaaS Durable Job'
    _order = 'priority, run_after, id'

    # How many due jobs a single _cron_run_jobs tick claims.
    _RUN_BATCH = 50
    # A running job whose heartbeat is older than this is presumed dead.
    _HEARTBEAT_STALE_MIN = 15
    # Retry back-off: BASE * 2**(attempts-1) minutes, capped, + jitter.
    _BACKOFF_BASE_MIN = 1
    _BACKOFF_CAP_MIN = 60

    idempotency_key = fields.Char(index=True, copy=False)
    model = fields.Char(required=True)
    res_id = fields.Integer()
    method = fields.Char(required=True)
    args_json = fields.Text(default='[]')
    state = fields.Selection(
        [('pending', 'Pending'), ('running', 'Running'),
         ('done', 'Done'), ('failed', 'Failed'), ('cancelled', 'Cancelled')],
        default='pending', required=True, index=True)
    priority = fields.Integer(default=10)
    channel = fields.Char(default='default', index=True)
    lock_key = fields.Char(help='Per-resource serialisation key (advisory lock).')
    idempotent = fields.Boolean(
        default=False,
        help='Safe to re-run if the worker dies mid-flight; such jobs are '
             'requeued by the reaper, others are failed for manual review.')
    attempts = fields.Integer(default=0)
    max_attempts = fields.Integer(default=3)
    run_after = fields.Datetime(default=fields.Datetime.now, index=True)
    last_heartbeat = fields.Datetime()
    started_at = fields.Datetime()
    finished_at = fields.Datetime()
    error = fields.Text(readonly=True)
    result_json = fields.Text(readonly=True)

    # ------------------------------------------------------------------ API
    @api.model
    def _enqueue(self, record, method, args=(), *, idempotency_key=None,
                 channel='default', lock_key=None, max_attempts=3,
                 idempotent=False, priority=10, eta=None, run_now=True):
        """Persist a job and return its record. Idempotent on
        ``idempotency_key``: if a pending/running/done job already carries it,
        that job is returned and nothing new is created.

        ``run_now`` (default True, and only when not delayed by ``eta``) kicks
        an immediate background worker so the job starts promptly — like the old
        ``run_in_background`` — while the durable row + reaper guarantee it still
        runs if that worker (or the process) dies. The cron is the backstop."""
        if idempotency_key:
            existing = self.sudo().search([
                ('idempotency_key', '=', idempotency_key),
                ('state', 'in', ('pending', 'running', 'done')),
            ], limit=1)
            if existing:
                return existing
        job = self.sudo().create({
            'model': record._name,
            'res_id': record.id,
            'method': method,
            'args_json': json.dumps(list(args)),
            'idempotency_key': idempotency_key or False,
            'channel': channel,
            'lock_key': lock_key or False,
            'max_attempts': max_attempts,
            'idempotent': idempotent,
            'priority': priority,
            'run_after': eta or fields.Datetime.now(),
        })
        if run_now and not eta:
            job._spawn_worker()
        return job

    def _spawn_worker(self):
        """Commit the job, then run it in a daemon thread with its own cursor.
        Mirrors utils.run_in_background, but the durable row means a crash is
        recovered by the cron/reaper rather than lost."""
        self.ensure_one()
        job_id = self.id
        dbname = self.env.cr.dbname
        self.env.cr.commit()  # publish the job so the new cursor sees it

        def _target():
            import odoo
            from odoo import api as odoo_api, SUPERUSER_ID
            try:
                reg = odoo.modules.registry.Registry(dbname)
                with reg.cursor() as cr:
                    env = odoo_api.Environment(cr, SUPERUSER_ID, {})
                    env['saas.job']._run_one(job_id)
            except Exception:
                _logger.exception("saas.job %s worker thread crashed", job_id)

        threading.Thread(
            target=_target, name='saas_job_%s' % job_id, daemon=True).start()

    @api.model
    def _run_one(self, job_id):
        """Claim a single job by id (no-op if the cron/another worker already
        took it) and execute it."""
        now = fields.Datetime.now()
        self.env.cr.execute(
            """
            UPDATE saas_job SET state='running', started_at=%s,
                   last_heartbeat=%s, attempts=attempts+1
            WHERE id=%s AND state='pending' AND run_after<=%s
                  AND attempts<max_attempts
            RETURNING id
            """, (now, now, job_id, now))
        if not self.env.cr.fetchone():
            return  # already claimed elsewhere
        self.env.cr.commit()
        job = self.browse(job_id)
        job.invalidate_recordset()
        job._execute()

    # -------------------------------------------------------------- worker
    @api.model
    def _claim_jobs(self, limit):
        """Atomically claim up to *limit* due jobs (state->running). Uses
        ``FOR UPDATE SKIP LOCKED`` so concurrent workers never grab the same
        job. Increments attempts so the count survives a crash."""
        now = fields.Datetime.now()
        self.env.cr.execute(
            """
            UPDATE saas_job SET state='running', started_at=%s,
                   last_heartbeat=%s, attempts=attempts+1
            WHERE id IN (
                SELECT id FROM saas_job
                WHERE state='pending' AND run_after <= %s
                      AND attempts < max_attempts
                ORDER BY priority, run_after, id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            RETURNING id
            """, (now, now, now, limit))
        ids = [r[0] for r in self.env.cr.fetchall()]
        jobs = self.browse(ids)
        # The UPDATE bypassed the ORM cache; refresh so state/attempts read true.
        jobs.invalidate_recordset()
        return jobs

    @api.model
    def _cron_run_jobs(self):
        jobs = self._claim_jobs(self._RUN_BATCH)
        if not jobs:
            return
        # Publish the claim so a parallel worker sees these as 'running'.
        self.env.cr.commit()
        for job in jobs:
            try:
                job._execute()
            except Exception:
                # _execute handles its own failures; this guards the loop.
                _logger.exception("saas.job %s executor crashed", job.id)
                self.env.cr.rollback()

    @staticmethod
    def _lock_int(key):
        """Stable signed-64-bit int for pg_advisory_xact_lock from a string."""
        h = hashlib.sha256(key.encode('utf-8')).digest()[:8]
        return int.from_bytes(h, 'big', signed=True)

    def _execute(self):
        self.ensure_one()
        if self.lock_key:
            # Serialise same-resource jobs for the duration of this txn.
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(%s)", (self._lock_int(self.lock_key),))
        record = self.env[self.model].browse(self.res_id) if self.res_id else None
        if self.res_id and (record is None or not record.exists()):
            self._finish_failed("Target %s,%s no longer exists." % (self.model, self.res_id))
            return
        try:
            args = json.loads(self.args_json or '[]')
            result = getattr(record, self.method)(*args)
            payload = False
            try:
                payload = json.dumps(result)
            except (TypeError, ValueError):
                payload = False  # non-JSON result (e.g. recordset) — not stored
            self.write({
                'state': 'done', 'finished_at': fields.Datetime.now(),
                'result_json': payload, 'error': False,
            })
            self.env.cr.commit()
        except Exception as e:
            self.env.cr.rollback()
            _logger.exception("saas.job %s (%s.%s) failed", self.id, self.model, self.method)
            self._reschedule_or_fail(str(e))

    def _backoff_run_after(self):
        mins = min(self._BACKOFF_BASE_MIN * (2 ** max(0, self.attempts - 1)),
                   self._BACKOFF_CAP_MIN)
        delay = datetime.timedelta(minutes=mins, seconds=random.uniform(0, 30))
        return fields.Datetime.now() + delay

    def _reschedule_or_fail(self, message):
        """Retry with back-off while attempts remain, else fail terminally."""
        self.ensure_one()
        if self.attempts < self.max_attempts:
            self.write({
                'state': 'pending', 'run_after': self._backoff_run_after(),
                'error': (message or '')[:2000],
            })
            self.env.cr.commit()
            return
        self._finish_failed(message)

    def _finish_failed(self, message):
        self.ensure_one()
        self.write({
            'state': 'failed', 'finished_at': fields.Datetime.now(),
            'error': (message or '')[:2000],
        })
        self.env.cr.commit()
        # Operational alert + immutable audit on terminal failure.
        try:
            self.env['saas.alert']._notify(
                'job_failed',
                'job %s (%s.%s) failed after %d attempts'
                % (self.id, self.model, self.method, self.attempts),
                level='error', detail=(message or '')[:500])
            self.env['saas.audit.log']._saas_audit(
                'job_failed', result='error', model=self.model,
                res_id=self.res_id, res_name=self.method,
                detail=(message or '')[:500])
        except Exception:
            _logger.exception("saas.job %s: alert/audit on failure failed", self.id)

    # --------------------------------------------------------------- reaper
    @api.model
    def _cron_reap_jobs(self):
        """Recover jobs whose worker died (stale heartbeat): requeue idempotent
        ones, fail the rest for review."""
        cutoff = fields.Datetime.now() - datetime.timedelta(
            minutes=self._HEARTBEAT_STALE_MIN)
        stuck = self.search([
            ('state', '=', 'running'),
            '|', ('last_heartbeat', '<', cutoff), ('last_heartbeat', '=', False),
        ])
        for job in stuck:
            if job.idempotent and job.attempts < job.max_attempts:
                job.write({'state': 'pending', 'run_after': fields.Datetime.now()})
                _logger.warning("saas.job %s requeued after stale heartbeat", job.id)
            else:
                job._finish_failed("Worker died (no heartbeat) and job is not "
                                   "safe to auto-retry.")
            self.env.cr.commit()
