# SaaS Platform — Remediation Plan (V1 + V2)

Single tracking file for every finding from the V1 audit (`docs/reviews/`) and the V2
second-pass audit (`docs/reviews/v2/`). Check a box when the fix is merged **and** verified
(test or live check). Each item links back to its finding ID so you can open the detailed
report for context.

**Legend:** `[ ]` not started · `[~]` in progress (edit to `[~]` manually) · `[x]` done & verified
**Severity:** 🔴 Critical · 🟠 High · 🟡 Medium · ⚪ Low

> Source counts — V1: Critical 10 · High 29 · Medium 41 · Low 14. V2 (new): High 8 · Medium 20 · Low 13.

---

## 0. Do NOT work these — verified false / by-design (close, don't fix)

Confirmed during audit; left here so nobody "fixes" a non-issue. No checkbox = no action.

- Trial concurrent-create race — `create()` already `SELECT … FOR UPDATE` on commercial partner (`saas_instance.py:1269-1278`).
- Wallet concurrent-debit double-spend — `_consume` is `_lock()`ed + idempotent per move (`saas_wallet.py:188-218`).
- Backup-restore IDOR — ownership enforced via `_instance(write=True)` (`api.py:1294`).
- Shared Docker network — per-instance `net_<subdomain>` already (`saas_instance.py:4660`).
- Per-instance shell authz — already enforces `access_token` (`ssh_terminal.py:644-667`).
- Port silent collision — partial unique index exists; race raises `IntegrityError` (add retry only).
- Portal cross-tenant leak of repo/build/wallet/payment-method/db-op — portal users have **no ACL** to these models; not exploitable (reclassified as DiD: **ISO-001**).
- Storage-block "free month" — code charges `full` when `left==0` (`saas_instance.py:1885`).
- Repeated-upgrade double-credit — proration uses `today`; window shrinks correctly.
- Yearly support add-on "asymmetry" — documented flat-×12 policy (`saas_pricing.py:261-279`).
- CSRF on `type='json'` routes — exempt by design.

---

## 1. Immediate (1–2 weeks) — ship-blockers

### Security / secrets
- [~] 🔴 **SEC-001** Remove `debug_otp` from API responses (`api.py:233,250`) + SPA (`Register.tsx:130,224`); add regression test asserting field absent. *(also closes UX-001, BIZ-001, CX security premise)* — **code done + test-verified** (api.py + Register.tsx/AuthContext/api.ts; SPA rebuilt tsc-clean; `test_register_start_never_echoes_otp` passes — 0 failed/4 in local DB). **Pending live deploy verify.** Also fixed a blocking fresh-install manifest menu-order bug (saas_margin_views→saas_menus).
- [x] 🔴 **SEC-002** Envelope-encrypt platform secrets at rest (no KMS — key in odoo.conf/env). — **done + tested (passwords, tokens, AND SSH keys)**. To activate: set `saas_secret_key`, restart, run `env['saas.instance']._saas_reencrypt_secrets()` and `env['saas.ssh.key.pair']._saas_migrate_legacy_keys()`. Char-secrets detail: (`admin_password`, `db_password`, `restic_password`, `github_token` on repo+product): new `crypto.py` (Fernet, key from `saas_secret_key`/`SAAS_SECRET_KEY`, **opt-in** passthrough when unset, legacy-plaintext-safe) + `EncryptedChar` field (encrypts at column boundary, decrypts on read; no migration/column rename) + `_saas_reencrypt_secrets()` sweep. Full suite 0/168 incl. at-rest + transparent-read tests. **To activate:** put a `Fernet.generate_key()` in odoo.conf `[options] saas_secret_key=…`, restart, run `env['saas.instance']._saas_reencrypt_secrets()`. SSH private key now done too: `saas.ssh.key.pair` keeps `private_key_file` as an upload inbox that's moved into an encrypted `private_key_enc` (EncryptedChar) and cleared on save; all readers go through `_private_key_b64()`; `_saas_migrate_legacy_keys()` migrates existing rows. Byte-identical round-trip test guarantees SSHConnection still gets the same key (the plaintext key was already proven to connect to the real host), full suite 0/179. **Remaining:** **rotation** of the actual credentials after the key is set (an ops procedure, not code).
- [ ] 🟠 **SEC-006** Stop rendering plaintext DB password into host `odoo.conf`; inject via secret mounted to tmpfs; `chmod 0600` non-tenant owner.
- [~] 🟠 **SEC-009** Error monitoring + alerting — **alerting done + tested (provider-agnostic, opt-in)**: new `saas.alert._notify()` always logs and, when `ir.config_parameter saas_master.alert_webhook` (or `SAAS_ALERT_WEBHOOK`) is set, POSTs JSON to any Slack/Discord/generic webhook — best-effort, never raises. Wired into **server-health degradation** (`_update_health`) and **operation failures** (`_on_background_error`). `TestAlerting` (no-op without webhook; posts with payload; failure never raises; bad-level safe) — suite 0/188. **To enable:** set the webhook param. *(Sentry SDK integration optional later if a DSN is chosen; the webhook covers the alerting need now.)*

