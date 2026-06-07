from odoo import api, fields, models, _


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
    saas_snapshot_price_per_gb = fields.Float(
        string='Snapshot Price per GB (monthly)',
        config_parameter='saas_master.snapshot_price_per_gb',
        default=0.40,
        help='Usage-based snapshot pricing: the storage actually consumed '
             'by the instance\'s snapshots is rounded UP to the next whole '
             'GB and charged at this monthly rate (1 GB minimum). '
             'Re-evaluated on every monthly renewal. Retention is fixed at '
             '7 days per database.',
    )
    # Hosting snapshot retention is fixed (HOSTING_MAX_SNAPSHOTS=7 in
    # saas.instance.backup); there is no per-plan hosting backup count, so
    # no hosting_min_backups / hosting_max_backups settings here.

    # ========== Extra Storage Pricing ==========
    saas_extra_storage_price_per_gb = fields.Float(
        string='Extra Storage Price per GB',
        config_parameter='saas_master.extra_storage_price_per_gb',
        default=0.0,
        help='Price charged per extra GB of storage that exceeds the plan limit. '
             'Added as a separate line on the renewal invoice. '
             'Set to 0 to suspend instances instead of charging.',
    )

    # ========== Pricing Engine: cost floor & storage blocks ==========
    # The pricing engine (saas.pricing.engine) charges custom configs as
    # max(rate_formula, floor). Floor rates are cost-derived: they protect
    # margin and block "cheap workers + huge storage" abuse. Defaults are 0
    # => no floor, so behaviour is unchanged until you set them.
    saas_hosting_worker_floor = fields.Float(
        string='Hosting: Worker Cost Floor',
        config_parameter='saas_master.hosting_worker_floor',
        default=0.0,
        help='Minimum monthly cost per worker on hosting custom configs '
             '(cost-derived floor). The engine charges max(rate, floor). '
             '0 = no floor.',
    )
    saas_hosting_storage_floor = fields.Float(
        string='Hosting: Storage Cost Floor (per GB)',
        config_parameter='saas_master.hosting_storage_floor',
        default=0.0,
        help='Minimum monthly cost per GB on hosting custom configs. 0 = no floor.',
    )
    saas_worker_floor = fields.Float(
        string='Services: Worker Cost Floor',
        config_parameter='saas_master.worker_floor',
        default=0.0,
        help='Minimum monthly cost per worker on services custom configs. 0 = no floor.',
    )
    saas_storage_floor = fields.Float(
        string='Services: Storage Cost Floor (per GB)',
        config_parameter='saas_master.storage_floor',
        default=0.0,
        help='Minimum monthly cost per GB on services custom configs. 0 = no floor.',
    )
    saas_hosting_minimum_monthly = fields.Float(
        string='Hosting: Minimum Monthly Charge',
        config_parameter='saas_master.hosting_minimum_monthly',
        default=0.0,
        help='Floor on the FINAL monthly total for hosting plans. A tiny '
             'config still bills at least this much, so it covers fixed '
             'business costs (payment fees, support, monitoring, CAC) that '
             'don\'t scale down. The customer just sees this as the price '
             '— no surcharge. 0 = no minimum.',
    )
    saas_minimum_monthly = fields.Float(
        string='Services: Minimum Monthly Charge',
        config_parameter='saas_master.minimum_monthly',
        default=0.0,
        help='Floor on the final monthly total for services custom plans. '
             '0 = no minimum.',
    )
    saas_storage_block_gb = fields.Integer(
        string='Storage Expansion Block (GB)',
        config_parameter='saas_master.storage_block_gb',
        default=50,
        help='Size of one storage-expansion block (GB). Storage above the '
             'plan allowance is sold/billed in whole blocks of this size '
             '(wired from S6). Keeps storage pricing predictable for users.',
    )
    saas_storage_block_price = fields.Float(
        string='Storage Expansion Block Price (monthly)',
        config_parameter='saas_master.storage_block_price',
        default=0.0,
        help='Monthly price for one storage-expansion block. 0 = not yet '
             'configured (no block-based charging until set).',
    )

    # ========== Pricing Policy (Booleans) ==========
    # NOTE: like the website-section toggles above, these intentionally do
    # NOT use ``config_parameter=`` — see the note there. We read/write the
    # ir.config_parameter rows by hand in get_values / set_values, storing
    # the literal strings 'True'/'False'.
    saas_merge_snapshot_into_renewal_invoice = fields.Boolean(
        string='Merge Snapshot into Renewal Invoice',
        default=False,
        help='When ON, the monthly Daily Backups charge is added as a line '
             'on the main renewal invoice whenever the backup month falls '
             'due on the same date as the renewal — so the customer gets a '
             'single invoice (Plan + Support + Snapshot + Overage). The '
             'snapshot stays MONTHLY (one month at a time, never prepaid): '
             'on a monthly plan it merges every month; on a yearly plan it '
             'merges once a year and bills separately the other 11 months. '
             'When the backup is not due on the renewal date it is NOT shown '
             'on the renewal (the customer is already billed for it that '
             'month). OFF (default) = separate backup billing cycle '
             '(current behaviour).',
    )
    # ========== Support ==========
    saas_support_email = fields.Char(
        string='Support Email',
        config_parameter='saas_master.support_email',
        help='Support email address shown to clients in email notifications '
             'and portal pages when they need to contact support.',
    )
    # The retained-snapshot restoration fee is COMPUTED, not configured:
    # months retained after cancellation × snapshot size (rounded up to
    # the next whole GB) × saas_master.snapshot_price_per_gb. See
    # saas.instance._get_retained_snapshot_fee().

    # ========== Website Sections ==========
    # Toggle visibility of the public Services / Hosting sections.
    # These intentionally don't use ``config_parameter=`` — that path
    # routes through Odoo's set_param() which unlinks the row on False,
    # and through a Boolean coercion that reads ``bool('False')`` (True!)
    # — so the toggle always springs back on. We read/write the
    # underlying ir.config_parameter rows by hand in get_values /
    # set_values below, storing the literal strings ``'True'`` and
    # ``'False'``. The templates check ``!= 'False'`` so an unset row
    # (fresh install) defaults to shown.
    saas_show_services_section = fields.Boolean(
        string='Show Services Section',
        default=True,
        help='Show the "Services" section (catalog and detail pages) on '
             'the public website. Turn off if you only want to sell '
             'Hosting at this stage. The data is preserved.',
    )
    saas_show_hosting_section = fields.Boolean(
        string='Show Hosting Section',
        default=True,
        help='Show the "Hosting" section (landing page and configurator) '
             'on the public website. Turn off to hide hosting offerings '
             'temporarily. The data is preserved.',
    )

    # ========== Rate Limiting ==========
    # NO config_parameter= here — deliberately. The framework persists
    # integer settings as ``repr(value) if value else False`` and
    # ``set_param(key, False)`` DELETES the parameter, so saving 0
    # ("unlimited", per the help text) silently reverted to the default
    # on reload. Handled manually in get_values/set_values instead,
    # like the Boolean settings below (same falsy-value trap).
    saas_max_instances_per_user = fields.Integer(
        string='Max Instances Per User',
        default=5,
        help='Maximum number of active instances a single customer can have. '
             '0 = unlimited.',
    )

    # ========== Backup Storage ==========
    saas_backup_provider = fields.Selection([
        ('aws', 'AWS S3'),
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
    saas_backup_endpoint = fields.Char(
        string='Endpoint URL',
        config_parameter='saas_backup.endpoint',
        help='Custom S3-compatible endpoint. Required for DigitalOcean Spaces. '
             'e.g. https://nyc3.digitaloceanspaces.com',
    )
    # Dedicated, broader-privilege credentials used ONLY by the "Allow
    # browser uploads" (PutBucketCORS) button — kept separate from the
    # least-privilege object key above so the backup/restore key never
    # needs bucket-admin rights.
    saas_backup_cors_access_key = fields.Char(
        string='CORS Admin Access Key',
        config_parameter='saas_backup.cors_access_key',
    )
    saas_backup_cors_secret_key = fields.Char(
        string='CORS Admin Secret Key',
        config_parameter='saas_backup.cors_secret_key',
    )

    # Snapshot storage uses the same bucket as backups — there's a
    # single Storage block in settings. ``saas.product._get_storage_config``
    # reads the same ``saas_backup.*`` parameters. Any leftover
    # ``saas_snapshot.*`` rows from an earlier configuration are ignored
    # (they're cleaned up by the migration in 18.0.14.0.0/post-migrate.py).

    def set_values(self):
        res = super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(
            'saas_master.show_services_section',
            'True' if self.saas_show_services_section else 'False',
        )
        ICP.set_param(
            'saas_master.show_hosting_section',
            'True' if self.saas_show_hosting_section else 'False',
        )
        ICP.set_param(
            'saas_master.merge_snapshot_into_renewal_invoice',
            'True' if self.saas_merge_snapshot_into_renewal_invoice else 'False',
        )
        # Always write the string — '0' (unlimited) included. See the
        # field definition for why config_parameter= can't be used.
        ICP.set_param(
            'saas_master.max_instances_per_user',
            str(int(self.saas_max_instances_per_user or 0)),
        )
        return res

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        res['saas_show_services_section'] = ICP.get_param(
            'saas_master.show_services_section', 'True',
        ) != 'False'
        res['saas_show_hosting_section'] = ICP.get_param(
            'saas_master.show_hosting_section', 'True',
        ) != 'False'
        res['saas_merge_snapshot_into_renewal_invoice'] = ICP.get_param(
            'saas_master.merge_snapshot_into_renewal_invoice', 'False',
        ) == 'True'
        try:
            res['saas_max_instances_per_user'] = int(
                ICP.get_param('saas_master.max_instances_per_user', '5') or 0
            )
        except (TypeError, ValueError):
            res['saas_max_instances_per_user'] = 5
        return res

    def action_apply_bucket_cors(self):
        """Configure the storage bucket's CORS so customers' browsers can
        upload restore files straight to it (presigned PUT). Persists the
        current settings first, then applies the policy via the bucket
        API using the configured credentials — no cloud-console trip."""
        self.ensure_one()
        # Make sure freshly-typed provider/keys/bucket are saved before
        # we open a client against them.
        self.set_values()
        origins = self.env['saas.instance.backup'].apply_bucket_cors()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Bucket ready for uploads"),
                'message': _(
                    "Browser uploads (restore from file) are now allowed "
                    "from: %s"
                ) % ', '.join(origins),
                'sticky': False,
            },
        }
