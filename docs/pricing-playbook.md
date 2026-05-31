# Pricing System — Complete Architecture & Reference

A full, implementation-accurate explanation of how this SaaS hosting
platform prices and bills. Written for a new product owner who must
understand every pricing decision and billing rule. Everything below is
derived from the actual code: the pricing engine
(`saas_core/models/saas_pricing.py`), the settings model
(`res_config_settings.py`), the add-on / support / region / plan models,
the website controllers (`saas_website/controllers/main.py`,
`portal.py`, `registration.py`, `api.py`), and the instance billing flows
(`saas_core/models/saas_instance.py`).

---

# 1. High-Level Pricing Architecture

## The single source of truth

There is exactly **one** place a price is computed:
`saas.pricing.engine.compute(...)` — an Odoo `AbstractModel`. Every
surface that shows or charges a price calls it:

- the public configurator preview (`/saas/api/v1/hosting/calculate`,
  `/saas/custom-plan/calculate`, `/saas/hosting-plan/calculate`),
- the QWeb purchase funnel (`/hosting/configure`),
- plan-record creation (`_get_or_create_hosting_plan`,
  `_get_or_create_custom_plan`),
- and indirectly, renewals/overage (the engine's `storage_overage`).

The engine never reaches out to the UI; callers pass inputs in and read a
result dict out. This guarantees the slider preview, the checkout total,
and the stored plan price are always the same number.

## Models / classes involved

| Model | Role in pricing |
|---|---|
| `saas.pricing.engine` (AbstractModel) | The calculation. `compute()` and `storage_overage()`. |
| `res.config.settings` | Holds every rate, floor, limit, discount, minimum (as `ir.config_parameter` keys under `saas_master.*`). |
| `saas.plan` | A concrete priced plan record (`price`, `yearly_price`, `workers`, `storage_limit`, `max_backups`, `is_public_tier`, `is_recommended`, `badge`). Custom configs create plan records on the fly. |
| `saas.addon` | Paid recurring add-ons (Daily Snapshots). Carries the price mode (flat / storage / hybrid). |
| `saas.support.plan` | Paid support tiers (flat monthly fee). |
| `saas.region` | A region with a `price_multiplier`. |
| `saas.instance` | The customer's subscription. Holds `plan_id`, `region_id`, `support_plan_id`, `daily_backup_enabled`, `total_storage_bytes`, `backup_price_locked_until`, and all billing/renewal logic. |

## Which settings affect pricing

Per-unit rates (`*_worker_price`, `*_storage_price_per_gb`), the cost
floors (`*_worker_floor`, `*_storage_floor`), the minimum monthly charge
(`*_minimum_monthly`), the tier policy (`custom_min_is_nearest_tier`,
`tier_floor_buffer_pct`), the yearly discount (`*_yearly_discount_pct`),
the region `price_multiplier`, add-on prices, support-plan prices, and the
storage-overage rates (`extra_storage_price_per_gb`, `storage_block_gb`,
`storage_block_price`, `snapshots_count_toward_storage`).

## Which settings do NOT affect the computed price

- **Min/max workers & storage** (`*_min_workers`, `*_max_workers`,
  `*_min_storage`, `*_max_storage`): they only **clamp** the requested
  config into range before pricing; they are not multipliers.
- **`cpu_per_worker` / `ram_per_worker`**: provisioning sizing only — they
  set the container's CPU/RAM, not the price.
- **`resource_usage_multiplier`** (default 2.0): monitoring only — scales
  the CPU/RAM **usage %** shown to the customer; never billed.
- **`custom_plan_min_backups` / `max_backups`**: control how many backups
  a *services* plan retains; not a price input. (Hosting retention is a
  fixed constant `HOSTING_MAX_SNAPSHOTS = 7`.)
- **`trial_days`, `max_instances_per_user`, `support_email`,
  `default_instance_starting_port`, the `saas_backup.*` storage
  credentials**: operational, not pricing.

## Pricing flow (text diagram)

```
Customer moves sliders / picks options
        │
        ▼
Controller gathers: kind(hosting|services), workers, storage, billing,
                    addon_codes, region, support_code
        │
        ▼
saas.pricing.engine.compute(...)
        │
        ├─ _rate_config(kind)            → worker_price, storage_price, floors,
        │                                   discount, minimum, limits
        ├─ clamp(workers, storage)       → into [min,max]
        ├─ base = workers·wp + storage·sp
        ├─ cost_floor = workers·wf + storage·sf
        ├─ tier_floor = nearest public tier × (1 − buffer%)   (if policy on)
        ├─ floor = max(cost_floor, tier_floor)
        ├─ region_factor = region.price_multiplier            (default 1.0)
        ├─ resource = max(base, floor) × region_factor
        ├─ addons   = Σ add-on prices (storage-aware)          (NOT × region)
        ├─ support  = support_plan.monthly_price               (NOT × region)
        ├─ pre_minimum = resource + addons + support
        ├─ monthly  = max(pre_minimum, minimum_monthly)
        └─ yearly   = monthly × 12 × (1 − discount)
        │
        ▼
Result dict {monthly, yearly, total, breakdown{...}, region_factor,
             floored, minimum_applied, limits}
        │
        ├─► Preview / funnel show `monthly` (or `yearly`)
        ├─► Checkout stamps `plan.price` / `plan.yearly_price`
        └─► Renewal & overage billed from plan + engine.storage_overage
```

---

# 2. Core Pricing Formula

## The exact calculation (verbatim from `compute()`)

```
base            = workers × worker_price  +  storage_gb × storage_price_per_gb
cost_floor      = workers × worker_floor  +  storage_gb × storage_floor
tier_floor      = (highest public tier the config contains).price × (1 − tier_buffer/100)
                  — only when custom_min_is_nearest_tier == True, else 0
floor           = max(cost_floor, tier_floor)
region_factor   = region.price_multiplier        (1.0 if no region)
resource_monthly= max(base, floor) × region_factor
addons_monthly  = Σ effective add-on prices (storage-aware)
support_monthly = support_plan.monthly_price (0 if none/free/unknown)
pre_minimum     = resource_monthly + addons_monthly + support_monthly
monthly         = max(pre_minimum, minimum_monthly)
yearly          = monthly × 12 × (1 − yearly_discount_pct/100)
total           = yearly if billing == 'yearly' else monthly
```

## Every variable

| Variable | Source | Meaning |
|---|---|---|
| `workers`, `storage` | request, clamped | requested resources |
| `worker_price`, `storage_price_per_gb` | settings (per kind) | per-unit sticker rates |
| `worker_floor`, `storage_floor` | settings (per kind) | per-unit cost floors |
| `tier_floor` | computed from `saas.plan` public tiers | tier-protection floor (soft) |
| `region_factor` | `saas.region.price_multiplier` | regional cost multiplier |
| `addons_monthly` | `saas.addon` | recurring add-on fees |
| `support_monthly` | `saas.support.plan` | recurring support fee |
| `minimum_monthly` | settings (per kind) | absolute floor on the total |
| `yearly_discount_pct` | settings (per kind) | annual-billing discount |

## Calculation order — and why it matters

1. **Clamp** first: a config out of range can't be priced below the
   smallest sellable plan or above the ceiling.
2. **base vs floor**, then **× region**: the floor is a *per-unit cost*
   floor, so it must be compared to base **before** the regional
   multiplier; the region then scales the whole compute+storage cost
   (because infra genuinely costs more in some regions).
3. **Add-ons & support are added AFTER the region multiplier** and are
   **never region-scaled** — a backup lives in object storage and support
   is human labour priced once; neither should be 1.5× just because the
   instance is in an expensive region.
4. **Minimum is the LAST floor**, applied to `pre_minimum` (which already
   includes add-ons and support). This is deliberate: add-ons/support
   **count toward** the minimum, so a customer who buys $30 of support on
   a $12 base isn't charged "max(12,15)+30"; they're charged
   `max(12+30, 15) = 42`. The minimum only bites when the *entire* bill is
   still tiny.
5. **Yearly discount last**: applied to the final monthly so the discount
   reflects everything the customer actually pays.

## Worked examples

Assume hosting defaults: worker $10, GB $0.30, discount 20%.

**A. Plain config, nothing special** — 4 workers, 50 GB, monthly:
`base = 4·10 + 50·0.30 = 55.00`; no floor, no region, no extras →
`monthly = $55.00`. Yearly = `55·12·0.8 = $528.00`.

**B. Minimum bites** — 1 worker, 5 GB, monthly, `minimum_monthly = 15`:
`base = 10 + 1.5 = 11.50`; `pre_minimum = 11.50`; `monthly = max(11.5,15)
= $15.00`, `minimum_applied = True`.

**C. Region + add-on + support** — 2 workers, 20 GB, region ×2, a
storage backup add-on (base $0, $2/10 GB), support $30:
`base = 26.0` → `resource = 52.0` (×2) → backup `ceil(20/10)·2 = 4.0` (flat)
→ support `30.0` (flat) → `pre_minimum = 86.0`. With `minimum_monthly = 50`
the minimum doesn't bite → `monthly = $86.00`. (This is the exact
integration test `test_v2_full_stack_order`.)

