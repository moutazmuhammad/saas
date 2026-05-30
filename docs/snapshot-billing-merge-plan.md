# Merge Snapshot Billing into the Renewal Invoice — Design & Execution Plan

> **Plan only — not implemented.** Production-critical billing change.
> Implement step-by-step (M1→M6) on approval, each step verified on a DB
> clone. Goal: one invoice per renewal (plan + support + snapshot +
> overage), behind a toggle, with zero double-billing during migration.

Grounded in the actual code: `saas_instance.py`
(`_generate_renewal_invoice`, `_cron_generate_recurring_invoices`,
`_cron_renew_daily_backup_addons`, `_generate_daily_backup_renewal_invoice`,
`action_purchase_daily_backup`, `_sync_daily_backup_suspension`),
`account_move.py` (`_saas_check_instance_payment`), and the
`ORIGIN_BACKUP_ADDON` / `ORIGIN_RENEWAL` flows.

---

## 0. Progress checklist

- [ ] **M1** — Config toggle `merge_snapshot_into_renewal_invoice` (default False = current behaviour)
- [ ] **M2** — Snapshot line builder (`_snapshot_order_line`) reused by both paths
- [ ] **M3** — Renewal generator includes the snapshot line when merged
- [ ] **M4** — Backup cron skips merged instances (no separate invoice); suspension still works
- [ ] **M5** — Migration: flip the cycle safely on next renewal, no double charge
- [ ] **M6** — Tests + docs

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

### Target: ONE invoice when merged

```
CYCLE A — subscription (monthly OR yearly)
  _generate_renewal_invoice()
    origin = SAAS:RENEWAL:<sub>
    lines: [ plan, support, SNAPSHOT, overage ]   ← snapshot now here
    advance next_invoice_date

CYCLE B — daily backup add-on cron
  _cron_renew_daily_backup_addons()
    ├─ _sync_daily_backup_suspension()   ← STILL runs (pause/resume logic kept)
    └─ issue separate invoice  ONLY IF  merge flag is OFF for that instance
```

### Core principle — single billing-aggregation change

The **pricing engine is untouched**. We only change the **aggregation
layer**: which generator emits the snapshot line. The snapshot price is
still `_get_daily_backup_price()` (storage-aware + lock-aware). We add
**one** reusable line builder and route it.

### The hard problem: monthly snapshot on a yearly plan

Today a yearly customer pays backups 12× a year (monthly). If we merge the
snapshot into a **yearly** renewal invoice, we must bill **12 months of
snapshot up-front** on that yearly invoice (qty = 12 at the monthly rate)
— exactly as support already does (`_support_order_line` uses qty 12 on
yearly). This keeps the snapshot term aligned with the plan term and
preserves total revenue. Monthly plans bill qty 1. This is the key design
decision and it mirrors the existing support pattern, so it's consistent.

Consequence when merged: `daily_backup_next_invoice_date` is no longer the
billing driver for merged instances — the plan's `next_invoice_date` is.
The backup cron must NOT also bill them.

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
New `_snapshot_order_line(period, period_label)` returning a sale-order
line tuple or `None`:
```
if not (is_hosting and daily_backup_enabled): return None
price = self._get_daily_backup_price()      # storage-aware + lock-aware
if price <= 0: return None
months = 12 if period == 'yearly' else 1    # snapshot is a MONTHLY rate
return (0,0,{ product: daily_backup_product, name: 'Daily Backups (...)',
             product_uom_qty: months, price_unit: price })
```
Mirrors `_support_order_line` exactly. `_generate_daily_backup_renewal_invoice`
is refactored to reuse this builder (qty 1) so there's one definition.

### M3 — Renewal generator includes it (`_generate_renewal_invoice`)
After the support line, before/after overage:
```
if self._merge_snapshot_billing():
    snap = self._snapshot_order_line(period, period_label)
    if snap:
        order_lines.append(snap)
        # keep the standalone backup cycle from also billing:
        bump daily_backup_last_invoice_date = today
        daily_backup_next_invoice_date = next_invoice_date (the NEW one)
```
When merged, the snapshot's "next invoice" is pinned to the plan's next
renewal so cron B sees it as not-yet-due.