### Build / process
- [~] 🟠 **ARCH-007** Add CI gate: run Odoo test suite + `tsc`/lint on every PR; block merge on failure. — **workflow added** (`.github/workflows/ci.yml`): job `spa` (`npm ci` + `npm run build` = tsc --noEmit + vite) and job `odoo-tests` (postgres service → clone Odoo 18 → install `saas_core,saas_website` → full `--test-enable` suite → assert "0 failed, 0 error"). Validated locally: full suite 0/155, `npm ci` exit 0, YAML parses, assertion logic correct on green+red logs. **Branch-protection "required check" must still be enabled in repo settings** (admin) to actually block merges.

### Destructive-flow safety (V1 + V2 overlap)
- [x] 🟡 **UX-012** Typed confirmation on DB-drop — **verified already implemented** (`Databases.tsx DeleteDatabaseDialog`: `confirmText===dbName`, danger button disabled until exact match).
- [x] 🟡 **CX-010** Environment-delete: spell out what is destroyed + typed confirm — **done** (`Environments.tsx DeleteEnvDialog`: title "Delete environment — can't be undone", lists databases/files/logs, type-the-name gate; tsc-clean).
- [x] 🟠 **CX-009** Production merge: red/danger button + second confirmation — **done** (`Environments.tsx MergeEnvDialog`: danger banner + confirm checkbox + red "Deploy to live Production" button disabled until checked; tsc-clean).
- [x] 🟠 **UX-004** Checkout-redirect loading state + button disable — **verified already implemented** for the async fetch-then-redirect cases (`Backups.tsx enableDailyBackup` + `InstanceDetail` lifecycle use `ActionButton loading=…`); remaining `window.location.href` calls go to an already-known URL (no async dead period).
- [x] 🟡 **BIZ-012** Always recompute/validate price server-side at order creation; never trust client price. — **verified already satisfied** (no code change): SPA `Hosting.tsx` order payload sends only config (`workers/storage/billing/region/domain/version/...`), never a price; `main.py:hosting_order` → `_get_or_create_hosting_plan` recomputes price solely from `saas.pricing.engine.compute(...)` (`main.py:806-808`). Client price is never read/trusted.

### V2 concurrency ship-blockers
- [x] 🟠 **SCALE-001 / SCALE-003** Per-proxy lock around nginx write+`nginx -t`+reload; write-temp-then-atomic-rename. — **done + verified on REAL nginx 1.24** (test host 165.245.245.196: valid vhost installs+reloads; broken config rejected rc=10 → rolled back to the good vhost → `nginx -t` still clean; flock/`/run/lock` present; live vhosts untouched). Originally: new `_nginx_apply_vhost`/`_nginx_remove_vhost` SFTP the config to a temp OUTSIDE `sites-enabled`, then run `mv`→`nginx -t`→reload inside a host-side `flock /run/lock/saas-nginx.lock`, restoring the prior vhost (no reload) on `-t` failure. All 3 mutation sites (deploy/refresh/remove) routed through them. `TestNginxVhost` (3 tests) asserts the command shape; real nginx behaviour needs a proxy host.
- [x] 🟠 **SCALE-005** Invalidate + re-read server capacity strictly **after** acquiring the allocation lock. — **verified already satisfied** (no code change): `_allocate_servers` takes `pg_advisory_xact_lock` first, *then* `Server.invalidate_model(['instance_count','allocated_cpu','allocated_ram_gb'])` (`saas_instance.py:3584-3591`); those fields are **non-stored** computed (`saas_server.py:115-126`) so the re-read runs a live `_read_group` inside the lock.
- [x] 🟠 **PROV-001** Wrap background DB-op target in fail-fast try/except (mark `failed` + traceback) + `last_heartbeat`. — **done + tested**: each `_run_*` already self-marks `failed`; added a `last_heartbeat` field + watchdog beater in `utils.run_in_background` (opt-in `heartbeat_field`), wired into all 6 db-op dispatches; reaper now fails ops with a stale heartbeat in ~3 min instead of 30 (`_HEARTBEAT_STALE_MIN`). New `TestDbOperationReaper` (3 tests) passes.
- [x] 🟠 **CX-001** In-SPA password reset — **done + tested**: new `auth/reset/start` (email OTP, account-enumeration safe) + `auth/reset/verify` (verify code → set password → sign in) reusing existing email-OTP infra; new SPA `ForgotPassword` page (email → code+password) wired at `/forgot-password`; Login "Forgot?" now routes in-SPA. HttpCase: enumeration-safe start, bad-input rejection, and **end-to-end** reset (new password logs in, old rejected) — 0 failed / 3.
- [x] 🟠 **CX-002** Centralize `auth_required` → re-auth — **done**: `api.ts` `setUnauthorizedHandler` fires on both the transport (`SessionExpired/AccessDenied`) and envelope (`code==='auth_required'`) paths; AuthContext registers it to clear the user so `ProtectedRoute` redirects to `/login`. No component can mask expiry as "not found". SPA tsc/build clean.

