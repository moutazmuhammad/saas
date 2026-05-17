from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    saas_default_instance_starting_port = fields.Integer(
        string='Default Starting Port',
        config_parameter='saas_master.default_instance_starting_port',
        default=32000,
        help='First port number in the range used for auto-assigning HTTP and '
             'longpolling ports to new instances. Ports are allocated in pairs '
             '(HTTP, longpolling) starting from this value.',
    )

    # ========== Resource Usage ==========
    saas_resource_usage_multiplier = fields.Float(
        string='Resource Usage Multiplier',
        config_parameter='saas_master.resource_usage_multiplier',
        default=2.0,
        help='Multiplier applied to CPU and RAM measurements to account for '
             'shared DB server usage that cannot be measured per instance. '
             'E.g. 2.0 means displayed usage = measured × 2.',
    )

    # ========== Free Trial ==========
    saas_trial_days = fields.Integer(
        string='Free Trial Duration (Days)',
        config_parameter='saas_master.trial_days',
        default=14,
        help='Number of days for the free trial period. '
             'After expiry the instance is suspended until the client pays.',
    )

    # ========== Custom Plan Pricing ==========
    saas_worker_price = fields.Float(
        string='Price per Worker',
        config_parameter='saas_master.worker_price',
        default=0.0,
        help='Monthly price per Odoo worker for custom plan configurations. '
             'Used in the custom plan builder on the pricing page.',
    )
    saas_storage_price_per_gb = fields.Float(
        string='Price per GB (Custom Plan)',
        config_parameter='saas_master.storage_price_per_gb',
        default=0.0,
        help='Monthly price per GB of storage for custom plan configurations. '
             'Used in the custom plan builder on the pricing page.',
    )
    saas_custom_plan_min_workers = fields.Integer(
        string='Min Workers (Custom)',
        config_parameter='saas_master.custom_plan_min_workers',
        default=2,
        help='Minimum number of workers selectable in the custom plan builder.',
    )
    saas_custom_plan_max_workers = fields.Integer(
        string='Max Workers (Custom)',
        config_parameter='saas_master.custom_plan_max_workers',
        default=8,
        help='Maximum number of workers selectable in the custom plan builder.',
    )
    saas_custom_plan_min_storage = fields.Integer(
        string='Min Storage GB (Custom)',
        config_parameter='saas_master.custom_plan_min_storage',
        default=5,
        help='Minimum storage (GB) selectable in the custom plan builder.',
    )
    saas_custom_plan_max_storage = fields.Integer(
        string='Max Storage GB (Custom)',
        config_parameter='saas_master.custom_plan_max_storage',
        default=200,
        help='Maximum storage (GB) selectable in the custom plan builder.',
    )

    # --- Resource allocation per worker ---
    saas_custom_plan_cpu_per_worker = fields.Float(
        string='CPU per Worker',
        config_parameter='saas_master.custom_plan_cpu_per_worker',
        default=0.5,
        help='vCPU allocated per worker in custom plans (e.g. 0.5 = half a core per worker).',
    )
    saas_custom_plan_ram_per_worker = fields.Integer(
        string='RAM per Worker (MB)',
        config_parameter='saas_master.custom_plan_ram_per_worker',
        default=512,
        help='RAM in MB allocated per worker in custom plans (e.g. 512 = 512MB per worker).',
    )
    saas_custom_plan_min_backups = fields.Integer(
        string='Min Backups (smallest plan)',
        config_parameter='saas_master.custom_plan_min_backups',
        default=3,
        help='Backups for the smallest custom plan (fewest workers + lowest storage).',
    )
    saas_custom_plan_max_backups = fields.Integer(
        string='Max Backups (largest plan)',
        config_parameter='saas_master.custom_plan_max_backups',
        default=14,
        help='Backups for the largest custom plan (most workers + highest storage).',
    )
    saas_custom_plan_users_per_worker_min = fields.Integer(
        string='Min Users per Worker',
        config_parameter='saas_master.custom_plan_users_per_worker_min',
        default=6,
        help='Minimum concurrent users each worker can handle (light usage). '
             'Used in the recommendation display.',
    )
    saas_custom_plan_users_per_worker_max = fields.Integer(
        string='Max Users per Worker',
        config_parameter='saas_master.custom_plan_users_per_worker_max',
        default=10,
        help='Maximum concurrent users each worker can handle (heavy usage). '
             'Used in the recommendation display.',
    )
    saas_custom_plan_yearly_discount_pct = fields.Integer(
        string='Yearly Discount %',
        config_parameter='saas_master.custom_plan_yearly_discount_pct',
        default=20,
        help='Percentage discount applied when yearly billing is selected for custom plans.',
    )

    # ========== Hosting Plan Builder ==========
    saas_hosting_worker_price = fields.Float(
        string='Hosting: Price per Worker',
        config_parameter='saas_master.hosting_worker_price',
        default=10.0,
        help='Monthly price per worker for self-managed hosting plans.',
    )
    saas_hosting_storage_price_per_gb = fields.Float(
        string='Hosting: Price per GB',
        config_parameter='saas_master.hosting_storage_price_per_gb',
        default=0.3,
        help='Monthly price per GB of storage for self-managed hosting plans.',
    )
    saas_hosting_min_workers = fields.Integer(
        string='Hosting: Min Workers',
        config_parameter='saas_master.hosting_min_workers',
        default=2,
    )
    saas_hosting_max_workers = fields.Integer(
        string='Hosting: Max Workers',
        config_parameter='saas_master.hosting_max_workers',
        default=8,
    )
    saas_hosting_min_storage = fields.Integer(
        string='Hosting: Min Storage GB',
        config_parameter='saas_master.hosting_min_storage',
        default=5,
    )
    saas_hosting_max_storage = fields.Integer(
        string='Hosting: Max Storage GB',
        config_parameter='saas_master.hosting_max_storage',
        default=200,
    )
    saas_hosting_cpu_per_worker = fields.Float(
        string='Hosting: CPU per Worker',
        config_parameter='saas_master.hosting_cpu_per_worker',
        default=0.5,
    )
    saas_hosting_ram_per_worker = fields.Integer(
        string='Hosting: RAM per Worker (MB)',
        config_parameter='saas_master.hosting_ram_per_worker',
        default=512,
    )
    saas_hosting_yearly_discount_pct = fields.Integer(
        string='Hosting: Yearly Discount %',
        config_parameter='saas_master.hosting_yearly_discount_pct',
        default=20,
    )
    saas_hosting_min_backups = fields.Integer(
        string='Hosting: Min Backups',
        config_parameter='saas_master.hosting_min_backups',
        default=3,
    )
    saas_hosting_max_backups = fields.Integer(
        string='Hosting: Max Backups',
        config_parameter='saas_master.hosting_max_backups',
        default=14,
    )

    # ========== Extra Storage Pricing ==========
    saas_extra_storage_price_per_gb = fields.Float(
        string='Extra Storage Price per GB',
        config_parameter='saas_master.extra_storage_price_per_gb',
        default=0.0,
        help='Price charged per extra GB of storage that exceeds the plan limit. '
             'Added as a separate line on the renewal invoice. '
             'Set to 0 to suspend instances instead of charging.',
    )

    # ========== Support ==========
    saas_support_email = fields.Char(
        string='Support Email',
        config_parameter='saas_master.support_email',
        help='Support email address shown to clients in email notifications '
             'and portal pages when they need to contact support.',
    )
    saas_data_restoration_fee = fields.Float(
        string='Data Restoration Fee',
        config_parameter='saas_master.data_restoration_fee',
        default=0.0,
        help='Fee charged to clients when restoring data from a retained '
             'backup of a cancelled instance. An invoice is created '
             'automatically when the admin performs the restoration. '
             'Set to 0 for no charge.',
    )

    # ========== Website Sections ==========
    # Toggle visibility of the public Services / Hosting sections.
    # When False, the nav link, footer link, home-page card, and CTA are
    # hidden, and the corresponding routes redirect to /. The underlying
    # data (products, plans, hosting versions) is untouched, so flipping
    # the toggle back on instantly restores the section.
    saas_show_services_section = fields.Boolean(
        string='Show Services Section',
        config_parameter='saas_master.show_services_section',
        default=True,
        help='Show the "Services" section (catalog and detail pages) on '
             'the public website. Turn off if you only want to sell '
             'Hosting at this stage. The data is preserved.',
    )
    saas_show_hosting_section = fields.Boolean(
        string='Show Hosting Section',
        config_parameter='saas_master.show_hosting_section',
        default=True,
        help='Show the "Hosting" section (landing page and configurator) '
             'on the public website. Turn off to hide hosting offerings '
             'temporarily. The data is preserved.',
    )

    # ========== Rate Limiting ==========
    saas_max_instances_per_user = fields.Integer(
        string='Max Instances Per User',
        config_parameter='saas_master.max_instances_per_user',
        default=5,
        help='Maximum number of active instances a single customer can have. '
             '0 = unlimited.',
    )

    # ========== Backup Storage ==========
    saas_backup_provider = fields.Selection([
        ('aws', 'AWS S3'),
        ('gcs', 'Google Cloud Storage'),
        ('digitalocean', 'DigitalOcean Spaces'),
    ], string='Backup Provider',
        config_parameter='saas_backup.provider',
    )
    saas_backup_bucket_name = fields.Char(
        string='Bucket Name',
        config_parameter='saas_backup.bucket_name',
    )
    saas_backup_region = fields.Char(
        string='Region',
        config_parameter='saas_backup.region',
        help='e.g. us-east-1, europe-west1, nyc3',
    )
    saas_backup_access_key = fields.Char(
        string='Access Key',
        config_parameter='saas_backup.access_key',
    )
    saas_backup_secret_key = fields.Char(
        string='Secret Key',
        config_parameter='saas_backup.secret_key',
    )
    saas_backup_service_account_key_file = fields.Binary(
        string='Service Account JSON Key',
        help='Upload the GCP service account key JSON file.',
    )
    saas_backup_service_account_key_filename = fields.Char(
        string='Key Filename',
    )
    saas_backup_endpoint = fields.Char(
        string='Endpoint URL',
        config_parameter='saas_backup.endpoint',
        help='Custom S3-compatible endpoint. Required for DigitalOcean Spaces. '
             'e.g. https://nyc3.digitaloceanspaces.com',
    )

    # ========== Snapshot Storage (pre-built DB templates) ==========
    saas_snapshot_same_as_backup = fields.Boolean(
        string='Use Backup Storage for Snapshots',
        config_parameter='saas_snapshot.same_as_backup',
        default=False,
        help='When enabled, snapshots use the same cloud storage configuration as backups.',
    )
    saas_snapshot_provider = fields.Selection([
        ('aws', 'AWS S3'),
        ('gcs', 'Google Cloud Storage'),
        ('digitalocean', 'DigitalOcean Spaces'),
    ], string='Snapshot Provider',
        config_parameter='saas_snapshot.provider',
    )
    saas_snapshot_bucket_name = fields.Char(
        string='Snapshot Bucket Name',
        config_parameter='saas_snapshot.bucket_name',
    )
    saas_snapshot_region = fields.Char(
        string='Snapshot Region',
        config_parameter='saas_snapshot.region',
        help='e.g. us-east-1, europe-west1, nyc3',
    )
    saas_snapshot_access_key = fields.Char(
        string='Snapshot Access Key',
        config_parameter='saas_snapshot.access_key',
    )
    saas_snapshot_secret_key = fields.Char(
        string='Snapshot Secret Key',
        config_parameter='saas_snapshot.secret_key',
    )
    saas_snapshot_service_account_key_file = fields.Binary(
        string='Snapshot Service Account JSON Key',
        help='Upload the GCP service account key JSON file for the snapshot bucket.',
    )
    saas_snapshot_service_account_key_filename = fields.Char(
        string='Snapshot Key Filename',
    )
    saas_snapshot_endpoint = fields.Char(
        string='Snapshot Endpoint URL',
        config_parameter='saas_snapshot.endpoint',
        help='Custom S3-compatible endpoint. Required for DigitalOcean Spaces. '
             'e.g. https://nyc3.digitaloceanspaces.com',
    )

    def set_values(self):
        res = super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        if self.saas_backup_service_account_key_file:
            import base64
            key_json = base64.b64decode(self.saas_backup_service_account_key_file).decode('utf-8')
            ICP.set_param('saas_backup.service_account_key', key_json)
        if self.saas_snapshot_same_as_backup:
            # Copy backup storage config into snapshot params
            ICP.set_param('saas_snapshot.provider', ICP.get_param('saas_backup.provider', ''))
            ICP.set_param('saas_snapshot.bucket_name', ICP.get_param('saas_backup.bucket_name', ''))
            ICP.set_param('saas_snapshot.region', ICP.get_param('saas_backup.region', ''))
            ICP.set_param('saas_snapshot.access_key', ICP.get_param('saas_backup.access_key', ''))
            ICP.set_param('saas_snapshot.secret_key', ICP.get_param('saas_backup.secret_key', ''))
            ICP.set_param('saas_snapshot.endpoint', ICP.get_param('saas_backup.endpoint', ''))
            ICP.set_param('saas_snapshot.service_account_key',
                          ICP.get_param('saas_backup.service_account_key', ''))
        elif self.saas_snapshot_service_account_key_file:
            import base64
            key_json = base64.b64decode(self.saas_snapshot_service_account_key_file).decode('utf-8')
            ICP.set_param('saas_snapshot.service_account_key', key_json)
        return res

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        sa_key = ICP.get_param('saas_backup.service_account_key', '')
        if sa_key:
            import base64
            res['saas_backup_service_account_key_file'] = base64.b64encode(
                sa_key.encode('utf-8')
            )
            res['saas_backup_service_account_key_filename'] = 'service_account.json'
        sa_key_snap = ICP.get_param('saas_snapshot.service_account_key', '')
        if sa_key_snap:
            import base64
            res['saas_snapshot_service_account_key_file'] = base64.b64encode(
                sa_key_snap.encode('utf-8')
            )
            res['saas_snapshot_service_account_key_filename'] = 'service_account.json'
        return res