---

# 3. Hosting Pricing

Hosting uses the `hosting_*` rate set. Fields (config key → default):

| Field | Key | Default | Effect |
|---|---|---|---|
| Price per worker | `hosting_worker_price` | 10.0 | linear term `workers × this` |
| Price per GB | `hosting_storage_price_per_gb` | 0.3 | linear term `storage × this` |
| Worker floor | `hosting_worker_floor` | 0.0 | min cost per worker (off when 0) |
| Storage floor | `hosting_storage_floor` | 0.0 | min cost per GB (off when 0) |
| Min/Max workers | `hosting_min_workers` / `hosting_max_workers` | 2 / 8 | slider clamp |
| Min/Max storage | `hosting_min_storage` / `hosting_max_storage` | 5 / 200 | slider clamp (GB) |
| Yearly discount | `hosting_yearly_discount_pct` | 20 | % off annual |
| Minimum monthly | `hosting_minimum_monthly` | 0.0 | final-total floor (off when 0) |

**How a hosting plan is priced:** the funnel calls
`compute('hosting', workers, storage, ...)`. The returned `monthly` /
`yearly` are stamped onto a `saas.plan` record by
`_get_or_create_hosting_plan` (it reuses an identical existing custom plan
if one exists, else creates one). Hosting plans set `max_backups` to the
fixed hosting snapshot cap (7) — backup count is **not** a per-plan price
input on hosting. `cpu_per_worker`/`ram_per_worker` size the container
only.

