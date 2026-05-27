1# دليل التشغيل في الإنتاج — من شراء السيرفر إلى تشغيل المشروع (VELTNEX)

دليل عملي خطوة بخطوة لنشر منصّة **VELTNEX** (Odoo 18: `saas_core` + `saas_website`
+ واجهة React) على سيرفر إنتاج جديد بالكامل، باستخدام الدومين **veltnex.com**.

> الأوامر بالإنجليزية (انسخها كما هي)، والشرح بالعربية. استبدل أي قيمة بين
> `<...>` بقيمتك. النسخة الإنجليزية المختصرة المرجعية في [`DEPLOYMENT.md`](DEPLOYMENT.md)،
> وإعداد أسطول الحاويات (سيرفرات العملاء) في
> [`saas_core/docker/SERVER-SETUP.md`](saas_core/docker/SERVER-SETUP.md).

---

## 0. نظرة عامة على البنية (مهم تفهمها الأول)

عندك **نوعان من السيرفرات**:

1. **سيرفر الماستر (Control Plane)** — موضوع هذا الدليل. عليه Odoo الذي يدير كل
   شيء ويقدّم موقع VELTNEX وبوابة العملاء والـAPI. دومينه `veltnex.com`.
2. **أسطول التشغيل (Docker hosts + PostgreSQL servers)** — سيرفرات تعمل عليها
   نسخ العملاء (كل عميل في حاوية Docker). دومينها `*.apps.veltnex.com`. إعدادها
   في `saas_core/docker/SERVER-SETUP.md`. يمكن أن تبدأ بسيرفر واحد يجمع الماستر
   + التشغيل ثم تفصلهما لاحقًا.

```
المستخدم ── HTTPS ──▶ nginx ──▶ Odoo (الماستر) ──▶ PostgreSQL (قاعدة الماستر)
                                      │
                                      └── SSH/API ──▶ Docker hosts (نسخ العملاء)
                                                          *.apps.veltnex.com
```

---

## 1. شراء السيرفر

اختر VPS/Cloud (DigitalOcean / Hetzner / AWS EC2 / أي مزوّد) بمواصفات للماستر:

| البند | الحد الأدنى | الموصى به (للبداية) |
|---|---|---|
| النظام | Ubuntu 22.04 LTS | **Ubuntu 24.04 LTS** |
| المعالج | 2 vCPU | 4 vCPU |
| الذاكرة | 4 GB | 8 GB |
| التخزين | 40 GB SSD | 80 GB SSD |

ملاحظات:
- النسخ الفعلية للعملاء ستحتاج سيرفرات Docker منفصلة بموارد أكبر لاحقًا.
- احصل على **IP ثابت (public IP)** للسيرفر.

---

## 2. أول دخول وتأمين السيرفر

```bash
# من جهازك، ادخل كـ root (المزوّد يعطيك كلمة المرور أو مفتاح SSH)
ssh root@<SERVER_IP>

# حدّث النظام
apt update && apt upgrade -y

# أنشئ مستخدم تشغيل (لا تشغّل Odoo كـ root)
adduser veltnex
usermod -aG sudo veltnex

# (موصى به) انسخ مفتاح SSH للمستخدم الجديد ثم عطّل دخول root وكلمة المرور
rsync --archive --chown=veltnex:veltnex ~/.ssh /home/veltnex

# الجدار الناري: اسمح فقط بـ SSH + HTTP + HTTPS
apt install -y ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

> أعد الدخول كـ `veltnex` للخطوات التالية: `ssh veltnex@<SERVER_IP>`، واستخدم
> `sudo` عند الحاجة.

---

## 3. تثبيت متطلبات النظام

```bash
sudo apt update
sudo apt install -y \
  git python3 python3-venv python3-dev build-essential \
  libpq-dev libxml2-dev libxslt1-dev libldap2-dev libsasl2-dev \
  libjpeg-dev zlib1g-dev libffi-dev libssl-dev \
  postgresql postgresql-client \
  nginx certbot python3-certbot-nginx \
  fontconfig xfonts-75dpi xfonts-base

# wkhtmltopdf (نسخة Qt المعدّلة — ضرورية لطباعة الفواتير PDF)
wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb
sudo apt install -y ./wkhtmltox_0.12.6.1-3.jammy_amd64.deb
wkhtmltopdf --version    # للتأكد

# (اختياري) Node.js 20 — فقط إذا أردت بناء الواجهة على السيرفر.
# الواجهة المبنية مرفوعة بالفعل في git (static/spa)، فغالبًا لن تحتاجه.
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

---

## 4. إعداد PostgreSQL

```bash
# أنشئ مستخدم قاعدة بيانات باسم نفس مستخدم النظام (Odoo يتصل بـ peer/md5)
sudo -u postgres createuser -d -R -S veltnex

# عيّن له كلمة مرور قوية
sudo -u postgres psql -c "ALTER USER veltnex WITH PASSWORD '<STRONG_DB_PASSWORD>';"
```

