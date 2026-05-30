# Database Setup, Pricing System & Self‑Testing Guide

A complete, hands‑on guide for this SaaS platform (`saas_core` + `saas_website`
+ the React SPA `veltnex`). It covers three things:

1. **Part A — Database setup**: how to create / upgrade / clone the Odoo
   database, and how customer instance databases are created.
2. **Part B — How the new pricing system works**: the single pricing engine,
   floors, tiers, add‑ons, regions and storage overage.
3. **Part C — How to test it all yourself**, end to end, without touching
   your live data.

> **Golden rule:** the system ships **behaviour‑neutral**. With the default
> configuration (floors = 0, one ×1.0 "Default" region, no published tiers,
> snapshots counted toward storage) prices and flows are exactly what they
> were before the pricing rebuild. Nothing changes until *you* change a
> setting or create a tier/region.

---

## 0. Environment at a glance

This is the local development layout (yours may differ in paths/ports):

| Thing | Value |
|---|---|
| Odoo root | `/home/moutaz/Documents/Work/odoo18` |
| Python venv | `/home/moutaz/Documents/Work/odoo18/.env` |
| Odoo source | `/home/moutaz/Documents/Work/odoo18/odoo` |
| Custom addons | `/home/moutaz/Documents/Work/odoo18/custom/saas` |
| Config file | `/home/moutaz/Documents/Work/odoo18/odoo.conf` |
| Live DB | `saas` |
| HTTP port | `8018` (from `xmlrpc_port` in `odoo.conf`) |
| PostgreSQL | system Postgres, `localhost:5432`, user `odoo18` / pass `odoo18` |

`odoo.conf` (reference):

```ini
[options]
admin_passwd = admin_passwd
db_host = localhost
db_port = 5432
db_user = odoo18
db_password = odoo18
addons_path = /home/moutaz/Documents/Work/odoo18/odoo/addons,/home/moutaz/Documents/Work/odoo18/custom/saas
xmlrpc_port = 8018
```

The two modules:

- **`saas_core`** — models, pricing engine, regions, add‑ons, crons,
  provisioning, billing. Depends on: `base, mail, sale, account, portal,
  phone_validation, payment, account_payment`.
- **`saas_website`** — public website + JSON API (`/saas/api/v1/...`) + the
  purchase funnel + serves the built React SPA. Depends on: `saas_core,
  website, portal, payment, account_payment`.

**Python libraries** (required by `saas_core`): `paramiko`, `jinja2`,
`boto3`, `google-cloud-storage`.

```bash
cd /home/moutaz/Documents/Work/odoo18
.env/bin/python3 -c "import paramiko, jinja2, boto3, google.cloud.storage; print('deps OK')"
```

---

# Part A — Database setup

There are **two completely different kinds of database** in this platform.
Do not confuse them:

1. **The manager database** (`saas`) — the Odoo DB that *runs the SaaS
   platform itself* (this is where `saas_core`/`saas_website` are installed).
2. **Customer instance databases** — the Odoo databases that get created
   *for each hosted customer instance*, on the Docker/DB servers. These are
   created automatically by the platform when a customer's instance is
   provisioned (PostgreSQL template clone — see A.4). You normally never
   touch these by hand.

This guide's Part A is about the **manager database**, plus a short note on
how customer DBs are made.

## A.1 First‑time install (fresh manager DB)

If you are starting from scratch (no `saas` DB yet):

```bash
cd /home/moutaz/Documents/Work/odoo18

# Create the DB and install both modules in one shot.
.env/bin/python3 odoo/odoo-bin -c odoo.conf -d saas \
  -i saas_core,saas_website \
  --stop-after-init
```

- `-d saas` selects/creates the database named `saas`.
- `-i ...` **installs** the listed modules (and their dependencies).
- `--stop-after-init` runs the install then exits (no server stays up).

If the database does not exist yet, Odoo creates it automatically the first
time. (If your Postgres role can't create databases, create it first:
`createdb -h localhost -U odoo18 saas`.)

## A.2 Upgrade after pulling new code (most common)

Whenever you change Python models, views, data files, or security, you must
**upgrade** the module so Odoo reloads them into the DB. Pricing changes
(new models like `saas.region` / `saas.addon`, new fields, new views) all
require this.

