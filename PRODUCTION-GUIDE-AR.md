# دليل التشغيل في الإنتاج — VELTNEX (Odoo 18 SaaS)

دليل كامل خطوة بخطوة لنشر منصّة **VELTNEX** (Odoo 18: `saas_core` + `saas_website` + واجهة React) على بيئة إنتاج حقيقية، باستخدام الدومين **veltnex.com**.

> الأوامر **بالإنجليزية** (انسخها كما هي). الشرح بالعربية. استبدل كل قيمة بين `<...>` بقيمتك الفعلية. النسخة الإنجليزية المختصرة في [`DEPLOYMENT.md`](DEPLOYMENT.md). إعداد سيرفرات الأسطول الفعلية لاحقًا في [`saas_core/docker/SERVER-SETUP.md`](saas_core/docker/SERVER-SETUP.md).

---

## 📑 جدول المحتويات

| المرحلة | المحتوى |
|---|---|
| **0** | البنية المعمارية ونوعا السيرفرات |
| **1** | شراء السيرفر ومتطلبات الأجهزة |
| **2** | تجهيز Ubuntu، تأمين أوّلي، مستخدم تشغيل |
| **3** | جدار ناري، fail2ban، تحديثات تلقائية |
| **4** | تثبيت متطلبات النظام (Python, libs, wkhtmltopdf) |
| **5** | PostgreSQL — تثبيت، إعدادات، تأمين، performance |
| **6** | جلب الكود، بيئة Python، (اختياري) بناء الواجهة |
| **7** | ملف إعدادات Odoo للإنتاج |
| **8** | تهيئة قاعدة بيانات الماستر أول مرة |
| **9** | systemd service + log rotation |
| **10** | DNS، nginx، شهادة wildcard SSL |
| **11** | تهيئة المنصّة من لوحة Odoo (SMTP / دفع / SMS / تخزين) |
| **12** | إعداد سيرفرات الأسطول (Docker hosts) |
| **13** | اختبارات تأكّد ما بعد الإطلاق |
| **14** | استراتيجية النسخ الاحتياطي للماستر |
| **15** | المراقبة والإنذار |
| **16** | التحديثات والـ rolling deploys |
| **17** | التعافي من الكوارث |
| **18** | Operations runbooks (مهام يومية) |
| **A** | ضبط الأداء (PostgreSQL + Odoo) |
| **B** | قائمة فحص ما قبل الإطلاق |
| **C** | الأخطاء الشائعة وحلولها |

---

## 0. البنية المعمارية — افهمها أولًا

عندك **نوعان من السيرفرات**، كلٌّ منهما دور مختلف:

### 0.1 سيرفر الماستر (Control Plane)
**هذا الدليل يركّز عليه.** Odoo واحد يستضيف:
- موقع VELTNEX (الواجهة العامة + بوابة العملاء)
- لوحة الإدارة + الـ API JSON
- يدير الأسطول عن طريق SSH/API
- يخزّن بيانات العملاء (حسابات، خطط، فواتير، سجلات)

الدومين: **`veltnex.com`**

### 0.2 أسطول التشغيل (Customer Workload)
سيرفرات منفصلة تشغّل نسخ العملاء الفعلية:
- **Docker hosts**: كل عميل في حاوية Docker
- **PostgreSQL servers**: قواعد بيانات العملاء (يمكن أن تكون نفس Docker host في البداية، يفضل تفصلها لاحقًا)
- **Proxy server**: nginx يوجّه `*.apps.veltnex.com` للحاوية الصحيحة

الدومين: **`*.apps.veltnex.com`**

> يمكنك البدء بسيرفر واحد يجمع الماستر + الأسطول، ثم فصلهما لاحقًا عند النمو.

### 0.3 المخطط الكامل

```
┌──────────────────────────────────────────────────────────────┐
│                       Internet                                │
└────────────────────┬────────────────────────┬────────────────┘
                     │ veltnex.com            │ *.apps.veltnex.com
                     ▼                        ▼
        ┌────────────────────────┐  ┌──────────────────────────┐
        │ Master Server          │  │ Fleet Proxy              │
        │ ─ nginx (TLS)          │  │ ─ nginx (TLS wildcard)   │
        │ ─ Odoo 18              │  │ ─ يوجّه للحاوية الصحيحة     │
        │ ─ saas_core            │  └────────────┬─────────────┘
        │ ─ saas_website         │               │
        │ ─ SPA (React)          │               ▼
        │ ─ PostgreSQL (master)  │  ┌──────────────────────────┐
        └──────┬─────────────────┘  │ Docker host(s)            │
               │                    │ ─ حاويات العملاء          │
               │  SSH / API         │ ─ restic (نسخ يومية)      │
               └───────────────────▶│                          │
                                    └─────────┬────────────────┘
                                              │
                                              ▼
                                    ┌──────────────────────────┐
                                    │ PostgreSQL server(s)      │
                                    │ ─ قواعد العملاء          │
                                    └──────────────────────────┘
                                              │
                                              ▼
                                    ┌──────────────────────────┐
                                    │ Object storage (S3 / GCS) │
                                    │ ─ النسخ الاحتياطية        │
                                    └──────────────────────────┘
```

---

## 1. شراء السيرفر ومتطلبات الأجهزة

### 1.1 سيرفر الماستر — متطلبات الأجهزة

| البند | الحد الأدنى | الموصى به (إنتاج) | لو عندك عملاء كتير |
|---|---|---|---|
| OS | Ubuntu 22.04 LTS | **Ubuntu 24.04 LTS** | Ubuntu 24.04 LTS |
| CPU | 2 vCPU | **4 vCPU** | 8 vCPU |
| RAM | 4 GB | **8 GB** | 16 GB |
| Disk | 40 GB SSD | **80 GB SSD** | 160 GB NVMe |
| Network | 100 Mbps | 1 Gbps | 1 Gbps |
| IP | Public IPv4 ثابت | Public IPv4 ثابت | Public IPv4 + IPv6 |

### 1.2 سيرفر الأسطول (Docker host) — متطلبات

تشغيل حاويات العملاء يحتاج موارد أكبر. القاعدة العامة:

