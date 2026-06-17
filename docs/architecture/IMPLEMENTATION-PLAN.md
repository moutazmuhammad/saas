# Implementation Plan — Evolving the Existing Platform toward architecture-spec-v1

**Goal of this plan:** take the EXISTING production system and evolve it, phase by phase, into the
target design in `architecture-spec-v1.md` — without a rewrite and without breaking production.
**Mode:** planning ahead (no imminent large customer). Order by dependency + risk, not urgency.
**Codebase:** `/home/moutaz/Documents/Work/odoo18/custom/saas` (modules `saas_core` + `saas_website` + SPA `veltnex`).
**Live:** https://odoo.odex.sa (`165.22.69.199`, DB `veltnex`), server repo `/home/odoo/saas`, branch `newhosting`.
**Start date:** 2026-06-17
**This file is the living reference:** update the progress log in §10 after every step.

> Target architecture: `architecture-spec-v1.md`. Existing-system log: `…/saas/SESSION_NOTES.md` (read before resuming).
> **Granular executable steps:** `PHASE-BREAKDOWN.md` — every phase decomposed into small verifiable units. Execute from there.

---

## 0. As-built vs. target — the gap we are closing

Odoo 18 IS the Control Plane today (provisions Odoo containers on remote hosts over SSH/paramiko).
Each phase below moves one spec component from "as-built" to "to-spec".

| Spec component | As-built today | Gap to close (phase) |
|---|---|---|
| Control Plane (§1) | Odoo module — keep this choice | refactor god-model (cross-cutting) |
| API Layer (§1.2) | `saas_website/controllers/api.py` | OK; tidy as we go |
| Reconciliation Engine (§1.3) | recovery crons (stuck/pending) | formalize desired→actual loop (Phase 3) |
| Compute Driver (§1.4) | Docker/SSH hardcoded in `saas_instance.py` | extract ComputeDriver seam (Phase 1) |
| Data Service (§1.5) | scattered (backup model + `_pg_clone_db` + `_restore_snapshot`) | consolidate to SNAPSHOT/MATERIALIZE (Phase 1) |
| Build Pipeline (§1.6) | source clone + build on host (verify) | immutable registry images by SHA (Phase 2) |
| Billing (§1.7) | extensive (wallet/pricing/v49) | keep; do not disturb |
| Placement Service (§1.8) | `saas_server`/`saas_region` + `_allocate_*` | formalize interface (Phase 6) |
| Observability (§1.9) | basic usage sampling | metrics stack + tenant_id + margin (Phase 4) |
| PostgreSQL system of record (§2.1) | meta in Odoo DB; 1 DB/tenant | add tiers + replica (Phase 5) |
| Object Storage (§2.2) | local `cp -a` filestore; S3 only for snapshots | object-storage-first filestore (Phase 2) |
| Container Registry (§2.3) | source-based (verify) | introduce registry + SHA tags (Phase 2) |
| Deployment Flow (§3) | `_do_deploy` over SSH | immutable image deploy + health gate (Phase 2–3) |
| Backup/Restore Flow (§4–5) | restic + PG-template clone | wrap in DataService; tested restore (Phase 1) |
| Upgrade Flow (§6) | manual | clone-upgrade-promote via DataService (Phase 7) |
| Per-tenant scale-out | one container/host, one DB | scale-out tier (Phase 5) |

**Dominant risk threaded through everything:** `saas_instance.py` = 11,334 lines / 248 methods (god-model).
Each phase peels one concern out of it behind tests; no big-bang rewrite.

**Invariants we must establish early (spec principles P1–P6):** desired-state-as-truth, disposable
compute, one driver interface, edition-as-attribute, `tenant_id` on all telemetry. These are what make
"scale to thousands of tenants without a Control-Plane rewrite" true.

---

## Phase 0 — Audit & safety net (prerequisite for all phases)

Goal: know the as-built behavior precisely and lock it with tests before changing anything.

