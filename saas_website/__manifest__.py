{
    'name': 'SaaS Website',
    'version': '18.0.2.0.0',
    'category': 'SaaS',
    'summary': 'Customer-facing website for SaaS plan selection, ordering, and instance management',
    'author': 'SaaS Platform',
    'license': 'LGPL-3',
    'depends': ['saas_core', 'website', 'portal', 'payment', 'account_payment'],
    'data': [
        'security/saas_website_security.xml',
        'security/ir.model.access.csv',
        'views/saas_services_templates.xml',
        'views/saas_portal_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'saas_website/static/src/js/subdomain_check.js',
            'saas_website/static/src/js/portal_actions.js',
        ],
    },
    'installable': True,
    'auto_install': False,
}
