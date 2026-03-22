{
    'name': 'SaaS Instance Manager',
    'version': '18.0.6.0.0',
    'category': 'SaaS',
    'summary': 'Provision and manage multi-tenant Odoo instances with Docker containers',
    'description': """
Manage your SaaS platform directly from Odoo.

Key capabilities:

- **Instance lifecycle** -- provision, start, stop, restart, suspend, and delete
  Odoo instances running in Docker containers on remote servers.
- **Automatic provisioning** -- generates docker-compose and odoo.conf files,
  creates PostgreSQL users and databases, assigns ports, and initialises the
  Odoo database, all over SSH.
- **Module management** -- fetch available modules from a Docker image, organise
  them into sellable products, and install them on running instances.
- **Product catalog integration** -- modules and products are standard Odoo
  products (product.template) so they can be quoted, sold, and invoiced through
  the regular Sales workflow.
- **Infrastructure registry** -- keep track of Docker host servers, PostgreSQL
  servers, SSH keys, and base domains used by the platform.
""",
    'author': 'SaaS Platform',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'sale', 'account'],
    'external_dependencies': {
        'python': ['paramiko', 'jinja2', 'boto3', 'google-cloud-storage'],
    },
    'data': [
        'security/saas_security.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'data/mail_templates.xml',
        'data/saas_backup_cron.xml',
        'data/saas_storage_check_cron.xml',
        'data/saas_usage_refresh_cron.xml',
        'data/saas_trial_expiry_cron.xml',
        'data/saas_recurring_billing_cron.xml',
        'views/saas_plan_views.xml',
        'views/saas_instance_views.xml',
        'views/saas_ssh_key_pair_views.xml',
        'views/saas_docker_container_views.xml',
        'views/saas_docker_server_views.xml',
        'views/saas_db_server_views.xml',
        'views/saas_domain_views.xml',
        'views/saas_odoo_version_views.xml',
        'views/product_template_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/saas_menus.xml',
        'wizards/saas_config_viewer_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'saas_core/static/src/components/container_logs/container_logs.js',
            'saas_core/static/src/components/container_logs/container_logs.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