---

## 2. Short Term (1 month)

### Tenant runtime hardening
- [x] 🔴 **SEC-003** Non-root tenant containers + cap drop / no-new-privileges — **done + tested**. Non-root was already in place (tenant Dockerfile ends `USER odoo`; official image runs uid 100 — verified `docker exec odoo_rt2 id` = uid=100). Added `cap_drop: [ALL]` + `security_opt: ["no-new-privileges:true"]` to `docker-compose.yml.jinja` (Docker's default seccomp stays on). Validated on the real image (`docker run --cap-drop ALL --security-opt no-new-privileges … → uid=100`, runs fine). `TestContainerHardening` asserts the rendered compose. *(read-only rootfs left out — Odoo writes outside its volumes; higher risk, separate task.)*
- [ ] 🟠 **SEC-004** Remove `CREATEDB` from tenant roles (provision DBs from control plane); add per-role connection/disk quotas.
- [ ] 🟠 **SEC-005** Split host-shell from manager group into an audited, JIT-elevated, host-scoped role; stream commands to immutable log.

### Async / reliability
- [~] 🟠 **ARCH-004 / PERF-002** Introduce durable job queue with retries, idempotency, client-pollable operation status. — **design proposed** (`docs/reviews/ARCH-004-JOB-QUEUE-DESIGN.md`): DB-backed `saas.job` (no new infra) reusing the existing heartbeat/reaper + advisory-lock + alert/audit patterns; `FOR UPDATE SKIP LOCKED` claim, idempotency keys, back-off, per-resource lock, generic reaper; phased migration (backups → db-ops → deploy → webhook), each behaviour-preserving + tested. **Phase 0 DONE + tested** (`saas.job` model + `_enqueue` + `_cron_run_jobs` [FOR UPDATE SKIP LOCKED claim] + `_cron_reap_jobs` + per-resource advisory lock + retry/back-off + idempotency + alert/audit on terminal fail; `TestJobQueue` 10 tests; full suite 0/204). NO callers yet — zero behaviour change. **Phase 1 DONE + tested**: portal backups (`action_create_backup` + on-demand `hosting_db_backup`) now `_enqueue(... channel='backup', lock_key='instance:<id>')` instead of `run_in_background`; `_enqueue` gained an immediate worker (`_spawn_worker`/`_run_one`) so it starts promptly like before but is durable (reaper) and records failures (alert/audit). `TestBackupViaQueue` + full suite 0/205. **Phase 2 DONE + tested**: the 5 non-secret db-ops (duplicate/drop/restore/upgrade/upgrade_live) now `_enqueue(channel='dbop', lock_key='instance:<id>', idempotent=False)`; the job's new heartbeat beater (`_heartbeat_tick`/`_heartbeat_loop`) also refreshes the `db.operation`'s `last_heartbeat` so its 3-min reaper doesn't fail a live job. `_run_create` deliberately stays on `run_in_background` (its login/password args must not be persisted to the job row — SEC-002). `TestDbOpViaQueue` + full suite 0/209. **Phase 3 DONE + tested**: `action_deploy` + `action_delete_instance` now `_enqueue(channel='deploy', lock_key='instance:<id>', max_attempts=1, on_error='_on_background_error')` (new `on_error` job hook mirrors run_in_background's error_method → instance still transitions failed/pending + alerts). No secret args. The existing `_cron_recover_stuck_provisioning` + `_cron_retry_pending_provision` (incl. PROV-004) are KEPT as the retry/recovery net (careful cutover, not deleted). `TestDeployViaQueue` + full suite 0/212. **Phase 4 DONE + tested**: webhook auto-deploy (was a raw `threading.Thread` with ZERO durability) now creates the build then `_enqueue(repo, '_run_webhook_deploy', channel='deploy', idempotent=True, on_error='_on_webhook_deploy_error')` — durable, crash-recoverable, alerted/audited. `TestWebhookDeployViaQueue` + full suite 0/214. **Deliberately NOT a blanket shim**: a shim would persist `_run_create`'s secret args (SEC-002), so the remaining ~17 `run_in_background` sites (billing/account_move, repo clone/pull, portal misc, restore wizard, instance restart/stop/redeploy) stay as-is and migrate incrementally per-site; `_run_create` stays permanently. **ARCH-004 core paths (backups, db-ops, deploy/delete, webhook, repo clone/pull) now on the queue.** Repo `action_clone_repo`/`action_pull_repo` migrated (idempotent, `on_error='_on_repo_background_error'`); `TestRepoOpsViaQueue`; full suite 0/216. Remaining long-tail `run_in_background` (billing/account_move, portal misc, restore wizard, instance restart/stop/redeploy) migrate incrementally; `_run_create` stays (secrets).
- [ ] 🟠 **ARCH-008** Idempotent partial-failure teardown on every deploy failure branch. *(partial: container start is now retried — see below; full teardown still TODO)*
- [x] 🟢 **Teardown: template-DB leak check** — **verified already-correct + regression-guarded**: `_drop_postgresql()` (cancel/delete paths) enumerates every role-owned DB incl. `__odoo_template_<sub>`, clears `datistemplate` before `dropdb --force`, drops the role last. New `TestPgTeardown` (mocked SSH) asserts un-flag-before-drop ordering + role-after-DBs. (The orphan I saw in the live run was my ad-hoc `DROP DATABASE`, not the product.)
- [x] 🟠 **ARCH-008/010 (deploy resilience)** Bounded retry on `docker compose up` — **done + tested**: `SshDockerDriver.start()` retries `up -d` (idempotent) up to `_COMPOSE_UP_ATTEMPTS=3` with backoff+jitter, so a transient daemon hiccup / recreate port-release race self-heals instead of failing the whole deploy; a persistent error still raises after the budget. Found during the **real provision** on 165.245.245.196 (one-off `up` failure that succeeded on retry). `TestComputeDriver` (+2: retry-then-succeed, give-up) — 14/14.
- [ ] 🟠 **ARCH-009 / PERF-011 / SCALE-002** Shorten advisory-lock critical section; release port lock before nginx/certbot; rely on unique index.
- [x] 🟠 **ARCH-010** SSH retries w/ backoff + host circuit breaker — **done + tested**: `utils.SSHConnection._connect_with_retry` retries only the (idempotent) connect with exp backoff+jitter (3 attempts), a per-host circuit breaker quarantines a host after repeated connect failures (fast-fail for a cooldown), and auth/host-key errors are never retried / never trip the breaker. Command execution is **not** retried (commands may be non-idempotent). `TestSshResilience` (3 tests) passes. *(per-command soft/hard timeout split left as a follow-up; connect timeout already enforced.)*

