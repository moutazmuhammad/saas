# Customer-documentation screenshots

The `/docs` page (template `saas_website.portal_docs_page`) references PNG
screenshots from this folder. Each filename below maps to a `<figure>` in
the template; the page degrades gracefully — a "Screenshot will appear
here" placeholder is shown for any file that's not on disk — so you can
roll out the docs page first and drop screenshots in as you capture them.

## Recommended capture settings

- **Format:** PNG, 16:9-ish aspect ratio.
- **Width:** ~1200 px wide (page is responsive, but anything wider just
  gets scaled down).
- **Theme:** match the portal theme that customers actually see (the
  dark-glass theme; if you have a "light mode" toggle, capture in
  whichever mode you ship as default).
- **Privacy:** scrub any real customer subdomains, emails, invoice
  numbers, etc. — substitute `my-company.sudud.com` or similar
  placeholders.

## Filenames + what each one should show

| Filename | Section anchor | What to capture |
|---|---|---|
| `01-home.png` | `#sec-welcome` | Public home page with both Services and Hosting hero offerings visible. |
| `02-signup.png` | `#sec-account` | Sign-up form filled in halfway, password strength meter visible. |
| `03-trial-banner.png` | `#sec-trial` | The green "Try hosting for X days free" banner at the top of any public page. |
| `04-plan-builder.png` | `#sec-purchase` | Hosting plan builder with sliders, daily-backup checkbox, and live order summary on the right. |
| `05-instance-detail.png` | `#sec-dashboard` | A running hosting instance's detail page — status pill, quick-action buttons, recent invoices. |
| `06-databases.png` | `#sec-databases` | The Databases page with at least two database rows so all action buttons (Open, Backup Now, Repair Feature, Reset Password, Duplicate, Delete) are visible. |
| `07-create-db.png` | `#sec-db-create` | The Create Database modal with the subdomain prefix shown next to an example name. |
| `08-duplicate.png` | `#sec-db-duplicate` | The Duplicate modal showing the source name pre-filled with `-copy` suffix in the target field. |
| `09-reset-password.png` | `#sec-db-reset-password` | The Reset Password modal with the blue "Admin login for this database: …" banner visible. |
| `10-repair-feature.png` | `#sec-db-repair` | The Repair Feature modal with the input field and the "Common picks" hint text. |
| `11-delete.png` | `#sec-db-delete` | The Delete confirmation modal with the retype-name field. |
| `12-backup-now.png` | `#sec-ondemand` | A database row mid-cycle — ideally three rows: one fresh, one with the "Backing up" badge, one with the "Backup ready" badge + Download button. (Compose this if you can't catch all three live.) |
| `13-enable-snapshots.png` | `#sec-snapshots-enable` | The blue "Protect this instance with daily snapshots" banner on the instance detail page, plus the green Enable button. |
| `14-snapshots-list.png` | `#sec-snapshots-restore` | The Snapshots page with at least 3 dated snapshot rows + their Restore buttons. |
| `15-change-plan.png` | `#sec-plan-change` | The Change Plan page showing the current vs new plan side by side. |
| `16-reactivate.png` | `#sec-cancel` | The instances list with one cancelled-instance card showing the Reactivate button. |
| `17-invoices.png` | `#sec-invoices` | The invoice list with a mix of paid (download icon) and unpaid (yellow Pay button) rows. |

## Workflow

1. Capture each screenshot at the right state.
2. Drop the PNG into this folder using the exact filename from the table.
3. No code or template change needed — the page picks them up on next
   reload thanks to the `static/src/img/docs/` asset path.

If you replace screenshots later, hard-refresh (Ctrl+Shift+R) to bypass
the browser cache.