### M4 — Backup cron respects the flag (`_cron_renew_daily_backup_addons`)
```
for instance in instances:
    instance._sync_daily_backup_suspension()     # ALWAYS (pause/resume kept)
    if instance._merge_snapshot_billing():
        continue                                  # merged → renewal bills it
    ... existing separate-invoice logic ...
```
Suspension still works for merged instances: an unpaid **renewal** invoice
(which now contains the snapshot line) pauses snapshots via the same
overdue check — but `_daily_backup_unpaid_invoices()` currently only looks
at `SAAS:BACKUP-ADDON` origins. **M4 must extend the suspension source** to
also treat an overdue merged renewal as "backup unpaid", OR (simpler and
safer) tie snapshot suspension for merged instances to the existing
subscription-overdue/suspension path (the instance gets suspended anyway
when the renewal is overdue, which already stops snapshots). Decision:
**reuse subscription suspension** — a merged snapshot is part of the
subscription, so if the renewal is unpaid the whole instance is suspended
(snapshots included). No separate snapshot-suspension needed when merged.

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

The flag is **global** but the transition is **per-instance and lazy**:

1. **Deploy with flag OFF** → nothing changes; both cycles run as today.
2. **Operator flips flag ON** → from that moment:
   - The **renewal generator** starts adding the snapshot line on each
     instance's **next** renewal.
   - The **backup cron** stops issuing standalone backup invoices for
     merged instances.
3. **No double charge during the gap**: an instance might have already
   been billed a standalone backup invoice for the current month before
   the flip. We must not also bill it inside the next renewal for an
   overlapping period. Guard:
   - When the renewal adds the snapshot line, it advances
     `daily_backup_next_invoice_date` to the new `next_invoice_date`.
   - The backup cron only bills when `daily_backup_next_invoice_date <=
     today` **and** no unpaid backup invoice exists — so once the renewal
     pins the date forward, cron B won't re-bill.
   - For a **yearly** plan flipping mid-year: the customer keeps paying
     monthly backup invoices (cron B) until their **yearly renewal**
     lands; at that renewal the 12-month snapshot block is billed and the
     date is pinned forward a year. To avoid the overlap month, the
     renewal's snapshot qty is reduced by any months already separately
     billed and not yet consumed — OR, simpler: **start merged billing
     only for instances whose `daily_backup_next_invoice_date` aligns with
     the renewal**. Decision: **lazy flip on the monthly boundary** — on
     the first renewal on/after the flip, charge the snapshot for the
     period that begins at that renewal; the prior standalone invoice
     covered the period up to it. No overlap because both are anchored to
     the same monthly boundary for monthly plans. Yearly plans: see §5.
4. **Historical invoices untouched** — we never modify posted invoices;
   only future generation changes.
5. **Migration file** (`18.0.23.0.0/post-migrate.py`): no data backfill
   needed if the flag defaults OFF; flipping is an operator action. If we
   want auto-on, the post-migrate would only set the config key — never
   touch invoices.

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