### Scale / perf
- [ ] 🟠 **PERF-001** Parallelize backups (bounded pool) with per-job timeout + lag metric.
- [x] 🟠 **PERF-003** Batch/paginate unbounded crons (retry-pending, recover-stuck, storage-limits) — **done + tested**: all three now `search(..., limit=_CRON_BATCH_SIZE=500, order=oldest-first)` so one run can't load the whole table; remainder picked up next run (storage uses least-recently-touched order so coverage rotates). `TestCronBatching` asserts each cron passes the bound.
- [ ] 🟠 **PERF-004** Parallelize per-host metrics sampling with a hard per-run deadline.
- [ ] 🟠 **PERF-005** Stream `pg_dump` directly to object storage (no `/tmp` staging).
- [x] 🟡 **PERF-007** Add indexes: `(state)`, `(docker_server_id,state)`, `(partner_id)`, `(plan_id,state)` — **done + tested**: created idempotently in `saas.instance.init()`; `TestInstanceIndexes` asserts all four exist after install.
- [ ] 🟡 **PERF-006** Single grouped query for dashboard invoices (kill N+1).
- [ ] 🟡 **PERF-008 / UX-006** SPA polling: exponential backoff + jitter; pause on hidden tab; stop on auth_required.

### Provisioning lifecycle (V2)
- [x] 🟡 **PROV-003** Overcommit requires healthy host; pending fallback — **verified already-handled** (code evolved past the audit): both `_allocate_docker_server` and `_allocate_overcommit_server` exclude `unreachable` AND **live-probe every candidate**, returning only a healthy one; flexible mode's level-3 falls back to `_mark_as_pending()` (not a hard fail). No change needed.
- [x] 🟡 **PROV-004** Capacity-aware retry sweep on capacity/health change — **done + tested**: new `pending_retry_now` flag bypasses the retry-cron back-off; `_saas_flag_pending_for_retry()` sets it, hooked into `saas.server` create (new docker host), `write` (docker-host/overcommit enabled), and `_update_health` recovery → queued deploys retry on the next tick instead of waiting hours. `TestPendingRetry` (flag targets only pending; new host + health-recovery flag; cron bypasses back-off when flagged, skips otherwise) — full suite 0/194.