> ملاحظة PostgreSQL 15+: عند إنشاء قواعد بيانات العملاء لاحقًا، النظام يضيف
> تلقائيًا `ALTER SCHEMA public OWNER` و`GRANT ALL ON SCHEMA public` للدور —
> هذا مُعالَج في الكود، لا تحتاج تفعله يدويًا.

---

## 5. جلب الكود

سنستخدم المسار `/opt/veltnex`. نحتاج **مصدر Odoo 18** + **ريبو مشروعك**.

```bash
sudo mkdir -p /opt/veltnex
sudo chown -R veltnex:veltnex /opt/veltnex
cd /opt/veltnex

# 1) مصدر Odoo 18 (يحتوي odoo-bin + addons القياسية)
git clone https://github.com/odoo/odoo --branch 18.0 --depth 1 odoo

# 2) ريبو مشروعك (saas_core + saas_website + veltnex)
#    استبدل الرابط برابط ريبو مشروعك الخاص
git clone <YOUR_PRIVATE_REPO_URL> custom/saas
```

الهيكل النهائي:
```
/opt/veltnex/
├── odoo/                  ← مصدر Odoo (odoo-bin، addons، odoo/addons)
├── custom/saas/           ← مشروعك (saas_core, saas_website, veltnex)
└── venv/                  ← بيئة بايثون (الخطوة التالية)
```

---

## 6. بيئة بايثون والاعتماديات

```bash
cd /opt/veltnex
python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip wheel
pip install -r odoo/requirements.txt

# اعتماديات saas_core الإضافية (SSH، القوالب، التخزين السحابي)
pip install paramiko jinja2 boto3 google-cloud-storage
```

---

## 7. (اختياري) بناء واجهة VELTNEX

الواجهة المبنية موجودة في `custom/saas/saas_website/static/spa/` ومرفوعة في git،
فالنشر العادي **لا يحتاج هذه الخطوة**. نفّذها فقط لو عدّلت كود الواجهة (`veltnex/src`):

```bash
cd /opt/veltnex/custom/saas/veltnex
npm ci
npm run build      # يكتب إلى ../saas_website/static/spa/
```

> بعد أي بناء جديد للواجهة يجب **إعادة تشغيل Odoo** (لأنه يخزّن `index.html` في
> الذاكرة).

---

## 8. إعداد ملف Odoo للإنتاج

```bash
sudo mkdir -p /etc/veltnex /var/log/odoo /var/lib/odoo
sudo chown veltnex:veltnex /var/log/odoo /var/lib/odoo
sudo nano /etc/veltnex/odoo.conf
```

ضع بداخله (عدّل الأسرار والمسارات):

```ini
[options]
admin_passwd = <LONG_RANDOM_MASTER_PASSWORD>
db_host = False
db_port = False
db_user = veltnex
db_password = <STRONG_DB_PASSWORD>
dbfilter = ^veltnex$
list_db = False

addons_path = /opt/veltnex/odoo/addons,/opt/veltnex/odoo/odoo/addons,/opt/veltnex/custom/saas
data_dir = /var/lib/odoo

http_port = 8069
gevent_port = 8072
proxy_mode = True
workers = 4
max_cron_threads = 2

limit_memory_soft = 2147483648
limit_memory_hard = 2684354560
limit_time_cpu = 600
limit_time_real = 1200
limit_request = 8192

logfile = /var/log/odoo/odoo.log
log_level = info
```

نقاط حرجة:
- **`max_cron_threads = 2`** إلزامي — الفوترة الدورية والنسخ الاحتياطي وفحوص
  الصحة وانتهاء التجارب وتوفير النسخ المعلّقة كلها Cron jobs؛ بدونها لن تعمل.
- **`proxy_mode = True`** لأن nginx أمام Odoo.
- **`list_db = False`** + كلمة مرور ماستر قوية لإخفاء مدير قواعد البيانات.
- **`workers = 4`** ≈ (2 × عدد الأنوية) + 1 — عدّلها حسب السيرفر.

---

## 9. تهيئة قاعدة البيانات أول مرة

```bash
cd /opt/veltnex
source venv/bin/activate

# ينشئ قاعدة veltnex ويثبّت الموديولات ثم يخرج
python3 odoo/odoo-bin -c /etc/veltnex/odoo.conf -d veltnex \
  -i saas_core,saas_website --stop-after-init
```

انتظر حتى ترى `Modules loaded.` بدون أخطاء.

---

## 10. التشغيل كخدمة systemd

```bash
sudo nano /etc/systemd/system/veltnex.service
```

```ini
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
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now veltnex
sudo systemctl status veltnex      # يجب أن تكون active (running)
```

---