```bash
cd /home/moutaz/Documents/Work/odoo18

# Stop any running server on the same DB/port first (see A.6), then:
.env/bin/python3 odoo/odoo-bin -c odoo.conf -d saas \
  -u saas_core,saas_website \
  --stop-after-init
```

- `-u ...` **upgrades** (updates) already‑installed modules.
- Always upgrade **both** `saas_core` and `saas_website` together — the
  website depends on core models.

> **Tip:** if you only changed Python logic (no new field/view/data), you can
> often just restart the server (A.5). But if you added a model, field, view,
> menu, security rule or data record — you **must** run `-u`.

## A.3 Run the server (development)

```bash
cd /home/moutaz/Documents/Work/odoo18
.env/bin/python3 odoo/odoo-bin -c odoo.conf -d saas
```

Then open `http://localhost:8018`. Log in with your admin user.

To run on a different port (e.g. to test alongside the live one):

```bash
.env/bin/python3 odoo/odoo-bin -c odoo.conf -d saas --http-port 8099
```

## A.4 How customer instance databases are created (reference)

When a customer buys/deploys an instance, the platform **does not** run a
slow `odoo -i base` per customer. Instead it uses a **PostgreSQL template
clone** for speed and reliability:

1. A per‑subscription template DB `__odoo_template_<subdomain>` is built
   once (a clean Odoo DB), then marked as a Postgres *template*
   (`datistemplate=true`) and shielded so live workers can't connect to it
   mid‑build.
2. Each new customer DB is created with
   `CREATE DATABASE <name> WITH TEMPLATE __odoo_template_<sub>` and the
   filestore is copied with `cp -a`.
3. On PostgreSQL 15+, every freshly created DB also gets an explicit
   `ALTER SCHEMA public OWNER TO <role>` + `GRANT ALL ON SCHEMA public` so
   the Odoo role can write to it.
4. Deletes use `dropdb --force`.

You don't run any of this manually — it's triggered by the instance
lifecycle (deploy / create‑db button / reset). It is mentioned here so you
understand that "create database" in the customer portal is a template
clone, not a full Odoo bootstrap.

## A.5 Clone the live DB into a throwaway test DB (recommended before testing)

This is the safe way to test: work on a **copy**, never the live `saas` DB.

```bash
export PGPASSWORD=odoo18
cd /home/moutaz/Documents/Work/odoo18

# 1) drop any stale test DB and recreate it empty
psql -h localhost -U odoo18 -d postgres -c "DROP DATABASE IF EXISTS saas_test;"
psql -h localhost -U odoo18 -d postgres -c "CREATE DATABASE saas_test OWNER odoo18;"

# 2) copy schema + data from the live DB into the clone
pg_dump -h localhost -U odoo18 --no-owner --no-privileges saas \
  | psql -h localhost -U odoo18 -d saas_test -q

# 3) sanity check
psql -h localhost -U odoo18 -d saas_test -tAc "SELECT count(*) FROM res_users;"
```

Now you can upgrade/test against `saas_test` and the live `saas` is never
touched. When done, drop it (A.7).

> The filestore (attachments) is **not** copied by `pg_dump`. For pricing /
> API / funnel testing this doesn't matter. If you need attachments too,
> also copy `~/.local/share/Odoo/filestore/saas` → `.../saas_test`.

## A.6 Find and stop a running server (avoid "port in use")

```bash
# What is bound to the dev port?
ss -ltnp | grep 8018          # live server
ss -ltnp | grep 8099          # a test server you started

# Find the Odoo process for a given DB:
pgrep -af "odoo-bin .* -d saas_test"

# Stop it (use the PID from pgrep):
kill <PID>
```

> **Caution:** don't `pkill -f saas` blindly — it can match unrelated shells.
> Prefer the specific pattern `odoo-bin .* -d saas_test` and kill by PID.

## A.7 Clean up a test DB

```bash
export PGPASSWORD=odoo18
# Make sure no server is using it first (A.6), then:
psql -h localhost -U odoo18 -d postgres -c "DROP DATABASE IF EXISTS saas_test;"
psql -h localhost -U odoo18 -d postgres -tAc \
  "SELECT datname FROM pg_database WHERE datistemplate=false ORDER BY 1;"
```

---