- [ ] Read `SESSION_NOTES.md`, `docker/SERVER-SETUP.md`, `docker/README.md` fully.
- [ ] Stand up a LOCAL Odoo 18 dev environment (DB + addons path + python deps: paramiko/jinja2/boto3/gcs).
- [ ] Document the as-built flows: provisioning (`action_deploy→_do_deploy→_provision_postgresql→
      _render_and_write_configs`), backup/restore/clone, billing crons.
- [ ] Inventory the god-model's 248 methods into bounded concerns (provisioning · PG ops · environments ·
      billing/wallet · usage/metrics · deploy/build · crons) — these are the decomposition seams.
- [ ] Catalog every hardcoded Docker/SSH call site (the future ComputeDriver boundary).
- [ ] **Verify** whether deploys are source-clone (mutable) or image-based — decides Phase 2 scope.
- [ ] Write characterization tests around provisioning + a full backup→restore round-trip (the safety net).

**Acceptance:** an as-built architecture map + concern inventory + a green test that proves a tenant can
be provisioned, backed up, destroyed, and restored.

---

## Phase 1 — Seams: ComputeDriver + DataService (spec §1.4, §1.5)

Goal: stop business logic from calling Docker/SSH directly; unify state ops. No behavior change.

- [ ] Define `ComputeDriver` interface: `create / destroy / start / stop / exec / logs / endpoint / health`.
- [ ] Implement `SshDockerDriver` = move existing paramiko/Docker calls behind it (the ONE impl).
- [ ] Replace direct call sites in `saas_instance.py` with driver calls (incrementally, test each).
- [ ] Define `DataService` with two primitives — `snapshot(tenant)` and `materialize(snapshot, target)` —
      wrapping existing restic + PG-template-clone + `_restore_snapshot` logic.
- [ ] Express backup / restore / clone as compositions of those primitives (+ a `neutralize` step for non-prod).

**Acceptance:** no Docker/SSH reference outside `SshDockerDriver`; backup/restore/clone behave identically
and pass the Phase-0 tests; a future `KubernetesDriver` would be a new file, not a rewrite.

---

## Phase 2 — Storage to spec: object-storage filestore + container registry (spec §2.2, §2.3, P2)

Goal: make compute disposable. This is the prerequisite for multi-host scale-out (Phase 5) and clean rollback.

- [ ] Object-storage-first filestore via an object-backed POSIX layer (JuiceFS) — NOT the Odoo S3 module,
      NOT raw s3fs. Local NVMe cache for hot files. Replaces `cp -a`.
- [ ] Migrate existing tenants' filestores onto it (one-time, per tenant, behind DataService).
- [ ] Introduce a container registry; build immutable tenant images tagged `tenant-<ver>-<sha>` (base image
      per Odoo version + tenant layer: custom modules + pip). Platform-generated Dockerfile (security boundary).
- [ ] Deploy = pull image by SHA (immutable) instead of clone-and-build-on-host. Rollback = previous SHA.
- [ ] Isolate the build worker (ephemeral, rootless, no credentials) — it runs untrusted customer code.

**Acceptance:** a tenant runs from a registry image by SHA with filestore in object storage; killing the host
and recreating the container elsewhere loses no data; rollback to a prior SHA works.

---

## Phase 3 — Reconciliation Engine + desired-state model (spec §1.3, §3, P1)

Goal: one idempotent loop drives reality toward desired state; replaces ad-hoc recovery crons.

- [ ] Add explicit desired-state fields (running/stopped + target image SHA) to the instance model.
- [ ] Build a reconciliation loop: read desired, read actual (`driver.health`), converge; idempotent + crash-safe.
- [ ] Fold the existing recovery crons (`_cron_retry_pending_provision`, `_cron_recover_stuck_provisioning`)
      into the reconciler.
- [ ] Health gate before admitting traffic on (re)deploy.

**Acceptance:** killing a container is auto-corrected by the reconciler; a half-failed deploy converges or
rolls back deterministically.

---

## Phase 4 — Observability & per-tenant margin (spec §1.9, P6)

Goal: see revenue − cost per tenant; mandatory `tenant_id` taxonomy from now on.

