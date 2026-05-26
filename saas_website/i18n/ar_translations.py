"""Arabic translations applied programmatically to every saas_website view.

Why this exists instead of relying on the .po file alone: Odoo's PO
loader uses the ``#:`` reference on each msgid to decide which view to
apply the translation to. Writing accurate per-view references for
hundreds of strings is impractical when we're delivering translations
in one shot, so we keep the .po file as documentation / fallback and
apply translations to every view that contains the source text using
this dictionary. Idempotent — re-running just re-applies the same
text.

To extend: add an (english, arabic) pair to ``TRANSLATIONS`` and run
the post-install hook (or upgrade the module to re-fire the migration
script). Strings here MUST EXACTLY MATCH the English source — same
whitespace, same casing, same punctuation. Multi-line strings should
preserve their newlines and indentation.
"""

# Format: english source → Arabic translation.
TRANSLATIONS = {
    # ===== Header / nav =====
    "Services": "الخدمات",
    "Hosting": "الاستضافة",
    "Docs": "التوثيق",
    "Documentation": "التوثيق",
    "Sign Up": "إنشاء حساب",
    "Sign In": "تسجيل الدخول",
    "Sign Out": "تسجيل الخروج",
    "Profile": "الملف الشخصي",
    "My Instances": "حساباتي",
    "Backend": "لوحة الإدارة",

    # ===== Hero / home =====
    "Launch Your Business Today": "أطلق نشاطك اليوم",
    "Choose a ready-made solution or deploy your own project":
        "اختر حلًا جاهزًا أو انشر مشروعك الخاص",
    "Scale Anytime": "وسّع متى شئت",
    "99.9% Uptime": "تشغيل بنسبة ٩٩٫٩٪",
    "Your Odoo instance": "حسابك من Odoo",
    "Running": "قيد التشغيل",
    "Databases": "قواعد البيانات",
    "Daily snapshots": "النسخ اليومية",
    "Uptime": "وقت التشغيل",
    "Get Started": "ابدأ الآن",

    # ===== Footer =====
    "Product": "المنتج",
    "Pricing": "الأسعار",
    "Features": "المميزات",
    "Company": "الشركة",
    "About": "من نحن",
    "Blog": "المدوّنة",
    "Careers": "الوظائف",
    "Support": "الدعم",
    "Help Center": "مركز المساعدة",
    "Contact": "اتصل بنا",
    "Legal": "قانوني",
    "Privacy": "الخصوصية",
    "Terms": "الشروط",
    "Security": "الأمان",

    # ===== Trial =====
    "Start free trial": "ابدأ التجربة المجانية",
    "Free Trial Active": "التجربة المجانية مفعّلة",
    "Free Trial": "تجربة مجانية",
    "Upgrade Plan": "ترقية الخطة",
    "Upgrade Now": "رقّي الآن",

    # ===== Hosting plan builder =====
    "Workers": "العمال",
    "Storage": "السعة التخزينية",
    "Monthly": "شهريًا",
    "Yearly": "سنويًا",
    "Billing Period": "دورة الفوترة",
    "Order Summary": "ملخّص الطلب",
    "Total Due Today": "المبلغ المستحق اليوم",
    "Continue to payment": "المتابعة إلى الدفع",
    "Subdomain": "النطاق الفرعي",
    "Add daily snapshots": "أضف النسخ اليومية",
    "Daily Backups Add-on": "خدمة النسخ اليومية الإضافية",

    # ===== Sign up / in =====
    "Create account": "إنشاء الحساب"  ,
    "Full name": "الاسم الكامل",
    "Work email": "البريد الإلكتروني للعمل",
    "Email": "البريد الإلكتروني",
    "Password": "كلمة المرور",
    "Confirm password": "تأكيد كلمة المرور",
    "Forgot password?": "نسيت كلمة المرور؟",
    "Send reset link": "إرسال رابط الاستعادة",
    "Already have an account?": "لديك حساب بالفعل؟",
    "Don't have an account?": "ليس لديك حساب؟",
    "99.9% uptime SLA": "اتفاقية مستوى خدمة بنسبة تشغيل ٩٩٫٩٪",

    # ===== Provisioning =====
    "Setting Up Your Instance": "جاري تجهيز حسابك",
    "This usually takes a few minutes. The page will refresh automatically.":
        "تستغرق هذه العملية بضع دقائق عادةً، وستُحدَّث الصفحة تلقائيًا عند الانتهاء.",
    "Payment Submitted": "تم إرسال الدفع",
    "Payment Received — Preparing Deployment":
        "تم استلام الدفع — جاري إعداد النشر",
    "Your payment is being processed. Your instance will start provisioning once confirmed.":
        "نُعالج دفعتك حاليًا. سيبدأ تجهيز حسابك بمجرّد تأكيد الدفع.",
    "Your payment was confirmed. Your instance is being set up now. This page will refresh automatically.":
        "تم تأكيد الدفع وجاري إعداد حسابك. ستُحدَّث الصفحة تلقائيًا عند الانتهاء.",

    # ===== Instance dashboard =====
    "Open Instance": "افتح الحساب",
    "Open": "افتح",
    "Manage Databases": "إدارة قواعد البيانات",
    "View Snapshots": "عرض النسخ",
    "View Activity": "عرض النشاط",
    "Start": "تشغيل",
    "Stop": "إيقاف",
    "Restart": "إعادة التشغيل",
    "Change Plan": "تغيير الخطة",
    "Reactivate Instance": "إعادة تفعيل الحساب",
    "Plan": "الخطة",
    "Service": "الخدمة",
    "Domain": "النطاق",
    "Status": "الحالة",
    "Stopped": "متوقف",
    "Suspended": "موقوف",
    "Provisioning": "قيد التجهيز",
    "Pending Payment": "بانتظار الدفع",
    "Failed": "فشل",
    "Cancelled": "ملغى",
    "Cancelled by Client": "ملغى من قبل العميل",
    "Draft": "مسودة",

    # ===== Databases page =====
    "Create Database": "إنشاء قاعدة بيانات",
    "Database name": "اسم قاعدة البيانات",
    "Admin login": "بريد المسؤول",
    "Admin password": "كلمة مرور المسؤول",
    "Language": "اللغة",
    "Create": "إنشاء",
    "Cancel": "إلغاء",
    "Duplicate": "نسخ",
    "Delete": "حذف",
    "Delete permanently": "حذف نهائي",
    "Reset Password": "إعادة تعيين كلمة المرور",
    "Reset password": "إعادة تعيين كلمة المرور",
    "Repair Feature": "إصلاح خاصية",
    "Backup Now": "أنشئ نسخة الآن",
    "Download Backup": "تحميل النسخة",
    "Backing up": "جاري النسخ",
    "Backup ready": "النسخة جاهزة",
    "Discard": "تجاهل",
    "Run upgrade": "تشغيل الإصلاح",
    "Feature to repair": "الخاصية المراد إصلاحها",
    "Minimum 6 characters.": "٦ أحرف على الأقل.",
    "New admin password": "كلمة المرور الجديدة للمسؤول",
    "Confirm new password": "تأكيد كلمة المرور الجديدة",
    "New database name": "اسم قاعدة البيانات الجديدة",

    # ===== Snapshots / backups =====
    "Snapshots": "النسخ الاحتياطية",
    "Daily Backups": "النسخ اليومية",
    "Enable Daily Backups": "تفعيل النسخ اليومية",
    "Daily Backups Active": "النسخ اليومية مفعّلة",
    "Daily Snapshots": "النسخ اليومية",
    "Restore": "استعادة",
    "Yes, restore": "نعم، استعد",
    "Date": "التاريخ",
    "Size": "الحجم",
    "Actions": "إجراءات",
    "Activate Daily Backups": "تفعيل النسخ اليومية",
    "Complete Payment": "أكمل الدفع",
    "Pay now": "ادفع الآن",

    # ===== Confirmation modals =====
    "Yes, replace": "نعم، استبدل",
    "Yes, disable": "نعم، أوقف",
    "Yes, confirm": "نعم، أكّد",
    "No, keep it": "لا، أبقِها",

    # ===== Common UI =====
    "Back": "رجوع",
    "Next": "التالي",
    "Save": "حفظ",
    "Edit": "تعديل",
    "Yes": "نعم",
    "No": "لا",
    "OK": "حسنًا",
    "Close": "إغلاق",
    "Confirm": "تأكيد",
    "Submit": "إرسال",
    "Refresh": "تحديث",
    "Back to Instance": "العودة إلى الحساب",
    "Back to top": "العودة إلى الأعلى",
    "Other": "أخرى",

    # ===== Invoices =====
    "Invoices": "الفواتير",
    "Recent invoices": "أحدث الفواتير",
    "Paid": "مدفوعة",
    "Unpaid": "غير مدفوعة",
    "Download": "تحميل",

    # ===== Docs page section headings =====
    "SUDUD Hosting — Customer Manual": "استضافة صدود — دليل العميل",
    "On this page": "في هذه الصفحة",
    "Part 1 — Getting started": "الجزء ١ — البداية",
    "Part 2 — Buying a hosting instance": "الجزء ٢ — شراء حساب استضافة",
    "Part 3 — Your instance dashboard": "الجزء ٣ — لوحة تحكّم حسابك",
    "Part 4 — Managing databases": "الجزء ٤ — إدارة قواعد البيانات",
    "Part 5 — Backups & snapshots": "الجزء ٥ — النسخ الاحتياطية",
    "Part 6 — Subscription & plan": "الجزء ٦ — الاشتراك والخطة",
    "Part 7 — Stop / start": "الجزء ٧ — الإيقاف والتشغيل",
    "Part 8 — Cancellation & reactivation": "الجزء ٨ — الإلغاء وإعادة التفعيل",
    "Part 9 — Invoices & payments": "الجزء ٩ — الفواتير والمدفوعات",
    "Part 10 — Activity logs": "الجزء ١٠ — سجلّات النشاط",
    "Part 11 — Troubleshooting": "الجزء ١١ — حلّ المشكلات",
    "Part 12 — FAQ": "الجزء ١٢ — الأسئلة الشائعة",
    "Part 13 — Glossary": "الجزء ١٣ — مسرد المصطلحات",
    "Instance": "الحساب",
    "Database": "قاعدة البيانات",
    "Worker": "عامل",
    "Snapshot": "نسخة",

    # ===== Misc =====
    "Required": "مطلوب",
    "Optional": "اختياري",
    "Recommended": "موصى به",
    "Free": "مجاني",
    "Per month": "شهريًا",
    "Per year": "سنويًا",
    "Total": "الإجمالي",
    "Subtotal": "المجموع الفرعي",
    "Tax": "الضريبة",
    "Discount": "الخصم",
    "Name": "الاسم",
    "Settings": "الإعدادات",
    "Account": "الحساب",
    "Logout": "تسجيل الخروج",
}


