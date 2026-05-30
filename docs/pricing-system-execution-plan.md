# Pricing System Redesign — Execution Plan (Source of Truth)

> **Status:** DESIGN APPROVED — implementation NOT started.
> **Owner module:** `custom/saas` (Odoo 18: `saas_core` + `saas_website` + React SPA `veltnex`).
> **This file is the source of truth.** Any engineer or AI session resuming this work should read this file top to bottom first, then jump to **§8 Continuation Instructions**.
>
> **Golden rule while executing:** do not break existing live subscriptions, and keep slider preview == checkout == stored `plan.price` at every step.

---

## 0. Progress Checklist (update this as you go)

Implementation order (details in §6). Tick when fully done + tested.

- [x] **S1** — Pricing engine model (single source of truth), reproduces current linear price. **Signature includes `region`.** → `saas_core/models/saas_pricing.py` (`saas.pricing.engine`, AbstractModel). Additive only; no caller repointed. Floor/region/add-ons wired as no-ops (defaults reproduce today's numbers). Deploy needs `-u saas_core` (new model). **Next: S2.**
- [x] **S2** — Repoint all callers (4× `main.py`, 1× `api.py`) to the engine. Add consistency test. → `custom_plan_calculate`, `hosting_calculate`, `_get_or_create_custom_plan`, `_get_or_create_hosting_plan` (main.py) + `_price` (api.py) all delegate to `saas.pricing.engine`; no inline `workers*rate + storage*rate` remains. Test: `saas_core/tests/test_pricing_engine.py` (engine == legacy formula across a grid; S1 no-ops; clamping; plan.price == engine). Behaviour-neutral. **Next: S3.**
- [x] **S3** — New config params (floor rates, storage block, policy flags) + `res_config_settings` UI. → `res_config_settings.py`: floor Floats (`hosting_worker_floor`, `hosting_storage_floor`, `worker_floor`, `storage_floor`), `storage_block_gb`(50)/`storage_block_price`(0), and two Booleans (`snapshots_count_toward_storage` default True = current, `custom_min_is_nearest_tier` default False) via manual get/set (Boolean trap). New "Pricing Engine" block in `res_config_settings_views.xml`. All defaults behaviour-neutral; engine already reads the floor keys (still 0 ⇒ no-op). **Next: S4.**
- [x] **S4** — `saas.plan` tier fields (`is_public_tier`, `is_recommended`, `badge`) + price≥floor validation + tiers API endpoint. → `saas_plan.py`: 3 fields + `_check_price_floor` `@constrains` (uses engine `_cost_floor`; skips trials; floor 0 ⇒ no-op). Engine `_tier_floor` reads `custom_min_is_nearest_tier` (default off ⇒ 0) and folds into `compute` (`floor = max(cost_floor, tier_floor)`); breakdown adds `cost_floor`/`tier_floor`. `GET /saas/api/v1/tiers?kind=` returns public tiers (`[]` until S9 seeds them). Tests extended (floor bites, constraint rejects below-floor, tier-floor blocks undercut). Default custom decision = available-to-all + guarded. Behaviour-neutral. **Next: S5.**
- [x] **S5** — `saas.addon` model; migrate Daily Snapshots onto it; checkout sums add-ons via engine. → new `saas.addon` (code/name/applies_to/monthly_price/price_config_param/active) + ACL + backend list/form view + Configuration menu. Seed `daily_snapshots` (data, noupdate) with `price_config_param=saas_master.hosting_daily_backup_price` so the live purchase/renewal/suspend flow is untouched (single source of truth). Engine `_addons_total` now sums via `saas.addon._sum_prices(kind, codes)`. Hosting configure display passes `addon_codes=['daily_snapshots']` when ticked → add-on flows through the engine. Test `test_addon_sum`. Behaviour-neutral. **Next: S6.**
- [x] **S6** — Snapshot policy flag; revert ½-snapshot from `total_storage_bytes`; overage uses block rate via engine. → `_refresh_usage_with_ssh` now adds the ½-snapshot only when `snapshots_count_toward_storage` is on (**default ON = current behaviour**; flip OFF in Settings = snapshots covered by the add-on, no double-charge). New engine `storage_overage(total_bytes, limit_gb)` → block-based when `storage_block_gb`/`storage_block_price` set, else legacy per-GB (behaviour-neutral default); `_generate_renewal_invoice` repointed to it. Test `test_storage_overage_per_gb_and_block`. **Next: S7 (region pricing).** NOTE: recommended production value of `snapshots_count_toward_storage` is **OFF** — owner decision.
- [~] **S7 (foundation done)** — Region pricing backend. DONE: `saas.region` model (code/name/price_multiplier/is_default/active + single-default & >0 constraints) + ACL + list/form view + Configuration→Regions menu; `region_id` on `saas.server` and `saas.instance` (instance defaults to `_get_default()`, fixed at create); engine `_region_multiplier` implemented (scales compute+storage only — add-ons unaffected, per decision #2); seed one Default region (×1.0, noupdate); `GET /saas/api/v1/regions`; test `test_region_multiplier_scales_compute_not_addons`. Behaviour-neutral (single ×1.0 region; legacy instances have no region ⇒ ×1.0). **DECISIONS: #1 custom=all (default kept), #2 compute+storage only, #3 fixed at create.**
- [x] **S7b** — Region ENFORCEMENT. DONE: `saas.server._region_match_domain(region)` (null-region servers = default region ⇒ behaviour-neutral; non-default region matches only assigned servers, never a cross-region fallback). `_allocate_docker_server`/`_allocate_overcommit_server` take `region=`; `_allocate_servers` passes `self.region_id`; `_allocate_db_server` region-filters the generic DB fallback → **docker + db co-located in the instance's region**. `instance.region_id` auto-set at create via field default (`_get_default()`). `_get_or_create_hosting_plan`/`_custom_plan` accept `region=` → engine multiplier (default None ⇒ ×1.0). `/regions` now returns `available` (region needs docker+db capacity). Test `test_region_match_domain_treats_null_as_default`. **REMAINING (folds into S8): proxy co-location** (proxy comes from `domain_id.proxy_server_id`; needs region-aware domain selection) and **passing the customer-picked region** into the create controllers + plan pricing (the picker is S8). Region pricing goes live once S8 wires the picker.
- [~] **S8** — SPA pricing UI. **S8a DONE:** unit rates no longer exposed — `/meta` strips `worker_price`/`storage_price_per_gb` (new `_public_plan_config`), removed from `PlanConfigMeta`; confirmed the SPA never used them (it prices via `hostingCalculate` → engine). `PlanBuilder` already takes a server-computed price (no client math). **S8b DONE:** `Hosting.tsx` renders `/tiers` (kind=hosting) as cards — recommended tier highlighted + `badge` (default "Most popular"), shared monthly/yearly toggle drives card prices via `config.cycle`, "Choose <tier>" → `/hosting/configure?workers&storage&billing`. Slider/`PlanBuilder` is behind a "Build a custom plan" toggle (`customize`), with "← Back to standard plans" to return. **Falls back to slider-only when `/tiers` returns `[]`** (none seeded yet ⇒ behaviour-neutral). Added `ApiTier` + `api.tiers(kind)` to `lib/api.ts`. `tsc --noEmit` + `vite build` clean. REMAINING: **S8c** region picker at create + pass region into create controllers/pricing + **proxy co-location** (region-aware domain selection — closes the 3-server rule). S8c is the riskiest (live signup/checkout) — do with care.
- [ ] **S9** — Seed example tiers (Starter/Pro/Business) + seed regions (with multipliers) as data records, placeholder values.

**Open decisions (answer before the dependent step):**
1. *(before S8, ideally S4)* Is the **custom slider** available to all customers (primary path) or limited to the top/Business tier (power-user fallback)? Changes configurator UX + the "custom ≥ tier" rule. Default assumption: **custom available to all, guarded so it can never price below the nearest tier.**
2. *(before S7)* **Region pricing scope:** does the region multiplier apply to (a) only the resource/compute+storage portion of the price, or (b) the whole price including add-ons? Default assumption: **(a)** — region scales compute+storage+floor; add-on prices (e.g. snapshots, which live in object storage) stay region-agnostic unless an add-on opts in.
3. *(before S7)* **Region after purchase:** is region fixed at create (changing it = a migration flow, out of scope here), or changeable later? Default assumption: **fixed at create.**

**Answers**
1. Custom Slider: ALL users (bounded by tiers)
2. Region Scope: compute + storage only
3. Region Mutability: fixed at creation
---

## 1. Current System Overview

### 1.1 How pricing works today
Hosting is **custom-plan-per-configuration**, priced by a single **linear formula**:

```
monthly_price = workers * worker_price + storage_gb * storage_price_per_gb
```

There are **two independent rate sets** (read from `ir.config_parameter`):

| Domain | worker price key (default) | storage/GB key (default) |
|---|---|---|
| Services (`/services`) | `saas_master.worker_price` (15.0) | `saas_master.storage_price_per_gb` (0.5) |
| Hosting (`/hosting`) | `saas_master.hosting_worker_price` (10.0) | `saas_master.hosting_storage_price_per_gb` (0.3) |

There are **no named tiers** (no Starter/Pro/Business records). Each chosen `(workers, storage)` creates/looks up a `saas.plan` with `is_custom=True`.

### 1.2 Where the formula lives (DUPLICATED — key problem)
The same arithmetic is reimplemented in 5 places:
- `saas_website/controllers/main.py` — services calc (~line 328)
- `saas_website/controllers/main.py` — hosting calc (~line 370)
- `saas_website/controllers/main.py` — `_get_or_create_custom_plan` (line 526)
- `saas_website/controllers/main.py` — `_get_or_create_hosting_plan` (line 752)
- `saas_website/controllers/api.py` — `_price` (line 311)

### 1.3 Config (already mostly externalized — good foundation)
Read via `ir.config_parameter`, surfaced in `saas_core/models/res_config_settings.py`:
- Services: `worker_price`, `storage_price_per_gb`, `custom_plan_min_workers`(2), `custom_plan_max_workers`(8), `custom_plan_min_storage`(5), `custom_plan_max_storage`(200), `custom_plan_cpu_per_worker`(0.5), `custom_plan_ram_per_worker`(512), `custom_plan_users_per_worker_min`(6), `custom_plan_users_per_worker_max`(10).
- Hosting: `hosting_worker_price`(10), `hosting_storage_price_per_gb`(0.3), `hosting_min_workers`(2), `hosting_max_workers`(8), `hosting_min_storage`(5), `hosting_max_storage`(200), `hosting_cpu_per_worker`(0.5), `hosting_ram_per_worker`(512), `hosting_min_backups`(3), `hosting_max_backups`(14), `hosting_yearly_discount_pct`(20), `hosting_daily_backup_price`(5.0).
- Cross-cutting: `extra_storage_price_per_gb`, `resource_usage_multiplier`(2.0).

### 1.4 `saas.plan` model (`saas_core/models/saas_plan.py`)
Fields: `name`, `sequence`, `is_trial_plan`, `is_custom`, `price`, `yearly_price`, `yearly_discount_pct` (computed), `currency_id`, `cpu_limit`, `ram_limit` (Char e.g. "2g"), `workers`, `storage_limit` (GB), `max_backups`, `instance_count`, `recommended_users`, `grace_period_days`. `price` is **stored per plan** (set at custom-plan creation from the formula), not computed on read.

### 1.5 Data flow (backend → API → frontend)
- **SPA configurator** → `POST /saas/api/v1/services/calculate` (`api.py:services_calculate` → `_price`) returns server-computed totals. **But** `api.ts` `ConfigData` ALSO ships `worker_price` + `storage_price_per_gb` to the browser (`veltnex/src/lib/api.ts:102-103`), so the client can/also computes price → rate leak + a 6th formula site.
- **Checkout:** configure POST → `_get_or_create_hosting_plan(workers, storage, config)` → creates/returns `saas.plan` → `sale.order` line priced at `plan.price` → invoice. Payment confirmation handled in `saas_core/models/account_move.py`.
- **Plan change (upgrade/downgrade):** `saas_instance.action_request_plan_change` + proration; applied on payment via the `account_move` hook.

### 1.6 Add-ons today
Only **Daily Snapshots**: flat monthly `hosting_daily_backup_price`, gated by `daily_backup_enabled` / `daily_backup_suspended` / `daily_backup_pending_invoice_id` on `saas.instance`; monthly renewal cron + auto-suspend-on-non-payment (see `_cron_renew_daily_backup_addons`, `_sync_daily_backup_suspension`). No generic add-on abstraction.

### 1.7b Regions / servers (current state — relevant to new region pricing)
- Servers are `saas.server` records with **role flags** — `is_docker_host`, `is_db_server`, `is_proxy_server` (one server can hold multiple roles). `saas.server` fields confirmed in audit: `sequence`, `name`, the three role booleans, `company_id`, SSH/host fields, CPU/RAM capacity, base path. **There is NO `region`/`location` field today** (`grep -c region` on the model = 0).
- An instance references `docker_server_id` / `db_server_id` (and a proxy host for nginx routing). Server selection today is **automatic** (`saas_instance._allocate_servers`, least-loaded / overcommit / pending strategy) — the customer does **NOT** pick a region at create.
- "Region" is currently only a **read-only display label** derived from the allocated docker server: `_serialize_instance` returns `region = docker_server_id.name or domain_id.name`; the SPA shows it (`api.ts` `ApiInstance.region`).
- There is **no first-class region model, no per-region pricing, and no customer region choice.**
- **New requirements:** (1) the customer selects a **region** when creating an instance; (2) each region can have a **different server cost** → pricing must reflect it; (3) **the nginx (proxy), Odoo (docker), and PostgreSQL (db) servers for an instance must all be in the SAME region** (no cross-region instances — latency + data-residency + cost integrity). See §3.7.

### 1.7 Storage usage & overage
- Usage measured in `saas_instance._refresh_usage_with_ssh`: `du -sb` (instance dir) + `pg_database_size` → written to `total_storage_bytes` / `storage_usage_pct` (10-min cron `_cron_refresh_usage`; live CPU/RAM sampler is separate, see `project_live_metrics_architecture`).
- **Recent change to revert:** `total_storage_bytes` currently also adds `½ × _snapshot_total_bytes()` (the snapshot double-charge — see §2).
- Overage billed per-GB above `plan.storage_limit` via `_cron_check_storage_limits` using `extra_storage_price_per_gb`.

---

## 2. Problems Summary

**Architectural**
- **A1 — Formula duplicated in 5–6 places** (§1.2 + the client). No single source of truth → slider preview, checkout, and stored `plan.price` can silently diverge.
- **A2 — No first-class tier concept.** Names/order/recommended/badge/price can't change without code. Hosting is custom-only.
- **A3 — No generic add-on model.** Each add-on would be bespoke code.

**Bugs / inconsistencies**
- **B1 — Snapshot double-charge.** Customers pay the flat Daily-Snapshots add-on AND ½ the snapshot size counts toward storage (overage risk). Must pick one (default: add-on only).
- **B2 — Block vs per-GB mismatch.** Proposed storage "blocks" for purchase, but overage bills per-GB. Two units = disputes.

**Revenue risks**
- **R1 — Linear pricing = no upgrade pull, no volume margin.** Same per-unit at all sizes.
- **R2 — No price floor.** A cheap-workers + huge-storage config can be sold below cost.
- **R3 — Unit-rate leak** (`worker_price`, `storage_price_per_gb` exposed to client) reveals cost structure.
- **R4 — Region-agnostic pricing (NEW requirement gap).** The same price is charged regardless of which region/server hosts the instance, but server cost varies by region. Selling an instance in an expensive region at the cheap-region price **erodes (or eliminates) margin** there. Pricing must apply a per-region factor.

**UX risks**
- **U1 — A flat floor on top of linear pricing creates a discontinuity** ("+1 GB jumped the price"). Floor must come from the same cost-rate table and be enforced by validation, not a runtime kink.
- **U2 — Per-unit math shown** contradicts "<10s to understand."

**Maintainability**
- **M1 — Business logic split across controllers**, not centralized; hard to evolve pricing safely.

---

## 3. Target Architecture

### 3.1 Pricing engine — single source of truth (NEW)
`saas_core/models/saas_pricing.py` → model `saas.pricing.engine` (or a stateless service model). Single entry point:

```
compute(kind, workers, storage, billing, addon_codes=(), region=None) ->
    { monthly, yearly, monthly_equivalent, breakdown, floored: bool,
      region_factor, limits }
```
- `kind` ∈ {`hosting`, `services`} selects the rate set (keep both; one engine).
- Reads ALL rates/limits/discount from config (§3.6). Clamps workers/storage to min/max.
- `base = workers*worker_price + storage*storage_price_per_gb` (preserves current behavior).
- `floor = workers*worker_floor + storage*storage_floor` (cost-derived, config).
- **Region factor** (see §3.7): `resource_price = max(base, floor) * region_multiplier(region)`. The floor scales with the region too, so margin is protected in costlier regions. `region=None` ⇒ multiplier `1.0` ⇒ identical to today.
- Default policy (Open decision #2): the region multiplier applies to the **compute+storage portion only**; `addons` are summed at their flat (region-agnostic) prices unless an add-on opts into region scaling.
- `price = resource_price + addons_total`. Set `floored=True` when the floor bound.
- Optional rule "custom ≥ nearest public tier price" (config toggle) — compared **within the same region**.
- Yearly via per-plan `yearly_price` when set, else `monthly*12*(1-discount)`.
- **Everything else calls this. No other code computes price.** Region is just one more input to the single engine — never a second pricing path.

### 3.2 Plans system — configurable tier registry
Extend `saas.plan` (it already holds price/limits): add `is_public_tier` (bool), `is_recommended` (bool), `badge` (Char); reuse `sequence` for display order. Admin edits tiers (name, price, included workers/storage, order, recommended, badge) entirely in the backend — no code. `is_custom` plans remain for slider builds. `@constrains` rejects any tier with `price < engine.floor(workers, storage)`.

### 3.3 Add-ons system
`saas_core/models/saas_addon.py` → `saas.addon`: `code`, `name`, `monthly_price` (or config-param-backed), `applies_to` (hosting/services), `active`. Seed **Daily Snapshots** as the first record (migrate from the standalone `hosting_daily_backup_price` while keeping that key as its price source for backward compat). Engine sums selected add-ons. New add-ons = new records, no code.

### 3.4 Storage model
Included allowance per tier (`storage_limit`). Expansion AND overage priced in the **same configurable block** (`storage_block_gb`, `storage_block_price`). One unit everywhere; overage cron uses the block rate via the engine.

### 3.5 Snapshot model
Config flag `snapshots_count_toward_storage` (default **false**). When false (recommended): snapshots are covered by the Daily-Snapshots add-on and are NOT added to `total_storage_bytes` → revert the ½-snapshot logic. When true: a single, clearly-disclosed policy (no flat add-on overlap). Never both.

### 3.7 Region pricing model (NEW)
**Goal:** the customer chooses a region at instance create; each region can carry a different price because server cost differs; the engine reflects it.

- **Region as configurable data.** Introduce a first-class region (either a new `saas.region` model, or — if `saas.server` already has a region/location field, confirm in audit — a small region registry). Fields: `code`, `name`, `price_multiplier` (Float, default `1.0`), `active`, `sequence` (display order), optional `default` flag, optional `currency_id`. All admin-editable, no code.
- **Multiplier, not a second rate table.** Final resource price = engine resource price × `region.price_multiplier`. One multiplier per region keeps it simple to reason about and to display ("Frankfurt +20%"). (A full per-region rate table is possible later but is over-engineering for v1 — a multiplier covers "server costs more here.")
- **Floor scales with region.** The floor is multiplied by the same factor so an expensive region can't be sold below its own cost.
- **Region ↔ servers.** Each `saas.server` gets a `region_id` (new field — confirmed absent today). `_allocate_servers` must allocate **only within the customer-chosen region**; if a region has no capacity, fall back to the existing pending/overcommit logic *within that region* (do not silently move the customer to a cheaper/different region they didn't pick).
- **Co-location is mandatory (hard rule).** All three server roles for an instance — **proxy/nginx host, docker/Odoo host, and PostgreSQL/db host — MUST be in the same region.** `_allocate_servers` selects the docker host, db host, and proxy host all filtered to the chosen region's servers. A region is only **selectable/available** if it has capacity in **all three** required roles; if any role is missing in a region, that region is hidden from the selector (and rejected server-side). Never split an instance across regions.
- **Availability.** A region may be enabled/disabled globally and (optionally, later) per tier; it is only offered when it satisfies the co-location rule above. Disabled/incomplete regions don't appear in the selector.
- **Region is fixed at create** (Open decision #3, default) — recorded on the instance (`region_id`). Plan upgrades/downgrades keep the same region and re-price through the engine with that region's multiplier (so an upgrade in an expensive region prices correctly).
- **Add-ons** are region-agnostic by default (snapshots live in object storage); a per-add-on `region_scaled` flag can opt specific add-ons in later.
- **Display:** tier cards and the slider show prices for the **currently-selected region**; the engine endpoint is always the source (no client math). Region selector defaults to the configured `default` region.

### 3.6 Billing model / configuration
All business values live in config (`ir.config_parameter` + `res_config_settings` UI) and/or `saas.plan` records:
- Rates: worker price, storage/GB, floor rates (worker_floor, storage_floor).
- Limits: min/max workers, min/max storage (per kind).
- Storage block: size + price. Overage = same.
- Yearly: global discount % and/or per-plan `yearly_price`.
- Add-ons: per-record price.
- Tiers: name, price, included, order, recommended, badge (data records).
- Regions: per-region `price_multiplier`, active, order, default, region↔server mapping (data records).
- Policy flags: `snapshots_count_toward_storage`, "custom ≥ tier", "region multiplier applies to add-ons" (default off).

---

## 4. Migration Strategy (logical, not yet executed)

1. **Introduce the engine alongside existing code**, configured so it reproduces today's exact linear prices (floor rates default 0 / below base, no tiers, no new add-on behavior). Net price change = **zero**.
2. **Repoint callers** to the engine one by one; after each, assert the produced price equals the previous code's output for the same inputs (consistency test). Pure refactor.
3. **Layer new capabilities** (floor, tiers, add-on model, block storage, snapshot flag, **regions**) behind config defaults that keep current behavior until an admin turns them on. For regions: ship one default region at multiplier `1.0` and map all existing servers to it, so prices and allocation are identical to today until more regions/multipliers are configured.
4. **Frontend last:** switch SPA to tier cards + calculate-endpoint pricing; remove client math and rate exposure.
5. **Seed example tiers** with placeholder prices for the admin to edit.

**Backward compatibility**
- Existing `is_custom` plans and live `sale.order`/subscriptions are untouched (their stored `plan.price` is historical and remains valid).
- New columns are nullable/defaulted; new config keys have defaults that reproduce today.
- Checkout/upgrade still resolve a concrete `saas.plan` — unchanged contract.

---

## 5. System Rules (NON-NEGOTIABLE)

1. **No duplicated pricing logic.** Exactly one engine; all callers delegate.
2. **No frontend pricing calculations.** The SPA shows server-computed totals + tier defs only. Unit rates are NOT sent to the client.
3. **No hardcoded pricing values** in application logic. Rates, limits, discounts, floors, blocks, add-on prices, tier definitions all live in config/records.
4. **All business logic configurable** without code (names, order, recommended, prices, floors, validation, upgrade rules).
5. **No breaking existing subscriptions.** Historical prices preserved; defaults reproduce current behavior until an admin changes them.
6. **Consistency invariant:** for any `(kind, workers, storage, billing, addons)`, slider preview == configure == stored `plan.price` == checkout line == upgrade calc. Enforced by an automated test.
7. **Price floor by validation, not runtime kinks** where possible (tiers validated at write; custom clamped by engine).

---

## 6. Implementation Order (high level + WHY)

- **S1 — Pricing engine (`saas.pricing.engine`).** *Why first:* it's the foundation every other step delegates to. Built to reproduce the current linear result exactly (zero price change), so it's safe to merge before anything is wired.
- **S2 — Repoint all callers** (`main.py` ×4, `api.py:_price`) to the engine; add the consistency test. *Why second:* eliminates duplication (root cause A1/M1) with no behavior change — the safest high-value change, and it locks the invariant before adding features.
- **S3 — Config additions** (floor rates, storage block, policy flags) + `res_config_settings` UI. *Why third:* the engine needs these knobs to exist before the features that use them; defaults reproduce today.
- **S4 — `saas.plan` tier fields + validation + `/tiers` API.** *Why fourth:* introduces first-class tiers (A2) and the floor validation (R2/U1). Depends on engine (floor) + config.
- **S5 — `saas.addon` model + migrate Daily Snapshots + checkout sums add-ons.** *Why fifth:* generalizes add-ons (A3); depends on engine for summation.
- **S6 — Snapshot policy flag + revert ½-snapshot + overage uses block rate.** *Why sixth:* fixes B1/B2; depends on the config flag (S3) and add-on model (S5) for the "covered by add-on" semantics.
- **S7 — Region pricing: region model/registry + `price_multiplier`, region↔server mapping, region-aware `_allocate_servers`, engine applies the region factor.** *Why here:* depends on the engine (S1, region param) and config (S3); must land before the frontend so the create flow can offer region selection with correct prices. Fixes R4. Backward compatible: with one default region at multiplier 1.0, prices are unchanged.
- **S8 — Frontend: tier cards (recommended/default/badge from config) + region selector at instance create (price reflects region live), slider→calculate, remove client math + rate exposure.** *Why eighth:* the UI consumes everything above (tiers, add-ons, regions); doing it last avoids churn and closes R3/U2.
- **S9 — Seed example tiers + regions.** *Why last:* purely data; needs S4 + S7 fields present. Placeholder prices/multipliers the admin edits.

Each step is independently deployable and backward compatible.

---

## 7. Risk Areas & Migration Considerations

- **Price drift during S2:** mitigate with the consistency test comparing engine output to the old inline formula for a grid of inputs before deleting the old code.
- **`saas.plan` schema change (S4):** new columns → requires `-u saas_core`; backfill `is_public_tier=False` on existing custom plans.
- **Add-on migration (S5):** keep `hosting_daily_backup_price` as the snapshot add-on's price source so the live renewal/suspend flow (`_cron_renew_daily_backup_addons`, `_sync_daily_backup_suspension`, `account_move` hook) is undisturbed; only the *price lookup* indirection changes.
- **Snapshot revert (S6):** ensure `_cron_check_storage_limits` and the downgrade 75%-threshold gate read the corrected `total_storage_bytes` (they already read that single field — flipping the flag is enough).
- **Frontend caching (S7):** SPA bundle is hashed; require a hard refresh. Don't remove `/services/calculate` (kept as the pricing endpoint).
- **Two rate sets (hosting vs services):** keep both `kind`s in the engine; do NOT collapse them silently — they are distinct products.
- **Region (S7) — allocation safety + co-location:** `_allocate_servers` must never relocate a customer to a region they didn't choose, and must place the instance's **proxy, docker, and db hosts all in the same chosen region** (hard rule — see §3.7). A region is offered only if it has capacity in all three roles. If the chosen region is out of capacity, use the existing pending/overcommit path **scoped to that region**, never a cross-region fallback (cross-region would break co-location AND mean the wrong price was charged).
- **Region — pricing must be evaluated in the chosen region** at create AND at every upgrade/downgrade (pass the instance's `region_id` to the engine). A region change after create (if ever allowed) is a separate migration + re-pricing flow, explicitly out of scope here.
- **Region — backfill:** existing instances/servers get a single default region at multiplier `1.0` so historical prices and behavior are unchanged.
- **Deploy:** model/field/cron changes → `-u saas_core`; controller-only steps → restart; SPA steps → rebuild `veltnex` + hard refresh.

---

## 8. Continuation Instructions (resume safely from any point)

**To resume work later (new engineer or AI session):**

1. **Read this file fully**, then look at the **§0 Progress Checklist** to see which steps (S1…S8) are done.
2. **Assume state:** any unchecked step is NOT started; any checked step is implemented AND tested (consistency invariant holds). If unsure, re-run the consistency test (§ below) to confirm before proceeding.
3. **Resume at the lowest unchecked step.** Do not skip — steps depend on earlier ones (see §6 ordering rationale).
4. **For each step:** implement → keep all six System Rules (§5) → run the consistency invariant test → update the §0 checkbox in this file → note any deviation in §9 Change Log.
5. **Never** add a new place that computes price; route everything through `saas.pricing.engine`. **Never** ship unit rates to the client. **Never** change a default in a way that alters existing customers' prices without an explicit decision recorded in §9.
6. **Verify the invariant** (the single most important safety check): for a grid of `(kind ∈ {hosting,services}, workers ∈ min..max, storage ∈ min..max, billing ∈ {monthly,yearly}, addons ∈ {none, snapshots}, region ∈ {each active region})`, assert engine result == configure result == created `plan.price` == checkout order line == upgrade calc. If it holds, the refactor is safe. (Before S7, region collapses to the single default at ×1.0.)
7. **Open decisions** (top of §0): confirm (1) custom-slider scope, (2) whether the region multiplier applies to add-ons, (3) region fixed-at-create vs changeable — before the dependent steps.

**Key files to touch (reference):**
- Engine (new): `saas_core/models/saas_pricing.py`
- Add-ons (new): `saas_core/models/saas_addon.py`
- Region (new or extend `saas.server`): `saas_core/models/saas_region.py` (confirm whether `saas.server` already has a region/location field first)
- Plans: `saas_core/models/saas_plan.py`
- Server / allocation (region-aware): `saas_core/models/saas_server.py`, `saas_instance._allocate_servers` + `region_id` on `saas.instance`
- Settings/config: `saas_core/models/res_config_settings.py`
- Controllers (repoint + region in create/configure + region/tiers endpoints): `saas_website/controllers/main.py`, `saas_website/controllers/api.py`, `saas_website/controllers/registration.py`
- Storage/snapshot/overage: `saas_core/models/saas_instance.py`
- Frontend: `veltnex/src/pages/portal/*` (Plans/Configure/create), `veltnex/src/lib/api.ts`
- Data seed: `saas_core/data/*` (example tiers + regions)

---

## 9. Change Log (append as work proceeds)

- Initial blueprint created; no code changed.
- Added **region-based pricing** requirement: customer picks a region at instance create; each region has a configurable `price_multiplier` (server cost varies by region); engine applies the region factor to compute+storage+floor. See §1.7b, §2 (R4), §3.7, §3.6, §6 (S7/S8/S9), §7, §8. No code changed.
- Confirmed via audit: `saas.server` has role flags (`is_docker_host`/`is_db_server`/`is_proxy_server`) and **no region field today**; server selection is auto (`_allocate_servers`).
- Added **co-location hard rule**: an instance's nginx (proxy), Odoo (docker), and PostgreSQL (db) hosts must all be in the **same region**; a region is only selectable if it has capacity in all three roles; `_allocate_servers` must enforce this and never split across regions. See §1.7b, §3.7, §7. No code changed.
- **S2 IMPLEMENTED:** repointed all 5 inline-formula sites to `saas.pricing.engine` — `saas_website/controllers/main.py` (`custom_plan_calculate`, `hosting_calculate`, `_get_or_create_custom_plan`, `_get_or_create_hosting_plan`) and `saas_website/controllers/api.py` (`_price`). No `workers*rate + storage*rate` arithmetic remains in controllers (verified by grep). Added `saas_core/tests/__init__.py` + `saas_core/tests/test_pricing_engine.py` (engine reproduces legacy formula across a grid; S1 no-ops; clamping; created-plan price == engine quote). Behaviour-neutral. Run tests: `odoo -d <db> -u saas_core --test-enable --stop-after-init`.
- **S1 IMPLEMENTED:** added `saas_core/models/saas_pricing.py` (`saas.pricing.engine`, `AbstractModel`) + registered in `saas_core/models/__init__.py`. Reproduces the current linear formula per `kind` (hosting/services) exactly; `compute(kind, workers, storage, billing, addon_codes, region)` + `monthly_price(...)`. Floor (config keys default 0), region multiplier (1.0), add-on total (0.0) are no-ops so output == today. **No caller repointed yet (S2).** Deploy: `-u saas_core`.