## 11. الدومين + DNS + nginx + SSL

### 11.1 سجلات DNS (من لوحة مزوّد الدومين)

```
; موقع الماستر
veltnex.com.          A      <SERVER_IP>
www.veltnex.com.      CNAME  veltnex.com.

; نطاق نسخ العملاء → سيرفر بروكسي الأسطول (قد يكون نفس السيرفر في البداية)
*.apps.veltnex.com.   A      <FLEET_PROXY_IP>
```

> لماذا `apps.veltnex.com` لنسخ العملاء؟ لأن أسماء العملاء عشوائية (`acme`,
> `api`, `www`...)؛ لو كانت مباشرة تحت `*.veltnex.com` لاستطاع عميل أخذ
> `www.veltnex.com` وحجب موقعك. الفصل تحت `apps.` يحميك.

### 11.2 إعداد nginx

```bash
sudo nano /etc/nginx/sites-available/veltnex
```

```nginx
upstream odoo      { server 127.0.0.1:8069; }
upstream odoo_chat { server 127.0.0.1:8072; }

server {
    listen 80;
    server_name veltnex.com www.veltnex.com;
    return 301 https://veltnex.com$request_uri;
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
    client_max_body_size 200m;

    location /websocket {
        proxy_pass http://odoo_chat;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    location /longpolling { proxy_pass http://odoo_chat; }

    # كاش قوي لأصول الواجهة (أسماؤها تحوي hash ثابت)
    location /saas_website/static/spa/assets/ {
        proxy_pass http://odoo;
        add_header Cache-Control "public, max-age=2592000, immutable";
    }

    location / {
        proxy_pass http://odoo;
        proxy_read_timeout 720s;     # يسمح ببث اللوجات (SSE)
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/veltnex /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

# شهادة SSL (تأكد أن DNS يشير للسيرفر أولًا)
sudo certbot --nginx -d veltnex.com -d www.veltnex.com
```

افتح الآن **https://veltnex.com** — يجب أن تظهر واجهة VELTNEX.

---

## 12. تهيئة المنصّة من لوحة Odoo

ادخل لوحة الإدارة على **https://veltnex.com/odoo** ثم سجّل دخول بمستخدم
`admin` (كلمة المرور التي أُنشئت عند تهيئة القاعدة — أو اضبطها عبر
`/web/login`). كل ما يلي يُضبط من الواجهة ولا شيء منه مكتوب في الكود.

### 12.1 رابط الموقع الأساسي
`Settings → Technical → System Parameters`:
- `web.base.url` = `https://veltnex.com`
- `web.base.url.freeze` = `True`

> ضروري: Odoo يبني روابط **عودة الدفع** و**روابط الإيميلات** من هذه القيمة.

### 12.2 التسعير وأقسام الموقع (System Parameters، البادئة `saas_master.`)
| المعامل | المعنى |
|---|---|
| `saas_master.hosting_worker_price`, `hosting_storage_price_per_gb` | أسعار الاستضافة |
| `saas_master.hosting_min/max_workers`, `hosting_min/max_storage` | حدود الشرائح |
| `saas_master.worker_price`, `storage_price_per_gb` | أسعار الخطط المخصّصة للخدمات |
| `saas_master.*_yearly_discount_pct` | خصم الاشتراك السنوي |
| `saas_master.trial_days`, `max_instances_per_user` | التجربة/الحدود |
| `saas_master.support_email` | إيميل الدعم الظاهر للعملاء |

> الواجهة تقرأ هذه القيم عبر `/saas/api/v1/meta` و`hosting/calculate` — لا تضع
> أسعارًا في الواجهة.

### 12.3 التكاملات الإلزامية للإنتاج
- **بوابة دفع** (`Settings → Payment Providers`): فعّل واحدة على الأقل (Stripe…)
  — صفحات الـcheckout تعتمد عليها.
- **بوابة SMS / Odoo IAP**: التسجيل يستخدم **OTP عبر الهاتف**؛ بدون رصيد/بوابة
  SMS لن يكتمل إنشاء الحسابات.
- **بريد صادر (SMTP)**: لإيميلات التوفير والفوترة والتنبيهات.
- **تخزين سحابي للنسخ** (S3 / GCS / DigitalOcean Spaces): بيانات الاعتماد في
  الإعدادات/System Parameters (النسخ اليومية تستخدم restic، والطلبية المؤقتة zip).

### 12.4 سجلّ البنية التحتية (قوائم SaaS في اللوحة)
- **`saas.server`**: أضف سيرفرات Docker (Docker host) وسيرفرات PostgreSQL.
- **`saas.ssh.key.pair`**: مفاتيح SSH للوصول لتلك السيرفرات.
- **`saas.based.domain`**: أضف `apps.veltnex.com` (مع DNS wildcard يشير لبروكسي الأسطول).
- **`saas.odoo.version`**: نسخ/صور Odoo المتاحة للعملاء.
- انشر منتجًا واحدًا على الأقل **`saas.product`** (`is_published = True`) + خطة،
  وإلا ستظهر صفحة الخدمات فارغة.