# Part B — How the new pricing system works

## B.1 The big idea: one engine, one source of truth

Every price in the whole platform is computed by **one** model:
`saas.pricing.engine` (an Odoo `AbstractModel` in
`saas_core/models/saas_pricing.py`). The SPA, the QWeb purchase funnel, the
renewal‑invoice generator and the plan‑creation helpers **all** call it.
There is **no** pricing math in the browser, and per‑unit rates are **never
sent to the client** — the browser only receives final totals.

The one method you care about:

```python
env['saas.pricing.engine'].compute(
    kind,            # 'hosting' or 'services'  (selects which rate set)
    workers,         # requested workers (clamped to plan limits)
    storage,         # requested storage in GB (clamped to plan limits)
    billing='monthly',   # 'monthly' or 'yearly'
    addon_codes=(),  # e.g. ['daily_snapshots']
    region=None,     # a saas.region record, an id, or None
)
```

## B.2 The exact formula

Given the configured rates, the engine computes:

```
base              = workers * worker_price  +  storage * storage_price_per_gb
cost_floor        = workers * worker_floor   +  storage * storage_floor
tier_floor        = price of the nearest published tier the config "contains"
                    (only if the "custom ≥ nearest tier" switch is ON; else 0)
floor             = max(cost_floor, tier_floor)
region_factor     = the chosen region's price_multiplier   (default 1.0)

resource_monthly  = max(base, floor) * region_factor      # region scales THIS
addons_monthly    = sum of the selected add‑on prices       # NOT region‑scaled
monthly           = resource_monthly + addons_monthly

yearly            = monthly * 12 * (1 - yearly_discount_pct/100)
```

Key rules, in words:

- **Floors** guarantee you never sell below cost. `monthly` is at least the
  floor (× region). With floors = 0 (default) this does nothing.
- **The region multiplier applies to compute + storage + floor only** — it
  does **not** scale add‑ons (an add‑on like daily snapshots lives in object
  storage and is region‑agnostic).
- **Add‑ons are summed last**, after the region factor.
- **Clamping**: `workers`/`storage` outside the configured min/max are
  pulled back into range before pricing.

`compute(...)` returns a dict including `monthly`, `yearly`, `total`,
`currency`, `region_factor`, `floored`, `limits`, and a `breakdown`
(`base`, `floor`, `cost_floor`, `tier_floor`, `resource_monthly`,
`addons_monthly`, `workers_cost`, `storage_cost`).

## B.3 Where every value is configured

Everything is configurable from the Odoo admin — **no hard‑coded prices in
code.** The engine reads `ir.config_parameter` keys; the UI for most of them
is **Settings ▸ SaaS** (and a dedicated **Pricing Engine** block).

### Per‑unit rates & limits (Settings ▸ SaaS)

Hosting and the custom "services" plan have **independent** rate sets.

| Meaning | Hosting key | Services key |
|---|---|---|
| Worker price / month | `saas_master.hosting_worker_price` | `saas_master.worker_price` |
| Storage price / GB / month | `saas_master.hosting_storage_price_per_gb` | `saas_master.storage_price_per_gb` |
| Min / max workers | `saas_master.hosting_min_workers` / `..._max_workers` | `saas_master.custom_plan_min_workers` / `..._max_workers` |
| Min / max storage (GB) | `saas_master.hosting_min_storage` / `..._max_storage` | `saas_master.custom_plan_min_storage` / `..._max_storage` |
| Yearly discount % | `saas_master.hosting_yearly_discount_pct` | `saas_master.custom_plan_yearly_discount_pct` |

### Price floors (Settings ▸ SaaS ▸ Pricing Engine)

| Meaning | Key | Default |
|---|---|---|
| Hosting worker floor | `saas_master.hosting_worker_floor` | `0` (off) |
| Hosting storage floor | `saas_master.hosting_storage_floor` | `0` (off) |
| Services worker floor | `saas_master.worker_floor` | `0` (off) |
| Services storage floor | `saas_master.storage_floor` | `0` (off) |
| "Custom plan ≥ nearest tier" switch | `saas_master.custom_min_is_nearest_tier` | `False` |

A plan whose `price` is below its computed cost floor is **rejected on save**
(`saas.plan._check_price_floor`); trial plans are exempt.

