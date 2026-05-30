# Pricing v2 — Enhancement Execution Plan (Source of Truth)

> Design for 4 enhancements: (1) minimum monthly charge, (2) storage-aware
> backup pricing, (3) support plans as paid add-ons, (4) better tier
> protection. **Plan only — not implemented yet.** Implement step-by-step
> (P1→P7) on approval, each phase behaviour-neutral by default.
>
> Builds on the existing single engine `saas.pricing.engine.compute`. Read
> `pricing-playbook.md` (how pricing works today) first.

---

## 0. Progress checklist

- [x] **P1** — Minimum monthly charge (engine + setting + breakdown)
- [x] **P2** — Tier protection redesign (soft-floor %, the lowest-risk win)
- [x] **P3** — `saas.support.plan` model + ACL + admin views + seed
- [ ] **P4** — Storage-aware backup pricing (extend `saas.addon`)
- [ ] **P5** — Wire support + new backup into recurring billing
- [ ] **P6** — Customer UI (configure/upgrade/reactivate: support picker + line items)
- [ ] **P7** — Migration + tests + docs

---

## 1. Business analysis (short)

| Enhancement | Why it makes money | Risk |
|---|---|---|
| **Min monthly charge** | Tiny plans cover infra (floors) but not fixed business cost (payment fees, support, CAC). A $10–20 floor turns every customer profitable. | Low — just a `max()` at the end. |
| **Storage-aware backups** | A 2 TB customer costs 100× a 20 GB customer to back up but pays the same flat fee today. Scaling recovers real cost + margin on heavy users. | Medium — changes a live recurring charge; needs grandfathering. |
| **Support plans** | Highest-margin lever in cloud. Mission-critical customers pay a lot for fast SLAs; it's pure margin (you already staff support). | Low–medium — new recurring add-on, no infra. |
| **Tier protection** | Current hard floor makes a 3w/95GB custom cost ≈ the 4w/100GB Pro tier — feels rigged, kills conversions. A soft floor keeps tier value without the "rigged" feel. | Low — relaxes an existing rule. |

**Guiding principle:** transparent line items (customer sees exactly what
each thing costs), margins protected by floors + minimum, value sold via
support tiers and tier bonuses.

---

## 2. Recommended architecture