def apply_arabic_translations(env):
    """Walk every saas_website view and write Arabic translations
    into its ``arch_db`` JSONB for the strings we know about.

    Odoo stores translatable view content as JSONB keyed by language
    code (e.g. ``{'en_US': '<...>', 'ar_001': '<...>'}``). Setting
    ``arch_db`` while the cursor's context language is ``ar_001``
    writes the new value into the Arabic slot only — the English
    slot stays untouched.

    For each view we:
      1. Read the English source ``arch_db``.
      2. Replace every known English source with its Arabic
         translation (string replacement; safe because translatable
         strings in QWeb tend to be unique HTML text nodes).
      3. Save the result with the cursor in Arabic mode.

    Idempotent: re-running just re-applies the same replacements.
    """
    import logging
    _logger = logging.getLogger(__name__)

    if not TRANSLATIONS:
        return

    # Sort longer keys first so e.g. "Reset Password" is replaced
    # before "Reset" — avoids partial-substring collisions.
    ordered = sorted(TRANSLATIONS.items(), key=lambda kv: -len(kv[0]))

    # Pull every QWeb view we ship from saas_website plus any view
    # that inherits from one of ours (we want our portal templates
    # too).
    Module = env['ir.module.module']
    mod = Module.search([('name', '=', 'saas_website')], limit=1)
    if not mod:
        return

    IrModelData = env['ir.model.data']
    view_ids = IrModelData.search([
        ('module', '=', 'saas_website'),
        ('model', '=', 'ir.ui.view'),
    ]).mapped('res_id')
    if not view_ids:
        return

    View = env['ir.ui.view'].sudo()
    views = View.browse(view_ids).exists()
    _logger.info(
        "Applying Arabic translations to %d saas_website views.",
        len(views),
    )

    applied = 0
    for view in views:
        # Read the English source. ``arch_db`` returned with the
        # ``en_US`` context is the canonical source text.
        try:
            source = view.with_context(lang='en_US').arch_db or ''
        except Exception:
            _logger.exception(
                "Could not read arch_db for view %s — skipping.",
                view.xml_id or view.id,
            )
            continue
        if not source:
            continue

        # Build the Arabic version by replacing every known string.
        translated = source
        for en, ar in ordered:
            if en in translated:
                translated = translated.replace(en, ar)

        if translated == source:
            # No translatable string found in this view — skip.
            continue

        try:
            view.with_context(lang='ar_001').write({'arch_db': translated})
            applied += 1
        except Exception:
            _logger.exception(
                "Could not write Arabic arch_db for view %s.",
                view.xml_id or view.id,
            )

    _logger.info(
        "Arabic translations applied to %d view(s).",
        applied,
    )
