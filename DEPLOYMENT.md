# Production Deployment — SaaS Platform + VELTNEX Frontend

This guide covers deploying the **SaaS master application**: the Odoo 18
control-plane that runs `saas_core` + `saas_website` and serves the
**VELTNEX** React frontend.

> **Scope.** This document is about the *master* server (the control plane
> your customers log into). The fleet of **Docker hosts / PostgreSQL servers**
> that actually run provisioned customer instances is a separate concern —
> see [`saas_core/docker/SERVER-SETUP.md`](saas_core/docker/SERVER-SETUP.md).

---

## 1. Architecture

```
                         ┌──────────────────────────────────────────┐
   Internet ── HTTPS ──▶ │  nginx (TLS, reverse proxy)               │
                         │   ├─ /            → Odoo http  (SPA shell) │
                         │   ├─ /saas/api/*  → Odoo http  (JSON API)  │
                         │   ├─ /web, /odoo  → Odoo http  (backend)   │
                         │   └─ /websocket   → Odoo gevent (8072)     │
                         └───────────────┬──────────────────────────┘
                                         │
                         ┌───────────────▼──────────────┐     ┌──────────────┐
                         │  Odoo 18 (master)             │────▶│ PostgreSQL    │
                         │  saas_core + saas_website     │     │ (master DB)   │
                         │  serves static/spa/ (VELTNEX) │     └──────────────┘
                         └───────────────┬──────────────┘
                                         │ SSH / API (provisioning)
                         ┌───────────────▼───────────────────────────┐
                         │  Docker hosts + PG servers (customer       │
                         │  instances)  →  see docker/SERVER-SETUP.md │
                         └────────────────────────────────────────────┘
                                         │  backups
                         ┌───────────────▼──────────────┐
                         │  Object storage (S3 / GCS /   │
                         │  DO Spaces) — instance backups│
                         └──────────────────────────────┘
```

The React SPA and the JSON API are served by the **same Odoo process**
(same origin → the session cookie authenticates API calls). The SPA's built
assets live in `saas_website/static/spa/` and are **committed to git**, so
the production server does **not** need Node — it just needs the repo.

---

## 2. Prerequisites

**Master server** (Ubuntu 22.04/24.04 LTS recommended):

- Python 3.10+ (3.12 tested)
- PostgreSQL 15+ (local or managed) — see the PG 15 public-schema note in the
  platform docs
- nginx, certbot
- System libs for Odoo: `build-essential libpq-dev libxml2-dev libxslt1-dev
  libldap2-dev libsasl2-dev libjpeg-dev zlib1g-dev libffi-dev`
- `wkhtmltopdf` (patched Qt build) for PDF invoices
- A non-root system user, e.g. `odoo`

