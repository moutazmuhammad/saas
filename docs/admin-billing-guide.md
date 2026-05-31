# Admin Guide — How Pricing & Billing Work, and How to Configure Them

This guide is for the **platform administrator**. It explains, end to end:

1. How a price is **calculated** (every step, with worked examples for each case).
2. How the customer is **billed** (the two recurring cycles + one-off charges).
3. Every **field in the Settings screen** (`Settings → SaaS Manager`), what it
   does, its default, and which calculation it feeds.

> Companion docs: `docs/pricing-playbook.md` (deeper implementation reference)
> and `docs/snapshot-billing-merge-plan.md` (the snapshot-merge design).

---

## 0. The big picture

There are **two distinct moments** where money is decided:

| Moment | What happens | Who drives it |
|--------|--------------|---------------|
| **Quote time** | A price is computed for a configuration (slider preview, configure page, checkout, plan creation, upgrade/downgrade). | `saas.pricing.engine.compute()` — one engine, one formula. |
| **Billing time** | An invoice is generated on a schedule. | Two crons: the **subscription renewal** and the **daily-backup** cycle. |

Two product families share the same engine but have **separate rate sets**,
selected by `kind`:

- **`hosting`** — self-managed hosting plans (`saas_master.hosting_*` params).
- **`services`** — the managed "custom plan" builder (`saas_master.*` params).

A **public tier** (a named plan like Starter/Pro) has its monthly/yearly price
**stamped from the engine when it was created**, then stored on the plan record.
At renewal we charge that stored price — we do **not** re-run the engine. So
changing a rate in Settings affects **new** quotes/plans, not the price already
locked onto an existing instance's plan.

---

## 1. The pricing formula (quote time)

`compute(kind, workers, storage, billing, addon_codes, region, support_code)`
runs these steps **in order**. Each step maps to a setting (see §6).

```
1. Clamp inputs        workers → [min_workers, max_workers]
                       storage → [min_storage, max_storage]

2. base              = workers·worker_price + storage·storage_price_per_gb

3. cost_floor        = workers·worker_floor + storage·storage_floor
   tier_floor        = nearest public tier price − buffer%   (only if the
                       "Custom ≥ Nearest Tier" policy is ON; else 0)
   floor             = max(cost_floor, tier_floor)

4. resource_monthly  = max(base, floor) × region_multiplier

5. addons_monthly    = Σ effective price of selected add-ons (storage-aware)
   support_monthly   = flat fee of the chosen support plan (NOT region-scaled)
   pre_minimum       = resource_monthly + addons_monthly + support_monthly

6. monthly           = max(pre_minimum, minimum_monthly)   ← final floor

7. yearly            = monthly × 12 × (1 − yearly_discount%)
```

Key rules that trip people up:

- **The floor replaces the formula, it doesn't add to it.** Step 4 is
  `max(base, floor)`, so a floor only matters when the linear formula comes out
  *below* it.
- **Region scales infrastructure only.** The region multiplier hits
  `max(base, floor)` — **not** add-ons and **not** support.
- **The minimum-monthly is the last word, and add-ons count toward it.** A
  config that computes to \$12 with a \$25 minimum bills \$25 — the customer just
  sees \$25, never "\$12 + \$13 surcharge". Add-ons/support are inside
  `pre_minimum`, so they help *reach* the minimum rather than stack on top.
- **The yearly discount is baked into the stored `yearly_price`.** Renewal
  charges that number directly; it does not re-apply the discount.

### Engine fallback defaults (when a param was never saved)

If the Settings page has never been saved on a fresh DB, the engine falls back
to these hardcoded rates (`_rate_config`):

| | worker_price | storage_price_per_gb |
|---|---|---|
| hosting | **10.0** | **0.3** |
| services | **15.0** | **0.5** |

Note the **services** field defaults shown in the UI are `0.0`; once you save
Settings, the saved value (even 0) wins over the fallback. Set real rates
before going live.

---

## 2. Worked examples (every case)

All examples use the hosting rate set unless noted. Defaults:
`worker_price=10`, `storage_price_per_gb=0.3`, `yearly_discount=20%`.

### Case A — plain custom config, no floors/minimum/region

`4 workers, 50 GB, monthly`
```
base = 4·10 + 50·0.3 = 40 + 15 = 55.00
floor = 0 → resource_monthly = 55.00
no add-ons, no support, no minimum → monthly = 55.00
```
**Bills \$55.00/mo.** Yearly: `55·12·0.8 = 528.00/yr` (≈ \$44/mo).

### Case B — cost floor protects margin