| لكل 10 عملاء (workers خفيفة) | CPU | RAM | Disk |
|---|---|---|---|
| 10 عملاء × 2 worker = 20 | 4 vCPU | 16 GB | 100 GB |
| 30 عميل | 8 vCPU | 32 GB | 250 GB |
| 100 عميل | 16 vCPU | 64 GB | 500 GB NVMe |

### 1.3 مزوّدو السحاب الموصى بهم

- **Hetzner Cloud** — أرخص بكتير، أداء ممتاز (CX/CCX series)
- **DigitalOcean** — أبسط لوحة، Spaces جاهزة للنسخ
- **AWS EC2** — أعلى مرونة، RDS managed PostgreSQL
- **OVHcloud** — لو عاوز سيرفرات في أوروبا/الأردن

---

## 2. أول دخول وتجهيز Ubuntu

```bash
# من جهازك المحلي
ssh root@<MASTER_SERVER_IP>

# حدّث النظام
apt update && apt upgrade -y

# عيّن hostname واضح
hostnamectl set-hostname veltnex-master

# اضبط المنطقة الزمنية (UTC مفضّل للسيرفرات)
timedatectl set-timezone UTC

# اضبط locale
locale-gen en_US.UTF-8

# أنشئ مستخدم تشغيل (لا تشغّل Odoo كـ root أبدًا)
adduser veltnex                       # سيطلب كلمة مرور
usermod -aG sudo veltnex

# انسخ مفاتيح SSH للمستخدم الجديد
rsync --archive --chown=veltnex:veltnex ~/.ssh /home/veltnex/

# جرّب الدخول بالمستخدم الجديد من نافذة طرفية ثانية:
# ssh veltnex@<MASTER_SERVER_IP>
# لو نجح، أكمل الخطوات. لو فشل، لا تقفل الجلسة الحالية.
```

### 2.1 تأمين SSH

```bash
sudo nano /etc/ssh/sshd_config
```

اضبط الآتي (أو أضفه):

```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
```

```bash
sudo systemctl restart ssh
```

> ⚠️ **مهم**: لا تقفل الجلسة الحالية إلا بعد تجريب الدخول بـ `veltnex` من نافذة ثانية وتأكدت أنه يشتغل.

---

## 3. أمان الشبكة + الحماية ضد الهجمات

### 3.1 الجدار الناري (UFW)

```bash
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp comment 'HTTP'
sudo ufw allow 443/tcp comment 'HTTPS'
sudo ufw --force enable
sudo ufw status verbose
```

> ❌ **لا تفتح بورت Odoo (8069) للخارج أبدًا** — هو خلف nginx فقط.

### 3.2 fail2ban — حماية من brute force

```bash
sudo apt install -y fail2ban

sudo tee /etc/fail2ban/jail.local > /dev/null <<EOF
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true

[nginx-http-auth]
enabled = true

[nginx-botsearch]
enabled  = true
filter   = nginx-botsearch
logpath  = /var/log/nginx/access.log
EOF

sudo systemctl enable --now fail2ban
sudo fail2ban-client status
```

### 3.3 التحديثات الأمنية التلقائية

```bash
sudo apt install -y unattended-upgrades apt-listchanges

sudo dpkg-reconfigure -plow unattended-upgrades   # اختر "Yes"

# تفعيل وتأكيد:
sudo systemctl status unattended-upgrades
```

---

## 4. متطلبات النظام

```bash
sudo apt update
sudo apt install -y \
  git curl wget gnupg ca-certificates \
  python3 python3-venv python3-dev python3-pip \
  build-essential pkg-config \
  libpq-dev libxml2-dev libxslt1-dev libldap2-dev libsasl2-dev \
  libjpeg-dev zlib1g-dev libffi-dev libssl-dev libxmlsec1-dev \
  postgresql-client \
  nginx certbot python3-certbot-nginx python3-certbot-dns-cloudflare \
  fontconfig xfonts-75dpi xfonts-base \
  restic htop ncdu jq tmux
```

### 4.1 wkhtmltopdf (لطباعة الفواتير PDF)

Odoo يحتاج نسخة Qt مرقعة، **مش الإصدار الافتراضي من apt**.

```bash
cd /tmp
wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb
sudo apt install -y ./wkhtmltox_0.12.6.1-3.jammy_amd64.deb
wkhtmltopdf --version    # يجب أن يظهر "wkhtmltopdf 0.12.6.1 (with patched qt)"
rm wkhtmltox_0.12.6.1-3.jammy_amd64.deb
```

### 4.2 (اختياري) Node.js — فقط لبناء الواجهة على السيرفر

الواجهة المبنية موجودة في git (`saas_website/static/spa/`)، فإنت ما تحتاج Node إلا لو هتعدّل React وتبني محليًّا.

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version && npm --version
```

---

## 5. PostgreSQL — تثبيت، تأمين، tuning

### 5.1 التثبيت (PostgreSQL 15+)

```bash
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc
sudo sh -c 'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
sudo apt update
sudo apt install -y postgresql-16

# تأكد أنه شغّال
sudo systemctl status postgresql
```

### 5.2 إنشاء مستخدم قاعدة البيانات

```bash
# اسم المستخدم نفس اسم مستخدم النظام (peer auth)
sudo -u postgres createuser -d -R -S veltnex
sudo -u postgres psql -c "ALTER USER veltnex WITH PASSWORD '<STRONG_DB_PASSWORD>';"
```

> 📌 **PostgreSQL 15+**: عند إنشاء قواعد العملاء لاحقًا، الكود يضيف `ALTER SCHEMA public OWNER` و`GRANT ALL ON SCHEMA public` تلقائيًا — هذا مُعالَج في `saas_core`.

### 5.3 ضبط أداء PostgreSQL

```bash
sudo nano /etc/postgresql/16/main/postgresql.conf
```

لسيرفر 8 GB RAM، عدّل القيم التالية (راجع الملحق A لحساب أدق):

```ini
# Memory
shared_buffers = 2GB                    # ~25% من RAM
effective_cache_size = 6GB              # ~75% من RAM
work_mem = 20MB
maintenance_work_mem = 512MB

# Checkpoint
checkpoint_completionhtop_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100

# Connections
max_connections = 200                   # workers × 2 + cron + margin

