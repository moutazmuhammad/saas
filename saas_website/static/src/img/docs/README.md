# Customer-documentation screenshots

The `/docs` page (template `saas_website.portal_docs_page`) references
PNG screenshots from this folder. The page degrades gracefully — a
"Screenshot will appear here" placeholder is shown for any file that
isn't on disk yet — so you can ship the docs page first and drop
screenshots in as you capture them.

## Recommended capture settings

- **Format:** PNG, 16:9-ish aspect ratio.
- **Width:** ~1200 px (the page is responsive, but anything wider gets
  scaled down).
- **Theme:** match the portal theme customers actually see.
- **Privacy:** scrub real customer subdomains, emails, invoice numbers.
  Substitute `my-company.sudud.com` or similar placeholders.

## Filenames + what each one should show

The docs are hosting-only — every screenshot below is a hosting flow.
The Services product line is feature-flagged off and not documented.

| Filename | Section | What to capture |
|---|---|---|
| `01-home.png` | 1.1 | The public home page with the hero call-to-action visible. |
| `02-signup.png` | 1.2 | The sign-up form filled in halfway, password-strength meter showing "Strong". |
| `03-trial-banner.png` | 1.5 | The green "Try hosting for X days free" banner at the top of the home page. |
| `04-subdomain.png` | 2.1 | The subdomain field with a live-availability green check next to it. |
| `05-plan-builder.png` | 2.2 | The hosting plan builder with workers + storage sliders, monthly/yearly toggle, and the live order-summary panel on the right. |
| `06-checkout.png` | 2.6 | The checkout page — order summary on the left, secure card-input widget on the right. |
| `07-provisioning.png` | 2.7 | The provisioning page mid-deploy, with the 5-step progress indicator visible. |
| `08-instance-detail.png` | 3.1 | A running hosting instance's detail page showing status pill, action buttons, repos section, invoices column. |
| `09-databases.png` | 4.2 | The Databases page with at least two database rows so all action buttons (Open, Backup Now, Repair Feature, Reset Password, Duplicate, Delete) are visible. |
| `10-create-db.png` | 4.4 | The Create Database modal with the subdomain prefix visible and an example name typed. |
| `11-duplicate.png` | 4.6 | The Duplicate Database modal with the suggested `-copy` suffix in the target field. |
| `12-reset-password.png` | 4.7 | The Reset Password modal showing the blue "Admin login for this database: …" banner and the two password fields. |
| `13-repair-feature.png` | 4.8 | The Repair Feature modal showing the input field and the "Common picks" hint list. |
| `14-delete.png` | 4.9 | The Delete confirmation modal with the retype-name field. |
| `15-backup-now.png` | 5.2 | A database row in the "Backing up" state plus another row with the "Backup ready" badge and Download button visible. (Compose if you can't catch both live.) |
| `16-enable-snapshots.png` | 5.4 | The blue "Protect this instance with daily snapshots" prompt on the instance detail page, with the green Enable Daily Backups button. |
| `17-snapshots-list.png` | 5.5 | The Snapshots page with at least 3 dated snapshot rows and their Restore buttons. |
| `18-reactivate.png` | 8.3 | The My Instances page with one cancelled-instance card showing the Reactivate button. |

## Workflow

1. Capture each screenshot at the right state.
2. Drop the PNG into this folder using the exact filename above.
3. No code or template change needed — the page picks them up on next
   reload from the `static/src/img/docs/` asset path.

When replacing screenshots later, hard-refresh (Ctrl+Shift+R) to bypass
the browser cache.