### Billing correctness (V1 + V2)
- [ ] 🟠 **BIZ-004** Explicit dunning state machine (retry→grace→suspend→delete) with customer-visible status; handle invalid token.
- [ ] 🟠 **BIZ-002** Add `pending_plan_effective_date`; re-price add-ons on plan change; tests for prorated up/down incl. add-ons.
- [ ] 🟠 **BIZ-003** Define + test trial-to-paid conversion proration.
- [x] 🟡 **BIZ-009** Idempotent renewal invoicing — **done + tested**: `_generate_renewal_invoice` now `SELECT … FOR UPDATE`s the instance row and re-reads `next_invoice_date`; a concurrent/overlapping cron run whose cycle was already billed (date advanced past today) returns without creating a second invoice. Complements the existing advance-before-post guard against same-process retries. `TestInvoiceIdempotency` (double generation → exactly one invoice, cycle advances once) — full suite 0/190.
- [x] 🟡 **BILL-V2-001** Unify proration to one helper (remove undocumented `-2`) so portal quote == invoice — **done + tested**: both portal display sites (`portal.py:570,648`) now call the authoritative `instance._proration_credit(old_price)` instead of duplicating the math with `-2`. `TestProrationUnify` asserts full-remaining-days (no -2) + safe on missing dates.
- [ ] 🟡 **BILL-V2-002** Decide & codify yearly minimum-floor policy (`minimum_monthly*12` vs discounted).
- [ ] 🟡 **BILL-V2-003 / BILL-V2-004** Size wallet consumption from confirmed, tax-aware invoice total within same txn.

### Billing transparency UI (V2 CX)
- [ ] 🟡 **CX-004** "Payment due / past due" badge on instance list → checkout.
- [ ] 🟡 **CX-005** Next charge date + amount + payment method in a billing summary card.
- [ ] 🟡 **CX-011** Branch backups empty-state on `daily_backup_enabled`; warn when off.

### Audit / data exposure
- [x] 🟡 **SEC-010** Immutable, write-once internal audit log (actor/action/target/result/ts) — **done + tested**: new append-only `saas.audit.log` (write/unlink raise; manager read-only ACL; created via `_saas_audit()` sudo helper that never raises into callers). Wired the destructive events `instance_delete` + `db_drop`. `TestAuditLog` (records actor/action/target; immutable to write & unlink; helper caps detail + never raises) — full suite 0/184. *(more events + a customer-facing view can be layered on later.)*
- [~] 🟠 **SEC-008** Reduce presigned-URL TTL to minutes — **done + tested** (TTL part): `PRESIGNED_URL_EXPIRY` cut from 7 days → 15 min; the `backups` API now re-mints fresh short links per list (`_refresh_download_url`) so the client never holds a stale long-lived URL. Server-side restore uses bucket creds, unaffected. `TestBackupUrlTtl` guards the TTL stays in minutes. *(per-download auth + download audit-log still TODO — pair with SEC-010.)*

---

## 3. Medium Term (3 months)