# Logging
log_min_duration_statement = 1000       # log queries > 1s
log_checkpoints = on
log_lock_waits = on
```

```bash
sudo systemctl restart postgresql
```

### 5.4 تأمين PostgreSQL

```bash
sudo nano /etc/postgresql/16/main/pg_hba.conf
```

تأكد إن سطر `local` يستخدم `peer` و`host` يستخدم `scram-sha-256`:

```
local   all   postgres   peer
local   all   all        peer
host    all   all        127.0.0.1/32   scram-sha-256
host    all   all        ::1/128        scram-sha-256
```

> ❌ **لا تخلي PostgreSQL يستمع على عنوان عام**. لو سيرفر الأسطول والماستر منفصلين، استخدم نفق SSH أو شبكة خاصة (VPC) — مش `listen_addresses = '*'`.

---

## 6. الكود + بيئة Python

سنستخدم المسار `/opt/veltnex`.

### 6.1 جلب الكود

```bash
sudo mkdir -p /opt/veltnex
sudo chown -R veltnex:veltnex /opt/veltnex
cd /opt/veltnex

# 1) مصدر Odoo 18
git clone https://github.com/odoo/odoo --branch 18.0 --depth 1 odoo

# 2) ريبو مشروعك
mkdir -p custom
git clone <YOUR_PRIVATE_REPO_URL> custom/saas

# تأكد إن الواجهة المبنية موجودة:
ls custom/saas/saas_website/static/spa/index.html
# لو مفقود، راجع القسم 6.4
```

الهيكل النهائي:
```
/opt/veltnex/
├── odoo/                      # مصدر Odoo
├── custom/saas/               # مشروعك
│   ├── saas_core/             # Odoo module
│   ├── saas_website/          # Odoo module
│   └── veltnex/               # React SPA source
└── venv/                      # virtualenv (التالي)
```

### 6.2 إنشاء virtualenv

```bash
cd /opt/veltnex
python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip wheel setuptools

# متطلبات Odoo
pip install -r odoo/requirements.txt

# متطلبات إضافية لـ saas_core
pip install paramiko jinja2 boto3 google-cloud-storage requests
```

### 6.3 ملف requirements مجمّع (اختياري)

أنشئ `/opt/veltnex/requirements-veltnex.txt`:

```
-r odoo/requirements.txt
paramiko>=3.4
jinja2>=3.1
boto3>=1.34
google-cloud-storage>=2.10
requests>=2.31
```

### 6.4 (اختياري) بناء الواجهة على السيرفر

الواجهة المبنية في git (`saas_website/static/spa/`)، فمعظم النشرات **لا تحتاج هذه الخطوة**. نفّذها فقط لو عدّلت `veltnex/src/`:

```bash
cd /opt/veltnex/custom/saas/veltnex
npm ci
npm run build      # يكتب في ../saas_website/static/spa/
```

> ⚠️ بعد أي بناء جديد للواجهة، أعد تشغيل Odoo (`systemctl restart veltnex`) لأنه يخزّن `index.html` في الذاكرة.

---

## 7. ملف إعدادات Odoo (`odoo.conf`)

```bash
sudo mkdir -p /etc/veltnex /var/log/odoo /var/lib/odoo
sudo chown veltnex:veltnex /var/log/odoo /var/lib/odoo
sudo chmod 750 /var/log/odoo /var/lib/odoo

sudo nano /etc/veltnex/odoo.conf
```

```ini
[options]
;------------------------------------------------------------------
; قاعدة بيانات الماستر
;------------------------------------------------------------------
admin_passwd = <VERY_LONG_RANDOM_MASTER_PASSWORD>
db_host = False                          ; محلي عبر peer
db_port = False
db_user = veltnex
db_password = <STRONG_DB_PASSWORD>
dbfilter = ^veltnex$                     ; لا يظهر إلا قاعدة الماستر
list_db = False                          ; إخفاء مدير قواعد البيانات

;------------------------------------------------------------------
; مسارات الموديولات
;------------------------------------------------------------------
addons_path = /opt/veltnex/odoo/addons,/opt/veltnex/odoo/odoo/addons,/opt/veltnex/custom/saas
data_dir = /var/lib/odoo

;------------------------------------------------------------------
; الشبكة + العمال
;------------------------------------------------------------------
http_port = 8069
gevent_port = 8072
proxy_mode = True                        ; nginx أمامه

; قاعدة Odoo: workers = (2 × cores) + 1
workers = 4
max_cron_threads = 2                     ; ⚠️ إلزامي ≥ 1 وإلا تقف الفوترة/النسخ

;------------------------------------------------------------------
; حدود الموارد لكل worker (يمنع تجمّد الـrequests)
;------------------------------------------------------------------
limit_memory_soft = 2147483648           ; 2 GB
limit_memory_hard = 2684354560           ; 2.5 GB
limit_time_cpu = 600                     ; 10 دقائق CPU
limit_time_real = 1200                   ; 20 دقيقة wall clock
limit_request = 8192

;------------------------------------------------------------------
; اللوجات
;------------------------------------------------------------------
logfile = /var/log/odoo/odoo.log
log_level = info
log_handler = :INFO,odoo.addons.saas_core:DEBUG
```

```bash
sudo chmod 640 /etc/veltnex/odoo.conf
sudo chown veltnex:veltnex /etc/veltnex/odoo.conf
```

### 7.1 توليد كلمة مرور ماستر آمنة

```bash
# انسخ المخرج إلى admin_passwd
openssl rand -base64 48 | tr -d '+/=' | head -c 60; echo
```

---

## 8. تهيئة قاعدة بيانات الماستر أول مرة

```bash
cd /opt/veltnex
source venv/bin/activate

# ينشئ قاعدة veltnex ويثبّت saas_core + saas_website ثم يخرج
python3 odoo/odoo-bin -c /etc/veltnex/odoo.conf -d veltnex \
  -i saas_core,saas_website --stop-after-init --without-demo=all