Set `hosting_worker_floor=8`, `hosting_storage_floor=0.25`.
Config `2 workers, 5 GB`:
```
base       = 2·10 + 5·0.3   = 21.50
cost_floor = 2·8  + 5·0.25  = 17.25   → below base, no effect
```
Now a "cheap workers + huge storage" abuse attempt `2 workers, 200 GB` where you
dropped `storage_price_per_gb` to 0.05:
```
base       = 2·10 + 200·0.05 = 30.00
cost_floor = 2·8  + 200·0.25 = 66.00   → floor wins
resource_monthly = 66.00
```
**The floor caught it: bills \$66, not \$30.**

### Case C — minimum monthly charge

`hosting_minimum_monthly=25`. Tiny config `2 workers, 5 GB`:
```
base = 21.50 → pre_minimum = 21.50
monthly = max(21.50, 25) = 25.00   (minimum_applied = true)
```
**Bills \$25.00** — covers fixed costs (payment fees, support, monitoring, CAC).

### Case D — region multiplier

Region "KSA" with `price_multiplier=1.3`. Config `4 workers, 50 GB`:
```
resource_monthly = max(55, 0)·1.3 = 71.50
```
**Bills \$71.50/mo.** (Add-ons/support, if any, would be added *after* this and
are not multiplied.)

### Case E — support plan

Customer picks the **Pro** support plan (`monthly_price=40`) on the \$55 config:
```
resource_monthly = 55.00
support_monthly  = 40.00   (flat, not region-scaled)
monthly = 95.00
```
**Bills \$95.00/mo.** Yearly renewal shows support as **qty 12 × \$40**.

### Case F — storage-aware backup add-on

The `daily_snapshots` add-on in `storage` mode, `price_per_block=2`,
`block_gb=10`, on an instance using 50 GB:
```
blocks = ceil(50/10) = 5
backup price = 5 × 2 = 10.00/mo
```
In `hybrid` mode it's `flat monthly_price + blocks×price_per_block`. In `flat`
mode (default) it's just `hosting_daily_backup_price` from Settings.

### Case G — tier floor (soft)

Policy **"Custom ≥ Nearest Tier"** ON, buffer 10%. The Pro tier is
`4w/100GB @ \$80`. A custom `3w/95GB` whose formula gives \$58.50:
```
tier_floor = 80 × (1 − 10/100) = 72.00   → above formula
monthly = 72.00
```
**Bills \$72** — cheaper than Pro, but Pro is still better value per resource.
With buffer 0 it would be pinned to the full \$80 (hard floor).

---

## 3. Storage overage (separate renewal line)

`storage_overage(total_bytes, plan_storage_limit_gb)` runs **at renewal**, not
at quote time, and adds a line only when usage exceeds the plan allowance:

- **Block mode** (when `storage_block_gb>0` **and** `storage_block_price>0`):
  `blocks = ceil(over_GB / block_gb)`, charge `= blocks × block_price`.
- **Per-GB mode** (fallback): `charge = ceil(over_GB) × extra_storage_price_per_gb`.
- If `extra_storage_price_per_gb=0` and no block price, there's **no overage
  line** — the policy instead is to suspend over-quota instances.

Example: plan limit 50 GB, using 78 GB, block 50 GB @ \$5 →
`over=28GB → ceil(28/50)=1 block → \$5.00` line on the renewal.

---

## 4. Billing cycles (billing time)

### 4.1 Subscription renewal — `_cron_generate_recurring_invoices`

For each due instance, `_generate_renewal_invoice` builds **one** sale order →
invoice (origin `SAAS:RENEWAL:<full-domain>`) with these lines:

1. **Plan line** — `plan._get_price_for_period(period)`: `yearly_price` for
   yearly, else `price`. (The stored, engine-stamped number.)
2. **Support line** — if the instance has a priced support plan: qty **1 on
   monthly / 12 on yearly** (so the support term matches the plan term).
3. **Snapshot line** — *only if* the merge toggle is ON and the backup month is
   due on this date (see 4.3).
4. **Storage overage line** — only when `charge > 0` (see §3).

A scheduled downgrade is applied **first**, so the renewal uses the new lower
plan and trims excess backups.

### 4.2 Daily-backup cycle — `_cron_renew_daily_backup_addons`

Runs **independently** and **monthly**, even for yearly-plan customers, so
snapshots are always billed one month at a time (origin
`SAAS:BACKUP-ADDON:<full-domain>`). For each running hosting instance with
backups enabled it:

