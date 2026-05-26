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
    "SUDUD: The Logic of Stability. Deploy, manage, and scale your business applications on the cloud with ease.": "صدود: منطق الاستقرار. انشر تطبيقات أعمالك على السحابة، أدِرها وأوسعها بكل سهولة.",
    "Launch Your Business Today": "أطلق نشاطك اليوم",
    "Choose a ready-made solution or deploy your own project": "اختر حلًا جاهزًا أو انشر مشروعك الخاص",
    "Scale Anytime": "وسّع متى شئت",
    "99.9% Uptime": "تشغيل بنسبة ٩٩٫٩٪",
    "Your Odoo instance": "حسابك من Odoo",
    "Running": "قيد التشغيل",
    "Databases": "قواعد البيانات",
    "Daily snapshots": "النسخ اليومية",
    "Uptime": "وقت التشغيل",
    "Get Started": "ابدأ الآن",
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
    "© 2026 SUDUD. All rights reserved.": "© ٢٠٢٦ صدود. جميع الحقوق محفوظة.",
    "Create account": "إنشاء الحساب",
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
    "Try hosting for %s days free. No credit card required.": "جرّب الاستضافة مجانًا لمدة %s يومًا. لا حاجة لبطاقة ائتمان.",
    "Start free trial": "ابدأ التجربة المجانية",
    "Free Trial Active": "التجربة المجانية مفعّلة",
    "Free Trial": "تجربة مجانية",
    "Upgrade Plan": "ترقية الخطة",
    "Upgrade Now": "رقّي الآن",
    "Workers": "العمال",
    "Storage": "السعة التخزينية",
    "Monthly": "شهريًا",
    "Yearly": "سنويًا",
    "Billing Period": "دورة الفوترة",
    "Order Summary": "ملخّص الطلب",
    "Total Due Today": "المبلغ المستحق اليوم",
    "Continue to payment": "المتابعة إلى الدفع",
    "Choose a subdomain": "اختر النطاق الفرعي",
    "Subdomain": "النطاق الفرعي",
    "Add daily snapshots": "أضف النسخ اليومية",
    "Daily Backups Add-on": "خدمة النسخ اليومية الإضافية",
    "/mo": "/شهريًا",
    "Setting Up Your Instance": "جاري تجهيز حسابك",
    "This usually takes a few minutes. The page will refresh automatically.": "تستغرق هذه العملية بضع دقائق عادةً، وستُحدَّث الصفحة تلقائيًا عند الانتهاء.",
    "Payment Received — Preparing Deployment": "تم استلام الدفع — جاري إعداد النشر",
    "Your payment was confirmed. Your instance is being set up now. This page will refresh automatically.": "تم تأكيد الدفع وجاري إعداد حسابك. ستُحدَّث الصفحة تلقائيًا عند الانتهاء.",
    "Payment Submitted": "تم إرسال الدفع",
    "Your payment is being processed. Your instance will start provisioning once confirmed.": "نُعالج دفعتك حاليًا. سيبدأ تجهيز حسابك بمجرّد تأكيد الدفع.",
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
    "Creating database…": "جاري إنشاء قاعدة البيانات…",
    "Creating…": "جاري الإنشاء…",
    "Duplicating…": "جاري النسخ…",
    "Deleting…": "جاري الحذف…",
    "Resetting…": "جاري إعادة التعيين…",
    "Backing up…": "جاري إنشاء النسخة…",
    "Repairing your database…": "جاري إصلاح قاعدة البيانات…",
    "Working on it…": "جاري العمل…",
    "This page will refresh automatically when it's done. Please don't close the tab.": "ستُحدَّث الصفحة تلقائيًا عند الانتهاء. الرجاء عدم إغلاق التبويب.",
    "This usually takes about a minute. Please don't close the tab — the page will refresh automatically.": "تستغرق هذه العملية حوالي دقيقة. لا تغلق التبويب، وستُحدَّث الصفحة تلقائيًا.",
    "Please don't close the tab — the page will refresh when it's done.": "لا تغلق التبويب، وستُحدَّث الصفحة عند الانتهاء.",
    "Please don't close the tab — the page will refresh when the database is gone.": "لا تغلق التبويب، وستُحدَّث الصفحة عند انتهاء عملية الحذف.",
    "Please don't close the tab — the page will refresh when your download link is ready.": "لا تغلق التبويب، وستُحدَّث الصفحة بمجرّد أن يصبح رابط التحميل جاهزًا.",
    "Your instance will be briefly unavailable. The page will refresh automatically when it's done.": "سيتوقّف حسابك مؤقتًا. ستُحدَّث الصفحة تلقائيًا عند الانتهاء.",
    "Run upgrade": "تشغيل الإصلاح",
    "Feature to repair": "الخاصية المراد إصلاحها",
    "Minimum 6 characters.": "٦ أحرف على الأقل.",
    "New admin password": "كلمة المرور الجديدة للمسؤول",
    "Confirm new password": "تأكيد كلمة المرور الجديدة",
    "Type the database name exactly to confirm deletion.": "اكتب اسم قاعدة البيانات بالضبط لتأكيد الحذف.",
    "This cannot be undone.": "لا يمكن التراجع عن هذه العملية.",
    "The database and every file uploaded to it will be deleted permanently.": "ستُحذف قاعدة البيانات وجميع الملفات المرفوعة إليها نهائيًا.",
    "To confirm, retype the database name": "للتأكيد، أعد كتابة اسم قاعدة البيانات",
    "New database name": "اسم قاعدة البيانات الجديدة",
    "Admin login for this database:": "اسم مسؤول قاعدة البيانات هذه:",
    "Sign in with this login and the new password once the reset completes.": "سجّل الدخول باستخدام هذا الاسم وكلمة المرور الجديدة فور انتهاء إعادة التعيين.",
    "Snapshots": "النسخ الاحتياطية",
    "Snapshots for": "نسخ",
    "Daily Backups": "النسخ اليومية",
    "Enable Daily Backups": "تفعيل النسخ اليومية",
    "Disable Daily Backups": "إيقاف النسخ اليومية",
    "Daily Backups Active": "النسخ اليومية مفعّلة",
    "Daily Snapshots": "النسخ اليومية",
    "Up to 7 snapshots, oldest rolled off": "حتى ٧ نسخ، تُحذف الأقدم تلقائيًا",
    "Protect this instance with daily snapshots": "احمِ حسابك بنسخ يومية",
    "Restore": "استعادة",
    "Yes, restore": "نعم، استعد",
    "Date": "التاريخ",
    "Size": "الحجم",
    "Actions": "إجراءات",
    "Yes, replace": "نعم، استبدل",
    "Yes, disable": "نعم، أوقف",
    "Yes, confirm": "نعم، أكّد",
    "No, keep it": "لا، أبقِها",
    "Keep backups on": "ابقَ نسخ الاحتياطي مفعّلة",
    "Activate Daily Backups": "تفعيل النسخ اليومية",
    "Complete Payment": "أكمل الدفع",
    "Pay now": "ادفع الآن",
    "Already enabled.": "مفعّلة بالفعل.",
    "Daily backups are already enabled.": "النسخ اليومية مفعّلة بالفعل.",
    "Backup not available.": "النسخة الاحتياطية غير متاحة.",
    "Backup not found.": "لم يُعثر على النسخة الاحتياطية.",
    "Backup cancelled.": "تم إلغاء النسخة الاحتياطية.",
    "Restore started. Refresh in a moment.": "بدأت عملية الاستعادة. حدّث الصفحة بعد لحظات.",
    "Restore could not be started. Please try again or contact support if the problem continues.": "تعذّر بدء الاستعادة. حاول مرة أخرى أو تواصل مع الدعم إن استمرّت المشكلة.",
    "Instance must be Running or Stopped to restore.": "يجب أن يكون الحساب قيد التشغيل أو متوقفًا للاستعادة.",
    "Type the database name exactly to confirm restore.": "اكتب اسم قاعدة البيانات بالضبط لتأكيد الاستعادة.",
    "Pick a database to back up.": "اختر قاعدة البيانات المراد نسخها.",
    "Pick a database to reset.": "اختر قاعدة البيانات المراد إعادة تعيين كلمة مرورها.",
    "Both database and module are required.": "قاعدة البيانات والخاصية كلاهما مطلوبان.",
    "New password and confirmation don't match.": "كلمة المرور الجديدة وتأكيدها غير متطابقتين.",
    "Storage cannot be reduced. Current storage: %d GB.": "لا يمكن تقليل السعة التخزينية. السعة الحالية: %d جيجابايت.",
    "Please configure your plan.": "الرجاء إعداد خطتك.",
    "No changes selected.": "لا توجد تغييرات محددة.",
    "Daily backups are not available on trial plans.": "النسخ اليومية غير متاحة في خطط التجربة.",
    "Daily backups can't be disabled from the portal. Contact support if you need to make a change.": "لا يمكن إيقاف النسخ اليومية من بوابة العميل. تواصل مع الدعم إن احتجت إلى تغيير.",
    "Pending payment cancelled. You can re-enable daily backups any time.": "تم إلغاء الدفع المعلّق. يمكنك تفعيل النسخ اليومية مجددًا في أي وقت.",
    "Restore failed — see instance logs.": "فشلت الاستعادة — راجع سجل النشاط.",
    "We couldn't generate the download link right now. Please try again in a moment, or contact support.": "تعذّر توليد رابط التحميل الآن. أعد المحاولة لاحقًا أو تواصل مع الدعم.",
    "This operation didn't finish in time. If the database isn't there yet, dismiss this and try again.": "لم تنتهِ العملية في الوقت المتوقّع. إن لم تظهر قاعدة البيانات بعد، أغلق هذا الإشعار وأعد المحاولة.",
    "Database '%s' does not exist on this instance.": "قاعدة البيانات «%s» غير موجودة في هذا الحساب.",
    "Database '%s' does not belong to this instance.": "قاعدة البيانات «%s» لا تنتمي إلى هذا الحساب.",
    "A backup of '%s' is still in progress. Wait for it to finish before starting another.": "نسخة احتياطية لـ«%s» قيد التنفيذ. انتظر انتهاءها قبل بدء أخرى.",
    "Backup of '%(db)s' started. Refresh in a minute — a download link valid for 24 hours will appear once ready.": "بدأت نسخة «%(db)s». حدّث الصفحة بعد دقيقة — سيظهر رابط تحميل صالح لمدة ٢٤ ساعة عند الجهوزية.",
    "Replaced by a newer on-demand backup request.": "تم استبدالها بطلب نسخة فورية أحدث.",
    "Instance must be running to create a backup.": "يجب أن يكون الحساب قيد التشغيل لإنشاء نسخة احتياطية.",
    "On-demand backups are available for hosting instances only.": "النسخ الاحتياطية الفورية متاحة لحسابات الاستضافة فقط.",
    "Admin password reset for '%(db)s'. Sign in as '%(login)s' with your new password.": "تم إعادة تعيين كلمة مرور المسؤول لـ«%(db)s». سجّل الدخول باسم «%(login)s» بكلمة المرور الجديدة.",
    "Repairing '%(module)s' on '%(db)s'… your instance will come back up automatically. This page auto-refreshes.": "جاري إصلاح «%(module)s» في «%(db)s»… سيعود حسابك تلقائيًا. ستُحدَّث الصفحة تلقائيًا.",
    "Deleting database '%s'…": "جاري حذف قاعدة البيانات «%s»…",
    "Duplicating to '%s'… refresh to see progress.": "جاري النسخ إلى «%s»… حدّث الصفحة لمتابعة التقدّم.",
    "Creating database '%s'… this takes about a minute. Refresh the page to see its progress.": "جاري إنشاء قاعدة البيانات «%s»… تستغرق حوالي دقيقة. حدّث الصفحة لمتابعة التقدّم.",
    "Invoices": "الفواتير",
    "Recent invoices": "أحدث الفواتير",
    "Paid": "مدفوعة",
    "Unpaid": "غير مدفوعة",
    "Download": "تحميل",
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
    "Loading…": "جاري التحميل…",
    "Refresh": "تحديث",
    "Back to Instance": "العودة إلى الحساب",
    "Back to top": "العودة إلى الأعلى",
    "Other": "أخرى",
    "SUDUD Hosting — Customer Manual": "استضافة صدود — دليل العميل",
    "A complete, step-by-step guide to every screen, every button and every situation you'll encounter as a SUDUD Hosting customer. Nothing assumed — if it's a click you'll make, it's in here.": "دليل شامل خطوة بخطوة لكلّ شاشة وكلّ زرّ وكلّ حالة قد تواجهك كعميل لاستضافة صدود. لا شيء مفترض — إن كانت نقرة ستضغطها، فهي هنا.",
    "How to use this manual.": "كيفية استخدام هذا الدليل.",
    "The table of contents on the left is sticky — it follows you as you scroll. Click any entry to jump straight to that step. Every section is self-contained, so you can read only the part you need.": "قائمة المحتويات على اليسار ثابتة — تتبعك أثناء التمرير. اضغط أيّ بند للقفز مباشرةً إلى الخطوة المعنيّة. كلّ قسم مكتفٍ بذاته، فيمكنك قراءة الجزء الذي تحتاجه فقط.",
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
    "1.1 What is SUDUD Hosting?": "١٫١ ما هي استضافة صدود؟",
    "1.2 Signing up for an account": "١٫٢ إنشاء حساب",
    "1.3 Signing in": "١٫٣ تسجيل الدخول",
    "1.4 Forgot your password": "١٫٤ نسيت كلمة المرور",
    "1.5 Free trial overview": "١٫٥ نظرة على التجربة المجانية",
    "2.1 Choosing your subdomain": "٢٫١ اختيار النطاق الفرعي",
    "2.2 The plan builder": "٢٫٢ منشئ الخطة",
    "2.3 Daily snapshots add-on": "٢٫٣ خدمة النسخ اليومية الإضافية",
    "2.4 Custom Python packages (advanced, optional)": "٢٫٤ حزم Python مخصّصة (متقدّم، اختياري)",
    "2.5 GitHub repositories (advanced, optional)": "٢٫٥ مستودعات GitHub (متقدّم، اختياري)",
    "2.6 Checkout and payment": "٢٫٦ الدفع وإتمام الطلب",
    "2.7 What happens after payment": "٢٫٧ ما يحدث بعد الدفع",
    "3.1 Layout tour": "٣٫١ جولة في تصميم الصفحة",
    "3.2 Status pill reference": "٣٫٢ مرجع شارات الحالة",
    "3.3 Quick-action buttons": "٣٫٣ أزرار الإجراءات السريعة",
    "3.4 In-flight banners": "٣٫٤ إشعارات التشغيل الفوري",
    "4.1 Instance vs database — what's the difference?": "٤٫١ الحساب مقابل قاعدة البيانات — ما الفرق؟",
    "4.2 Getting to the Databases page": "٤٫٢ الوصول إلى صفحة قواعد البيانات",
    "4.3 Database naming rules": "٤٫٣ قواعد تسمية قواعد البيانات",
    "4.4 Create a database": "٤٫٤ إنشاء قاعدة بيانات",
    "4.5 Open a database / sign in": "٤٫٥ فتح قاعدة بيانات / تسجيل الدخول",
    "4.6 Duplicate a database": "٤٫٦ نسخ قاعدة بيانات",
    "4.7 Reset the admin password": "٤٫٧ إعادة تعيين كلمة مرور المسؤول",
    "4.8 Repair Feature (error-page recovery)": "٤٫٨ إصلاح خاصية (التعافي من صفحات الخطأ)",
    "4.9 Delete a database": "٤٫٩ حذف قاعدة بيانات",
    "5.1 The two kinds of backup": "٥٫١ نوعا النسخ الاحتياطية",
    "5.2 Backup Now — on-demand per-database backup": "٥٫٢ «أنشئ نسخة الآن» — نسخة فورية لقاعدة بيانات واحدة",
    "5.3 Daily snapshots — overview": "٥٫٣ النسخ اليومية — نظرة عامة",
    "5.4 Enabling daily snapshots": "٥٫٤ تفعيل النسخ اليومية",
    "5.5 Viewing your snapshots": "٥٫٥ عرض النسخ المتوفّرة",
    "5.6 Restoring from a snapshot": "٥٫٦ الاستعادة من نسخة",
    "6.1 Viewing your plan": "٦٫١ عرض خطتك",
    "6.2 Upgrading (more resources)": "٦٫٢ الترقية (موارد أكبر)",
    "6.3 Downgrading (fewer resources)": "٦٫٣ التخفيض (موارد أقل)",
    "6.4 Renewals & billing cycles": "٦٫٤ التجديد ودورات الفوترة",
    "6.5 Failed payments": "٦٫٥ المدفوعات الفاشلة",
    "8.1 How cancellation works": "٨٫١ كيف يعمل الإلغاء",
    "8.2 What gets deleted vs retained": "٨٫٢ ما الذي يُحذف وما الذي يُحفظ",
    "8.3 Reactivating a cancelled instance": "٨٫٣ إعادة تفعيل حساب ملغى",
    "8.4 Restoring your retained snapshot": "٨٫٤ استعادة النسخة المحفوظة",
    "SUDUD Hosting gives you a private Odoo instance on your own subdomain (e.g.": "تمنحك استضافة صدود حسابًا خاصًا من Odoo على نطاقك الفرعي (مثل",
    ") with full admin access. Think of it as renting a ready-to-use Odoo environment that we keep running 24/7 on cloud infrastructure — you get the keys, we handle the hosting.": ") بصلاحيات مسؤول كاملة. تخيّله كأنّك تستأجر بيئة Odoo جاهزة للاستخدام نُبقيها قيد التشغيل ٢٤/٧ على بنية تحتية سحابية — أنت تحصل على المفاتيح ونحن نتولّى الاستضافة.",
    "What's included with every hosting instance:": "ما يتضمّنه كلّ حساب استضافة:",
    "A private subdomain": "نطاق فرعي خاص",
    "like": "مثل",
    "secured with a Let's Encrypt SSL certificate (the green padlock in the browser).": "مؤمَّن بشهادة SSL من Let's Encrypt (القفل الأخضر في المتصفّح).",
    "One or more Odoo databases": "قاعدة بيانات Odoo واحدة أو أكثر",
    "you create on demand. You decide how many (within your plan's storage limits) and what they're called.": "تُنشئها عند الطلب. أنت من يقرّر عددها (ضمن سعة خطّتك) وأسماءها.",
    "Full admin rights": "صلاحيات مسؤول كاملة",
    "inside every database — install apps, configure users, customize fields, the works.": "داخل كلّ قاعدة بيانات — ثبّت التطبيقات، أعدّ المستخدمين، خصّص الحقول، وكلّ شيء.",
    "Your custom modules": "وحداتك المخصّصة",
    "can be deployed via a GitHub repository link — we pull and install them for you.": "يمكن نشرها عبر رابط مستودع GitHub — نقوم بسحبها وتثبيتها نيابةً عنك.",
    "Optional daily snapshots": "نسخ يومية اختيارية",
    "of everything on the instance, plus the ability to take ad-hoc backups of any single database on demand.": "لكلّ ما في الحساب، بالإضافة إلى إمكانية إنشاء نسخ فورية لأيّ قاعدة بيانات عند الحاجة.",
    "What we manage so you don't have to:": "ما نتولّى إدارته نيابةً عنك:",
    "Server provisioning and patching.": "تجهيز الخوادم وتحديثها.",
    "The web server / proxy and SSL certificate renewal.": "خادم الويب / البروكسي وتجديد شهادة SSL.",
    "The Odoo Docker image and Python dependencies.": "صورة Odoo والاعتماديات.",
    "The PostgreSQL database server.": "خادم قاعدة بيانات PostgreSQL.",
    "Backup storage in encrypted cloud storage.": "تخزين النسخ الاحتياطية في تخزين سحابي مشفَّر.",
    "You need a free account before you can buy anything or start a trial. Sign-up takes about a minute.": "تحتاج إلى حساب مجاني قبل شراء أيّ شيء أو بدء التجربة. التسجيل يستغرق دقيقة تقريبًا.",
    "From any public page, click": "من أيّ صفحة عامّة، اضغط",
    "in the top right of the navigation bar.": "في أعلى يمين شريط التنقّل.",
    "On the sign-up form, enter:": "في نموذج التسجيل، أدخل:",
    "— used on your invoices, so put your real name or company name.": "— يُستخدم على فواتيرك، فضع اسمك أو اسم شركتك الحقيقي.",
    "— where every notification (sign-in links, invoices, snapshot status, password resets) is delivered. Use a real address you'll actually read.": "— حيث تصل كلّ الإشعارات (روابط الدخول، الفواتير، حالة النسخ، إعادة تعيين كلمات المرور). استخدم عنوانًا حقيقيًّا ستقرأه فعلًا.",
    "— at least 8 characters. The strength meter below the field turns from red to green as you type; aim for at least \"Strong\".": "— ٨ أحرف على الأقل. يتحوّل مؤشّر القوّة أسفل الحقل من الأحمر إلى الأخضر أثناء الكتابة؛ استهدف على الأقل «قوي».",
    "Pill": "الشارة",
    "What it means": "ما تعنيه",
    "What you can do": "ما يمكنك فعله",
    "Your instance is up and serving traffic.": "حسابك يعمل ويستقبل الطلبات.",
    "Open it, manage databases, take backups, change plan, stop it.": "افتحه، أدِر قواعد البيانات، أنشئ نسخًا، غيّر الخطة، أوقفه.",
    "We're setting up infrastructure (deploy, restore or repair).": "نقوم بإعداد البنية التحتية (نشر أو استعادة أو إصلاح).",
    "Wait — the page auto-refreshes when it's done.": "انتظر — ستُحدَّث الصفحة تلقائيًا عند الانتهاء.",
    "You stopped the instance manually. No traffic served.": "أوقفت الحساب يدويًا. لا يستقبل أيّ طلبات.",
    "Start it back up. Databases stay intact.": "أعد تشغيله. تبقى قواعد البيانات سليمة.",
    "Auto-suspended due to an overdue payment or expired trial.": "موقوف تلقائيًا بسبب دفعة متأخّرة أو انتهاء التجربة.",
    "Pay the outstanding invoice (or upgrade from trial) to reactivate.": "ادفع الفاتورة المستحقّة (أو رقِّ من التجربة) لإعادة التفعيل.",
    "Order placed, payment not yet confirmed.": "تم وضع الطلب، ولم يتأكّد الدفع بعد.",
    "Wait for payment confirmation, or pay the invoice manually.": "انتظر تأكيد الدفع، أو ادفع الفاتورة يدويًا.",
    "Deployment failed after several auto-retries.": "فشل النشر بعد عدّة محاولات تلقائية.",
    "Contact support — we'll investigate.": "تواصل مع الدعم — سنحقّق في الأمر.",
    "Cancelled. Most data deleted; the most recent snapshot is retained.": "ملغى. حُذف معظم البيانات؛ تُحفظ أحدث نسخة.",
    "Where to find them": "أين تجدها",
    "Paying an unpaid invoice": "دفع فاتورة غير مدفوعة",
    "Downloading a PDF": "تحميل PDF",
    "What each charge means": "ماذا تعني كلّ رسوم",
    "Frequently asked questions": "الأسئلة الشائعة",
    "My Odoo shows an error page on every URL": "يُظهر حسابي صفحة خطأ على كلّ رابط",
    "I can't sign in to my Odoo": "لا أستطيع تسجيل الدخول إلى Odoo",
    "My instance is suspended": "حسابي موقوف",
    "My page didn't refresh on its own": "لم تتحدّث صفحتي تلقائيًا",
    "My download link doesn't work": "رابط التحميل لا يعمل",
    "A snapshot is \"missing\"": "إحدى النسخ «مفقودة»",
    "I created a database with the wrong name": "أنشأت قاعدة بيانات باسم خاطئ",
    "I want to move data between instances": "أريد نقل البيانات بين الحسابات",
    "How do I report a bug or get help?": "كيف أبلغ عن خلل أو أطلب المساعدة؟",
    "How many databases can I have on one instance?": "كم قاعدة بيانات يمكنني وضعها في حساب واحد؟",
    "Can I install any Odoo app I want?": "هل أستطيع تثبيت أيّ تطبيق Odoo أريده؟",
    "Can I use a custom domain instead of the subdomain?": "هل يمكنني استخدام نطاق مخصّص بدلًا من النطاق الفرعي؟",
    "Where is my data physically stored?": "أين تُخزَّن بياناتي فعليًا؟",
    "Are my backups encrypted?": "هل نُسخي الاحتياطية مشفّرة؟",
    "Can someone else access my Odoo with my subdomain?": "هل يستطيع شخص آخر الوصول إلى Odoo الخاص بي عبر نطاقي؟",
    "What's the difference between Backup Now and a snapshot?": "ما الفرق بين «أنشئ نسخة الآن» والنسخة؟",
    "How do I get a refund?": "كيف أحصل على استرداد؟",
    "Can I have more than one instance?": "هل يمكنني الحصول على أكثر من حساب؟",
    "Instance": "الحساب",
    "Database": "قاعدة البيانات",
    "Worker": "عامل",
    "Snapshot": "نسخة",
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
    "Save %s%%": "وفّر %s٪",
    "Welcome": "مرحبًا",
    "Name": "الاسم",
    "Settings": "الإعدادات",
    "Account": "الحساب",
    "Logout": "تسجيل الخروج",
    "Sign in": "تسجيل الدخول",
    "Sign up": "إنشاء حساب",
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
        "[saas_website] apply_arabic_translations: scanning %d "
        "view(s) against a %d-entry dictionary.",
        len(views), len(ordered),
    )

    applied = 0
    skipped_no_match = 0
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
            skipped_no_match += 1
            continue

        try:
            view.with_context(lang='ar_001').write({'arch_db': translated})
            applied += 1
            _logger.info(
                "[saas_website]   ✓ %s (id=%s) — Arabic arch_db written.",
                view.xml_id or view.id, view.id,
            )
        except Exception:
            _logger.exception(
                "[saas_website]   ✗ %s (id=%s) — write FAILED.",
                view.xml_id or view.id, view.id,
            )

    _logger.info(
        "[saas_website] Arabic translations applied to %d view(s); "
        "%d view(s) had no matching strings.",
        applied, skipped_no_match,
    )