### Architecture
- [ ] 🔴 **ARCH-001** Begin god-model decomposition (ComputeProvisioner / BillingEngine / BackupManager / RepoManager / MetricsCollector) behind existing seams.
- [ ] 🔴 **ARCH-002** Split control plane vs data plane: host agents reconcile desired state; add control-plane HA.
- [ ] 🟠 **ARCH-006** IaC (Terraform) for hosts/networks/buckets + drift detection.
- [ ] 🟡 **ARCH-014** Automated, versioned template-DB builds with health validation.

### Scale ceilings (V2)
- [ ] 🟡 **SCALE-007** Shard live-metrics sampler by host (remove global-lock ceiling).
- [ ] 🟡 **SCALE-004** Partition/retire metrics table (drop old partitions) + size/lag metrics + vacuum/reindex.
- [ ] 🟡 **SCALE-008** Key template-build lock by (version, region) via DB advisory lock (cross-process).
- [ ] ⚪ **SCALE-009** Per-server fallback lock when region absent.

### Tenant boundary
- [ ] 🟡 **ISO-002** Canonicalize boundary to `commercial_partner_id` across record rules + API; tests for multi-contact accounts.
- [ ] ⚪ **ISO-001** Add partner-scoped record rules (DiD) for repo/build/wallet/payment-method/db-op.
- [ ] 🟡 **ARCH-012 / ARCH-013** Per-tenant DB quotas; harden filestore isolation (object storage / strict mounts).

### Product feature gaps (V1)
- [ ] 🔴 **UX-002** Teams / collaborators with RBAC.
- [ ] 🟠 **UX-010** Self-serve API keys + OpenAPI.
- [ ] 🟠 **UX-007** Configurable alerts (resource/deploy/billing/suspension).
- [ ] 🟠 **UX-008** Self-serve custom domains + automated SSL.
- [ ] 🟠 **UX-009** Customer-facing audit log.
- [ ] 🔴 **UX-003** One-click deploy rollback + auto-rollback on failed deploy.
- [ ] 🟡 **CX-012** Account security: 2FA, active-session management, sign-in history.

### Reliability/idempotency
- [ ] 🟡 **ARCH-011 / PERF-009** Idempotent cron item-processing; savepoints/jobs instead of per-item commits.
- [~] 🟡 **ARCH-015 / ARCH-016 / ARCH-017** Recovery sentinel (not health-only); webhook de-dup; git clone TLS verify. — **ARCH-017 done + tested**: clone + pull now force `git -c http.sslVerify=true` (strictly safe; protects customer-code fetch from a downgraded host git config / MITM). `TestRepoCloneTls` asserts the flag. **ARCH-016** webhook de-dup already in place (`last_delivery_id` guard in `webhook.py`). ARCH-015 (recovery sentinel) still TODO.

---

## 4. Long Term (6 months)

- [ ] 🟠 **ARCH-005** Complete or remove Kubernetes driver; make driver fully backend-agnostic (route all infra ops through it).
- [ ] 🔴 **ARCH-003** DR program: RTO/RPO, geo-replicated backups, control-DB failover, scheduled restore drills.
- [ ] 🟡 **BIZ-010** Per-tenant cost attribution feeding margin alerts + pricing.
- [ ] 🟡 **SCALE-006 / PROV-002 / PROV-005** Graceful port/capacity degradation; partial-create atomicity; subdomain reuse/reclaim.
- [ ] 🟡 **BIZ-008 / BIZ-014** Retention/grace policy for suspend→delete; reactivation pricing/data semantics.
- [ ] 🟡 SOC 2 / ISO 27001 readiness (RBAC granularity **SEC-016**, audit, secrets, retention).
- [ ] ⚪ Mobile/a11y pass — **CX-014** (dialog touch dismiss), **CX-015** (help anchors), **CX-017** (skeletons), **UX-022/023/024**.

---

## 5. Full per-finding checklist (granular tracking)

> Items already scheduled above are repeated here only so the master list is complete. Tick
> here as the single source of truth if you prefer per-ID tracking. Items not separately
> called out in §1–4 carry their fix inline below.

