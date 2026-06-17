# Phase 1 Status — ComputeDriver + DataService seams

**Date:** 2026-06-17 · **Branch:** `architecture-evolution`
**Outcome:** the substantive Phase 1 goal is met — every important code path runs through the
`ComputeDriver` / `DataService` seams, each verified on **real infrastructure** (live tenants `rt1`, `rt2`).

---

## What exists now
- `saas_core/drivers/base.py` — `ComputeDriver` ABC + Odoo-free descriptors (`ComputeSpec`,
  `ComputeHandle`, `ExecResult`, `HealthStatus`).
- `saas_core/drivers/ssh_docker_driver.py` — the single v1 impl. Capabilities:
  `start` / `stop` / `restart` / `destroy(purge=)` / `exec` / `service_exec(env=)` / `stats` / `logs` /
  `endpoint` / `health`, with **optional connection reuse** (pass an open `SSHConnection`).
- `saas_core/dataservice/service.py` — `DataService.snapshot()` + `materialize()` (delegate to the
  proven restic backup + 5-step restore).
- `saas.instance._compute_driver(connection=)` / `_compute_handle()` / `_data_service()`;
  `saas.docker.container._driver_handle()`.

## Call sites routed (~23) — all real-proven
provision (first `_do_deploy` `up`) · template build (`down`/`up`) · backup→restore round-trip ·
`_do_stop` / `_do_restart` / `_do_suspend` · redeploy down+up · config-refresh down+up ·
addons-restart down+up · restic-restore Step2/Step5 · zip-restore pre-stop · cancel/teardown
`down -v --remove-orphans` · `_docker_exec_sql` · `_docker_exec_python` · `_refresh_usage` stats ·
`saas_docker_container` admin stop/restart.

## Real-infra evidence (live server 165.245.245.196)
- Provisioned a fresh tenant `rt2` end-to-end (own port + Let's Encrypt SSL, HTTP 303→200).
- Created `rt2_rtdb` (template build) → HTTP 200.
- Backup→restore round-trips on `rt1` ×3 with tenant-owned marker integrity (marker vanishes on
  restore, `res_users` intact, HTTP 200).
- Lifecycle (stop/restart/suspend), destroy+start recreate, purge+recreate (data survives) — all verified.
- `rt1` + `rt2` both healthy and serving 200 after all churn.
- **66/66 unit tests** green on clean DB `saas_ci` (`test_compute_driver.py`, `test_dataservice.py`).

## Remaining tail (~10 bespoke call sites — finish in a focused pass)
Each needs a small, deliberate decision, NOT a mechanical reroute:
1. `_sample_live_metrics_for_host` — a **host-batch** `docker stats` over many containers at once;
   add a `stats_many(container_names)` driver method (doesn't fit per-handle `stats`).
2. `_docker_exec_*` pip-install helpers — use `bash -c` (driver `exec` uses `sh -c`); add a
   `shell=` option to `exec`, then route. Trigger needs custom pip packages to real-test.
3. deploy **wait-loop** `docker inspect` poll — replace the bash loop with a `health`-based poll.
4. one health-check `docker inspect` (`{{.State.Status}}|{{.RestartCount}}`) and a repair/upgrade `up`.

**Definition of done:** real `docker `-command call sites in `saas_instance.py` = 0 (remaining grep hits are
comments / log strings), unit suite green, and a fresh end-to-end re-provision + backup/restore on the
server still passes. At that point a `KubernetesDriver` is purely a new file.

## Note
Routing the tail above is best done with a fresh context budget so the bespoke nuances (host-batch,
shell choice, poll semantics) are handled without behavior drift. The high-risk, design-bearing work
(provisioning, template build, backup/restore, lifecycle) is complete and proven.