### Storage overage (Settings ▸ SaaS ▸ Pricing Engine)

When an instance exceeds its plan's storage limit, the **renewal invoice**
adds an overage line (`engine.storage_overage`):

| Mode | Keys | Behaviour |
|---|---|---|
| Per‑GB (default) | `saas_master.extra_storage_price_per_gb` | `over_GB × rate` |
| Block‑based | `saas_master.storage_block_gb` + `saas_master.storage_block_price` | billed per started block |

Block mode activates only when **both** block keys are > 0; otherwise it
falls back to per‑GB (behaviour‑neutral).

There is also a policy switch **"Snapshots count toward storage"**
(`saas_master.snapshots_count_toward_storage`, default `True`). When on, half
the total snapshot size is included in an instance's measured usage.
Recommended **OFF** in production if you don't want backups to inflate the
storage bill — this is an owner decision left ON for behaviour‑neutrality.

> **Boolean trap (important for developers):** the two Booleans
> (`snapshots_count_toward_storage`, `custom_min_is_nearest_tier`) are stored
> as the strings `'True'`/`'False'` and handled with manual
> `get_values`/`set_values` — do **not** wire them through `config_parameter=`
> on the field, or they will misbehave.

## B.4 Named tiers (the pricing cards) — SaaS ▸ Plans

Tiers are ordinary `saas.plan` records flagged for the storefront:

- **Is Public Tier** (`is_public_tier`) → publish it as a card.
- **Is Recommended** (`is_recommended`) → highlight + default it.
- **Badge** (`badge`, e.g. "Most popular") → the ribbon text.
- `sequence` → card order; plus the usual `workers`, `storage_limit`,
  `price`, `yearly_price`.

With **no** published tier, the hosting page shows only the slider
configurator. Publish one or more and the SPA renders them as cards (slider
moves behind a "Build a custom plan" toggle). The public endpoint
`GET /saas/api/v1/tiers?kind=hosting` serves them; it returns `[]` until you
publish a tier, so the SPA gracefully falls back to the slider.

## B.5 Add‑ons — SaaS ▸ Add‑ons

`saas.addon` records add a recurring monthly charge on top of the resource
price. Each has a `code`, an `applies_to` (hosting / services / both), and a
price — either a fixed `monthly_price` or a `price_config_param` pointing at
a config key. The seeded **Daily Snapshots** add‑on (`code = daily_snapshots`)
reads `saas_master.hosting_daily_backup_price`, so the existing daily‑backup
purchase/renewal flow is unchanged. Deactivate an add‑on to retire it without
deleting history.

## B.6 Regions & co‑location — SaaS ▸ Regions