# انتظر السطر:
#   "Modules loaded."
# بدون أخطاء.
```

> 💡 **بدون بيانات تجريبية** (`--without-demo=all`) — مهم للإنتاج.

### 8.1 تعيين كلمة مرور admin

أول دخول من المتصفح هيطلب كلمة مرور admin. يمكنك تعيينها من CLI:

```bash
python3 odoo/odoo-bin -c /etc/veltnex/odoo.conf -d veltnex shell --no-http <<'EOF'
admin = env.ref('base.user_admin')
admin.password = '<STRONG_ADMIN_PASSWORD>'
env.cr.commit()
EOF
```

---

## 9. systemd service + log rotation

### 9.1 unit file

```bash
sudo tee /etc/systemd/system/veltnex.service > /dev/null <<'EOF'
[Unit]
Description=VELTNEX Odoo Master
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=veltnex
Group=veltnex
ExecStart=/opt/veltnex/venv/bin/python3 /opt/veltnex/odoo/odoo-bin -c /etc/veltnex/odoo.conf
Restart=always
RestartSec=5
StartLimitBurst=10
StartLimitIntervalSec=300

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/var/log/odoo /var/lib/odoo

# Resource limits
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now veltnex
sudo systemctl status veltnex
```

### 9.2 log rotation

```bash
sudo tee /etc/logrotate.d/veltnex > /dev/null <<'EOF'
/var/log/odoo/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 640 veltnex veltnex
    sharedscripts
    postrotate
        systemctl reload veltnex >/dev/null 2>&1 || true
    endscript
}
EOF

sudo logrotate -d /etc/logrotate.d/veltnex   # dry-run للتأكد
```

---

## 10. DNS + nginx + SSL

### 10.1 سجلات DNS

من لوحة مزوّد الدومين:

```
; الماستر
veltnex.com.              A      <MASTER_SERVER_IP>
www.veltnex.com.          CNAME  veltnex.com.

; نطاق نسخ العملاء (DNS wildcard — يشير لسيرفر بروكسي الأسطول)
*.apps.veltnex.com.       A      <FLEET_PROXY_IP>
apps.veltnex.com.         A      <FLEET_PROXY_IP>    ; للـ ACME challenge
```

> 🧠 **لماذا `apps.veltnex.com` لنسخ العملاء؟**
> أسماء العملاء عشوائية (`acme`, `api`, `www`...). لو كانت تحت `*.veltnex.com` مباشرة، عميل خبيث ممكن يأخذ `www.veltnex.com` ويعطّل موقعك. الفصل تحت `apps.` يحميك.

تحقق من DNS:
```bash
dig +short veltnex.com
dig +short test.apps.veltnex.com    # يجب أن يرجع <FLEET_PROXY_IP>
```

### 10.2 nginx config للماستر

```bash
sudo tee /etc/nginx/sites-available/veltnex > /dev/null <<'EOF'
upstream odoo      { server 127.0.0.1:8069; }
upstream odoo_chat { server 127.0.0.1:8072; }

# HTTP → HTTPS redirect
server {
    listen 80;
    listen [::]:80;
    server_name veltnex.com www.veltnex.com;
    return 301 https://veltnex.com$request_uri;
}

# Canonical: www → apex
server {
    listen 443 ssl;
    http2 on;
    server_name www.veltnex.com;
    ssl_certificate     /etc/letsencrypt/live/veltnex.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/veltnex.com/privkey.pem;
    return 301 https://veltnex.com$request_uri;
}