1. **Pauses/resumes** snapshots based on whether the add-on is paid up.
2. Issues the next monthly invoice **if due and no unpaid backup invoice is
   already open** (never stacks two — the customer owes one, snapshots stay
   paused until it's settled).

The monthly amount is `_get_daily_backup_price()` — storage-aware via the
`daily_snapshots` add-on, with **grandfathering**: while
`backup_price_locked_until` is in the future, the old flat price is kept so an
existing subscriber's charge never jumps mid-subscription.

### 4.3 Merging the snapshot into the renewal (the toggle)

`Merge Snapshot into Renewal Invoice` (default **OFF**):

- **OFF** → snapshot always bills on its own monthly cycle (4.2). Customer may
  get two invoices.
- **ON** → the snapshot is **still monthly (qty 1, never prepaid)**, but it's
  folded into the renewal **only when its monthly due date falls on/before the
  renewal date** (`daily_backup_next_invoice_date <= next_invoice_date`). When
  merged, that date advances one month so the standalone cron skips it — **a
  month can never be billed twice** (the one date field is the source of truth).
  - Monthly plan → dates coincide every month → **one combined invoice**.
  - Yearly plan → coincide once a year → **1 merged month + 11 standalone**.
  - Backup not due on the renewal date → **no snapshot line shown** (the
    customer is already paying it separately that month).
- An **unpaid merged renewal** pauses snapshots just like an unpaid standalone
  backup invoice.

---

## 5. One-off charges

- **Data Restoration Fee** (`data_restoration_fee`) — invoiced automatically
  when an admin restores data from a **cancelled** instance's retained backup.
  `0` = free.
- **Snapshot Retention Surcharge** (`hosting_snapshot_retention_surcharge`) — a
  one-time fee on the **first** Daily-Backups activation invoice *after a
  reactivation*, only when a snapshot was kept in cloud storage through the
  cancellation period. `0` = disabled.

---

## 6. Settings screen field reference

`Settings → SaaS Manager`. Fields are grouped into blocks; below mirrors that
layout. "Param" is the `ir.config_parameter` key.

### Block: Website Sections
| Field | Default | Effect |
|---|---|---|
| Show Services Section | On | Show the public Services catalog. Off hides it; data preserved. |
| Show Hosting Section | On | Show the public Hosting landing/configurator. Off hides it; data preserved. |

> These two and the four pricing-policy booleans (below) are stored as the
> literal strings `'True'`/`'False'` by hand — they intentionally do **not** use
> Odoo's `config_parameter=` (which mis-handles boolean `False`).

### Block: General
| Field | Param | Default | Effect |
|---|---|---|---|
| Free Trial Duration (Days) | `trial_days` | 14 | Trial length; instance suspended at expiry until paid. |
| Max Instances Per User | `max_instances_per_user` | 5 | Cap on active instances per customer. `0` = unlimited. |
| Default Starting Port | `default_instance_starting_port` | 32000 | First port for auto-assigning HTTP/longpolling pairs. |

### Block: Support
| Field | Param | Default | Effect |
|---|---|---|---|
| Support Email | `support_email` | — | Shown to clients in emails/portal. |
| Data Restoration Fee | `data_restoration_fee` | 0.0 | One-off fee when restoring a cancelled instance's backup. `0` = free. |

> **Support *plans*** (the recurring SLA tiers that add `support_monthly`) are
> separate records, not Settings fields — manage them under the
> `saas.support.plan` model. Keep exactly one `is_default` (the free tier).
> Don't change a `code` once in use.

### Block: Plan Pricing & Limits
Two parallel rate sets — **Services** (custom builder) and **Hosting**.

| Field | Param | Default | Effect |
|---|---|---|---|
| Price per Worker (Services) | `worker_price` | 0.0¹ | `base` worker rate, services. |
| Price per GB (Services) | `storage_price_per_gb` | 0.0¹ | `base` storage rate, services. |
| Hosting: Price per Worker | `hosting_worker_price` | 10.0 | `base` worker rate, hosting. |
| Hosting: Price per GB | `hosting_storage_price_per_gb` | 0.3 | `base` storage rate, hosting. |
| Min/Max Workers (Custom) | `custom_plan_min/max_workers` | 2 / 8 | Clamp + slider range, services. |
| Min/Max Storage GB (Custom) | `custom_plan_min/max_storage` | 5 / 200 | Clamp + slider range, services. |
| Hosting: Min/Max Workers | `hosting_min/max_workers` | 2 / 8 | Clamp + slider range, hosting. |
| Hosting: Min/Max Storage GB | `hosting_min/max_storage` | 5 / 200 | Clamp + slider range, hosting. |
| CPU / RAM per Worker (Custom) | `custom_plan_cpu_per_worker` / `..._ram_per_worker` | 0.5 / 512 | Container resources allocated per worker (vCPU / MB). |
| Hosting: CPU / RAM per Worker | `hosting_cpu_per_worker` / `..._ram_per_worker` | 0.5 / 512 | Same, hosting. |
| Min/Max Backups (Custom) | `custom_plan_min/max_backups` | 3 / 14 | Backup count for smallest/largest custom plan. (Hosting retention is fixed at 7.) |
| Users per Worker Min/Max | `custom_plan_users_per_worker_min/max` | 6 / 10 | Display-only sizing recommendation. |
| Yearly Discount % (Services) | `custom_plan_yearly_discount_pct` | 20 | Discount baked into yearly price, services. |
| Hosting: Yearly Discount % | `hosting_yearly_discount_pct` | 20 | Same, hosting. |
| Hosting: Daily Backup Add-on Price | `hosting_daily_backup_price` | 5.0 | Flat monthly snapshot price (used when the `daily_snapshots` add-on is flat mode). 7-day retention. |
| Hosting: Snapshot Retention Surcharge | `hosting_snapshot_retention_surcharge` | 0.0 | One-off post-reactivation fee (see §5). |

¹ Services rates show `0.0` in the UI but the engine falls back to 15.0 / 0.5
until you save a value — **set real services rates before selling services**.

### Block: Pricing Engine
| Field | Param | Default | Effect |
|---|---|---|---|
| Services: Worker / Storage Cost Floor | `worker_floor` / `storage_floor` | 0.0 | `cost_floor` per worker / GB, services. `0` = no floor. |
| Hosting: Worker / Storage Cost Floor | `hosting_worker_floor` / `hosting_storage_floor` | 0.0 | Same, hosting. |
| Services: Minimum Monthly Charge | `minimum_monthly` | 0.0 | Final-total floor, services. `0` = none. |
| Hosting: Minimum Monthly Charge | `hosting_minimum_monthly` | 0.0 | Final-total floor, hosting. `0` = none. |
| Extra Storage Price per GB | `extra_storage_price_per_gb` | 0.0 | Per-GB overage rate (fallback when no block price). `0` = suspend instead of charge. |
| Storage Expansion Block (GB) | `storage_block_gb` | 50 | Block size for block-mode overage. |
| Storage Expansion Block Price | `storage_block_price` | 0.0 | Monthly price per block. `0` = block mode off (use per-GB). |
| Count Snapshots Toward Storage | `snapshots_count_toward_storage` | On | When on, half the dedup snapshot footprint counts against the plan storage allowance. Off = snapshots covered solely by the backup add-on. |
| Merge Snapshot into Renewal Invoice | `merge_snapshot_into_renewal_invoice` | Off | The snapshot-merge toggle (see §4.3). |
| Custom Price ≥ Nearest Tier | `custom_min_is_nearest_tier` | Off | Enables the `tier_floor` (a custom config can't undercut the nearest tier). |
| Custom-vs-Tier Buffer % | `tier_floor_buffer_pct` | 0.0 | Soft floor: allows a custom config up to N% below the nearest tier. `0` = hard floor (pinned to tier). |

### Block: Monitoring
| Field | Param | Default | Effect |
|---|---|---|---|
| Resource Usage Multiplier | `resource_usage_multiplier` | 2.0 | Display-only: multiplies measured CPU/RAM to account for shared DB usage. Not a billing input. |

### Block: Cloud Storage
| Field | Param | Effect |
|---|---|---|
| Backup Provider | `saas_backup.provider` | AWS S3 / GCS / DigitalOcean Spaces. |
| Bucket Name / Region | `saas_backup.bucket_name` / `saas_backup.region` | Target bucket + region. |
| Access Key / Secret Key | `saas_backup.access_key` / `..._secret_key` | S3-compatible credentials. |
| Service Account JSON Key | `saas_backup.service_account_key` | GCP credentials (upload JSON). |
| Endpoint URL | `saas_backup.endpoint` | Custom S3 endpoint (required for DO Spaces). |

> Snapshots reuse the **same** bucket as backups — there is one Storage block.

---

## 7. Admin recipes ("how do I…")

- **Raise hosting prices for new customers** → bump `hosting_worker_price` /
  `hosting_storage_price_per_gb`. Existing instances keep their stamped plan
  price until they change plan.
- **Stop selling at a loss on tiny configs** → set `hosting_minimum_monthly`
  (e.g. 25). Customers just see the higher price, no surcharge wording.
- **Block "cheap workers + huge storage" abuse** → set `hosting_storage_floor`
  to your real per-GB cost; the engine charges `max(formula, floor)`.
- **Charge more in expensive regions** → set the region's `price_multiplier`
  (>1). Only infrastructure scales, not support/add-ons.
- **One combined invoice per customer** → turn **Merge Snapshot into Renewal
  Invoice** ON. Monthly plans then get a single bill; yearly plans get one
  combined month + 11 standalone backup invoices.
- **Make backups scale with data size** → set the `daily_snapshots` add-on to
  `storage` or `hybrid` mode with a `price_per_block` / `block_gb`. Existing
  subscribers are grandfathered on the flat price until
  `backup_price_locked_until` passes.
- **Protect named tiers from being undercut** → turn **Custom ≥ Nearest Tier**
  ON; soften it with **Custom-vs-Tier Buffer %** if pinning feels rigged.
- **Sell storage in predictable chunks** → set `storage_block_gb` +
  `storage_block_price`; otherwise overage uses the per-GB rate.
```
