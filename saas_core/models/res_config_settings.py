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