Each `saas.region` has a `price_multiplier` applied to the **compute +
storage** portion of the quote (not add‑ons). Exactly one region is the
**Default** (used when the customer doesn't pick). Assign servers
(proxy / docker / db) to a region via the server's **Region** field.

**The co‑location rule:** an instance's three servers — nginx (proxy), Odoo
(docker) and DB — must all sit in the **same region**. This is enforced at
instance creation:

- The purchase funnel only offers **domains whose reverse proxy is in the
  chosen region** (a proxy‑less domain is region‑neutral — nginx then runs on
  the region‑matched docker host).
- Server allocation pins the docker + db servers to the instance's region.
- A server with **no** region is treated as belonging to the Default region,
  so an un‑regioned fleet keeps working exactly as before.

**The region picker appears only when there is more than one active region.**
With zero or one region the funnel is unchanged. Region is **fixed at
instance creation**. A region is selectable only if it has both a docker host
and a db server (capacity check surfaced by `GET /saas/api/v1/regions` as
`available`).

## B.7 The public API surface (for the SPA & for your tests)

All are JSON‑RPC `POST` endpoints under `/saas/api/v1/`, `auth='public'`:

| Endpoint | Params | Returns |
|---|---|---|
| `/meta` | — | site config + limits (rates stripped) |
| `/tiers` | `kind` | published tier cards (`[]` if none) |
| `/regions` | — | active regions (`multiplier`, `default`, `available`) |
| `/hosting/calculate` | `workers, storage, billing` | a full price quote |
| `/services/calculate` | `workers, storage, billing` | a full price quote |

The QWeb purchase funnel lives at **`/hosting/configure`** (this is where an
instance is actually created; the SPA tier cards / slider redirect here).

---

# Part C — How to test it yourself (end to end)

Work on a **clone** (`saas_test`), never the live `saas` DB. The plan:

1. Clone + upgrade the DB.
2. Run the automated test suite.
3. Run engine logic scenarios with dummy data (rolled back — DB stays clean).
4. Seed dummy regions/servers/tiers and test the live HTTP API + funnel.
5. Clean up.

## C.1 Clone and upgrade

```bash
export PGPASSWORD=odoo18
cd /home/moutaz/Documents/Work/odoo18

psql -h localhost -U odoo18 -d postgres -c "DROP DATABASE IF EXISTS saas_test;"
psql -h localhost -U odoo18 -d postgres -c "CREATE DATABASE saas_test OWNER odoo18;"
pg_dump -h localhost -U odoo18 --no-owner --no-privileges saas \
  | psql -h localhost -U odoo18 -d saas_test -q

# Upgrade both modules into the clone (also confirms a clean migration).
.env/bin/python3 odoo/odoo-bin -c odoo.conf -d saas_test \
  -u saas_core,saas_website --stop-after-init --http-port 8099 --no-http
```

## C.2 Run the automated pricing test suite

The suite `TestPricingEngine` (in `saas_core/tests/test_pricing_engine.py`)
locks the engine to the legacy linear formula and exercises floors, tiers,
add‑ons, regions, the plan‑floor constraint and storage overage.

```bash
cd /home/moutaz/Documents/Work/odoo18
.env/bin/python3 odoo/odoo-bin -c odoo.conf -d saas_test \
  -u saas_core,saas_website \
  --test-enable --test-tags /saas_core:TestPricingEngine \
  --stop-after-init --http-port 8099 --no-http --log-level=test 2>&1 \
  | grep -E "failed, .* error"
```

**Expected:** `0 failed, 0 error(s) of 11 tests`.

> Note: the tests live in `saas_core`, so you must include `saas_core` in
> `-u`. If you upgrade only `saas_website` you'll see "0 of 0 tests".

## C.3 Engine logic scenarios with dummy data (safe — rolled back)

This drives the engine directly via `odoo shell` with dummy values and rolls
the transaction back at the end, so the DB is untouched. Save as
`/tmp/price_scenarios.py`:

```python
# /tmp/price_scenarios.py — run via: odoo shell ... < /tmp/price_scenarios.py
from odoo.exceptions import ValidationError
engine = env['saas.pricing.engine']
icp = env['ir.config_parameter'].sudo()
P=[]; F=[]
def ck(n,c): (P if c else F).append(n); print(("PASS " if c else "FAIL ")+n)

# Pin deterministic hosting rates so numbers are predictable.
for k,v in {
    'saas_master.hosting_worker_price':'10.0',
    'saas_master.hosting_storage_price_per_gb':'0.3',
    'saas_master.hosting_min_workers':'2','saas_master.hosting_max_workers':'8',
    'saas_master.hosting_min_storage':'5','saas_master.hosting_max_storage':'200',
    'saas_master.hosting_yearly_discount_pct':'20',
    'saas_master.hosting_worker_floor':'0','saas_master.hosting_storage_floor':'0',
    'saas_master.custom_min_is_nearest_tier':'False',
}.items(): icp.set_param(k,v)

# 1) base price: 4*10 + 50*0.3 = 55.0 ; yearly = 55*12*0.8 = 528.0
q=engine.compute('hosting',4,50,'monthly')
ck("base monthly 55.0", abs(q['monthly']-55.0)<0.01)
ck("base yearly 528.0", abs(q['yearly']-528.0)<0.01)
ck("region factor 1.0", q['region_factor']==1.0)

# 2) clamping
ck("workers clamp hi 8", engine.compute('hosting',999,1,'monthly')['workers']==8)
ck("storage clamp lo 5", engine.compute('hosting',1,1,'monthly')['storage']==5)

# 3) cost floor: floor = 2*12 + 5*0.5 = 26.5 > base 21.5
icp.set_param('saas_master.hosting_worker_floor','12')
icp.set_param('saas_master.hosting_storage_floor','0.5')
qf=engine.compute('hosting',2,5,'monthly')
ck("floored", qf['floored'] and abs(qf['monthly']-26.5)<0.01)
icp.set_param('saas_master.hosting_worker_floor','0')
icp.set_param('saas_master.hosting_storage_floor','0')

# 4) region multiplier scales compute, not add-ons
rx2=env['saas.region'].create({'name':'ZZ x2','code':'zz_x2','price_multiplier':2.0})
qb=engine.compute('hosting',4,50,'monthly')
qr=engine.compute('hosting',4,50,'monthly',region=rx2.id)
ck("region x2 doubles resource",
   abs(qr['breakdown']['resource_monthly']-qb['breakdown']['resource_monthly']*2)<0.01)

# 5) add-on summed, NOT region-scaled
if env['saas.addon'].search_count([('code','=','daily_snapshots')]):
    icp.set_param('saas_master.hosting_daily_backup_price','7.0')
    w=engine.compute('hosting',4,50,'monthly',addon_codes=['daily_snapshots'])
    ck("add-on adds 7.0", abs(w['monthly']-qb['monthly']-7.0)<0.01)
    wr=engine.compute('hosting',4,50,'monthly',addon_codes=['daily_snapshots'],region=rx2.id)
    ck("add-on not region-scaled", abs(wr['breakdown']['addons_monthly']-7.0)<0.01)

# 6) storage overage per-GB then block
GB=1024**3
icp.set_param('saas_master.extra_storage_price_per_gb','0.5')
icp.set_param('saas_master.storage_block_gb','0')
icp.set_param('saas_master.storage_block_price','0')
o=engine.storage_overage(60*GB,50)
ck("overage per_gb 5.0", o['mode']=='per_gb' and abs(o['charge']-5.0)<0.01)
icp.set_param('saas_master.storage_block_gb','50')
icp.set_param('saas_master.storage_block_price','9')
o2=engine.storage_overage(60*GB,50)
ck("overage block 9.0", o2['mode']=='block' and abs(o2['charge']-9.0)<0.01)

# 7) plan below floor rejected
prod=env['saas.product'].search([('is_hosting','=',True)],limit=1) \
     or env['saas.product'].create({'name':'ZZ Host','is_hosting':True,'is_published':True})
icp.set_param('saas_master.hosting_worker_floor','12')
icp.set_param('saas_master.hosting_storage_floor','0.5')
try:
    env['saas.plan'].create({'name':'ZZ low','is_public_tier':True,'workers':2,
        'storage_limit':5,'cpu_limit':1.0,'ram_limit':'1g','price':10.0,
        'currency_id':env.company.currency_id.id,'saas_product_ids':[(6,0,[prod.id])]})
    ck("below-floor plan rejected", False)
except ValidationError:
    ck("below-floor plan rejected", True)

# 8) co-location domain filter logic
Server=env['saas.server']
ck("no region -> no constraint", Server._region_match_domain(None)==[])
ck("region -> exact match", Server._region_match_domain(rx2)==[('region_id','=',rx2.id)])

print("\nSUMMARY PASS=%d FAIL=%d" % (len(P),len(F)))
for f in F: print("  FAILED:",f)
env.cr.rollback()
print("DONE")
```

Run it:

```bash
cd /home/moutaz/Documents/Work/odoo18
.env/bin/python3 odoo/odoo-bin shell -c odoo.conf -d saas_test \
  --no-http --log-level=warn < /tmp/price_scenarios.py 2>/dev/null \
  | grep -E "PASS |FAIL |SUMMARY|FAILED|DONE"
```

**Expected:** every line `PASS ...` and `SUMMARY PASS=... FAIL=0`.

## C.4 Seed dummy infra, then test the live HTTP API + funnel

This commits dummy data so a running HTTP server can see it. Save as
`/tmp/price_seed.py`:

```python
# /tmp/price_seed.py — seeds two regions, a full server stack each,
# three domains, a published tier, and an admin password. COMMITS.
R=env['saas.region']; S=env['saas.server']; D=env['saas.based.domain']
P=env['saas.plan']; Prod=env['saas.product']

eu=R.search([('code','=','default')],limit=1)
if eu: eu.write({'name':'EU (Frankfurt)','price_multiplier':1.0,'is_default':True})
else:  eu=R.create({'name':'EU (Frankfurt)','code':'default','price_multiplier':1.0,'is_default':True})
us=R.search([('code','=','us')],limit=1) or R.create({'name':'US (Virginia)','code':'us','price_multiplier':1.5})

def srv(name,region,**roles):
    s=S.search([('name','=',name)],limit=1)
    vals=dict(name=name,ip_v4='10.9.9.9',ssh_user='root',region_id=region.id); vals.update(roles)
    return s.write(vals) and s or s if s else S.create(vals)
srv('ZZ-eu-proxy',eu,is_proxy_server=True);  srv('ZZ-eu-docker',eu,is_docker_host=True);  srv('ZZ-eu-db',eu,is_db_server=True)
srv('ZZ-us-proxy',us,is_proxy_server=True);  srv('ZZ-us-docker',us,is_docker_host=True);  srv('ZZ-us-db',us,is_db_server=True)

eup=S.search([('name','=','ZZ-eu-proxy')],limit=1); usp=S.search([('name','=','ZZ-us-proxy')],limit=1)
def dom(name,proxy=None):
    d=D.search([('name','=',name)],limit=1); vals={'name':name,'proxy_server_id':proxy.id if proxy else False}
    return d.write(vals) and d or d if d else D.create(vals)
dom('zz-eu.example.com',eup); dom('zz-us.example.com',usp); dom('zz-neutral.example.com',None)

prod=Prod.search([('is_hosting','=',True)],limit=1) or Prod.create({'name':'ZZ Host','is_hosting':True,'is_published':True})
if not P.search([('name','=','ZZ Pro')],limit=1):
    P.create({'name':'ZZ Pro','is_public_tier':True,'is_recommended':True,'badge':'Most popular',
        'is_custom':True,'workers':4,'storage_limit':50,'cpu_limit':2.0,'ram_limit':'2g',
        'price':55.0,'yearly_price':528.0,'currency_id':env.company.currency_id.id,
        'saas_product_ids':[(6,0,[prod.id])]})

env.ref('base.user_admin').write({'password':'testpass123'})
env.cr.commit()
print("SEEDED regions=%d zz_servers=%d tiers=%d" % (
    R.search_count([]), S.search_count([('name','like','ZZ-')]),
    P.search_count([('is_public_tier','=',True)])))
print("DONE")
```

Seed it, then start a test server on port 8099:

```bash
cd /home/moutaz/Documents/Work/odoo18
.env/bin/python3 odoo/odoo-bin shell -c odoo.conf -d saas_test \
  --no-http --log-level=warn < /tmp/price_seed.py 2>/dev/null | grep -E "SEEDED|DONE"

# Start the test server (leave it running in a second terminal):
.env/bin/python3 odoo/odoo-bin -c odoo.conf -d saas_test \
  --http-port 8099 --log-level=warn --max-cron-threads=0
```

### Test the JSON API

In another terminal:

```bash
cd /home/moutaz/Documents/Work/odoo18
python3 - <<'PY'
import json, urllib.request
def call(path, params):
    data=json.dumps({"jsonrpc":"2.0","method":"call","params":params}).encode()
    req=urllib.request.Request("http://localhost:8099"+path, data=data,
                               headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=8).read())['result']

m=call("/saas/api/v1/meta",{})['data']
print("rates leaked?:", 'worker_price' in json.dumps(m))         # expect False
for t in call("/saas/api/v1/tiers",{"kind":"hosting"})['data']:
    print("tier:", t['name'], "$%.2f/mo"%t['monthly'], "rec=",t['recommended'])
for g in call("/saas/api/v1/regions",{})['data']:
    print("region:", g['name'], "x%.2f"%g['multiplier'], "default=",g['default'], "available=",g['available'])
print("calc hosting 4/50/mo:", call("/saas/api/v1/hosting/calculate",
      {"workers":4,"storage":50,"billing":"monthly"})['data']['total'])
PY
```

**Expected:**
- `rates leaked?: False`
- one tier `ZZ Pro $55.00/mo rec= True`
- two regions: `EU ... x1.00 default= True available= True` and
  `US ... x1.50 default= False available= True`
- `calc hosting 4/50/mo: 55.0`

### Test the purchase funnel (region price + co‑location domain filter)

```bash
cd /home/moutaz/Documents/Work/odoo18
python3 - <<'PY'
import urllib.request, http.cookiejar, re, json
BASE="http://localhost:8099"
cj=http.cookiejar.CookieJar()
op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
# authenticate (sets the session cookie)
op.open(urllib.request.Request(BASE+"/web/session/authenticate",
    data=json.dumps({"jsonrpc":"2.0","method":"call",
        "params":{"db":"saas_test","login":"admin","password":"testpass123"}}).encode(),
    headers={"Content-Type":"application/json"}), timeout=12).read()
def get(p): return op.open(urllib.request.Request(BASE+p), timeout=12).read().decode("utf-8","replace")
def doms(h):
    m=re.search(r'<select[^>]*name="domain_id".*?</select>', h, re.S)
    return [o.strip() for o in re.findall(r'<option[^>]*>\s*\.?([^<]+?)\s*</option>', m.group(0))] if m else []
def price(h):
    m=re.search(r'id="hosting-total-amount"[^>]*>\s*\$?([0-9,]+\.\d{2})', h); return m.group(1) if m else "?"
for tag,q in [("EU(default)",""), ("US(x1.5)","&region_id=%d" % json.loads('[10]')[0])]:
    h=get("/hosting/configure?workers=4&storage=50&billing=monthly"+q)
    print(tag, "price=$"+price(h), "domains=", doms(h))
PY
```

> Replace `region_id=10` with the actual US region id from the `/regions`
> output above (ids depend on your DB).

**Expected:**
- `EU(default) price=$55.00 domains= ['zz-eu.example.com', 'zz-neutral.example.com']`
- `US(x1.5) price=$82.50 domains= ['zz-us.example.com', 'zz-neutral.example.com']`

i.e. the **price scales ×1.5** for US, and each region offers **only its own
domain + the neutral (proxy‑less) one** — the cross‑region domain is hidden
(proxy co‑location enforced at the UI).

### What "behaviour‑neutral" looks like

If you delete the dummy `us` region (or set it inactive) so only one region
remains, and unpublish the `ZZ Pro` tier, then re‑run the funnel: there is
**no region picker**, the slider is shown, and the price is the plain
`55.00`. That confirms the system is inert until you configure it.

## C.5 Clean up

```bash
cd /home/moutaz/Documents/Work/odoo18
# Stop the test server (Ctrl-C in its terminal, or kill by PID):
pgrep -af "odoo-bin .* -d saas_test"        # find PID, then: kill <PID>

export PGPASSWORD=odoo18
psql -h localhost -U odoo18 -d postgres -c "DROP DATABASE IF EXISTS saas_test;"
rm -f /tmp/price_scenarios.py /tmp/price_seed.py

# Confirm only postgres + the live saas DB remain:
psql -h localhost -U odoo18 -d postgres -tAc \
  "SELECT datname FROM pg_database WHERE datistemplate=false ORDER BY 1;"
# And the live server is fine:
curl -s -o /dev/null -w "live=%{http_code}\n" http://localhost:8018/web/login
```

---

## Quick reference — command cheat‑sheet

```bash
# fresh install
.env/bin/python3 odoo/odoo-bin -c odoo.conf -d saas -i saas_core,saas_website --stop-after-init
# upgrade after code change
.env/bin/python3 odoo/odoo-bin -c odoo.conf -d saas -u saas_core,saas_website --stop-after-init
# run dev server
.env/bin/python3 odoo/odoo-bin -c odoo.conf -d saas
# clone live -> test
pg_dump -h localhost -U odoo18 --no-owner --no-privileges saas | psql -h localhost -U odoo18 -d saas_test -q
# automated tests
.env/bin/python3 odoo/odoo-bin -c odoo.conf -d saas_test -u saas_core,saas_website \
  --test-enable --test-tags /saas_core:TestPricingEngine --stop-after-init --http-port 8099 --no-http
# odoo shell (dummy-data / one-off checks)
.env/bin/python3 odoo/odoo-bin shell -c odoo.conf -d saas_test --no-http < script.py
```

See also **`docs/pricing-admin-guide.md`** (operator‑facing configuration
guide) and **`docs/pricing-system-execution-plan.md`** (design/source of
truth for the pricing rebuild, steps S1–S10).