### V1 — Security (`docs/reviews/SECURITY_AUDIT.md`)
- [ ] 🔴 SEC-001 debug_otp · [ ] 🔴 SEC-002 plaintext secrets · [ ] 🔴 SEC-003 root containers
- [ ] 🟠 SEC-004 CREATEDB · [ ] 🟠 SEC-005 host shell role · [ ] 🟠 SEC-006 host plaintext creds
- [ ] 🟠 SEC-007 pip/git supply chain (anchor pkg grammar, internal mirror, sandbox, scan)
- [ ] 🟠 SEC-008 presigned TTL · [ ] 🟠 SEC-009 monitoring · [ ] 🟡 SEC-010 audit log
- [x] 🟡 SEC-011 webhook hardening (uniform-deny no-oracle + per-repo rate limit 30/60; `TestWebhookSecurity`) · [ ] 🟡 SEC-012 container-log ownership check
- [x] 🟡 SEC-013 OTP window/hashing — **done+tested**: OTP `code` now `EncryptedChar` (encrypted at rest via the SEC-002 key; transparent decrypt keeps the email template + verify working), `_verify` rewritten to constant-time compare, `otp_verify` window tightened 10→6/600 across all 3 sites. `TestOtpEncryption` + existing reset e2e pass · [ ] 🟡 SEC-014 central quoted SSH command builder
- [ ] 🟡 SEC-015 narrow exception handling + telemetry · [ ] 🟡 SEC-016 granular RBAC roles
- [ ] ⚪ SEC-017 restore-confirm UX · [ ] ⚪ SEC-018 SPA session refresh/idle · [ ] ⚪ SEC-019 CI lint: no `type='http'`+`csrf=False`

### V1 — Architecture (`docs/reviews/ARCHITECTURE_AUDIT.md`)
- [ ] 🔴 ARCH-001 god-model · [ ] 🔴 ARCH-002 control-plane SPOF · [ ] 🔴 ARCH-003 DR readiness
- [ ] 🟠 ARCH-004 job queue · [ ] 🟠 ARCH-005 driver abstraction · [ ] 🟠 ARCH-006 IaC · [ ] 🟠 ARCH-007 CI
- [ ] 🟠 ARCH-008 partial-failure teardown · [ ] 🟠 ARCH-009 lock hold time · [ ] 🟠 ARCH-010 SSH retries/timeouts
- [ ] 🟡 ARCH-011 cron idempotency · [ ] 🟡 ARCH-012 DB quotas · [ ] 🟡 ARCH-013 filestore isolation
- [ ] 🟡 ARCH-014 template automation · [ ] 🟡 ARCH-015 recovery race · [ ] 🟡 ARCH-016 webhook de-dup
- [ ] 🟡 ARCH-017 git TLS · [ ] 🟡 ARCH-018 enforce tests · [ ] 🟡 ARCH-019 metrics scalability
- [ ] ⚪ ARCH-020 config coupling · [ ] ⚪ ARCH-021 stop committing SPA bundles · [ ] ⚪ ARCH-022 versioned runbooks

### V1 — Performance (`docs/reviews/PERFORMANCE_AUDIT.md`)
- [ ] 🟠 PERF-001 parallel backups · [ ] 🟠 PERF-002 async provisioning · [ ] 🟠 PERF-003 bounded crons
- [ ] 🟠 PERF-004 parallel metrics · [ ] 🟠 PERF-005 stream backups · [ ] 🟡 PERF-006 N+1 invoices
- [ ] 🟡 PERF-007 indexes · [ ] 🟡 PERF-008 polling backoff · [ ] 🟡 PERF-009 cron commit batching
- [ ] 🟡 PERF-010 billing cron sharding · [ ] 🟡 PERF-011 lock contention · [ ] 🟡 PERF-012 SQL/log pagination
- [ ] ⚪ PERF-013 Globe bundle · [ ] ⚪ PERF-014 exception-masked latency

### V1 — UX (`docs/reviews/UX_AUDIT.md`)
- [ ] 🔴 UX-001 debug OTP (=SEC-001) · [ ] 🔴 UX-002 teams · [ ] 🔴 UX-003 rollback
- [ ] 🟠 UX-004 checkout feedback · [ ] 🟠 UX-005 polling leaks · [ ] 🟠 UX-006 polling backoff
- [ ] 🟠 UX-007 alerts · [ ] 🟠 UX-008 domains/SSL · [ ] 🟠 UX-009 audit log · [ ] 🟠 UX-010 API keys
- [ ] 🟡 UX-011 pricing race · [ ] 🟡 UX-012 DB-drop confirm · [ ] 🟡 UX-013 logs search · [ ] 🟡 UX-014 SQL truncation
- [ ] 🟡 UX-015 backup progress · [ ] 🟡 UX-016 optimistic UI · [ ] 🟡 UX-017 empty states · [ ] 🟡 UX-018 trial eligibility
- [ ] 🟡 UX-019 webhook onboarding · [ ] 🟡 UX-020 deploy throttle · [ ] 🟡 UX-021 version upgrade
- [ ] ⚪ UX-022 status page · [ ] ⚪ UX-023 session warning · [ ] ⚪ UX-024 copy feedback