---

# 4. Services Pricing

"Services" is the custom-plan builder for the non-hosting product line.
It uses a **separate rate set** (`worker_price`, `storage_price_per_gb`,
`custom_plan_*`), but the **same engine and the same formula** — `kind`
just selects which config keys are read.

| Aspect | Hosting | Services |
|---|---|---|
| Worker/GB rate keys | `hosting_worker_price`, `hosting_storage_price_per_gb` | `worker_price`, `storage_price_per_gb` |
| Limits keys | `hosting_min/max_*` | `custom_plan_min/max_*` |
| Discount key | `hosting_yearly_discount_pct` | `custom_plan_yearly_discount_pct` |
| Floors | `hosting_worker_floor` / `hosting_storage_floor` | `worker_floor` / `storage_floor` |
| Minimum | `hosting_minimum_monthly` | `minimum_monthly` |
| Backup-count range | fixed (7 snapshots) | `custom_plan_min/max_backups` retained |
| User-estimate display | n/a | `custom_plan_users_per_worker_min/max` (shown as a recommendation, not priced) |

**Shared logic:** the entire `compute()` flow — clamping, floors, tier
protection, region, add-ons, support, minimum, discount — is identical.
**Separate logic:** only the config keys (rates/limits/discount/floors/
minimum) and the services-only backup-count + user-estimate knobs.

---

# 5. Public Plan Tiers

## How public tiers work

A `saas.plan` with `is_public_tier = True` is shown as a marketing tier
card (the SPA `/tiers` endpoint and the storefront render them). Fields:
`name`, `price`, `yearly_price`, `workers`, `storage_limit`,
`is_recommended` (highlights one as the default/"best value"), `badge`
(ribbon text), `sequence` (ordering).

## Custom (slider) plans vs tiers

