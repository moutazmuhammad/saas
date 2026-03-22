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

    # ========== Free Trial ==========
    saas_trial_days = fields.Integer(
        string='Free Trial Duration (Days)',
        config_parameter='saas_master.trial_days',
        default=14,
        help='Number of days for the free trial period. '
             'After expiry the instance is suspended until the client pays.',
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

    def set_values(self):
        res = super().set_values()
        if self.saas_backup_service_account_key_file:
            import base64
            key_json = base64.b64decode(self.saas_backup_service_account_key_file).decode('utf-8')
            self.env['ir.config_parameter'].sudo().set_param(
                'saas_backup.service_account_key', key_json,
            )
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
        return res