**Python packages** (Odoo `requirements.txt` plus this platform's externals):

```bash
pip install -r odoo/requirements.txt
pip install paramiko jinja2 boto3 google-cloud-storage
```

(`paramiko`, `jinja2`, `boto3`, `google-cloud-storage` are declared in
`saas_core/__manifest__.py` → `external_dependencies`.)

**Build toolchain (build machine / CI only, not the server):** Node 20+,
npm 10+.

---

## 3. Build the VELTNEX frontend

The build output (`saas_website/static/spa/`) is tracked in git. Choose one:

**Option A — build in CI / on a dev machine, commit the result (recommended):**

```bash
cd custom/saas/veltnex
npm ci
npm run build          # → writes custom/saas/saas_website/static/spa/
git add ../saas_website/static/spa
git commit -m "build: VELTNEX frontend"
```

**Option B — build on the server during deploy** (needs Node there):

```bash
cd /opt/saas/custom/saas/veltnex && npm ci && npm run build
```

> The Odoo controller caches `index.html` in-process, so **after any new SPA
> build you must restart Odoo** (see §8).

---

## 4. Odoo production config

Create `/etc/odoo/odoo.conf` (do **not** reuse the dev `odoo.conf` verbatim):

```ini
[options]
; --- secrets ---
admin_passwd = <LONG-RANDOM-STRING>        ; master password for DB manager
db_password  = <PG-PASSWORD>

; --- database ---
db_host = 127.0.0.1
db_port = 5432
db_user = odoo
dbfilter = ^saas$                          ; pin to the single master DB
list_db = False                            ; hide the DB manager in prod

; --- addons ---
addons_path = /opt/saas/odoo/odoo/addons,/opt/saas/odoo/addons,/opt/saas/custom/saas
data_dir = /var/lib/odoo                   ; filestore (back this up!)

; --- http / workers ---
http_port = 8069
gevent_port = 8072                         ; websockets / longpolling
proxy_mode = True                          ; trust X-Forwarded-* from nginx
workers = 4                                ; ~ (2 * vCPU) + 1
max_cron_threads = 2                       ; REQUIRED — billing/backup/health crons

; --- limits (tune to RAM) ---
limit_memory_soft = 2147483648
limit_memory_hard = 2684354560
limit_time_cpu = 600
limit_time_real = 1200
limit_request = 8192

; --- logging ---
logfile = /var/log/odoo/odoo.log
log_level = info
```

Key points specific to this platform:

- **`max_cron_threads` ≥ 1** is mandatory — recurring billing, daily backups,
  trial expiry, health checks, storage checks, and pending-provision crons all
  run as Odoo crons (`saas_core/data/saas_*_cron.xml`). With workers > 0, crons
  run in a dedicated process; with `max_cron_threads = 0` they never fire.
- **`proxy_mode = True`** so OAuth/payment redirects and `request.httprequest`
  see the real scheme/host behind nginx.
- **`list_db = False`** + a strong `admin_passwd` — the SPA/customers never
  touch the DB manager.

---

## 5. Run Odoo as a systemd service

`/etc/systemd/system/odoo.service`:

```ini
[Unit]
Description=Odoo SaaS Master
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=odoo
Group=odoo
ExecStart=/opt/saas/venv/bin/python3 /opt/saas/odoo/odoo-bin -c /etc/odoo/odoo.conf
Restart=always
RestartSec=3
# Hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now odoo
sudo systemctl status odoo
```

This replaces the manual `python3 odoo-bin -c odoo.conf -d saas` dev launch
(which has no restart, no supervision).

---

## 6. Domains, DNS & TLS

The platform uses **two kinds of hostname**, and they must not collide:

| Purpose | Hostname | Points at |
|---|---|---|
| Master app (marketing, portal, API) | `veltnex.com`, `www.veltnex.com` | the **master** server (this guide) |
| Customer instances (one per tenant) | `<subdomain>.apps.veltnex.com` | the **instance proxy** on the Docker fleet |

Why a separate namespace for instances: customer subdomains are arbitrary
(`acme`, `api`, `www`, …). If instances lived directly under `*.veltnex.com`
a customer could claim `www.veltnex.com` or `api.veltnex.com` and shadow your
master app. Putting them under a dedicated base domain like **`apps.veltnex.com`**
(or a separate `veltnex.app`) keeps them isolated.

**DNS records:**

```
; master app
veltnex.com.            A      <MASTER_SERVER_IP>
www.veltnex.com.        CNAME  veltnex.com.

; customer-instance base domain → instance reverse proxy (a Docker-fleet proxy)
*.apps.veltnex.com.     A      <INSTANCE_PROXY_IP>
```

Then create a `saas.based.domain` record with name **`apps.veltnex.com`** in
the SaaS backend (§7). New instances become `<subdomain>.apps.veltnex.com`.

**TLS:**
- Master: a normal Let's Encrypt cert for `veltnex.com` + `www.veltnex.com`
  (issued below).
- Instances: a **wildcard** cert for `*.apps.veltnex.com` on the instance
  proxy (requires DNS-01 / a DNS-provider plugin), or per-instance certs —
  this lives with the fleet, see `saas_core/docker/SERVER-SETUP.md`.

### nginx (master)

`/etc/nginx/sites-available/saas`:

```nginx
upstream odoo      { server 127.0.0.1:8069; }
upstream odoo_chat { server 127.0.0.1:8072; }   # gevent_port

server {
    listen 80;
    server_name veltnex.com www.veltnex.com;
    return 301 https://veltnex.com$request_uri;   # canonicalize to apex
}

server {
    listen 443 ssl http2;
    server_name veltnex.com www.veltnex.com;

    ssl_certificate     /etc/letsencrypt/live/veltnex.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/veltnex.com/privkey.pem;

    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;

    client_max_body_size 200m;       # backup downloads / uploads

    # Websockets (Odoo bus / live features)
    location /websocket {
        proxy_pass http://odoo_chat;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    location /longpolling { proxy_pass http://odoo_chat; }

    # Cache the immutable, content-hashed SPA bundle aggressively
    location /saas_website/static/spa/assets/ {
        proxy_pass http://odoo;
        proxy_cache_valid 200 30d;
        add_header Cache-Control "public, max-age=2592000, immutable";
    }

    # Everything else → Odoo http (SPA shell, JSON API, /web, QWeb funnel)
    location / {
        proxy_pass http://odoo;
        proxy_read_timeout 720s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/saas /etc/nginx/sites-enabled/
sudo certbot --nginx -d veltnex.com -d www.veltnex.com
sudo nginx -t && sudo systemctl reload nginx
```

> **Note on Server-Sent Events.** The live **logs** page streams via SSE
> (`/saas/instance/<id>/logs/stream`). The default `location /` block proxies
> it fine; the long `proxy_read_timeout` keeps the stream open. Do not enable
> response buffering for that path if you tighten the config later.

---

## 7. First-run platform configuration

After the service is up and the DB is installed/upgraded (§8), configure the
platform from the Odoo backend (`/odoo` → SaaS menus) and System Parameters
(`Settings → Technical → System Parameters`). Nothing here is hard-coded.

**Pricing & sections** (`ir.config_parameter`, prefix `saas_master.`):

| Parameter | Meaning |
|---|---|
| `saas_master.hosting_worker_price`, `hosting_storage_price_per_gb` | hosting rates |
| `saas_master.hosting_min/max_workers`, `hosting_min/max_storage` | slider limits |
| `saas_master.worker_price`, `storage_price_per_gb` | service custom-plan rates |
| `saas_master.*_yearly_discount_pct` | yearly discount |
| `saas_master.trial_days`, `max_instances_per_user` | trial / quotas |
| `saas_master.support_email` | shown to customers |
| `saas_master.show_services_section`, `show_hosting_section` | toggle catalog sections |

> The VELTNEX frontend reads all of these through `/saas/api/v1/meta` and
> `/saas/api/v1/hosting/calculate` — **never** hard-code prices in the SPA.

**Infrastructure registry** (SaaS backend menus): add `saas.server` records
(Docker hosts + PG servers), `saas.ssh.key.pair`, `saas.based.domain` (with
wildcard DNS pointing at the proxy), and `saas.odoo.version` images. See
`saas_core/docker/SERVER-SETUP.md`.

**Base URL** — set `web.base.url` to `https://veltnex.com` (and set
`web.base.url.freeze = True`) in System Parameters. Odoo builds absolute links
from this for **payment-provider return URLs** and **outgoing emails**; if it's
left at `localhost:8069`, checkout redirects and email links break.

**Integrations that must be live in production:**

- **Object storage** for backups (S3 / GCS / DigitalOcean Spaces) — credentials
  in Settings/System Parameters. Daily backups use restic; on-demand use zip.
- **Payment providers** (`Settings → Payment Providers`) — the checkout funnel
  (`/checkout`) the SPA hands off to requires at least one enabled provider.
- **SMS gateway / Odoo IAP** — registration uses **phone OTP**
  (`saas.registration.otp`). Without SMS credits/gateway, sign-up can't
  complete.
- **Outgoing email (SMTP)** — provisioning, billing, and dunning emails.
- **Published catalog** — create at least one `saas.product` with
  `is_published = True` (+ plans) or the SPA shows an empty Services page.

---

## 8. Install / upgrade / redeploy

**Initial install:**

```bash
sudo -u odoo /opt/saas/venv/bin/python3 /opt/saas/odoo/odoo-bin \
  -c /etc/odoo/odoo.conf -d saas -i saas_core,saas_website --stop-after-init
sudo systemctl start odoo
```

**Routine redeploy:**

```bash
cd /opt/saas
git pull
# If the SPA changed and you build on the server (Option B):
( cd custom/saas/veltnex && npm ci && npm run build )
# Apply Python/data changes:
sudo systemctl stop odoo
sudo -u odoo /opt/saas/venv/bin/python3 odoo/odoo-bin \
  -c /etc/odoo/odoo.conf -d saas -u saas_core,saas_website --stop-after-init
sudo systemctl start odoo
```

> A plain `systemctl restart odoo` is enough for a **SPA-only** change (it
> clears the in-process `index.html` cache). Schema/data/controller changes
> need the `-u` upgrade step above.

---

## 9. Backups (master DB & filestore)

The platform backs up *customer* instances automatically. You must
independently back up the **master**:

- **Database:** `pg_dump saas` on a schedule, shipped off-box.
- **Filestore:** `/var/lib/odoo` (attachments, signed assets). Back up together
  with the DB — they must be consistent.
- Test a restore periodically.

---

## 10. Security & hardening checklist

- [ ] `list_db = False` and a strong `admin_passwd`
- [ ] `proxy_mode = True`; only nginx is internet-facing; Odoo binds localhost
- [ ] `dbfilter = ^saas$` (single DB)
- [ ] Firewall: expose only 80/443; PostgreSQL not public
- [ ] HTTPS enforced; HSTS once verified
- [ ] SSH keys used for provisioning stored as Odoo records with least-privilege
      access on the Docker hosts (see SERVER-SETUP.md)
- [ ] Rotate the webhook secrets used by `/saas/webhook/<secret>`
- [ ] Object-storage credentials scoped to the backup bucket only
- [ ] Regular OS + Python dependency updates

---

## 11. Health checks

- `GET /web/login` → 200 (Odoo up)
- `GET /` → 200 and returns the VELTNEX shell (`saas_website/static/spa`)
- `POST /saas/api/v1/meta` → `{"result":{"ok":true,...}}` (API + DB reachable)
- `journalctl -u odoo -f` / `/var/log/odoo/odoo.log` for errors
- Confirm crons are firing: `Settings → Technical → Scheduled Actions` show
  recent "Last Run" timestamps (proves `max_cron_threads` > 0)
```
