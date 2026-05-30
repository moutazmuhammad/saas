# Pricing — Operator Guide

How to configure the SaaS pricing system. **Every business value is
configurable from the admin UI** — the code holds no hard-coded prices.
The single source of truth is the `saas.pricing.engine` model; every
quote (SPA, hosting funnel, renewal invoice, plan creation) goes through
it, so a change here is reflected everywhere at once.

> Out of the box the system is **behaviour-neutral**: floors are 0, there
> is one ×1.0 "Default" region (so no region picker is shown), there are
> no published tiers (customers see the slider), and snapshots count
> toward storage. Nothing below changes prices until you change it.

---

## 1. Per-unit rates & limits — *Settings ▸ SaaS*

The base of every quote is
`workers × worker_price + storage × storage_price_per_gb`, clamped to the
min/max worker & storage limits, with a yearly discount. Hosting and the
custom "services" plan have **independent** rate sets.

| What | Config parameter |
|---|---|
| Worker price / month | `saas_master.hosting_worker_price`, `saas_master.worker_price` |
| Storage price / GB / month | `saas_master.hosting_storage_price_per_gb`, `saas_master.storage_price_per_gb` |
| Worker min/max | `saas_master.hosting_min_workers` / `..._max_workers` (+ `custom_plan_*`) |
| Storage min/max (GB) | `saas_master.hosting_min_storage` / `..._max_storage` (+ `custom_plan_*`) |
| Yearly discount % | `saas_master.hosting_yearly_discount_pct`, `saas_master.custom_plan_yearly_discount_pct` |

## 2. Price floors (never sell below cost) — *Settings ▸ SaaS ▸ Pricing Engine*

A floor guarantees a minimum regardless of the slider. The quote is
`max(base, cost_floor, tier_floor)`.

- **Cost floor** — `hosting_worker_floor`, `hosting_storage_floor`,
  `worker_floor`, `storage_floor`. Same shape as the per-unit rates but
  used as a *minimum*. Leave at `0` to disable.
- **Tier floor** — toggle **"Custom plan ≥ nearest tier"**
  (`custom_min_is_nearest_tier`). When on, a custom config that *contains*
  a published tier (≥ its workers **and** storage) can't be priced below
  that tier — stops a custom build from undercutting a named plan.
- A plan whose `price` is below its computed cost floor is **rejected on
  save** (`saas.plan._check_price_floor`); trials are exempt.

## 3. Named tiers (the cards) — *SaaS ▸ Plans*

Tiers are ordinary `saas.plan` records flagged for the storefront. With
**no** published tier the hosting page shows only the slider; publish one
or more and they render as cards (the recommended one highlighted), with
the slider moved behind a "Build a custom plan" toggle.

On the plan, set: **Is Public Tier** (`is_public_tier`) to publish it;
**Is Recommended** (`is_recommended`) to highlight + default it; **Badge**
(`badge`, e.g. "Most popular") for the ribbon; `sequence` for order; plus
the usual `workers`, `storage_limit`, `price`, `yearly_price`. The public
`/saas/api/v1/tiers` endpoint serves these to the SPA.

## 4. Add-ons — *SaaS ▸ Add-ons*

`saas.addon` records add a recurring monthly charge on top of the
resource price (add-ons are **not** scaled by region). Each has a `code`,
`applies_to` (hosting / services / both), and a price — either a fixed
`monthly_price` or a `price_config_param` pointing at a config parameter
(the seeded **Daily Snapshots** add-on reads
`saas_master.hosting_daily_backup_price`). Deactivate to retire an add-on
without deleting history.

## 5. Regions (price varies by location) — *SaaS ▸ Regions*

Each `saas.region` has a `price_multiplier` applied to the
**compute + storage** portion of the quote (not add-ons). One region is
marked **Default** (used when the customer doesn't pick). Assign servers
(proxy / docker / db) to a region via the server's **Region** field.

**Co-location rule** — an instance's nginx (proxy), Odoo (docker) and DB
servers must all be in the same region. Enforced at create:

- The funnel only offers **domains whose reverse proxy is in the chosen
  region** (a proxy-less domain is region-neutral — nginx then runs on the
  region-matched Docker host).
- Allocation pins the docker + db servers to the instance's region (S7b).
- A server with **no** region is treated as belonging to the Default
  region, so an un-regioned fleet keeps working unchanged.

**The region picker appears only when there is more than one active
region.** With a single region the funnel is unchanged. Region is **fixed
at instance creation**. A region is selectable in `/regions` only if it
has both a docker host and a db server (capacity check).

## 6. Storage overage on renewal — *Settings ▸ SaaS ▸ Pricing Engine*

When an instance exceeds its plan's storage limit, the renewal invoice
adds an overage line (`engine.storage_overage`):

- **Per-GB (default)** — `extra_storage_price_per_gb` × GB over.
- **Block-based** — set `storage_block_gb` (e.g. 50) and
  `storage_block_price`; the customer is billed per started block.

**What counts as "used"** is governed by **"Snapshots count toward
storage"** (`snapshots_count_toward_storage`). When on, half the total
snapshot size is included in usage. Recommended **off** if you don't want
backups to inflate the storage bill (currently on for behaviour-neutrality
— an owner decision).

---

## Verifying a change

The engine reflects config/record edits immediately — no restart. To
sanity-check the arithmetic, run the engine test suite (it locks the
engine to the legacy linear formula and exercises floors, tiers, add-ons,
regions and overage):

```
odoo -d <db> -u saas_core --test-enable --stop-after-init \
  --test-tags /saas_core:TestPricingEngine
```

A green run means the SPA, funnel, renewals and plan creation all price
identically through the one engine.
