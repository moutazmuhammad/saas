{
    'name': 'SaaS Website',
    'version': '18.0.5.1.0',
    'category': 'SaaS',
    'summary': 'Customer-facing website for SaaS plan selection, ordering, and instance management',
    'author': 'SaaS Platform',
    'license': 'LGPL-3',
    'depends': ['saas_core', 'website', 'portal', 'payment', 'account_payment'],
    'data': [
        'security/saas_website_security.xml',
        'security/ir.model.access.csv',
        'data/mail_templates.xml',
        'views/saas_frontend_layout.xml',
        'views/saas_login_templates.xml',
        'views/saas_services_templates.xml',
        'views/saas_hosting_templates.xml',
        'views/saas_registration_templates.xml',
        'views/saas_invoice_templates.xml',
        'views/saas_portal_templates.xml',
        'views/saas_docs_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'saas_website/static/src/css/cloudodoo.css',
            'saas_website/static/src/css/cloudodoo_rtl.css',
            'saas_website/static/src/js/cloudodoo_app.js',
            'saas_website/static/src/js/subdomain_check.js',
            'saas_website/static/src/js/portal_actions.js',
            'saas_website/static/src/js/portal_logs.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    # Activate Arabic on FIRST install. For existing installations
    # being upgraded to this version, ``migrations/18.0.5.1.0/post-update.py``
    # does the same work. Both call into ``_activate_arabic`` in
    # __init__.py so behaviour stays in one place.
    'post_init_hook': '_activate_arabic',
}
