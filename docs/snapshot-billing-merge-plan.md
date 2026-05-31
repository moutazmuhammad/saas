# Merge Snapshot Billing into the Renewal Invoice — Design & Execution Plan

> **Plan only — not implemented.** Production-critical billing change.
> Implement step-by-step (M1→M6) on approval, each step verified on a DB
> clone.
>
> **DECISION (owner): the snapshot is ALWAYS billed monthly — never 12×
> up-front.** It is merged into the renewal invoice **only when its monthly
> due date falls on the same renewal** (i.e. it lands in the same invoice
> opportunistically, one month's worth). When the snapshot's next due date
> differs from the instance's renewal date, the snapshot is NOT shown in
> the renewal invoice at all — it stays on its own monthly cycle, so the
> customer never pays for it twice. The merge must be visible/clear to the
> customer wherever it appears.

Grounded in the actual code: `saas_instance.py`
(`_generate_renewal_invoice`, `_cron_generate_recurring_invoices`,
`_cron_renew_daily_backup_addons`, `_generate_daily_backup_renewal_invoice`,
`action_purchase_daily_backup`, `_sync_daily_backup_suspension`),
`account_move.py` (`_saas_check_instance_payment`), and the
`ORIGIN_BACKUP_ADDON` / `ORIGIN_RENEWAL` flows.

---

## 0. Progress checklist

- [x] **M1** — Config toggle `merge_snapshot_into_renewal_invoice` (default False = current behaviour)
- [x] **M2** — Snapshot line builder (`_snapshot_order_line`, ALWAYS qty 1 = one month) reused by both paths
- [x] **M3** — Renewal includes the snapshot line **only when the snapshot is due on/before this renewal**, then advances the snapshot date by 1 month
- [x] **M4** — Backup cron skips an instance **only for the month already merged** (no separate invoice for that month); suspension always runs
- [x] **M5** — Migration: no double charge; the snapshot's own due date is the single source of "is this month already billed?"
- [x] **M6** — Tests + docs + clear customer-facing labelling

---

## 1. Architecture design

### How billing works TODAY (two independent cycles)

```
CYCLE A — subscription (monthly OR yearly)
  cron _cron_generate_recurring_invoices  (next_invoice_date <= today)
    └─ _generate_renewal_invoice()
         origin = SAAS:RENEWAL:<sub>
         lines: [ plan, support(×1 or ×12), overage ]
         advance next_invoice_date by 1 month / 1 year

CYCLE B — daily backup add-on (ALWAYS monthly, even on yearly plans)
  cron _cron_renew_daily_backup_addons  (daily_backup_next_invoice_date <= today)
    ├─ _sync_daily_backup_suspension()   pause/resume snapshots on payment state
    └─ _generate_daily_backup_renewal_invoice()  (only if no unpaid one exists)
         origin = SAAS:BACKUP-ADDON:<sub>
         lines: [ daily backup monthly price ]
         advance daily_backup_next_invoice_date by 1 month
```

The two cycles are deliberately decoupled today because backups bill
**monthly at the monthly rate even on a yearly plan**. Activation
(`action_purchase_daily_backup`) and the payment hook
(`account_move._saas_check_instance_payment`) drive the
`daily_backup_enabled` / `daily_backup_suspended` /
`daily_backup_next_invoice_date` state machine.

### Target: opportunistic, date-aligned merge (always one month)

```
The snapshot's OWN monthly due date (daily_backup_next_invoice_date) stays
the single source of truth for "is this month billed?". Nothing bills a
month twice because both generators check + advance that one date.

CYCLE A — subscription (monthly OR yearly)
  _generate_renewal_invoice()
    origin = SAAS:RENEWAL:<sub>
    lines: [ plan, support, overage ]
    IF merge_flag AND daily_backup_enabled AND
       daily_backup_next_invoice_date <= renewal_date:
         + SNAPSHOT line  (qty 1 = ONE month, at the monthly rate)
         advance daily_backup_next_invoice_date += 1 month
    advance next_invoice_date (by month or year)

CYCLE B — daily backup add-on cron (runs daily, ALWAYS)
  _cron_renew_daily_backup_addons()
    ├─ _sync_daily_backup_suspension()             (pause/resume — always)
    └─ IF daily_backup_next_invoice_date <= today AND no unpaid backup inv:
           _generate_daily_backup_renewal_invoice()  (separate monthly inv)
           advance daily_backup_next_invoice_date += 1 month
```

So the merge is **opportunistic**: on a renewal day, if the snapshot's
monthly charge happens to be due too, it rides along in the same invoice
(one month) and its date advances — so cron B then sees it as not-due and
skips it. On any other day, cron B bills the snapshot separately. The
snapshot is **always exactly one month**, on the same date it would have
billed anyway — never 12× up-front, never doubled.

### Customer requirement: never offer/show it if the dates differ

Per the owner: if the snapshot's next due date ≠ the instance's renewal
date, the customer must NOT see a snapshot line on the renewal (they're
already paying for it separately that month). The `<=` date check enforces
exactly this: the line only appears when the snapshot month genuinely
coincides with the renewal.

### Why a YEARLY plan is automatically correct here

A yearly renewal happens once a year. On that one day the snapshot is due
(monthly), so it merges **one month** and advances a month. The other 11
months, cron B bills the snapshot separately — **monthly, as required**.
No 12× prepay, no behaviour change to the snapshot cadence; the only
difference is that one month a year lands on the same invoice as the plan.

### Core principle — single billing-aggregation change

The **pricing engine is untouched**. The snapshot price is still
`_get_daily_backup_price()` (storage-aware + lock-aware). We add **one**
reusable line builder (always one month) and a date check that routes it
into either the renewal or the standalone cron — never both for the same
month.

---

## 2. Required code changes

### M1 — Config toggle (`res_config_settings.py`)
- New Boolean, manual get/set (Boolean trap):
  `saas_master.merge_snapshot_into_renewal_invoice`, **default False**
  (current behaviour preserved). Surfaced in Settings ▸ SaaS ▸ Pricing
  Engine (or Billing) block.
- Helper on the engine or instance: `_merge_snapshot_billing()` → reads
  the flag once.

### M2 — Reusable snapshot line builder (`saas_instance.py`)
New `_snapshot_order_line()` returning a sale-order line tuple or `None`,
**always one month** (the snapshot rate is monthly, period-independent):
```
if not (is_hosting and daily_backup_enabled): return None
price = self._get_daily_backup_price()      # storage-aware + lock-aware
if price <= 0: return None
return (0,0,{ product: daily_backup_product,
             name: 'Daily Backups (1 month) — <sub>',
             product_uom_qty: 1, price_unit: price })
```
`_generate_daily_backup_renewal_invoice` is refactored to reuse this
builder, so there is ONE definition of the snapshot line.

### M3 — Renewal merges it ONLY when the snapshot month is due
In `_generate_renewal_invoice`, after the support line:
```
renewal_date = self.next_invoice_date            # the cycle boundary being billed
snap_due = (self.daily_backup_enabled
            and self.daily_backup_next_invoice_date
            and self.daily_backup_next_invoice_date <= renewal_date)
if self._merge_snapshot_billing() and snap_due:
    snap = self._snapshot_order_line()
    if snap:
        order_lines.append(snap)
        # this month is now billed → advance the snapshot's own date so
        # cron B won't re-bill it. ONE month only.
        self.write({
          'daily_backup_last_invoice_date': fields.Date.today(),
          'daily_backup_next_invoice_date':
              self.daily_backup_next_invoice_date + relativedelta(months=1),
        })
```
If the snapshot isn't due on this renewal date, no line is added (the
customer doesn't see it) and cron B bills it on its own date — never
double.

### M4 — Backup cron unchanged except it naturally skips the merged month
`_cron_renew_daily_backup_addons` already guards on
`daily_backup_next_invoice_date <= today AND no unpaid backup invoice`.
Because M3 advanced that date when it merged the month, the cron simply
sees "not due yet" and skips — **no flag check needed in the cron**. The
only addition: `_sync_daily_backup_suspension()` still runs every tick.

**Suspension when merged-and-unpaid:** if a renewal that *contains* a
snapshot line goes unpaid, the snapshot for that month was already
advanced (date moved forward) but not paid. To keep the existing
"pause snapshots when the backup month is unpaid" guarantee, the overdue
check (`_daily_backup_unpaid_invoices`) must also recognise an **unpaid
RENEWAL invoice that contains a snapshot line** as an unpaid backup. M4
extends `_daily_backup_unpaid_invoices()` to include renewal invoices
whose lines reference the daily-backup product. (Simpler alternative kept
as fallback: an unpaid renewal suspends the whole instance via normal
dunning, which stops snapshots anyway.)

### M5 — Migration (see §3).

### M6 — Tests (see §6).

---

## 3. Database / model + migration plan

### Model
- No new columns strictly required. `backup_price_locked_until`,
  `daily_backup_enabled`, `daily_backup_next_invoice_date` all stay and
  keep their meaning.
- Optional: a per-instance audit note in chatter when an instance flips to
  merged billing.

### Migration strategy (the critical part — no double charge)

Because **`daily_backup_next_invoice_date` is the single source of truth**
for "is this month billed?", there is essentially **nothing to migrate**:

1. **Deploy with flag OFF** → both cycles run exactly as today.
2. **Operator flips flag ON** → from that moment, each renewal *checks*
   whether the snapshot month is due (`daily_backup_next_invoice_date <=
   renewal_date`). If it is, it merges one month and advances that date;
   if not, it leaves it alone and cron B bills it.
3. **No double charge — structurally**: only one generator ever advances
   the snapshot date for a given month. If the renewal merges it, the date
   moves and cron B skips. If the renewal doesn't (date not yet due), cron
   B bills it on its own day. The two can never bill the same month
   because they share — and advance — the same date field.
4. **No overlap on the flip**: an instance billed separately yesterday has
   its `daily_backup_next_invoice_date` already a month out, so a renewal
   today won't re-bill it (date not due). It merges naturally the first
   time the snapshot month genuinely lands on a renewal day.
5. **Historical invoices untouched** — only future generation changes.
6. **Migration file** (`18.0.23.0.0/post-migrate.py`): only sets the config
   key default if we want auto-on; **never touches invoices or dates**.
   With the default OFF, no post-migrate is even required.

---

## 4. Cron job modifications

| Cron | Change |
|---|---|
| `_cron_generate_recurring_invoices` | unchanged (still drives renewals) |
| `_generate_renewal_invoice` | + snapshot line when merged; pin backup date forward |
| `_cron_renew_daily_backup_addons` | always run suspension; **skip invoice issue** for merged instances |
| `_generate_daily_backup_renewal_invoice` | refactor to reuse `_snapshot_order_line`; only called for non-merged |
| `account_move._saas_check_instance_payment` | activation path unchanged; for merged instances the "resume on payment" is covered by subscription-paid → un-suspend |

---

## 5. Invoice generation flow (target, with toggle)

```
RENEWAL DUE (next_invoice_date <= today)
  └─ _generate_renewal_invoice()
       apply scheduled downgrade (if any)
       lines = [ plan ]
       + support_line (qty 1 monthly / 12 yearly)
       if merge_flag:
            + snapshot_line (qty 1 monthly / 12 yearly, price = _get_daily_backup_price)
            pin daily_backup_next_invoice_date = new next_invoice_date
       + overage_line (if charge > 0)
       create SO (origin RENEWAL) → invoice → advance next_invoice_date → post
       auto-charge if token

BACKUP CRON (daily)
  └─ for each backup-enabled instance:
       _sync_daily_backup_suspension()          # always
       if merge_flag: continue                  # renewal handles billing
       else: existing standalone monthly invoice
```

### Yearly-plan handling (explicit) — DECIDED

The snapshot is **always monthly**, qty 1, never prepaid.

- **Monthly plan:** the snapshot's monthly date coincides with each
  monthly renewal, so it merges every month → one clean invoice per month
  (Plan + Support + Snapshot + Overage).
- **Yearly plan:** the yearly renewal day coincides with the snapshot's
  monthly date once a year, so on that one invoice the snapshot rides
  along (one month). The other 11 months, cron B issues the standalone
  monthly snapshot invoice. The customer thus always pays the snapshot
  monthly, exactly as before — only one of those months happens to share
  the plan's annual invoice.
- **Customer visibility:** because the line only appears when the snapshot
  month is genuinely due on that renewal, the customer never sees a
  snapshot line they're already paying separately, and never a 12-month
  block.

---

## 6. Edge case handling strategy

| Edge case | Handling |
|---|---|
| Yearly plan, snapshot monthly | Snapshot date coincides with the yearly renewal once a year → merges one month then; the other 11 months cron B bills separately. Always monthly, never 12× prepay. |
| Snapshot due date ≠ renewal date | `daily_backup_next_invoice_date <= renewal_date` is False → **no snapshot line on the renewal** (customer not shown it); cron B bills it on its own day. |
| Backups disabled mid-cycle | `_snapshot_order_line` returns None when `daily_backup_enabled` is False → renewal omits the line; cron B also skips. No proration refund (matches today). |
| Snapshot price change while active | `_get_daily_backup_price()` read at billing time, honouring `backup_price_locked_until` grandfathering — same as today, whichever generator bills it. |
| Reactivation with retained snapshot | `daily_backup_enabled` cleared on reactivate; customer re-enables (activation invoice + retention surcharge) — **unchanged** (activation stays a separate one-time invoice; only the recurring monthly snapshot can opportunistically merge). |
| Overage + backup + support same invoice | All are order lines on the one renewal SO (only when the snapshot month is due). Already how support+overage work. |
| Unpaid renewal that contains a snapshot line | The snapshot date was advanced; to keep "pause snapshots when the backup month is unpaid", `_daily_backup_unpaid_invoices` recognises an unpaid renewal carrying a daily-backup line. Fallback: dunning suspends the whole instance anyway. |
| Flag flipped OFF again | Renewals stop merging; cron B bills the snapshot on its (already-correct) due date. Fully reversible — the date field carries the state. |
| Idempotency | One date field (`daily_backup_next_invoice_date`) is checked AND advanced by whichever generator bills the month; the other then sees "not due" and skips. A month can never be billed twice. |

---

## 7. Risk analysis

| Risk | Severity | Mitigation |
|---|---|---|
| **Double billing** a month of snapshots | High → Low | Structurally impossible: one `daily_backup_next_invoice_date` is checked AND advanced by whichever generator bills the month; the other sees "not due" and skips. Verify on clone with monthly + yearly + mid-cycle instances. |
| Yearly customers prepaying a year of snapshots | **Eliminated** | The snapshot is always qty 1 (one month); never 12×. Decided. |
| Snapshot suspension diverges (merged renewal unpaid, snapshots keep running) | High | `_daily_backup_unpaid_invoices` extended to recognise an unpaid renewal carrying a daily-backup line; fallback is normal dunning suspending the instance. Test the unpaid-merged-renewal path explicitly. |
| Historical invoice integrity | High | Never modify posted invoices; only future generation changes. |
| Auto-charge: the merged renewal already includes the snapshot, so it's one charge | Low | Merged month → single renewal invoice → single `_try_auto_charge_invoice(kind='subscription')`. cron B doesn't issue a second invoice that month. |
| Revenue reporting (one snapshot month now under RENEWAL origin) | Low | Snapshot **line** is clearly named and uses the daily-backup product; reports key on product/line, not origin. Document it. |
| Partial rollout / mixed fleet | Low | Flag read per-instance at generation time; merged and non-merged instances coexist safely; the date field carries per-instance state. |

---

## 8. Expected outcome

- **Default (flag OFF):** byte-for-byte current behaviour — separate
  cycles. Zero change on deploy.
- **Flag ON:** the snapshot stays **monthly, qty 1, always**. On any
  renewal where the snapshot month is genuinely due, it rides along in the
  same invoice (Plan + Support + Snapshot + Overage) and the customer sees
  one clear "Daily Backups (1 month)" line; otherwise the snapshot bills
  on its own monthly date and the customer doesn't see it on the renewal.
  Monthly plans → effectively one invoice per month. Yearly plans → one
  merged month a year, 11 standalone months — always monthly.
- Pricing engine unchanged; snapshot price still storage-aware + lock-aware.
- No duplicate invoices (single shared date field); historical data
  intact; fully reversible.

---

## 9. Recommended implementation order
1. **M1** toggle (inert, default OFF).
2. **M2** `_snapshot_order_line` (always 1 month) + refactor the standalone
   generator to reuse it (pure refactor — lock with a test that the
   standalone invoice is unchanged).
3. **M3** renewal merges the line **only when the snapshot month is due**
   (`daily_backup_next_invoice_date <= renewal_date`), advancing that date.
4. **M4** extend `_daily_backup_unpaid_invoices` so an unpaid merged
   renewal still pauses snapshots; confirm cron B naturally skips the
   already-advanced month (no flag check needed in the cron).
5. **M5** migration note (no invoice/date backfill needed); verify on a
   clone: monthly merges every month, yearly merges once + 11 standalone,
   mismatched dates show no line, no month billed twice.
6. **M6** tests (merged-when-due single invoice; not-due → no line + cron
   bills it; yearly = 1 merged + standalone; disabled-backup omits;
   lock/storage price respected; unpaid merged renewal pauses snapshots)
   + update `pricing-playbook.md` + clear customer labelling.

Each step: behaviour-neutral default, verified on a DB clone, committed
separately.