# Main server
server {
    listen 443 ssl;
    http2 on;
    server_name veltnex.com;

    ssl_certificate     /etc/letsencrypt/live/veltnex.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/veltnex.com/privkey.pem;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Proxy headers لـ Odoo
    proxy_set_header Host              $host;
    proxy_set_header X-Forwarded-Host  $host;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP         $remote_addr;

    client_max_body_size 200m;
    proxy_buffers 16 64k;
    proxy_buffer_size 128k;

    # gzip
    gzip on;
    gzip_min_length 1100;
    gzip_buffers 4 32k;
    gzip_types text/css text/plain application/javascript application/json
               application/xml application/rss+xml image/svg+xml;
    gzip_vary on;

    # WebSocket (chatter, live notifications)
    location /websocket {
        proxy_pass http://odoo_chat;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 720s;
    }
    location /longpolling {
        proxy_pass http://odoo_chat;
        proxy_read_timeout 720s;
    }

    # Static assets — كاش طويل (الأسماء فيها hash)
    location ~* ^/saas_website/static/spa/assets/ {
        proxy_pass http://odoo;
        add_header Cache-Control "public, max-age=31536000, immutable";
        proxy_buffering on;
    }
    location ~* ^/web/static/ {
        proxy_pass http://odoo;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000, immutable";
    }

    # Server-Sent Events (live logs)
    location ~* /saas/instance/.*/logs/stream {
        proxy_pass http://odoo;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_set_header X-Accel-Buffering no;
    }

    # كل شيء آخر يذهب لـ Odoo
    location / {
        proxy_pass http://odoo;
        proxy_read_timeout 720s;
        proxy_redirect off;
    }

    # احتفظ بـ ACME webroot للـ certbot
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/veltnex /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
```

### 10.3 شهادة SSL — الماستر فقط

```bash
# تأكد إن DNS وصل قبل ما تجرّب
sudo certbot certonly --webroot -w /var/www/html \
  -d veltnex.com -d www.veltnex.com \
  --email <YOUR_EMAIL> --agree-tos --no-eff-email
sudo nginx -t && sudo systemctl reload nginx
```

### 10.4 شهادة Wildcard SSL لـ `*.apps.veltnex.com`

شهادة Wildcard تحتاج **DNS challenge** (لأن الـ HTTP challenge لا يدعم wildcard). نستخدم Cloudflare API كمثال:

```bash
# 1. أنشئ Cloudflare API token محصور على Zone:DNS:Edit
sudo mkdir -p /etc/letsencrypt
sudo tee /etc/letsencrypt/cloudflare.ini > /dev/null <<EOF
dns_cloudflare_api_token = <CLOUDFLARE_API_TOKEN>
EOF
sudo chmod 600 /etc/letsencrypt/cloudflare.ini

# 2. اطلب الشهادة
sudo certbot certonly --dns-cloudflare \
  --dns-cloudflare-credentials /etc/letsencrypt/cloudflare.ini \
  --dns-cloudflare-propagation-seconds 60 \
  -d "*.apps.veltnex.com" -d "apps.veltnex.com" \
  --email <YOUR_EMAIL> --agree-tos --no-eff-email
```

> الشهادة هتنزل في `/etc/letsencrypt/live/apps.veltnex.com/` — تستخدمها على بروكسي الأسطول لاحقًا.

### 10.5 تأكيد certbot auto-renew

```bash
sudo systemctl status certbot.timer        # يجب أن يكون active
sudo certbot renew --dry-run               # بدون أخطاء
```

افتح الآن **https://veltnex.com** — يجب أن تظهر واجهة VELTNEX (الـ SPA).

---

## 11. تهيئة المنصّة من لوحة Odoo

ادخل على **https://veltnex.com/odoo** بمستخدم `admin`. كل هذا يُضبط من الإدارة، **مش في الكود**.

### 11.1 رابط الموقع الأساسي ⚠️ إلزامي

`Settings → Technical → System Parameters`:

| المعامل | القيمة |
|---|---|
| `web.base.url` | `https://veltnex.com` |
| `web.base.url.freeze` | `True` |

> Odoo يبني روابط **عودة الدفع** والإيميلات من هذه القيمة. لو خطأ، تنكسر الفواتير.

### 11.2 معاملات SaaS

نفس المكان، بادئة `saas_master.`:

| المعامل | المعنى |
|---|---|
| `saas_master.hosting_worker_price` | سعر worker واحد للاستضافة (شهري) |
| `saas_master.hosting_storage_price_per_gb` | سعر GB التخزين |
| `saas_master.hosting_min_workers` / `_max_workers` | حدود شريحة الـworkers |
| `saas_master.hosting_min_storage` / `_max_storage` | حدود شريحة التخزين (GB) |
| `saas_master.worker_price` / `storage_price_per_gb` | أسعار الخدمات الجاهزة |
| `saas_master.monthly_yearly_discount_pct` | خصم الاشتراك السنوي (%) |
| `saas_master.trial_days` | أيام التجربة (الافتراضي 14) |
| `saas_master.max_instances_per_user` | حد عدد النسخ لكل عميل |
| `saas_master.support_email` | إيميل الدعم الظاهر للعملاء |
| `saas_master.show_services_section` | إظهار قسم الخدمات في الموقع |
| `saas_master.show_hosting_section` | إظهار قسم الاستضافة |

> الواجهة تقرأ هذه القيم عبر `/saas/api/v1/meta` — لا تضع أسعارًا في الكود.

### 11.3 SMTP — البريد الصادر

`Settings → General Settings → Discuss → Outgoing Email Servers`:

| الحقل | المثال |
|---|---|
| Name | `Primary SMTP` |
| SMTP Server | `smtp.sendgrid.net` (أو AWS SES / Mailgun / Postmark) |
| SMTP Port | `587` (STARTTLS) أو `465` (SSL) |
| Connection Security | `TLS (STARTTLS)` |
| Username | `apikey` (في حالة SendGrid) |
| Password | `<SMTP_PASSWORD>` |

ثم اضبط **From** الافتراضي في System Parameters:

| `mail.default.from` | `no-reply@veltnex.com` |
| `mail.bounce.alias` | `bounce` |
| `mail.catchall.alias` | `catchall` |

اضغط **Test Connection** وتأكد من نجاحه.

### 11.4 بوابة الدفع (إلزامي)

`Settings → Payment Providers`. فعّل واحدة على الأقل:

- **Stripe** — أبسط للبدء العالمي (API keys من dashboard.stripe.com)
- **PayPal** — للأسواق التي لا تدعم Stripe
- **Razorpay** — للهند
- **Paymob** — لمصر/الإمارات
- **Adyen / Authorize.net** — للشركات الكبرى

> ⚠️ بدون بوابة دفع مفعّلة، **الـ checkout لن يعمل** والعملاء لن يقدروا يدفعوا.

اربط Webhooks بوابة الدفع بـ `https://veltnex.com/payment/<provider>/webhook` (الـ provider يعرّفها).

### 11.5 OTP عبر الرسائل النصية (لتسجيل العملاء)

التسجيل في VELTNEX يستخدم **OTP عبر الهاتف**. لازم تشحن **Odoo IAP** أو تستخدم spider لـ SMS gateway:

`Settings → Technical → Odoo IAP → View My Services`:
- اشحن رصيد SMS (~$10 يكفي للبداية)

> بدون رصيد، **التسجيل الجديد لن يكتمل**.

### 11.6 تخزين سحابي للنسخ الاحتياطية (instances)

النسخ اليومية للعملاء تذهب لتخزين سحابي. اضبط بيانات الاعتماد في System Parameters:

#### S3 (AWS أو متوافق):
```
saas_master.backup_provider           = s3
saas_master.s3_endpoint               = https://s3.amazonaws.com
saas_master.s3_region                 = us-east-1
saas_master.s3_bucket                 = veltnex-backups
saas_master.s3_access_key             = AKIA...
saas_master.s3_secret_key             = <SECRET>
saas_master.restic_repository_password = <RESTIC_PWD>
```

#### DigitalOcean Spaces:
```
saas_master.s3_endpoint = https://fra1.digitaloceanspaces.com
saas_master.s3_region   = fra1
... (باقي الإعدادات نفسها)
```

> 💡 احفظ `restic_repository_password` في **password manager** — بدونه النسخ غير قابلة للاستعادة.

### 11.7 السجل الأساسي لبنية الأسطول

| الموديل | الغرض |
|---|---|
| `saas.server` | سيرفرات Docker + PostgreSQL (سيتم تسجيلها في القسم 12) |
| `saas.ssh.key.pair` | مفاتيح SSH للوصول لتلك السيرفرات |
| `saas.based.domain` | `apps.veltnex.com` + DNS wildcard |
| `saas.odoo.version` | صور Odoo المتاحة للعملاء (18, 17, 16...) |
| `saas.product` | منتج/خدمة واحدة على الأقل (`is_published = True`) + خطة |

> ⚠️ بدون `saas.product` منشور، صفحة `/services` ستظهر فارغة.

---

## 12. إعداد سيرفرات الأسطول

### 12.1 سيرفر Docker host — تجهيز

كرّر خطوات 2 + 3 (Ubuntu، مستخدم، UFW، fail2ban) على السيرفر الجديد، ثم:

```bash
# على Docker host
sudo apt update && sudo apt install -y restic

# تثبيت Docker Engine
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker veltnex     # أو اسم مستخدم تختاره

# تأكد أنه يشتغل بدون sudo
docker run --rm hello-world
```

التفاصيل الكاملة (subnetwork، nginx، wildcard SSL على Docker host، Docker compose...) في **`saas_core/docker/SERVER-SETUP.md`**.

### 12.2 SSH key pair (من الماستر للأسطول)

```bash
# على الماستر
ssh-keygen -t ed25519 -C "veltnex-fleet" -f ~/.ssh/veltnex_fleet -N ""

# انسخ المفتاح العام للأسطول
ssh-copy-id -i ~/.ssh/veltnex_fleet.pub veltnex@<DOCKER_HOST_IP>

# اختبر
ssh -i ~/.ssh/veltnex_fleet veltnex@<DOCKER_HOST_IP> "docker ps"
```

### 12.3 تسجيل السيرفرات في Odoo

ادخل لـ **Apps → SaaS → Infrastructure**:

#### SSH Key Pair:
- Name: `Fleet master key`
- Private key: محتوى `/root/.ssh/veltnex_fleet` (سيُخزن مشفّرًا)
- Public key: محتوى `/root/.ssh/veltnex_fleet.pub`

#### Server (Docker host):
- Name: `docker-host-01`
- Hostname/IP: `<DOCKER_HOST_IP>`
- SSH user: `veltnex`
- SSH key: اختر اللي عملته
- `is_docker_host = True`
- Max instances: 20 (مثال)
- Max CPU / RAM: حسب موارد السيرفر
- اضغط **Test Connection** وتأكد من النجاح

#### Based Domain:
- Name: `apps.veltnex.com`
- (اربطه بالـ Docker hosts ذات الصلة)

#### Odoo Versions:
- أضف الصور المتاحة (18.0, 17.0, ...) مع `is_hosting_version = True`

> الإعداد الكامل (Dockerfile، entrypoint، nginx على الأسطول، شهادة wildcard) موصوف في `saas_core/docker/SERVER-SETUP.md`.

---

## 13. اختبارات تأكّد ما بعد الإطلاق

```bash
# 1. الخدمة شغّالة
sudo systemctl is-active veltnex      # active
sudo systemctl is-enabled veltnex     # enabled

# 2. الموقع يقدّم الـ SPA
curl -s https://veltnex.com/ | grep -c "saas_website/static/spa"   # ≥ 1

# 3. الـ API يعمل
curl -s -X POST https://veltnex.com/saas/api/v1/meta \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"call","params":{},"id":1}' | jq .result.trial

# 4. لوحة الإدارة
curl -s -o /dev/null -w "%{http_code}\n" https://veltnex.com/web/login   # 200

# 5. شهادة SSL سليمة
echo | openssl s_client -connect veltnex.com:443 -servername veltnex.com 2>/dev/null \
  | openssl x509 -noout -dates

# 6. WebSocket
curl -s -o /dev/null -w "%{http_code}\n" -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" -H "Sec-WebSocket-Version: 13" \
  https://veltnex.com/websocket   # 101 / 400 (مش 502)
```

### 13.1 من الإدارة

ادخل: `Settings → Technical → Scheduled Actions`. تأكد أن:
- `SaaS: Daily Backup` آخر تشغيل خلال 24 ساعة
- `SaaS: Trial Expiry` يعمل
- `SaaS: Invoicing Cycle` يعمل

> لو "Last Run" قديم، `max_cron_threads = 0` أو الخدمة وقفت.

### 13.2 اختبار تسجيل عميل + استضافة (smoke test كامل)

1. افتح `https://veltnex.com/services/register` → سجّل حساب جديد
2. اطلب OTP، اكتمل التسجيل
3. سجل دخول → اطلب hosting → جرّب وضع تجربة (`/hosting/configure?is_trial=1`)
4. تابع `Apps → SaaS → Instances` — يجب أن تظهر النسخة وتنتقل من `provisioning` لـ `running`
5. افتح subdomain العميل → تأكد من ظهور Odoo

---

## 14. النسخ الاحتياطي للماستر

النظام ينسخ نسخ العملاء تلقائيًا. أمّن **قاعدة الماستر + filestore** بنفسك.

### 14.1 سكربت نسخ يومي

```bash
sudo tee /opt/veltnex/backup-master.sh > /dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

DATE=$(date +%F-%H%M)
BACKUP_DIR=/var/backups/veltnex
mkdir -p "$BACKUP_DIR"

# 1. PostgreSQL dump
sudo -u postgres pg_dump -Fc veltnex \
  | gzip > "$BACKUP_DIR/db-$DATE.dump.gz"

# 2. Filestore (must be consistent with DB — taken right after)
tar czf "$BACKUP_DIR/filestore-$DATE.tgz" \
  -C /var/lib/odoo/filestore veltnex

# 3. ارفع إلى تخزين سحابي
# مثال: AWS S3
# aws s3 cp "$BACKUP_DIR/db-$DATE.dump.gz" s3://veltnex-master-backups/
# aws s3 cp "$BACKUP_DIR/filestore-$DATE.tgz" s3://veltnex-master-backups/

# 4. احتفظ بآخر 14 يومًا فقط محليًا
find "$BACKUP_DIR" -name "*.gz" -mtime +14 -delete
find "$BACKUP_DIR" -name "*.tgz" -mtime +14 -delete

echo "[$(date)] backup OK: $DATE"
EOF

sudo chmod +x /opt/veltnex/backup-master.sh
sudo chown veltnex:veltnex /opt/veltnex/backup-master.sh
```

### 14.2 cron يومي

```bash
sudo crontab -e -u veltnex
```

```
# نسخ يومي 02:30
30 2 * * * /opt/veltnex/backup-master.sh >> /var/log/odoo/backup.log 2>&1
```

### 14.3 خارج السيرفر

**لا تكتفِ بالنسخة المحلية.** ارفعها لـ S3/GCS/box آخر:

```bash
# مثال rclone (بعد تركيب rclone وإعداد remote)
rclone copy /var/backups/veltnex remote:veltnex-master --age 24h
```

### 14.4 اختبار الاستعادة (مهم!)

شهريًا، استعد نسخة على سيرفر staging وتأكد من سلامتها:

```bash
# على staging
sudo -u postgres dropdb veltnex_test 2>/dev/null || true
sudo -u postgres createdb veltnex_test
gunzip -c db-2026-05-28.dump.gz | sudo -u postgres pg_restore -d veltnex_test
```

---

## 15. المراقبة والإنذار

### 15.1 صحة النظام

```bash
# سكربت سريع
sudo tee /opt/veltnex/health-check.sh > /dev/null <<'EOF'
#!/usr/bin/env bash
echo "=== Memory ==="; free -h
echo "=== Disk ==="; df -h / /var/lib/odoo /var/log
echo "=== Odoo ==="; systemctl is-active veltnex
echo "=== Postgres ==="; systemctl is-active postgresql
echo "=== Nginx ==="; systemctl is-active nginx
echo "=== Latency ==="; curl -s -o /dev/null -w "%{http_code} / %{time_total}s\n" https://veltnex.com
EOF
sudo chmod +x /opt/veltnex/health-check.sh
```

### 15.2 مراقبة اللوجات الحيّة

```bash
sudo journalctl -u veltnex -f               # لوجات الخدمة
sudo tail -f /var/log/odoo/odoo.log         # لوجات Odoo
sudo tail -f /var/log/nginx/access.log      # طلبات HTTP
sudo tail -f /var/log/nginx/error.log       # أخطاء nginx
```

### 15.3 أدوات اختيارية للإنتاج الجاد

| الأداة | الغرض |
|---|---|
| **Uptime Kuma** (self-hosted) | مراقبة HTTP من خارج السيرفر |
| **Netdata** (self-hosted) | dashboard لحظي لـ CPU/RAM/Disk/IO |
| **Prometheus + Grafana** | metrics + alerting |
| **Sentry** | تتبّع الأخطاء في الـ SPA و Python |

#### Sentry مع SPA:

```bash
# في veltnex/.env.production
VITE_SENTRY_DSN=<YOUR_DSN>
```

ثم في `veltnex/src/main.tsx` أضف:
```ts
import * as Sentry from "@sentry/react";
Sentry.init({ dsn: import.meta.env.VITE_SENTRY_DSN });
```

---

## 16. التحديثات وإعادة النشر

### 16.1 تحديث عادي (Python + الواجهة)

```bash
cd /opt/veltnex/custom/saas

# 1. تأكد إن مفيش شغل عميل جاري (`Settings → Scheduled Actions`)
# 2. اعمل snapshot لـ DB قبل التحديث:
sudo -u postgres pg_dump -Fc veltnex > /var/backups/veltnex/pre-deploy-$(date +%F).dump

# 3. اسحب الكود
git fetch --all
git checkout main
git pull --ff-only

# 4. (لو Python deps اتغيّرت)
source /opt/veltnex/venv/bin/activate
pip install -r /opt/veltnex/requirements-veltnex.txt

# 5. (لو الواجهة اتعدلت وتبني محليًّا)
( cd veltnex && npm ci && npm run build )

# 6. حدّث الموديولات
sudo systemctl stop veltnex
cd /opt/veltnex
python3 odoo/odoo-bin -c /etc/veltnex/odoo.conf -d veltnex \
  -u saas_core,saas_website --stop-after-init
sudo systemctl start veltnex

# 7. تأكد
sudo systemctl status veltnex
curl -s -o /dev/null -w "%{http_code}\n" https://veltnex.com
```

### 16.2 تحديث الواجهة فقط

```bash
cd /opt/veltnex/custom/saas
git pull
( cd veltnex && npm ci && npm run build )
sudo systemctl restart veltnex   # يكفي — لا تحتاج -u
```

### 16.3 Rollback سريع

```bash
# 1. ارجع للـ commit السابق
cd /opt/veltnex/custom/saas
git log --oneline -5
git checkout <PREVIOUS_COMMIT>

# 2. استعد قاعدة البيانات (لو فيه schema migration)
sudo systemctl stop veltnex
sudo -u postgres pg_restore -d veltnex -c /var/backups/veltnex/pre-deploy-*.dump
sudo systemctl start veltnex
```

---

## 17. التعافي من الكوارث

### 17.1 السيرفر تالف بالكامل — استعادة على سيرفر جديد

1. جهّز سيرفر جديد (الأقسام 1-7)
2. استعد قاعدة البيانات:
   ```bash
   sudo -u postgres createdb veltnex
   gunzip -c /tmp/db-LATEST.dump.gz | sudo -u postgres pg_restore -d veltnex
   ```
3. استعد filestore:
   ```bash
   tar xzf /tmp/filestore-LATEST.tgz -C /var/lib/odoo/filestore/
   sudo chown -R veltnex:veltnex /var/lib/odoo/filestore
   ```
4. شغّل Odoo + nginx
5. حدّث DNS إذا غيّرت IP

### 17.2 استعادة instance عميل من نسخة

في الإدارة: `Instance → Backups → اختر النسخة → Restore`

أو يدويًّا (لو الواجهة معطّلة):
```bash
# من الماستر، استدعِ الـ ORM:
python3 odoo/odoo-bin -c /etc/veltnex/odoo.conf -d veltnex shell --no-http <<'EOF'
inst = env['saas.instance'].browse(<INSTANCE_ID>)
backup = inst.backup_ids.filtered(lambda b: b.state == 'completed')[0]
inst.action_restore_backup(backup.id)
EOF
```

---

## 18. Operations Runbooks

### 18.1 إضافة Docker host جديد

1. جهّز السيرفر (القسم 12.1)
2. انسخ SSH public key للسيرفر الجديد
3. في الإدارة: `SaaS → Infrastructure → Servers → Create`
4. أدخل IP، اختر key pair، اضغط Test Connection
5. اربطه بـ `apps.veltnex.com` (Based Domain)
6. حدّث DNS لو الـ proxy server اتغيّر

### 18.2 إيقاف عميل (suspend)

```bash
# من الإدارة، أو من ORM:
env['saas.instance'].browse(ID).action_suspend()
```

النسخة تتوقف لكن البيانات تبقى. لإلغاء التوقف: `action_resume()`.

### 18.3 تغيير خطة عميل

من بوابة العميل أو الإدارة. الانتقال:
- **Upgrade**: prorated فورًا، تتم الفوترة بالفرق
- **Downgrade**: ينطبق في دورة الفوترة التالية (لا يتم رد رسوم)

### 18.4 إلغاء حساب عميل

`Settings → Users` → ابحث عن العميل → Archive. النسخ تتوقف. البيانات تبقى لمدة 30 يومًا قبل الحذف الفعلي (`saas.instance.cleanup` cron).

---

## ملحق A — ضبط الأداء

### A.1 حساب workers الـ Odoo

```
workers = (2 × CPU cores) + 1
```

لكل worker، احسب:
- RAM = `limit_memory_soft` (2 GB افتراضي)
- إذًا workers × 2 GB ≤ 70% من RAM السيرفر

| RAM السيرفر | CPU | workers موصى به |
|---|---|---|
| 4 GB | 2 | 2 |
| 8 GB | 4 | 4 |
| 16 GB | 8 | 6 |
| 32 GB | 16 | 10 |

### A.2 PostgreSQL tuning (تفصيل)

استخدم [PGTune](https://pgtune.leopard.in.ua/) بالقيم:
- DB Type: `Web Application`
- OS: `Linux`
- Total RAM: حسب السيرفر
- CPUs: حسب السيرفر
- Connections: 200
- Storage: `SSD`

### A.3 nginx caching للأصول الثابتة

في nginx config، للأصول الـ SPA (الأسماء فيها hash):
```nginx
location /saas_website/static/spa/assets/ {
    add_header Cache-Control "public, max-age=31536000, immutable";
}
```

سنة كاملة — لأن الـ filename فيه content hash، أي تغيير = URL جديد.

---

## ملحق B — قائمة فحص ما قبل الإطلاق

### الأمان
- [ ] `admin_passwd` كلمة مرور طويلة عشوائية
- [ ] `list_db = False`
- [ ] `dbfilter = ^veltnex$`
- [ ] `proxy_mode = True`
- [ ] Odoo بورت 8069 **مغلق من الخارج** (UFW)
- [ ] PostgreSQL يستمع على localhost فقط
- [ ] SSH: root معطّل، password auth معطّل
- [ ] fail2ban مفعّل
- [ ] HTTPS مع TLS 1.2+
- [ ] HSTS header مفعّل
- [ ] auto-renew للـ SSL مفعّل ومُختبر

### الوظائف
- [ ] `web.base.url` صحيح
- [ ] SMTP مُختبر (test email وصلت)
- [ ] بوابة دفع مفعّلة (اختبار transaction)
- [ ] SMS gateway / Odoo IAP مشحون
- [ ] تخزين سحابي للنسخ مُختبر
- [ ] على الأقل `saas.product` واحد منشور
- [ ] على الأقل `saas.server` (Docker host) مُسجّل و"Test Connection" ناجح
- [ ] `saas.based.domain` مُسجّل و DNS wildcard يعمل
- [ ] `saas.odoo.version` واحد على الأقل
- [ ] Crons تعمل (`max_cron_threads ≥ 1`، "Last Run" حديث)

### التشغيل
- [ ] backup يومي للماستر يعمل
- [ ] نسخة backup سحابية مُختبرة (استعادة على staging)
- [ ] لوجات تدور (logrotate)
- [ ] مراقبة uptime من خارج السيرفر
- [ ] خطة على الورق للـ DR
- [ ] runbook موثّق لأشهر المهام

### أداء
- [ ] PostgreSQL مضبوط (PGTune)
- [ ] Odoo workers = (2 × cores) + 1
- [ ] nginx gzip مفعّل
- [ ] static assets caching طويل
- [ ] swap مفعّل (insurance ضد OOM)

---

## ملحق C — الأخطاء الشائعة

| العَرَض | السبب الأرجح | الحل |
|---|---|---|
| الموقع يظهر QWeb بدل SPA | كاش shell في Odoo | `systemctl restart veltnex` |
| `502 Bad Gateway` | Odoo متوقف أو يتوقف عند الإقلاع | `journalctl -u veltnex -n 200` |
| `504 Gateway Timeout` | request طويل > `proxy_read_timeout` | ارفع `limit_time_real` في odoo.conf |
| WebSocket لا يعمل | nginx لا يوجّه `/websocket` لـ `gevent_port` | راجع nginx config |
| OTP لا يصل | Odoo IAP غير مشحون | اشحن SMS credits |
| الدفع لا يتم | `web.base.url` خاطئ أو HTTPS غير سليم | تأكد من القيمة والشهادة |
| فواتير PDF فارغة | wkhtmltopdf إصدار غير مرقع | ثبّت 0.12.6.1-3 |
| Crons لا تشتغل | `max_cron_threads = 0` | اضبط ≥ 1 |
| `/services` فارغة | لا يوجد `saas.product` منشور | أضف منتج |
| النسخ اليومية تفشل | restic غير مثبّت على Docker host | `apt install restic` على الـ host |
| تأكيد instance: "subdomain taken" | تكرار subdomain في `saas.instance` | تأكد من قاعدة البيانات + الـ DNS |
| `database not found` في DB selector | `dbfilter` يخفيها | تأكد من `dbfilter = ^veltnex$` |
| ذاكرة تنفد بسرعة | workers كتير أو memory leak | قلّل workers أو راقب بـ htop |
| SSL لا يجدّد تلقائيًّا | timer معطّل | `systemctl enable certbot.timer` |
| `view-source:` يظهر "Odoo" | كاش بعد ما عملت white-label | `systemctl restart veltnex` + browser refresh |
| الـ light theme لا يعمل على QWeb | الـ XML لم يُحدّث | `python3 odoo-bin -u saas_website -d veltnex --stop-after-init` |

---

## 🎯 خلاصة سريعة

| الخطوة الحرجة | الأمر |
|---|---|
| تثبيت كل شيء | `apt install -y python3-venv postgresql nginx certbot restic ...` |
| إنشاء قاعدة الماستر | `odoo-bin -d veltnex -i saas_core,saas_website` |
| تشغيل كخدمة | `systemctl enable --now veltnex` |
| شهادة SSL ماستر | `certbot --nginx -d veltnex.com` |
| شهادة SSL wildcard | `certbot certonly --dns-cloudflare -d *.apps.veltnex.com` |
| تحديث الكود | `git pull && systemctl restart veltnex` |
| تحديث الموديول | `odoo-bin -u saas_core,saas_website -d veltnex --stop-after-init` |
| نسخة احتياطية | `pg_dump -Fc veltnex > backup.dump` |
| استعادة | `pg_restore -d veltnex backup.dump` |

اللوجات: `journalctl -u veltnex -f` + `/var/log/odoo/odoo.log` + `/var/log/nginx/error.log`.