The slider builds an arbitrary `workers`/`storage` config and prices it
linearly through the engine. Tiers are fixed bundles. Both end up as
`saas.plan` records; the difference is only `is_public_tier` and whether
the price came from a card or the slider.

## Nearest-tier protection (the `tier_floor`)

When `custom_min_is_nearest_tier = True`, the engine finds the **highest-
priced public tier whose workers AND storage are both ≤ the requested
config** (i.e. the tier the custom config "contains") and uses its price
as a floor — so a custom config can't undercut a bundle it fully covers.

- **Hard floor** (default, `tier_floor_buffer_pct = 0`): the custom config
  is pinned to at least the tier's price.
- **Soft floor** (`tier_floor_buffer_pct = N`): the floor relaxes to
  `tier_price × (1 − N/100)`, so a custom config may sit up to N% under
  the nearest tier. The buffer is clamped to 0–100.

The `tier_floor` competes with `cost_floor` via `max(...)`, so whichever
is higher wins.

## Upgrade / downgrade paths (from `portal.py`)

- **Upgrade** (more workers or more storage): `action_request_plan_change`
  creates a prorated invoice for the difference and applies immediately on
  payment. The portal computes a proration credit for the unused remainder
  of the current cycle.
- **Downgrade** (fewer workers): `_request_downgrade` **schedules** the
  change for the next billing cycle (`scheduled_plan_id`) — the customer
  keeps current resources until then; the renewal then bills the lower
  plan. Storage **cannot** be reduced (hard block in the controller).
- The portal change-plan page prices the new config through the same
  engine, so the displayed and charged prices match.

## Edge cases