- [ ] Define and enforce the `tenant_id` label on all metrics/logs (hard to retrofit — do it now).
- [ ] Stand up VictoriaMetrics + Grafana (+ Loki later); ingest container stats + existing `_refresh_usage`.
- [ ] Margin dashboard: per-tenant cost (CPU/RAM/storage/egress) vs. billed revenue (wallet/plan).
- [ ] Alerts on unprofitable / runaway tenants.

**Acceptance:** one Grafana dashboard shows per-tenant margin from live data.

---

## Phase 5 — Tiered PostgreSQL + large-tenant scale-out tier (spec §2.1, scalability)

Goal: support a single large tenant (1000 users, millions of records, heavy reports) — as a PAID TIER, not
the default. Depends on Phase 2 (shared filestore) + Phase 1 (driver/DataService).

- [ ] Schema: model an instance as a SET — `container_ids` (N app workers) + 1 cron node (only one runs
      `ir.cron`) + 1 gevent/longpolling node.
- [ ] Load balancer (HAProxy/nginx) in front + sticky or shared sessions (replace `upstream=127.0.0.1`).
- [ ] PostgreSQL tiers: shared (Starter) → dedicated tuned (Business) → dedicated + PITR (Enterprise);
      tier = operational attribute, decoupled from billing plan.
- [ ] PgBouncer pooling + a read replica; route heavy reports/exports to the replica.
- [ ] Promotion between tiers via DataService `migrate` (size/load triggers).

**Acceptance:** one tenant served by ≥2 app containers across hosts behind an LB, sharing one DB + shared
filestore, reports hitting the read replica, with zero impact on other tenants.
**Honest ceiling (state to stakeholders):** a single Odoo DB cannot be sharded; one tenant's writes are
bounded by one PG primary. Beyond the biggest tuned box the levers are app-side (indexing, partitioning,
archiving). "Millions of records slow" is often a data-model problem, not only infra.

---

## Phase 6 — Placement Service + second ComputeDriver (spec §1.8, P3) — future

Goal: realize "no rewrite" by adding Kubernetes behind the same seams.

- [ ] Formalize a `Placement` interface (host + PG tier decision); v1 returns current `_allocate_*` logic.
- [ ] Implement a `KubernetesDriver` against the Phase-1 interface; pilot a subset of tenants.
- [ ] Keep PostgreSQL on dedicated hosts/managed PG — do NOT move tenant DBs onto K8s storage.

**Acceptance:** a tenant can be scheduled by Placement and run under either driver with no Control-Plane change.

---

## Phase 7 — Upgrade Flow: clone-upgrade-promote (spec §6) — future

- [ ] Odoo version migration (16→17→18) as a DataService op: clone → migrate (OpenUpgrade/official) → validate
      on staging URL → promote via cutover; original kept as instant rollback.
- [ ] Tier/server migration + major PG engine upgrades reuse the same clone-validate-promote discipline.

**Acceptance:** a tenant is upgraded to the next Odoo version with a tested rollback path and no in-place mutation.

---

## Cross-cutting — god-model decomposition (every phase)

Each phase extracts its concern out of `saas_instance.py` behind characterization tests (delegate to a new
model/mixin/service; never big-bang). Target end-state: `saas_instance` is a thin aggregate; provisioning,
PG ops, deploy, usage, billing live in focused units.

---

## 8. Do-NOT-revert rules (carried from SESSION_NOTES)

- Pricing: yearly discount = infra only; cheapest region = default; backup billed at checkout.
- Environments: children (staging/dev) never self-bill; excluded from crons via `parent_id=False`.
- Backup: daily = restic deduplicated; on-demand = zip ephemeral (keep separate).
- Hosting DB create = PG template clone (`__odoo_template_<sub>` + `CREATE DATABASE WITH TEMPLATE` + filestore copy).
- Deploy: stale cache → always `systemctl restart odoo`; XML/view change → `-u <module>`; SPA build breaks on
  unused imports (`tsc noUnusedLocals`).

## 9. Security follow-up

- [ ] Confirm the root SSH password was rotated (was typed into chat previously). Priority.

---

## 10. Progress Log (kept up to date)

