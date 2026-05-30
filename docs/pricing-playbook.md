# Pricing Playbook

How pricing works here, every field that affects the price, and exact
numbers to set for profit + fair customer value. Configure under
**Settings ▸ SaaS** unless noted.

---

## 1. The formula (this is the whole engine)

Every quote — SPA, funnel, renewals, plan creation — is one calculation
(`saas.pricing.engine.compute`):

```
base            = workers × worker_price  +  storage_gb × storage_price_per_gb
floor           = max( workers × worker_floor + storage_gb × storage_floor ,  nearest_tier_price )
resource        = max(base, floor) × region_multiplier
monthly         = resource + Σ(add-ons)            # add-ons are NOT × region
yearly          = monthly × 12 × (1 − yearly_discount/100)
```

Hosting and Services have **separate** rate sets. The customer never sees
`worker_price` / `storage_price_per_gb` — only the final total.

Storage **overage** (billed on renewal when usage exceeds the plan limit)
is separate:
```
over_gb = ceil(used − limit)
charge  = block_price × ceil(over_gb / block_gb)   if blocks configured
        = over_gb × extra_storage_price_per_gb     otherwise
```

---

## 2. Every field that affects price

### Base rates (drive the slider price)
| Field | Hosting key / Services key | What it does |
|---|---|---|
| Price per worker | `hosting_worker_price` / `worker_price` | $/worker/month. The main lever. |
| Price per GB | `hosting_storage_price_per_gb` / `storage_price_per_gb` | $/GB/month. |
| Yearly discount % | `hosting_yearly_discount_pct` / `custom_plan_yearly_discount_pct` | Discount for annual billing. Locks in cash + cuts churn. |

### Limits (bound the slider — not price directly, but they cap how cheap/expensive a config can get)
| Field | Keys | Purpose |
|---|---|---|
| Min/Max workers | `*_min_workers` / `*_max_workers` | Smallest sellable plan ↔ ceiling. |
| Min/Max storage | `*_min_storage` / `*_max_storage` | Same for GB. |

### Floors (margin protection — never sell below cost)
| Field | Keys | What it does |
|---|---|---|
| Cost floor / worker | `hosting_worker_floor` / `worker_floor` | Minimum $/worker. Quote = `max(rate, floor)`. |
| Cost floor / GB | `hosting_storage_floor` / `storage_floor` | Minimum $/GB. |
| Custom ≥ nearest tier | `custom_min_is_nearest_tier` | A slider config can't be priced below a named tier it contains. Protects tier value. |

→ Set floors at (or just above) your real infra cost. `0` = off.

### Regions (price varies by location)
| Field | Where | What it does |
|---|---|---|
| Price multiplier | SaaS ▸ Regions → `price_multiplier` | × on **compute+storage** (not add-ons). e.g. 1.5 = US 50% pricier than EU. |

A region is offered **only** if it has a proxy + docker + db server in it.
Empty regions are hidden. Region is fixed at instance creation.

### Add-ons (recurring extras, added after region)
| Field | Where | What it does |
|---|---|---|
| Daily backup price | `hosting_daily_backup_price` | Monthly add-on for daily snapshots. |
| Retention surcharge | `hosting_snapshot_retention_surcharge` | One-time fee on reactivation if a snapshot was kept after cancel. |
| Data restoration fee | `data_restoration_fee` | One-time fee to restore a cancelled instance's snapshot. |

### Storage overage (only billed when a customer exceeds their limit)
| Field | Keys | What it does |
|---|---|---|
| Per-GB overage | `extra_storage_price_per_gb` | Charged per GB over the plan limit, on renewal. |
| Block size / price | `storage_block_gb` / `storage_block_price` | If both > 0, overage is sold in whole blocks instead (predictable). |
| Snapshots count toward storage | `snapshots_count_toward_storage` | If ON, ½ the snapshot size counts against the limit. Recommended **OFF** (don't double-charge — snapshots are the paid add-on). |

### Not price — but tied to it
- `resource_usage_multiplier`: monitoring only (CPU/RAM % shown to customer), not billing.
- `cpu_per_worker` / `ram_per_worker`: resources provisioned per worker. Set to your real cost basis so floors make sense.

---

## 3. How to set it for profit + value

**Rule:** price on **value to the customer**, protect the downside with
**floors at cost**, win cash with the **annual discount**.

### Step 1 — Know your cost per unit
Work out your true monthly cost of 1 worker (vCPU+RAM share) and 1 GB
(NVMe + backup + overhead). Call them `Cw` and `Cs`.

### Step 2 — Set floors at cost (safety net)
```
hosting_worker_floor  = Cw
hosting_storage_floor = Cs
```
Now no slider combination can ever sell below cost.

### Step 3 — Set the sticker rate at a healthy margin
Target ~**60–75% gross margin** on compute (SaaS infra norm):
```
hosting_worker_price        = Cw / (1 − 0.70)   ≈ Cw × 3.3
hosting_storage_price_per_gb = Cs / (1 − 0.70)   ≈ Cs × 3.3
```
Storage is cheap to you but valued by the customer — a higher storage
markup is fine and rarely resisted.

### Step 4 — Annual discount that pays for itself
```
yearly_discount_pct = 15–20
```
20% off for 12 months paid upfront beats monthly churn: you get the cash
now and keep the customer a year. Don't exceed ~20% or you erode margin.

### Step 5 — Publish 3 tiers, keep the slider for power users
Create 3 `saas.plan` tiers (Starter / Pro / Business) under SaaS ▸ Plans,
mark **Is Public Tier**, set **Is Recommended** on the middle one. Tiers
convert better than a bare slider (anchoring + a clear "best value"
default). Turn on `custom_min_is_nearest_tier` so the slider can't
undercut them.

> Tier pricing tip: make the **middle (recommended)** tier the obvious
> best value — price Starter close to it so most buyers jump to Pro, and
> price Business clearly higher to anchor Pro as "reasonable".

### Step 6 — Storage overage = block-based, fair
```
storage_block_gb    = 10
storage_block_price = 10 × hosting_storage_price_per_gb   (≈ the normal rate)
snapshots_count_toward_storage = False
```
Predictable ("+$X per 10 GB") reads fairer than per-GB nickel-and-diming,
and OFF on the snapshot flag means you don't bill storage twice.

### Step 7 — Region multiplier = real cost difference only
Set each region's `price_multiplier` to your **actual** cost ratio (e.g.
US infra 1.4× EU → multiplier 1.4). Don't inflate it; customers compare.

### Step 8 — Backups as a clear paid add-on
Price `hosting_daily_backup_price` as a small, obvious monthly line (e.g.
10–15% of a typical plan). It's high-value, low-cost to you, and easy to
say yes to.

---

## 4. Quick sanity targets

| Lever | Healthy range |
|---|---|
| Gross margin on compute | 60–75% |
| Storage markup | 3–5× your cost |
| Yearly discount | 15–20% |
| Floor vs sticker | floor = cost, sticker ≈ 3× floor |
| Region multiplier | = real cost ratio (≈1.0–1.6) |
| Recommended tier | priced as the clear "best value" |

**Value side:** every plan already includes SSL, daily-snapshot option,
zero-downtime upgrades, logs/metrics, region choice, and one retained
snapshot after cancellation — lead with those, then price on value.

After any change the engine applies it instantly (no restart). Verify with
the test suite: `odoo -d <db> -u saas_core --test-enable --test-tags
/saas_core:TestPricingEngine --stop-after-init`.

See also: `pricing-admin-guide.md` (where each knob lives) and
`pricing-system-execution-plan.md` (design).