- A config that matches **no** tier → `tier_floor = 0` (no protection).
- Tier protection only applies to the **kind** matching the tier
  (a hosting tier doesn't floor a services config).
- Trials use a dedicated trial plan at price 0 and bypass paid add-ons.

---

# 6. Region Pricing

## What a region is and how it's applied

`saas.region` has `price_multiplier` (default 1.0), `is_default`,
`active`, and a set of servers. In `compute()`,
`region_factor = region.price_multiplier`, applied as:

```
resource_monthly = max(base, floor) × region_factor
```

## What it affects vs not

- **Affected:** compute + storage (the `resource_monthly` term), including
  the floors — because they're inside `max(base, floor)` before the
  multiply.
- **NOT affected:** add-ons (`addons_monthly`) and support
  (`support_monthly`) are added **after** the multiply, and storage
  overage is a separate calculation that does not apply the region factor.

## When it's applied / availability

- Region is **fixed at instance creation** and drives co-located server
  allocation (proxy + docker + db all in that region).
- A region is only **offered** to the customer if it has capacity
  (a proxy + docker host + db server in-region). Empty regions are hidden
  and cannot be selected, even via a hand-crafted URL.
- A server with no region is treated as the default region
  (behaviour-neutral for un-regioned fleets).

## Example

4 workers / 50 GB hosting (`base = 55`), region ×1.5 → `resource = 82.50`.
Add a $40 support plan → `monthly = 82.50 + 40 = 122.50` (support is **not**
multiplied; it stays $40, not $60).

---

# 7. Add-ons

Add-ons are `saas.addon` records, configured in **SaaS ▸ Configuration ▸
Add-ons**. They are summed into `addons_monthly` by the engine and are
**flat with respect to region** (added after the region multiply).

Each add-on has a **price mode**:
- `flat`: a fixed monthly amount (from `monthly_price`, or from a config
  key via `price_config_param`).
- `storage`: `ceil(storage_gb / block_gb) × price_per_block`.
- `hybrid`: `flat_amount + ceil(storage_gb / block_gb) × price_per_block`.

`block_gb` defaults to 10, so storage pricing reads as "+$X per 10 GB".

## The shipped add-on: Daily Snapshots

| Property | Value |
|---|---|
| Where configured | SaaS ▸ Configuration ▸ Add-ons → "Daily Snapshots"; flat price lives in Settings (`hosting_daily_backup_price`, default 5.0) via `price_config_param` |
| Recurring or one-time | **Recurring**, on its **own monthly cycle** (independent of the plan's monthly/yearly cycle) — `_cron_renew_daily_backup_addons` → `_generate_daily_backup_renewal_invoice` |
| Region multiplier | **No** — flat, added after region |
| Yearly discount | **No** — billed monthly regardless of the plan's billing period |
| Storage-aware | Optional: switch the add-on to `storage`/`hybrid` so a 2 TB instance pays proportionally more. Existing subscribers are **grandfathered** (kept at the flat price until `backup_price_locked_until`). |
| Applies to | Hosting only |

The actual recurring charge is `_get_daily_backup_price()`, which: returns
the flat price while `backup_price_locked_until` is in the future; else
delegates to the add-on's `effective_monthly_price(storage_gb)` using the
instance's real storage.

## Example

Daily Snapshots in hybrid mode, base $5, $1 per 10 GB:
- 20 GB instance → `5 + ceil(20/10)·1 = 5 + 2 = $7/mo`.
- 2 TB (2048 GB) → `5 + ceil(2048/10)·1 = 5 + 205 = $210/mo`.

---

# 8. Storage Overage Billing

Billed on **renewal** when measured usage exceeds the plan's storage
limit. Computed by `engine.storage_overage(total_bytes, limit_gb)`.

## What counts as "used"

`total_storage_bytes` = disk (instance folder) + database + **half** the
total snapshot footprint — but the snapshot half is only added when
`snapshots_count_toward_storage` (default ON). Turning it OFF means
snapshots are covered solely by the Daily Backups add-on and don't consume
the plan allowance (recommended, avoids double-charging).

## The two modes

```
over_gb = ceil((total_bytes − limit_bytes) / 1 GB)        # whole GB over
if storage_block_gb > 0 AND storage_block_price > 0:
    charge = ceil(over_gb / storage_block_gb) × storage_block_price   # BLOCK
else:
    charge = over_gb × extra_storage_price_per_gb                     # PER-GB
```

- **Per-GB** (default; `extra_storage_price_per_gb`, default 0.0 = no
  overage charge at all): linear per GB over.
- **Block** (when both block settings > 0): billed per started block —
  predictable "+$X per N GB".

If `extra_storage_price_per_gb` is 0 and no block is set, overage charge is
$0 (the platform may instead suspend over-limit instances; the charge path
simply adds nothing).

## Examples (limit 50 GB)

- Per-GB, rate $0.50, used 60 GB → `over_gb = 10`, charge `10·0.50 = $5.00`.
- Block, 10 GB blocks @ $9, used 60 GB → `over_gb = 10`,
  `blocks = 1`, charge `$9.00`.
- Used 40 GB (under limit) → mode `none`, charge `$0`.

---

# 9. Renewal Pricing

`_generate_renewal_invoice()` runs on the recurring-billing cron. Steps:

1. **Apply a scheduled downgrade** first (if any), so the renewal uses the
   new lower plan; updates container resources and trims excess backups.
2. **Plan line**: `plan._get_price_for_period(period)` — `yearly_price`
   for yearly, else `price`. The plan price was itself stamped from the
   engine at creation, so it already reflects rates/floors/region/minimum
   that were in effect.
3. **Support line** (P5): if the instance has a priced `support_plan_id`,
   a line at `support.monthly_price`, qty **1 on monthly / 12 on yearly**
   (so the support term matches the plan term). The free/$0 plan adds no
   line.
4. **Storage overage line**: `engine.storage_overage(...)` — added only
   when `charge > 0`.
5. **Daily-backup / snapshot — depends on the merge toggle**
   (`merge_snapshot_into_renewal_invoice`, default OFF):
   - **OFF (default):** the snapshot is NOT on this invoice; it bills on
     its **own monthly cycle** (`_cron_renew_daily_backup_addons`).
   - **ON:** the snapshot is always still **monthly (qty 1)**, but it is
     folded into this renewal **only when its monthly date is due on/before
     the renewal date** (`daily_backup_next_invoice_date <=
     next_invoice_date`). When merged, that date advances one month so the
     standalone cron skips it — a month can never be billed twice (the one
     date field is the source of truth). On a monthly plan the dates
     coincide every month (one invoice); on a yearly plan they coincide
     once a year (one merged month + 11 standalone monthly). If the backup
     isn't due on the renewal date, no snapshot line appears — the customer
     isn't shown a charge they're already paying separately. An unpaid
     merged renewal pauses snapshots just like an unpaid standalone backup
     invoice (M4).

### Discount handling

The yearly discount is **baked into `plan.yearly_price`** (set from the
engine's `yearly = monthly·12·(1−disc)`). The renewal simply charges
`yearly_price`; it does not re-apply the discount.

### Example (yearly hosting plan $528/yr, Pro support $40/mo, 10 GB over @ $0.50)

Renewal invoice lines:
- Plan (Yearly) — $528.00
- Support: Pro (Yearly) — qty 12 × $40 = $480.00
- Extra storage: 10 GB over — $5.00
- **Invoice total: $1,013.00** (+ daily-backup billed separately monthly).

---

# 10. Cancellation and Reactivation

## Snapshot retention on cancel

On cancellation the platform keeps the **most recent full-instance
snapshot** (the rest are purged). `pending_retention_surcharge` is set when
a snapshot was retained.

## Reactivation

`action_reactivate(new_plan_id, billing_period)` reuses the same record:
resets to draft with a new plan, **clears `daily_backup_enabled`** (the
customer must re-enable + pay for backups again), and keeps the retained
snapshot so data can be restored.

## The fees

| Fee | Key / source | Type | When charged |
|---|---|---|---|
| Snapshot retention surcharge | `hosting_snapshot_retention_surcharge` (default 0) | One-time | Added to the **first daily-backup activation invoice after reactivation**, only if a snapshot was retained (`pending_retention_surcharge`). |
| Data restoration fee | `data_restoration_fee` (default 0) | One-time | Charged via the restore-retained wizard when restoring a cancelled instance's snapshot; the restore proceeds once the invoice is paid (0 = free restore). |

## Example

Customer cancels with a retained snapshot. Later reactivates on a $55/mo
plan, then re-enables Daily Backups. With retention surcharge $20: the
daily-backup activation invoice = backup price + $20 one-time. To restore
the old data with `data_restoration_fee = $49`: a separate $49 invoice,
restore runs on payment.

---

# 11. Customer Journey — every billing event

Hosting, defaults (worker $10, GB $0.30, 20% yearly), region ×1.5, Pro
support $40/mo, Daily Snapshots flat $5/mo, minimum $15, overage per-GB
$0.50. Customer picks 4 workers / 50 GB, **monthly**.

1. **Selects plan (slider 4w/50GB)** → engine quotes `base = 55`. No event.
2. **Chooses region (×1.5)** → `resource = 82.50`. Preview updates. No event.
3. **Enables add-ons** → +Daily Snapshots, +Pro support → preview
   `82.50 + 5 + 40 = 127.50`. No event.
4. **Checks out** → instance created with `region`, `support_plan_id=pro`,
   `daily_backup_enabled` pending.
   - **Event 1 — Initial invoice**: Plan $82.50 + Support Pro $40 = **$122.50**
     (the plan line is the region-scaled resource price stamped onto the plan).
   - **Event 2 — Daily-backup activation invoice**: $5 (separate cycle),
     paid to turn backups on.
5. **Renews (next month)** → **Event 3**: Plan $82.50 + Support $40 = $122.50.
   **Event 4**: daily-backup monthly invoice $5.
6. **Exceeds storage** (uses 70 GB on a 50 GB plan) → next renewal adds an
   **Extra storage** line: `(70−50)·0.50 = $10` → **Event 5**: $132.50 + $5 backup.
7. **Cancels** → snapshot retained, `pending_retention_surcharge` set. No charge.
8. **Reactivates + restores** → **Event 6**: new plan's initial invoice +
   (on re-enabling backups) the retention surcharge one-time; **Event 7**:
   data-restoration fee invoice if configured. Restore runs on payment.

---

# 12. Admin Configuration (every pricing field)

| Technical key | Business meaning | Default | Effect on price | Misconfiguration risk |
|---|---|---|---|---|
| `hosting_worker_price` / `worker_price` | $/worker/month | 10.0 / 0.0 | linear base term | services rate 0 → services priced at $0 + storage only |
| `hosting_storage_price_per_gb` / `storage_price_per_gb` | $/GB/month | 0.3 / 0.5 | linear base term | too low → storage-heavy plans unprofitable |
| `hosting_worker_floor` / `worker_floor` | min $/worker | 0.0 | `max(base, floor)` | set above sticker → every plan jumps to the floor |
| `hosting_storage_floor` / `storage_floor` | min $/GB | 0.0 | `max(base, floor)` | same |
| `hosting_minimum_monthly` / `minimum_monthly` | floor on total | 0.0 | final `max()` | set very high → all small plans collapse to one price |
| `custom_min_is_nearest_tier` | tier protection on/off | False | enables `tier_floor` | on with badly-priced tiers → custom configs over-priced |
| `tier_floor_buffer_pct` | soft-floor % under tier | 0.0 | relaxes `tier_floor` | >0 lets custom undercut tiers; 100 disables protection |
| `hosting_yearly_discount_pct` / `custom_plan_yearly_discount_pct` | annual discount | 20 | `yearly = monthly·12·(1−d)` | too high → annual erodes margin |
| `region.price_multiplier` | regional cost factor | 1.0 | × compute+storage | <1 sells below other regions; very high → uncompetitive |
| `hosting_daily_backup_price` | backup add-on flat price | 5.0 | add-on term | 0 → "backups not configured" error on enable |
| add-on `price_mode`/`price_per_block`/`block_gb` | backup scaling | flat / 0 / 10 | add-on term | storage mode with block 0 blocked by constraint |
| support plan `monthly_price` | support tier fee | 0 (seeds) | support term | left 0 → support is free (no upsell revenue) |
| `extra_storage_price_per_gb` | per-GB overage | 0.0 | overage charge | 0 → no overage revenue (or relies on suspension) |
| `storage_block_gb` / `storage_block_price` | block overage | 50 / 0.0 | overage charge | price 0 → falls back to per-GB |
| `snapshots_count_toward_storage` | count ½ snapshots in usage | True | affects overage trigger | ON + paid backups → double-charge perception |
| `hosting_snapshot_retention_surcharge` | post-cancel keep fee | 0.0 | one-time on reactivation | high → discourages reactivation |
| `data_restoration_fee` | restore fee | 0.0 | one-time | high → customers feel held hostage |
| `*_min/max_workers`, `*_min/max_storage` | slider clamps | 2/8, 5/200 | bounds only | min too high → no cheap entry plan |
| `cpu_per_worker` / `ram_per_worker` | container sizing | — | none (provisioning) | over-allocation → infra cost up, price unchanged |
| `resource_usage_multiplier` | monitoring display | 2.0 | none | wrong value → misleading usage %, no billing impact |
| `trial_days`, `max_instances_per_user` | trial / limits | — | none | — |

---

# 13. Business Strategy Analysis

The implemented model is a **linear, transparent, value-add-on** strategy:

- **Margin protection** is layered: per-unit **cost floors** stop selling
  compute/storage below cost; the **minimum monthly charge** stops selling
  *any* plan below the cost of having a customer; **tier protection** stops
  the slider cannibalising packaged bundles.
- **Customer acquisition** is served by a low entry point (small configs,
  trials) while the minimum quietly ensures even the smallest paying
  customer is profitable.
- **Annual billing incentive**: the yearly discount (default 20%) trades
  margin for cash-up-front and a year of retention; it's baked into
  `yearly_price` so it's consistent everywhere.
- **Tier positioning**: public tiers with a "recommended" badge anchor the
  buyer toward a chosen plan, while the slider remains for power users —
  protected by the soft tier floor so it complements rather than undercuts.
- **Storage monetization**: storage is priced per GB in the base, can be
  overaged on renewal (per-GB or block), and backups can scale with
  storage — three independent levers to recover storage cost.
- **Regional pricing**: a single multiplier per region passes real infra
  cost differences to the customer, applied only to the infra portion.
- **Support as margin**: support tiers are a flat, region-independent,
  near-pure-margin upsell billed on the plan cycle.

---

# 14. Weaknesses and Limitations (current implementation)

- **No usage-based / metered compute billing.** Price is fixed per
  worker; a customer paying for 8 workers but idling pays the same as one
  maxing them out. No CPU-second / bandwidth / request metering.
- **Linear pricing only — no volume tapering.** `workers × rate` is flat;
  there's no "cheaper per worker as you scale", which large customers
  expect. Big configs can look expensive vs competitors' tiered curves.
- **Yearly discount is frozen into `yearly_price` at plan creation.** If
  rates change later, existing custom plans keep their old stamped price
  until a plan change — there's no re-pricing/version migration of live
  custom plans.
- **Support billed in 12× chunks on yearly plans** rather than truly
  monthly — a yearly customer pays a full year of support upfront, which
  may surprise.
- **Daily-backup runs a parallel billing cycle**, so a customer gets two
  invoices (plan + backup) on different dates — more billing noise and a
  second dunning surface.
- **Overage is reactive (billed after the fact on renewal)** with no
  pre-warning threshold or soft cap in the pricing path; `extra_storage`
  default 0 means overage is silently free unless configured.
- **No proration of add-ons/support** on mid-cycle plan changes — support
  isn't on the upgrade/proration invoice, only picked up next renewal.
- **No currency/tax localization in the engine** — a single company
  currency; region affects price but not currency or tax treatment.
- **No discounts/coupons/promotions** mechanism in the engine.
- **Tier protection compares only "contains" (≥ workers AND ≥ storage)** —
  a config that's bigger on one axis and smaller on the other matches no
  tier and gets no protection, which can be gamed.
- **Minimum-charge perception:** a customer configuring something tiny
  sees the price "stuck" at the minimum with no explanation of why moving
  the slider down doesn't lower it.

---

# 15. Strengths

- **One engine, one source of truth.** Preview, checkout, stored plan,
  renewal and overage can never disagree — a large class of pricing bugs
  is structurally impossible.
- **Layered margin protection** (cost floor → tier floor → minimum) that
  is each independently toggleable and **behaviour-neutral by default**.
- **Clean order of operations** with an explicit `breakdown` dict
  (`base`, `cost_floor`, `tier_floor`, `resource_monthly`, `addons_monthly`,
  `support_monthly`, `pre_minimum`, `minimum_monthly`) — fully auditable.
- **Region multiplier scoped correctly** (infra only, not add-ons/support)
  — matches real cost structure and keeps support competitive everywhere.
- **Storage monetized on three independent levers** (base rate, overage,
  storage-aware backups) without entangling them.
- **Safe migrations / grandfathering** — switching backups to storage-
  based doesn't jump existing subscribers mid-cycle.
- **Transparent line items** at checkout and on invoices (Plan, Support,
  Backup, Overage) — the customer sees what they pay for.
- **Everything is admin-configurable** via settings + records; no code
  change to adjust prices, add an add-on, a region, or a support tier.

---

# 16. Final Assessment

| Dimension | Score | Reasoning |
|---|---|---|
| **Technical** | **9/10** | Single-source-of-truth engine, explicit ordered formula, auditable breakdown, behaviour-neutral defaults, tested (17 cases incl. a full-stack integration lock), safe migrations with grandfathering. Loses a point: yearly price frozen into the plan record (no live re-pricing), and add-on/support not prorated on mid-cycle changes. |
| **Business** | **7/10** | Strong, layered margin protection (floors + minimum + tier guard), annual-billing incentive, support upsell, transparent line items. Held back by no volume tapering, no coupons/promotions, and reactive (often-zero-by-default) overage. |
| **Monetization** | **7/10** | Multiple revenue levers — compute, storage, overage, storage-aware backups, support tiers, regional uplift, one-time retention/restore fees. Misses metered/usage billing and volume-based expansion revenue from large accounts; several levers ship at $0 default and must be deliberately switched on. |
| **Scalability** | **8/10** | The engine is stateless and cheap; adding regions/add-ons/support tiers/plans is pure configuration. Co-located region allocation scales horizontally. Loses points for the parallel backup billing cycle (extra invoices/dunning) and the lack of plan-version migration for re-pricing a large live base. |

*Scores reflect the system exactly as implemented today; no changes or
recommendations are proposed here.*

---

## Related docs
- `pricing-admin-guide.md` — operator how-to: where each knob lives.
- `pricing-v2-execution-plan.md` — design/phasing of the v2 enhancements
  (minimum charge, soft tier floor, support plans, storage-aware backups).
- `pricing-system-execution-plan.md` — original engine design (S1–S10).