| Date | Phase | What was done | Status | Notes |
|------|-------|---------------|--------|-------|
| 2026-06-17 | — | Wrote architecture spec v1 | ✅ | target design |
| 2026-06-17 | — | Discovered existing production system; reframed plan to "evolve toward spec" | ✅ | god-model + per-tenant scale gaps identified |
| 2026-06-17 | — | Wrote this phased realization roadmap (Phases 0–7) | ✅ | ordered by dependency, not urgency |
| 2026-06-17 | — | Decomposed all phases into granular steps → `PHASE-BREAKDOWN.md` | ✅ | step IDs 0.1.1 … 7.2 |
| 2026-06-17 | 0 | 0.1.1 machine inventory: Odoo18 src, PG12+PG14, Docker, Node, venv `.env` (py3.12) all present | ✅ | no git token needed |
| 2026-06-17 | 0 | 0.1.2–0.1.4 deps present in `.env`; fresh DB `saas_dev` installed `saas_core`+`saas_website` clean (exit 0) | ✅ | only harmless warnings |
| 2026-06-17 | 0 | 0.3.1 ran suite: baseline RED (3/54 failed); root-caused as STALE tests; fixed → GREEN (0 failed of 54) | ✅ | see PHASE-0-FINDINGS.md |
| 2026-06-17 | 0 | Branch `architecture-evolution` created; docs + test fixes committed & pushed to origin | ✅ | repo `docs/architecture/` is now canonical |
| 2026-06-17 | 0 | 0.2.2/0.2.8 as-built map + deploy mechanism (hybrid base-image + mounted source) → `AS-BUILT.md` | ✅ | confirms Phase-2 scope |
| 2026-06-17 | 0 | 0.2.6 driver-boundary catalog (~140 docker sites; transport already clean) → `DRIVER-BOUNDARY.md` | ✅ | direct Phase-1 input |
| 2026-06-17 | 1 | 1.1.1 defined `ComputeDriver` interface + `ComputeSpec`/`ComputeHandle`/`ExecResult`/`HealthStatus` (drivers/base.py) | ✅ | additive, not wired in; baseline still green |
| 2026-06-17 | RT | Stood up real test server (165.245.245.196); prepped PG/nginx/restic/docker + odoo:18.0 | ✅ | minimal footprint (root, PG→docker subnet) |
| 2026-06-17 | RT | **Provisioned a REAL tenant via `_do_deploy` end-to-end** — container healthy, HTTPS+SSL, 303 login | ✅ | `REAL-TEST-RESULTS.md`; idle ~200MiB |
| 2026-06-17 | RT | Real DB create (`rt1_rtdb`, odoo-light+source) — HTTP 200; found official-image breaks template build | ✅ | Test 2 |
| 2026-06-17 | 0 | **Phase 0 ACCEPTANCE MET on real infra**: backup→restore round-trip PASS (marker gone, data intact, 200) | ✅ | Test 3 — DataService proven |
| 2026-06-17 | 1 | 1.2 implemented `SshDockerDriver` (start/stop/restart/exec/logs/endpoint/health) + `_compute_driver`/`_compute_handle` on instance | ✅ | additive; not yet routing call sites |
| 2026-06-17 | 1 | **Verified `SshDockerDriver` against LIVE rt1** (health/exec/logs + real stop→start) | ✅ | real-infra proof |
| 2026-06-17 | 1 | Unit baseline GREEN on clean DB `saas_ci` (54/54). NB: `saas_dev` now dirty w/ real-test data | ✅ | use saas_ci for unit tests |
| 2026-06-17 | 1 | 1.3 routed `_do_stop`/`_do_restart` → driver (2 of ~140 sites); removed inline `docker stop`/`restart` | ✅ | UserError semantics kept |
| 2026-06-17 | 1 | Added `test_compute_driver.py` (5 tests: cmd-building + routing + error-wrap); 59/59 green on saas_ci | ✅ | unit |
| 2026-06-17 | 1 | Real test: routed lifecycle on LIVE rt1 (running→stopped→running) | ✅ | real-infra |
| 2026-06-17 | 1 | 1.4 added `DataService` (snapshot/materialize) delegating to proven restic backup + 5-step restore | ✅ | seam, no rewrite |
| 2026-06-17 | 1 | `test_dataservice.py` (4 tests); 63/63 green on saas_ci | ✅ | unit |
| 2026-06-17 | 1 | Real test: DataService snapshot→materialize on LIVE rt1 (marker gone, data intact, 200) | ✅ | real-infra |
| 2026-06-17 | 1 | 1.3 driver gains `service_exec` + connection-reuse; routed `_docker_exec_sql`/`_docker_exec_python` (4 more sites) | ✅ | faithful, no perf regression |
| 2026-06-17 | 1 | 2 new unit tests (service_exec cmd + conn reuse); 65/65 on saas_ci | ✅ | unit |
| 2026-06-17 | 1 | Real test on LIVE rt1: routed `_docker_exec_sql` (SELECT 1→1) + `_docker_exec_python` (PYEXEC_OK) | ✅ | real-infra |
| 2026-06-17 | 1 | Driver stop/restart → raw `docker stop/restart <container>` (faithful to original; serves raw containers too) | ✅ | re-verified on rt1 |
| 2026-06-17 | 1 | Routed `saas_docker_container` admin stop/restart actions through driver (2 more sites) | ✅ | unit + 66/66 saas_ci |
| 2026-06-17 | 1 | Routed 2 redeploy/config-refresh `down+up` sites → driver.destroy+start (conn reuse) | ✅ | 66/66 saas_ci |
| 2026-06-17 | 1 | Real test on LIVE rt1: driver destroy→start recreates container, serves 200 | ✅ | real-infra |
| 2026-06-17 | 1 | Routed `_do_suspend` + restore-path pre-stop → driver.stop (2 more raw-stop sites) | ✅ | 66/66 saas_ci |
| 2026-06-17 | 1 | Real test on LIVE rt1: routed suspend (running→suspended→running) | ✅ | real-infra |
| 2026-06-17 | 1 | Routed 2 restore-path `up` sites → driver.start(conn reuse); 66/66 saas_ci | ✅ | driver.start already real-proven |
| 2026-06-17 | 1 | RESOLVED: empty-backup root cause = my integrity-marker tables were superuser-owned → tenant `pg_dump` hit "permission denied" | ✅ | NOT a bug/regression; dropped markers, backup OK |
| 2026-06-17 | 1 | Clean DataService round-trip re-verified on rt1 (TENANT-owned marker gone, users=5, 200) | ✅ | lesson: integrity markers must be owned by the tenant role |
| 2026-06-17 | 1 | Added driver.stats; routed `_refresh_usage_with_ssh` docker-stats call (conn reuse) | ✅ | 67/67 saas_ci |
| 2026-06-17 | 1 | Real test on LIVE rt1: driver.stats + action_refresh_usage (cpu/mem parsed OK) | ✅ | real-infra |
| 2026-06-17 | 1 | **Routed the first-`_do_deploy` `up` → driver.start** (the critical provisioning path) | ✅ | capstone |
| 2026-06-17 | 1 | Real test: provisioned a FRESH tenant rt2 end-to-end — healthy, HTTPS 303, own port/SSL; rt1+rt2 both running | ✅ | multi-tenant via driver |

**Local env quick reference:**
- venv: `/home/moutaz/Documents/Work/odoo18/.env` (py3.12, all deps). Config: `odoo18/odoo.conf` (PG12 @5432, user odoo18, addons incl. custom/saas).
- Run: `cd odoo18 && ./.env/bin/python odoo/odoo-bin -c odoo.conf -d saas_dev`. Disposable dev DB: `saas_dev` (don't touch `saas`/`saas_test`).

**Blockers / open decisions:**
- ❓ Verify deploy is source-clone vs image-based (decides Phase 2 scope) — step 0.2.8.
- Minor: duplicate field labels + view-accessibility warnings in saas_core (cosmetic; track during 0.2.7).

---

## 11. Immediate next step

Begin **Phase 0**: set up local dev for the Odoo 18 stack + write the as-built map and the
provision→backup→restore characterization test (the safety net every later phase depends on).