### Yearly-plan handling (explicit)
- **Monthly plan + merge:** snapshot qty 1 each month, fully aligned. Clean.
- **Yearly plan + merge:** snapshot billed qty 12 once a year on the
  yearly renewal (12 months up-front at the monthly rate). Between
  renewals cron B does NOT bill (date pinned a year forward). This changes
  the *cash timing* for yearly customers (they prepay a year of snapshots)
  but not the annual total. **This must be called out to the operator** —
  it's the one real behavioural change of merging. If prepaying a year of
  snapshots is undesirable, the alternative is to keep yearly plans on the
  separate monthly backup cycle even when merged (a sub-option). Recommend:
  **merge for monthly plans; for yearly plans keep monthly snapshot
  invoices** (flag becomes "merge monthly snapshots into monthly
  renewals"). This avoids the prepay surprise and is the safest default.

---

## 6. Edge case handling strategy

| Edge case | Handling |
|---|---|
| Yearly plan + monthly snapshot mismatch | Merge only for monthly plans; yearly keeps the monthly backup cycle (recommended) — OR bill 12× up-front (documented, opt-in). |
| Backups disabled mid-cycle | `_snapshot_order_line` returns None when `daily_backup_enabled` is False → next renewal simply omits the line. No proration refund (matches today). |
| Snapshot price change while active | `_get_daily_backup_price()` is read at renewal time, honouring `backup_price_locked_until` grandfathering — same as today. |
| Reactivation with retained snapshot | `daily_backup_enabled` is cleared on reactivate; customer re-enables (activation invoice + retention surcharge) — that flow is **unchanged** (activation stays a separate one-time invoice; only the recurring renewal is merged). |
| Overage + backup + support same invoice | All four are just order lines on the one renewal SO. Already how support+overage work. |
| Unpaid renewal (now contains snapshot) | Standard dunning/suspension suspends the instance; snapshots stop with it. No separate snapshot-dunning needed when merged. |
| Flag flipped OFF again | Renewals stop adding the snapshot line; backup cron resumes standalone invoices on the next due date. Reversible. |
| Idempotency | Renewal already advances `next_invoice_date` before post (no duplicate renewal). Backup cron already guards on "no unpaid backup invoice" + due date. Merged path pins the backup date forward so cron B can't double-issue. |

---

## 7. Risk analysis

| Risk | Severity | Mitigation |
|---|---|---|
| **Double billing** a month of snapshots during the flip | High | Lazy per-instance flip on the monthly boundary; renewal pins `daily_backup_next_invoice_date` forward; cron B skips merged. Verify on clone with an instance mid-cycle. |
| Yearly customers prepay a year of snapshots unexpectedly | Medium | Recommended default: don't merge yearly snapshots (keep monthly cycle). Make it explicit/opt-in. |
| Snapshot suspension logic diverges (merged invoice unpaid but snapshots keep running) | High | When merged, snapshot suspension follows subscription suspension (unpaid renewal → instance suspended → snapshots stop). Drop the separate snapshot-overdue check for merged instances. |
| Historical invoice integrity | High | Never modify posted invoices; only future generation changes. |
| Auto-charge double-charges (subscription token + snapshot token) | Medium | Merged → single invoice → single auto-charge. Remove the second `_try_auto_charge_invoice(kind='snapshot')` for merged. |
| Revenue reporting continuity (snapshot revenue now under RENEWAL origin) | Low | Keep the snapshot **line** clearly named; reports key on product/line, not origin. Document the origin change. |
| Partial rollout / mixed fleet | Medium | Flag is read per-instance at generation time, so merged and non-merged instances coexist safely. |

---

## 8. Expected outcome

- **Default (flag OFF):** byte-for-byte current behaviour — separate
  cycles. Zero change on deploy.
- **Flag ON:** monthly instances get a single renewal invoice with Plan +
  Support + Snapshot + Overage; the backup cron only manages
  pause/resume. Yearly instances either keep monthly snapshot invoices
  (recommended) or prepay 12 months on the yearly renewal (opt-in).
- Pricing engine unchanged; snapshot price still storage-aware + lock-aware.
- No duplicate invoices; historical data intact; fully reversible.

---

## 9. Recommended implementation order
1. **M1** toggle (inert, default OFF).
2. **M2** `_snapshot_order_line` + refactor the standalone generator to use
   it (no behaviour change — pure refactor, lockable by tests).
3. **M3** renewal includes the line when merged (monthly only first).
4. **M4** backup cron skips merged + suspension reuse.
5. **M5** decide yearly policy + migration note; verify the mid-cycle
   no-double-charge scenario on a clone.
6. **M6** tests (merged monthly single invoice; non-merged unchanged;
   no double charge across the flip; disabled-backup omits line;
   lock/storage price respected) + update `pricing-playbook.md`.

Each step: behaviour-neutral default, verified on a DB clone, committed
separately.