---

## 13. أسطول التشغيل (سيرفرات نسخ العملاء)

إعداد سيرفرات Docker (تثبيت Docker، البروكسي العكسي، شهادة wildcard لـ
`*.apps.veltnex.com`، المفاتيح) موصوف بالتفصيل في:
**`saas_core/docker/SERVER-SETUP.md`**. بعد إعدادها، سجّلها في الخطوة 12.4.

---

## 14. التحقق النهائي

```bash
# الخدمة شغّالة
sudo systemctl status veltnex

# الموقع يقدّم الواجهة
curl -s https://veltnex.com/ | grep -o "saas_website/static/spa" | head -1   # يجب أن يظهر

# الـAPI + قاعدة البيانات
curl -s -X POST https://veltnex.com/saas/api/v1/meta \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"call","params":{},"id":1}'   # ok:true

# لوحة الإدارة
curl -s -o /dev/null -w "%{http_code}\n" https://veltnex.com/web/login   # 200
```

في اللوحة: `Settings → Technical → Scheduled Actions` — تأكد أن الـCrons لها
"Last Run" حديث (دليل أن `max_cron_threads` يعمل).

---

## 15. النسخ الاحتياطي لقاعدة الماستر

النظام ينسخ نسخ العملاء تلقائيًا. أمّن **الماستر** بنفسك:

```bash
# مثال سكربت يومي (ضعه في cron)
pg_dump veltnex | gzip > /backups/veltnex-$(date +%F).sql.gz
# واحفظ مجلد الـfilestore مع القاعدة (متسقين)
tar czf /backups/filestore-$(date +%F).tgz /var/lib/odoo
```
انقل النسخ خارج السيرفر (S3/مكان آخر)، واختبر الاستعادة دوريًا.

---

## 16. التحديثات / إعادة النشر

```bash
cd /opt/veltnex/custom/saas
git pull

# لو تغيّرت الواجهة وتبني على السيرفر:
( cd veltnex && npm ci && npm run build )

# طبّق تغييرات بايثون/البيانات:
sudo systemctl stop veltnex
cd /opt/veltnex && source venv/bin/activate
python3 odoo/odoo-bin -c /etc/veltnex/odoo.conf -d veltnex \
  -u saas_core,saas_website --stop-after-init
sudo systemctl start veltnex
```

> تغيير الواجهة فقط؟ يكفي `sudo systemctl restart veltnex` (يُفرّغ كاش الـshell).
> تغييرات الكود/البيانات/الموديول تحتاج خطوة `-u` أعلاه.

---

## 17. قائمة الأمان

- [ ] `list_db = False` + كلمة مرور ماستر طويلة
- [ ] `proxy_mode = True`؛ Odoo خلف nginx فقط (لا يُفتح 8069 للخارج)
- [ ] `dbfilter = ^veltnex$`
- [ ] الجدار الناري يفتح 80/443 فقط؛ PostgreSQL غير عام
- [ ] HTTPS مفعّل (certbot يجدّد تلقائيًا — تحقّق `sudo certbot renew --dry-run`)
- [ ] مفاتيح SSH للأسطول بأقل صلاحية ممكنة
- [ ] تدوير أسرار الـwebhook (`/saas/webhook/<secret>`)
- [ ] بيانات اعتماد التخزين السحابي محصورة على باكِت النسخ فقط
- [ ] تحديثات نظام ومكتبات دورية

---

## 18. حل المشكلات الشائعة

| العَرَض | السبب/الحل |
|---|---|
| الموقع يظهر صفحة Odoo قديمة بدل الواجهة | أعد تشغيل الخدمة (`systemctl restart veltnex`) — كاش الـshell |
| `502 Bad Gateway` | Odoo متوقف: `journalctl -u veltnex -n 100` |
| الـWebSocket/البث لا يعمل | تأكد من `gevent_port` و`location /websocket` في nginx |
| فشل تسجيل العميل عند OTP | بوابة SMS/IAP غير مهيّأة (الخطوة 12.3) |
| الدفع لا يعمل/لا يعود | `web.base.url` خطأ أو لا توجد بوابة دفع مفعّلة |
| فواتير PDF فارغة | `wkhtmltopdf` غير مثبّت بنسخة Qt الصحيحة |
| الـCrons لا تعمل (لا فوترة/نسخ) | `max_cron_threads` = 0 — اضبطها ≥ 1 |
| صفحة الخدمات فارغة | لا يوجد `saas.product` منشور (الخطوة 12.4) |

اللوجات: `sudo journalctl -u veltnex -f` و`/var/log/odoo/odoo.log`.
```