One rule: **everything still flows through `saas.pricing.engine.compute`**
so SPA, funnel, renewals and plan creation stay consistent. New pricing
order (extends today's flow; new steps in **bold**):

```
base            = workers·worker_price + storage·storage_price_per_gb
floor           = max(cost_floor, tier_floor)            # P2 changes tier_floor
resource        = max(base, floor) × region_multiplier
addons_monthly  = Σ flat add-ons
                  + backup_addon(storage)                # P4: storage-aware
                  + support_plan_price                   # P3: not × region
monthly_raw     = resource + addons_monthly
monthly         = max(monthly_raw, minimum_monthly_charge)   # P1
yearly          = monthly × 12 × (1 − discount)
```

`compute()` gains two optional args — `support_code=None`,
`backup_enabled=False` — and the `breakdown` dict gains
`minimum_applied`, `backup_cost`, `support_cost`. All default to today's
behaviour (no min, no support, flat backup) so **P1–P5 are
behaviour-neutral until configured**.

---

## 3. Decisions taken (the 4 open questions)

**Backup pricing (Q2): HYBRID, default = pure-fixed.** One formula covers
all three modes via config:
`backup = base_fee + ceil(storage_gb / block) × per_block`.
- `fixed`: per_block = 0 → just `base_fee` (= today's behaviour).
- `storage_based`: base_fee = 0.
- `hybrid`: both set.
Billed per 10 GB block (not raw GB) so the customer sees "+$X per 10 GB",
not noisy decimals.

**Tier protection (Q4): OPTION A (soft floor) + a dash of B.** Recommended:
- Soft floor: a custom plan may be priced down to `(1 − buffer%) × nearest
  tier`, buffer configurable (default 10%). So 3w/95GB lands ~10% under
  Pro — cheaper, but the tier is still the better deal per resource.
- Plus make tiers visibly better value (B) via the existing tier badge /
  recommended flag — no code, just config. **Avoid Option C** (no
  protection) — it lets a slider fully cannibalise tiers.

**Support (Q3):** new model, NOT region-scaled, added after infra. Selected
support plan stored on the instance, billed every cycle.

**Minimum (Q1):** single global setting per kind (hosting/services), applied
as the final `max()`. Shown to the customer only as the final price (a
`minimum_applied` flag drives an optional "minimum plan" microcopy, never a
scary surcharge line).

---

## 4. Database / model changes

### P1 — Minimum monthly charge
`res.config.settings` (config params, no new model):
- `saas_master.hosting_minimum_monthly` (Float, default 0 = off)
- `saas_master.minimum_monthly` (services, default 0 = off)

### P2 — Tier protection
`res.config.settings`:
- `saas_master.tier_floor_buffer_pct` (Float, default 0 = today's hard
  floor; e.g. 10 = allow 10% under nearest tier).
  Reuses the existing `custom_min_is_nearest_tier` on/off switch.

### P3 — Support plans (new model)
`saas.support.plan`:
| field | type | notes |
|---|---|---|
| name | Char | "Standard", "Pro", "Enterprise" |
| code | Char unique | "standard" / "pro" / "enterprise" |
| monthly_price | Float | flat, NOT region-scaled |
| response_time | Char | "24h" / "4h" / "1h" (display) |
| description | Text | |
| sequence, active | Integer/Bool | |
| is_default | Bool | the free/best-effort default (price 0) |

`saas.instance`: `support_plan_id = Many2one('saas.support.plan')` (fixed
on the instance, editable on upgrade). Default = the `is_default` plan.

### P4 — Storage-aware backups (extend `saas.addon`, no new model)
Add to `saas.addon`:
- `price_mode` Selection: `flat` (default) / `storage` / `hybrid`
- `price_per_block` Float (per `block_gb`)
- `block_gb` Integer (default 10)
- `base_fee` Float (the flat part; for `flat` mode this == `monthly_price`)
`effective_monthly_price()` gains an optional `storage_gb` arg:
`base + ceil(storage_gb/block_gb) × price_per_block`. Existing flat add-ons
(price_mode='flat') are unchanged.

---

## 5. Pricing-engine modifications (`saas_pricing.py`)

- `_minimum_monthly(kind)` → reads the setting (0 = off).
- `_support_price(code)` → `saas.support.plan` lookup (0 if none/default).
- `_addons_total(kind, codes, storage)` → pass `storage` so a
  storage-aware backup add-on scales; flat ones ignore it.
- `_tier_floor(kind, workers, storage)` → multiply the matched tier price
  by `(1 − tier_floor_buffer_pct/100)`.
- `compute(... , support_code=None)`:
  ```
  addons   = _addons_total(kind, addon_codes, storage)
  support  = _support_price(support_code)          # after region, flat
  monthly  = resource + addons + support
  monthly  = max(monthly, _minimum_monthly(kind))
  ```
  `breakdown` adds: `backup_cost`, `support_cost`, `minimum_applied`
  (bool), `pre_minimum` (the raw value).

Order matters: **support & add-ons are added BEFORE the minimum** (so a
plan that already exceeds the minimum via add-ons isn't double-charged),
and **after region** (support/add-ons never × region).

---

## 6. Admin UI changes (`res_config_settings_views.xml` + new views)

- **Pricing Engine block**: add "Minimum monthly charge" (Hosting ·
  Services, two columns) and "Custom-vs-tier buffer %".
- **Backups**: the existing daily-backup add-on form (`saas.addon`) gains
  Mode / Base fee / Per-block / Block size fields (shown by mode).
- **New menu SaaS ▸ Support Plans**: list + form for `saas.support.plan`
  (name, code, price, response time, description, active, default).
- Seed: Free (0, best-effort, default), Standard (24h), Pro (4h),
  Enterprise (1h) — placeholder prices, `noupdate`.

## 6b. Customer-facing UI

- **Configure / upgrade / reactivate** (QWeb funnel + portal): add a
  **Support plan** selector (radio cards: name · response time · price).
  Region multiplier does NOT apply to it.
- **Order summary**: show line items — Plan, Daily Backups (with "scales
  with storage" note when storage-based), Support, and the final total.
  When the minimum kicks in, show just the final price (no surcharge
  line); optional small "minimum plan" note.
- **API** (`/meta`, `/hosting/calculate`, `/services/calculate`): accept
  `support_code`; return `support_plans` list + the new breakdown fields.
  `/tiers` unchanged.

---

## 7. Migration strategy

- **Config defaults**: minimum = 0, buffer = 0, backup mode = flat →
  **zero price change on deploy** for everyone.
- **Support**: every existing instance gets `support_plan_id` = the Free
  default in the post-migrate; no charge, no behaviour change.
- **Storage-aware backups — grandfather existing subscribers**: when you
  switch the backup add-on to storage/hybrid, existing
  `daily_backup_enabled` instances keep their **current** flat price until
  their next renewal, OR get a one-cycle notice. Add
  `backup_price_locked_until` (Date) on the instance, set on migration to
  the next invoice date; the engine uses the flat price while locked. New
  activations use the new model immediately. (Prevents a surprise jump on
  a live recurring charge — the only real risk in this whole plan.)
- Module version bump (e.g. 18.0.17.0.0) with one post-migrate doing the
  two backfills above. `-u saas_core,saas_website` on deploy.

## 8. Backward compatibility

- `compute()` new args are keyword-optional with neutral defaults → every
  existing caller works unchanged.
- `effective_monthly_price()` keeps its no-arg form (flat) → existing
  add-on callers unaffected.
- Daily-backup keeps its **separate monthly cycle**
  (`_cron_renew_daily_backup_addons`) — P4 only changes the amount, not
  the mechanism. Support rides the **plan** renewal cycle
  (`_generate_renewal_invoice`) as a new line.
- Defaults make P1–P5 inert until an admin configures them.

---

## 9. Example calculations

Rates: worker $10, GB $0.30, region ×1.0. Minimum (hosting) $15.

| Config | base | +backup | +support | raw | final |
|---|---|---|---|---|---|
| 1w / 5GB, no extras | 11.50 | — | — | 11.50 | **15.00** (min) |
| 1w / 5GB + Standard support $10 | 11.50 | — | 10 | 21.50 | 21.50 (min not hit) |
| 4w / 50GB | 55.00 | — | — | 55.00 | 55.00 |
| 4w / 2000GB + storage backups (base $5, $1/10GB) | 640.00 | 5 + 200 | — | 845.00 | 845.00 |
| 4w / 20GB + same backup | 46.00 | 5 + 2 | — | 53.00 | 53.00 |

Backup fairness: the 2 TB customer pays $205 backup vs $7 for 20 GB —
proportional to real cost. Support adds flat, region-independent.

Tier soft-floor (buffer 10%): Pro = 4w/100GB/$60. Custom 3w/95GB base
$58.50 → allowed down to $54 (0.9×60). So it's cheaper than Pro but Pro
still gives more per dollar.

---

## 10. Test scenarios (extend `test_pricing_engine.py`)

1. **Min off (default)** → price unchanged (regression lock).
2. **Min on**: tiny config → `monthly == minimum`, `minimum_applied=True`;
   config above min → unchanged, flag False.
3. **Min + add-ons**: add-ons counted before min (no double charge).
4. **Backup flat (default)** == today's number.
5. **Backup storage/hybrid**: 20GB vs 2TB give correct `base + blocks×rate`.
6. **Support**: price added, **not** × region (×2 region leaves support
   flat); default/free plan adds 0.
7. **Tier buffer 0** == current hard floor; **buffer 10** → custom allowed
   to 0.9× tier, not below.
8. **Order**: support+addons before min, after region — assert breakdown
   keys (`backup_cost`, `support_cost`, `pre_minimum`, `minimum_applied`).
9. **Grandfather**: a `backup_price_locked_until` instance keeps the flat
   price until the lock date.
10. **End-to-end**: renewal invoice has Plan + Support lines; backup keeps
    its own cycle with the new amount.

---

## 11. Recommended implementation order

Lowest risk / highest value first; each is shippable alone:

1. **P1 Minimum monthly charge** — one `max()`, instant margin floor.
2. **P2 Tier soft-floor** — relax one rule, removes the "rigged" feel,
   lifts conversions. Pure win.
3. **P3 Support plans** — new model + add-on; highest-margin revenue, no
   infra, no migration risk.
4. **P4 Storage-aware backups** — needs the grandfather migration; do
   after support so the add-on UX pattern exists.
5. **P5 Billing wiring** — support line on renewals; backup amount update.
6. **P6 Customer UI** — support picker + itemised summary across
   configure/upgrade/reactivate.
7. **P7 Migration + tests + docs** — backfills, full test pass, update
   `pricing-playbook.md`.

Each phase: behaviour-neutral default, verified on a DB clone, committed
separately on a branch.
