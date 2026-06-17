# Real-Test Results (live integration on 165.245.245.196)

**Date:** 2026-06-17 · **Branch:** `architecture-evolution`
Validating the platform against a real server, not just local unit tests. Setup: see `REAL-TEST-SETUP.md`.

---

## ✅ Test 1 — End-to-end provisioning (PASS)
Registered control-plane records in `saas_dev` (script: `scripts/rt_register.py`) and ran the real
`saas.instance._do_deploy()` against the live server. Result: a real Odoo 18 tenant, provisioned entirely
through the platform's own code path.

Evidence (from the provisioning log + verification):
- PostgreSQL role `saas_rt1` created (hosting mode: customer creates DBs, so no DB auto-created).
- `docker-compose.yml` + `odoo.conf` rendered and written over SFTP.
- Container **`odoo_rt1` created, started, and reports `healthy`** (image `odoo:18.0`).
- Nginx reverse proxy written + reloaded; **Let's Encrypt SSL obtained for `rt1.odoo.odex.sa`**
  (DNS for the subdomain resolves to the server — no manual DNS needed).
- Instance state → **running**; host ports 32000 (http) / 32001 (longpolling), bound to 127.0.0.1.

Verification:
- `curl http://127.0.0.1:32000/web/login` → **HTTP 303** (Odoo alive; redirects to DB selector since
  no database exists yet — expected for a hosting instance).
- `curl https://rt1.odoo.odex.sa/web/login` → **HTTP 303** (nginx + SSL proxy working).
- **Idle resource baseline: CPU ~2.4%, RAM ~199 MiB** (container limit 1.3 GiB).

### What this proves
The real provisioning pipeline works on a clean Ubuntu 24.04 + Docker + PostgreSQL 16 host: SSH transport,
PG role creation, config rendering, container lifecycle, nginx + automatic TLS. This is the integration
confidence local unit tests cannot give.

## Registration records (in `saas_dev`)
ssh key `cp-ed25519` (ed25519) · region `fra1` · server `rt-fra1` (docker+db, 165.245.245.196, root, host-key
pinned) · version `18.0` (`odoo:18.0`) · domain `odoo.odex.sa` · product/plan `RT Hosting`/`RT Plan` ·
partner `RT Customer` · instance `rt1` (production, running).

## Next tests (in progress)
- [ ] Create a database inside the tenant (so it's a usable Odoo, HTTP 200 on login).
- [ ] DataService round-trip: backup (restic → DO Spaces) → destroy → restore → verify; clone + neutralize.
- [ ] Resource baseline under a light, defined load (k6/Locust).

## Notes
- Per-tenant baseline (idle ~200 MiB) already informs the margin model (Phase 4) and scale math (Phase 5).
- Object-storage creds for the backup test are temporary/disposable and are **NOT** committed to the repo.