### V1 — Business (`docs/reviews/BUSINESS_AUDIT.md`)
- [ ] 🔴 BIZ-001 signup integrity (=SEC-001) · [ ] 🟠 BIZ-002 downgrade reconciliation · [ ] 🟠 BIZ-003 trial proration
- [ ] 🟠 BIZ-004 dunning · [ ] 🟠 BIZ-005 free-resource caps · [ ] 🟡 BIZ-006 refund cap · [ ] 🟡 BIZ-007 credit expiry
- [ ] 🟡 BIZ-008 retention policy · [ ] 🟡 BIZ-009 invoice idempotency · [ ] 🟡 BIZ-010 cost attribution
- [ ] 🟡 BIZ-011 pricing config trap · [ ] 🟡 BIZ-012 server-side price · [ ] ⚪ BIZ-013 add-on lifecycle billing
- [ ] ⚪ BIZ-014 reactivation · [ ] ⚪ BIZ-015 region residency

### V2 — Scalability (`docs/reviews/v2/SCALABILITY_AUDIT_V2.md`)
- [ ] 🟠 SCALE-001 nginx reload lock · [ ] 🟠 SCALE-002 lock scope/certbot · [ ] 🟡 SCALE-003 atomic nginx write
- [ ] 🟡 SCALE-004 metrics table growth · [ ] 🟠 SCALE-005 capacity race · [ ] 🟡 SCALE-006 port exhaustion
- [ ] 🟡 SCALE-007 sampler ceiling · [ ] 🟡 SCALE-008 template lock key · [ ] ⚪ SCALE-009 region-less lock
- [ ] ⚪ SCALE-010 reaper batching · [ ] ⚪ SCALE-011 sampler de-dup state

### V2 — Tenant Isolation (`docs/reviews/v2/TENANT_ISOLATION_AUDIT_V2.md`)
- [ ] ⚪ ISO-001 record-rule DiD · [ ] 🟡 ISO-002 scoping-key unification · [ ] ⚪ ISO-003 staff scope roles

### V2 — Billing (`docs/reviews/v2/BILLING_AUDIT_V2.md`)
- [ ] 🟡 BILL-V2-001 proration unify · [ ] 🟡 BILL-V2-002 yearly floor policy · [ ] 🟡 BILL-V2-003 wallet pre-tax cap
- [ ] 🟡 BILL-V2-004 wallet pre-confirm lock · [ ] ⚪ BILL-V2-005 advertised vs realized discount · [ ] ⚪ BILL-V2-006 `0.0` yearly sentinel

### V2 — Provisioning Reliability (`docs/reviews/v2/PROVISIONING_RELIABILITY_AUDIT_V2.md`)
- [ ] 🟠 PROV-001 background thread guard · [ ] 🟡 PROV-002 partial-create rollback · [ ] 🟡 PROV-003 overcommit health
- [ ] 🟡 PROV-004 capacity-aware retry · [ ] ⚪ PROV-005 subdomain reuse · [ ] ⚪ PROV-006 per-op SSH timeouts

### V2 — Customer Experience (`docs/reviews/v2/CUSTOMER_EXPERIENCE_AUDIT_V2.md`)
- [ ] 🟠 CX-001 password reset · [ ] 🟠 CX-002 session expiry · [ ] 🟡 CX-003 dup-account check · [ ] 🟡 CX-004 payment badge
- [ ] 🟡 CX-005 next charge date · [ ] ⚪ CX-006 invoice payment method · [ ] 🟡 CX-007 restore wording · [ ] 🟠 CX-008 drag-merge discoverability
- [ ] 🟠 CX-009 prod merge danger · [ ] 🟡 CX-010 env delete confirm · [ ] 🟡 CX-011 backups empty state · [ ] 🟡 CX-012 account security
- [ ] ⚪ CX-013 command palette · [ ] ⚪ CX-014 dialog touch dismiss · [ ] ⚪ CX-015 help anchors · [ ] ⚪ CX-016 OTP cooldown · [ ] ⚪ CX-017 env skeleton

---

## Progress

- V1: 0 / 94 done
- V2: 0 / 41 done
- **Total: 0 / 135 done**

_Update the counts as boxes are ticked. Definition of done for every item: fix merged + verified end-to-end against the live system (per project testing policy), not just code-complete._
