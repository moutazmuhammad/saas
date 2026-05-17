import datetime
import logging
import shlex

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_MAX_BACKUPS = 7
PRESIGNED_URL_EXPIRY = 7 * 24 * 3600
# On-demand backups are deliberately short-lived. The customer gets a
# 1-hour window to download; afterwards the file is reaped from the
# bucket so we don't accumulate orphaned ondemand/ objects.
ONDEMAND_URL_EXPIRY = 3600
ONDEMAND_PREFIX = 'ondemand'


class SaasInstanceBackup(models.Model):
    _name = 'saas.instance.backup'
    _description = 'SaaS Instance Backup'
    _order = 'create_date desc'

    instance_id = fields.Many2one(
        'saas.instance', string='Instance',
        required=True, ondelete='cascade', index=True,
    )
    name = fields.Char(string='Backup Name', required=True)
    db_name = fields.Char(
        string='Database', index=True,
        help='PostgreSQL database name this backup is a snapshot of. '
             'For service instances this equals instance.subdomain. '
             'Hosting instances can have multiple databases; the cron '
             'creates one backup record per database per day.',
    )
    bucket_path = fields.Char(
        string='Bucket Path', readonly=True,
        help='Full object key inside the cloud bucket.',
    )
    size_mb = fields.Float(string='Size (MB)', readonly=True)
    state = fields.Selection([
        ('running', 'In Progress'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], string='Status', default='running', required=True)
    error_message = fields.Text(string='Error', readonly=True)
    download_url = fields.Char(
        string='Download URL', readonly=True,
        help='Presigned download link valid for 7 days.',
    )
    download_url_expiry = fields.Datetime(
        string='Link Expires', readonly=True,
    )
    ephemeral = fields.Boolean(
        string='On-Demand', default=False, index=True,
        help='True for on-demand backups requested by the customer. '
             'The bucket object is deleted automatically after the '
             '1-hour download window via the ephemeral-cleanup cron.',
    )
    expires_at = fields.Datetime(
        string='Auto-Delete At', index=True,
        help='When this on-demand backup is reaped from the bucket. '
             'Only set on ephemeral backups.',
    )

    def _refresh_download_url(self):
        """Regenerate presigned URL if expired or missing."""
        now = fields.Datetime.now()
        for rec in self:
            if rec.state != 'done' or not rec.bucket_path:
                continue
            if rec.download_url and rec.download_url_expiry and rec.download_url_expiry > now:
                continue
            try:
                url = rec._generate_presigned_url()
                rec.write({
                    'download_url': url,
                    'download_url_expiry': now + datetime.timedelta(seconds=PRESIGNED_URL_EXPIRY),
                })
            except Exception as e:
                _logger.warning("Failed to refresh download URL for backup %s: %s", rec.id, e)

    def action_download(self):
        self.ensure_one()
        self._refresh_download_url()
        if not self.download_url:
            raise UserError(_("Could not generate download link."))
        return {
            'type': 'ir.actions.act_url',
            'url': self.download_url,
            'target': 'new',
        }

    def action_restore(self):
        """Restore this backup to its instance."""
        self.ensure_one()
        self.instance_id.action_restore_backup(self.id)
        return True

    def action_delete_backup(self):
        self.ensure_one()
        # The unlink() override below also deletes the cloud object;
        # action_delete_backup is kept as a thin wrapper for the UI button.
        self.unlink()
        return True

    def unlink(self):
        """Delete cloud objects when the backup record is removed.

        Without this override, cancelling/deleting an instance triggers
        ondelete='cascade' on instance_id and silently leaks every
        backup object in cloud storage. We best-effort delete here; failures
        are logged but do not block the unlink.
        """
        for rec in self:
            if rec.bucket_path and rec.state == 'done':
                try:
                    rec._delete_from_bucket()
                except Exception:
                    _logger.exception(
                        "Failed to delete cloud object for backup %s "
                        "(path: %s) on unlink — orphan possible.",
                        rec.id, rec.bucket_path,
                    )
        return super().unlink()

    # ------------------------------------------------------------------
    # Cloud storage helpers
    # ------------------------------------------------------------------
    def _get_backup_config(self):
        """Return backup configuration from system parameters."""
        ICP = self.env['ir.config_parameter'].sudo()
        provider = ICP.get_param('saas_backup.provider', '')
        bucket = ICP.get_param('saas_backup.bucket_name', '')
        if not provider or not bucket:
            raise UserError(_(
                "Cloud backup is not configured. Go to SaaS Manager > Configuration > Settings "
                "and fill in the Backup Storage section."
            ))
        return {
            'provider': provider,
            'bucket': bucket,
            'access_key': ICP.get_param('saas_backup.access_key', ''),
            'secret_key': ICP.get_param('saas_backup.secret_key', ''),
            'region': ICP.get_param('saas_backup.region', ''),
            'endpoint': ICP.get_param('saas_backup.endpoint', ''),
            'service_account_key': ICP.get_param('saas_backup.service_account_key', ''),
        }

    def _get_s3_client(self):
        """Return a boto3 S3-compatible client configured from settings."""
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError:
            raise UserError(_("The 'boto3' Python package is required. Install it with: pip install boto3"))

        cfg = self._get_backup_config()
        if not cfg['access_key'] or not cfg['secret_key']:
            raise UserError(_(
                "Access Key and Secret Key are required for %s. "
                "Go to SaaS Manager > Configuration > Settings."
            ) % cfg['provider'].upper())

        region = cfg['region'] or 'us-east-1'
        kwargs = {
            'aws_access_key_id': cfg['access_key'],
            'aws_secret_access_key': cfg['secret_key'],
            'region_name': region,
        }

        if cfg['provider'] == 'digitalocean':
            # DigitalOcean Spaces requires virtual-hosted style addressing
            # for presigned URLs to work correctly.
            # Endpoint: https://{region}.digitaloceanspaces.com
            kwargs['endpoint_url'] = 'https://%s.digitaloceanspaces.com' % region
            kwargs['config'] = BotoConfig(s3={'addressing_style': 'virtual'})
        elif cfg['endpoint']:
            kwargs['endpoint_url'] = cfg['endpoint']
            kwargs['config'] = BotoConfig(s3={'addressing_style': 'path'})

        return boto3.client('s3', **kwargs), cfg['bucket']

    def _get_gcs_client(self):
        """Return a google-cloud-storage client configured from settings."""
        try:
            from google.cloud import storage as gcs_storage
            from google.oauth2 import service_account
        except ImportError:
            raise UserError(_(
                "The 'google-cloud-storage' Python package is required. "
                "Install it with: pip install google-cloud-storage"
            ))

        import json as _json

        cfg = self._get_backup_config()
        sa_key = cfg['service_account_key']
        if not sa_key:
            raise UserError(_(
                "Service Account JSON Key is required for Google Cloud Storage. "
                "Go to SaaS Manager > Configuration > Settings."
            ))

        try:
            key_info = _json.loads(sa_key)
        except (ValueError, TypeError):
            raise UserError(_("Invalid Service Account JSON Key. Please check the format."))

        credentials = service_account.Credentials.from_service_account_info(key_info)
        client = gcs_storage.Client(credentials=credentials, project=key_info.get('project_id'))
        return client, cfg['bucket']

    def _upload_to_bucket(self, object_key, data_bytes):
        cfg = self._get_backup_config()
        _logger.info(
            "Uploading backup to %s bucket=%s key=%s size=%d bytes",
            cfg['provider'], cfg['bucket'], object_key, len(data_bytes),
        )
        if cfg['provider'] == 'gcs':
            client, bucket_name = self._get_gcs_client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(object_key)
            blob.upload_from_string(data_bytes, content_type='application/zip')
        else:
            client, bucket = self._get_s3_client()
            _logger.info(
                "S3 client endpoint=%s region=%s bucket=%s",
                client.meta.endpoint_url, client.meta.region_name, bucket,
            )
            try:
                client.put_object(
                    Bucket=bucket,
                    Key=object_key,
                    Body=data_bytes,
                    ContentType='application/zip',
                )
            except Exception as e:
                _logger.error(
                    "put_object failed: %s — trying upload_fileobj fallback", e,
                )
                # Fallback: use upload_fileobj which handles chunked upload
                import io
                client.upload_fileobj(
                    io.BytesIO(data_bytes),
                    bucket,
                    object_key,
                    ExtraArgs={'ContentType': 'application/zip'},
                )

    def _generate_presigned_url(self, expiry=None):
        """Return a presigned GET URL for this backup's bucket object.

        ``expiry`` overrides the default 7-day TTL — used by on-demand
        backups (1 hour) so the URL dies with the bucket object.
        """
        ttl = expiry or PRESIGNED_URL_EXPIRY
        cfg = self._get_backup_config()
        if cfg['provider'] == 'gcs':
            client, bucket_name = self._get_gcs_client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(self.bucket_path)
            return blob.generate_signed_url(
                expiration=datetime.timedelta(seconds=ttl),
                method='GET',
            )
        else:
            client, bucket = self._get_s3_client()
            return client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket, 'Key': self.bucket_path},
                ExpiresIn=ttl,
            )

    def _generate_presigned_put_url(self, object_key):
        """Generate a presigned PUT URL for direct server-to-bucket upload."""
        cfg = self._get_backup_config()
        if cfg['provider'] == 'gcs':
            client, bucket_name = self._get_gcs_client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(object_key)
            return blob.generate_signed_url(
                expiration=datetime.timedelta(hours=1),
                method='PUT',
                content_type='application/zip',
            )
        else:
            client, bucket = self._get_s3_client()
            return client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': bucket,
                    'Key': object_key,
                    'ContentType': 'application/zip',
                },
                ExpiresIn=3600,
            )

    def _delete_from_bucket(self):
        self.ensure_one()
        if self.bucket_path:
            self._delete_bucket_path(self.bucket_path)

    # Hard limit on backup size we'll download just to inspect manifest.
    # For larger backups the version check is skipped — safer to allow
    # the restore than to OOM the worker reading hundreds of MB.
    _MANIFEST_PEEK_MAX_MB = 100

    def _read_manifest_safe(self):
        """Read manifest.json from this backup's bucket object if available.

        Returns the parsed dict, or None if anything fails. Skips the
        check entirely for backups larger than _MANIFEST_PEEK_MAX_MB to
        avoid memory blowup. Used by restore to verify Odoo-version
        compatibility before nuking the target database.
        """
        self.ensure_one()
        if not self.bucket_path:
            return None
        if self.size_mb and self.size_mb > self._MANIFEST_PEEK_MAX_MB:
            _logger.info(
                "Skipping manifest check for %s (size %.1f MB > %d MB)",
                self.bucket_path, self.size_mb, self._MANIFEST_PEEK_MAX_MB,
            )
            return None
        try:
            cfg = self._get_backup_config()
            import io
            import json as _json
            import zipfile
            buf = io.BytesIO()
            if cfg['provider'] == 'gcs':
                client, bucket_name = self._get_gcs_client()
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(self.bucket_path)
                blob.download_to_file(buf)
            else:
                client, bucket_name = self._get_s3_client()
                client.download_fileobj(bucket_name, self.bucket_path, buf)
            buf.seek(0)
            with zipfile.ZipFile(buf) as zf:
                if 'manifest.json' not in zf.namelist():
                    return None
                with zf.open('manifest.json') as mf:
                    return _json.load(mf)
        except Exception:
            _logger.warning(
                "Could not read manifest from backup %s",
                self.bucket_path, exc_info=True,
            )
            return None

    @api.model
    def _delete_bucket_path(self, bucket_path):
        """Delete an arbitrary object key from the configured backup bucket.

        Use this when you have a bucket path but no `saas.instance.backup`
        record (e.g. retained backup paths after the source instance has
        been wiped). Replaces the previous `Backup.new(...)._delete_from_bucket()`
        anti-pattern.
        """
        if not bucket_path:
            return
        try:
            cfg = self._get_backup_config()
            if cfg['provider'] == 'gcs':
                client, bucket_name = self._get_gcs_client()
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(bucket_path)
                blob.delete()
            else:
                client, bucket = self._get_s3_client()
                client.delete_object(Bucket=bucket, Key=bucket_path)
        except Exception as e:
            _logger.warning("Failed to delete backup object %s: %s", bucket_path, e)

    def _move_to_cancelled_folder(self):
        """Move this backup's cloud object into the cancelled_backups/ prefix.

        Returns the new object key, or False on failure.
        Used when an instance is deleted to keep one retained backup in
        a separate folder for easy identification and lifecycle management.
        """
        self.ensure_one()
        if not self.bucket_path:
            return False
        new_key = 'cancelled_backups/%s' % self.bucket_path
        try:
            cfg = self._get_backup_config()
            if cfg['provider'] == 'gcs':
                client, bucket_name = self._get_gcs_client()
                bucket = client.bucket(bucket_name)
                src_blob = bucket.blob(self.bucket_path)
                bucket.copy_blob(src_blob, bucket, new_key)
                src_blob.delete()
            else:
                client, bucket_name = self._get_s3_client()
                client.copy_object(
                    Bucket=bucket_name,
                    CopySource={'Bucket': bucket_name, 'Key': self.bucket_path},
                    Key=new_key,
                )
                client.delete_object(Bucket=bucket_name, Key=self.bucket_path)
            _logger.info(
                "Moved backup %s → %s in bucket %s",
                self.bucket_path, new_key, bucket_name,
            )
            return new_key
        except Exception as e:
            _logger.warning(
                "Failed to move backup %s to cancelled folder: %s",
                self.bucket_path, e,
            )
            # Fallback: keep the original path rather than losing track
            return self.bucket_path

    # ------------------------------------------------------------------
    # Backup creation — zip on server, upload directly to bucket
    # ------------------------------------------------------------------
    def _create_and_upload_backup(self, instance, object_key, db_name=None):
        """SSH to the docker server, dump DB + copy filestore + manifest, zip,
        then upload directly from the server to the bucket via presigned URL.

        ``db_name`` selects which database to dump. Defaults to the
        record's own ``db_name`` (or ``instance.subdomain`` if blank
        for service instances).

        Returns the zip size in bytes.
        """
        instance._ensure_can_ssh()
        docker_server = instance.docker_server_id
        container_name = instance._get_container_name()
        db_name = db_name or self.db_name or instance.subdomain
        db_server = instance.db_server_id
        db_host = instance._get_db_host()
        db_port = db_server.psql_port or 5432
        ts = fields.Datetime.now().strftime('%Y%m%d%H%M%S')
        tmp_dir = '/tmp/saas_backup_%s_%s' % (db_name, ts)
        zip_path = '%s.zip' % tmp_dir
        script_path = '/tmp/saas_backup_script_%s_%s.sh' % (db_name, ts)

        import json
        manifest = json.dumps({
            'odoo_version': instance.odoo_version_id.name or '',
            'database': db_name,
            'partner': instance.partner_id.name or '',
            'timestamp': fields.Datetime.now().isoformat(),
            'instance': instance.name or '',
        }, indent=2)

        # Generate presigned PUT URL for direct upload from server to bucket
        try:
            presigned_put_url = self._generate_presigned_put_url(object_key)
        except Exception:
            presigned_put_url = None

        # Use environment variables instead of embedding credentials in shell script
        env_vars = {
            'SAAS_TMP_DIR': tmp_dir,
            'SAAS_ZIP_PATH': zip_path,
            'SAAS_CONTAINER': container_name,
            'SAAS_DB_NAME': db_name,
            'SAAS_DB_HOST': db_host,
            'SAAS_DB_PORT': str(db_port),
            'SAAS_DB_USER': instance.db_user,
            'SAAS_DB_PASS': instance.db_password,
        }
        if presigned_put_url:
            env_vars['SAAS_UPLOAD_URL'] = presigned_put_url

        env_prefix = ' '.join(
            '%s=%s' % (k, shlex.quote(v)) for k, v in env_vars.items()
        )

        # Build the upload step based on whether presigned URL is available
        if presigned_put_url:
            upload_step = (
                '# 5) Upload directly to cloud storage via presigned URL\n'
                'if curl -f -X PUT -H "Content-Type: application/zip" '
                '--data-binary "@$SAAS_ZIP_PATH" "$SAAS_UPLOAD_URL"; then\n'
                '    UPLOAD_OK=0\n'
                'else\n'
                '    UPLOAD_OK=1\n'
                'fi\n'
            )
        else:
            upload_step = 'UPLOAD_OK=1  # No presigned URL, will download via SFTP\n'

        script = r"""#!/bin/bash
set -e

mkdir -p "$SAAS_TMP_DIR/filestore"

# 1) pg_dump via docker exec (pass PGPASSWORD into the container env)
# Try inside container first (uses container's pg_dump + network access)
docker exec -e PGPASSWORD="$SAAS_DB_PASS" "$SAAS_CONTAINER" pg_dump \
    -h "$SAAS_DB_HOST" -p "$SAAS_DB_PORT" -U "$SAAS_DB_USER" \
    -d "$SAAS_DB_NAME" --no-owner > "$SAAS_TMP_DIR/dump.sql" 2>/tmp/saas_pgdump_err_$$ || true

# If container pg_dump failed or produced empty dump, try from host
if [ ! -s "$SAAS_TMP_DIR/dump.sql" ]; then
    echo "Container pg_dump failed or empty, trying from host..." >&2
    # Try pg_dump directly from the host (if installed)
    if command -v pg_dump >/dev/null 2>&1; then
        PGPASSWORD="$SAAS_DB_PASS" pg_dump \
            -h "$SAAS_DB_HOST" -p "$SAAS_DB_PORT" -U "$SAAS_DB_USER" \
            -d "$SAAS_DB_NAME" --no-owner > "$SAAS_TMP_DIR/dump.sql" 2>&1
    else
        # Try via the DB server's psql if host has no pg_dump
        echo "No pg_dump on host either. Backup will have empty DB dump." >&2
    fi
fi

# Verify dump is not empty
if [ ! -s "$SAAS_TMP_DIR/dump.sql" ]; then
    echo "ERROR: pg_dump produced empty output." >&2
    cat /tmp/saas_pgdump_err_$$ 2>/dev/null >&2 || true
    rm -f /tmp/saas_pgdump_err_$$
    exit 1
fi
rm -f /tmp/saas_pgdump_err_$$

# 2) Copy filestore from inside the container using docker cp
if docker exec "$SAAS_CONTAINER" test -d "/var/lib/odoo/filestore/$SAAS_DB_NAME" 2>/dev/null; then
    docker cp "$SAAS_CONTAINER:/var/lib/odoo/filestore/$SAAS_DB_NAME/." "$SAAS_TMP_DIR/filestore/" 2>/dev/null || true
elif docker exec "$SAAS_CONTAINER" test -d "/var/lib/odoo/.local/share/Odoo/filestore/$SAAS_DB_NAME" 2>/dev/null; then
    docker cp "$SAAS_CONTAINER:/var/lib/odoo/.local/share/Odoo/filestore/$SAAS_DB_NAME/." "$SAAS_TMP_DIR/filestore/" 2>/dev/null || true
fi

# 3) Write manifest.json
cat > "$SAAS_TMP_DIR/manifest.json" << 'MANIFEST_EOF'
%s
MANIFEST_EOF

# 4) Zip
cd "$SAAS_TMP_DIR"
zip -r -q "$SAAS_ZIP_PATH" dump.sql filestore manifest.json

# Cleanup temp dir (keep zip)
rm -rf "$SAAS_TMP_DIR"

%s

# Output zip size for tracking
stat -c %%s "$SAAS_ZIP_PATH" 2>/dev/null || stat -f %%z "$SAAS_ZIP_PATH" 2>/dev/null || echo 0

# Remove zip from server if upload succeeded (so Python knows not to SFTP it)
if [ "${UPLOAD_OK:-1}" = "0" ]; then
    rm -f "$SAAS_ZIP_PATH"
fi
""" % (manifest, upload_step)

        with docker_server._get_ssh_connection() as ssh:
            # Upload script file to avoid shell quoting issues
            ssh.write_file(script_path, script)
            ssh.execute('chmod +x %s' % shlex.quote(script_path))

            exit_code, stdout, stderr = ssh.execute(
                '%s bash %s' % (env_prefix, shlex.quote(script_path)),
                timeout=600,
            )

            # Remove script
            ssh.execute('rm -f %s' % shlex.quote(script_path))

            if exit_code != 0:
                ssh.execute('rm -f %s' % shlex.quote(zip_path))
                raise UserError(
                    _("Backup failed on server %s:\n%s") % (docker_server.name, stderr or stdout)
                )

            # Parse size from stdout (last line)
            size_bytes = 0
            for line in stdout.strip().splitlines():
                line = line.strip()
                if line.isdigit():
                    size_bytes = int(line)

            # Check if the zip still exists on the server (means upload
            # didn't happen or failed — need SFTP fallback)
            check_code, _, _ = ssh.execute(
                'test -f %s' % shlex.quote(zip_path)
            )
            if check_code == 0:
                # Zip still on server — download via SFTP and upload from Odoo
                try:
                    zip_data = ssh.read_file_bytes(zip_path)
                    size_bytes = len(zip_data)
                finally:
                    ssh.execute('rm -f %s' % shlex.quote(zip_path))
                if not zip_data:
                    raise UserError(_("Backup produced empty file."))
                self._upload_to_bucket(object_key, zip_data)

        return size_bytes

    # ------------------------------------------------------------------
    # Cron entry point
    # ------------------------------------------------------------------
    @api.model
    def _cron_backup_all_instances(self):
        """Create backups for all running instances and clean up old ones.

        Service instances: one backup per instance (DB name = subdomain).
        Hosting instances: skipped unless ``daily_backup_enabled``; then
        one backup per database owned by the instance's PG role. Hosting
        retention is fixed at 7 days per database (see _cleanup_old_backups).
        Trial-plan instances are skipped on both sides.
        """
        instances = self.env['saas.instance'].search([
            ('state', '=', 'running'),
            '|',
            ('plan_id', '=', False),
            ('plan_id.is_trial_plan', '=', False),
        ])
        for instance in instances:
            try:
                if instance.is_hosting:
                    if not instance.daily_backup_enabled:
                        continue
                    try:
                        dbs = [r['name'] for r in instance.hosting_db_list()]
                    except Exception as e:
                        _logger.error(
                            "Backup: could not list DBs for hosting %s: %s",
                            instance.name, e,
                        )
                        continue
                    for db_name in dbs:
                        try:
                            self._perform_backup_in_new_cursor(
                                instance.id, db_name=db_name,
                            )
                        except Exception as e:
                            _logger.error(
                                "Backup failed for %s/%s: %s",
                                instance.name, db_name, e,
                            )
                else:
                    self._perform_backup_in_new_cursor(instance.id)
            except Exception as e:
                _logger.error("Backup failed for instance %s: %s", instance.name, e)

        self._cleanup_old_backups()

    def _perform_backup_in_new_cursor(self, instance_id, db_name=None):
        """Run a single backup in a separate cursor to isolate transactions."""
        new_cr = self.pool.cursor()
        try:
            new_env = api.Environment(new_cr, self.env.uid, self.env.context)
            new_env['saas.instance.backup']._perform_backup(
                new_env['saas.instance'].browse(instance_id),
                db_name=db_name,
            )
            new_cr.commit()
        except Exception:
            new_cr.rollback()
            raise
        finally:
            new_cr.close()

    def _perform_backup(self, instance, db_name=None):
        """Perform a single backup for an instance.

        ``db_name`` is the database to snapshot. Defaults to
        ``instance.subdomain`` (service instances). For hosting
        instances the cron passes each enumerated DB name in turn.
        """
        db_name = db_name or instance.subdomain
        now_str = fields.Datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup_name = 'backup_%s' % now_str
        partner = instance.partner_id
        partner_folder = '%s_%s' % (
            partner.id, self._sanitize_name(partner.name),
        ) if partner else 'no_partner'
        # For hosting, segregate per DB so multiple DBs per instance
        # don't collide in the bucket. Service instances continue with
        # the legacy layout (partner/db/backup.zip) since their db == sub.
        if instance.is_hosting:
            object_key = '%s/%s/%s/%s.zip' % (
                partner_folder, instance.subdomain, db_name, backup_name,
            )
        else:
            object_key = '%s/%s/%s.zip' % (
                partner_folder, db_name, backup_name,
            )

        backup = self.create({
            'instance_id': instance.id,
            'name': backup_name,
            'db_name': db_name,
            'bucket_path': object_key,
            'state': 'running',
        })

        try:
            size_bytes = backup._create_and_upload_backup(
                instance, object_key, db_name=db_name,
            )
            url = backup._generate_presigned_url()
            now = fields.Datetime.now()
            backup.write({
                'state': 'done',
                'size_mb': round(size_bytes / (1024 * 1024), 2),
                'download_url': url,
                'download_url_expiry': now + datetime.timedelta(seconds=PRESIGNED_URL_EXPIRY),
            })
        except Exception as e:
            backup.write({
                'state': 'failed',
                'error_message': str(e),
            })
            raise

    def _run_portal_backup(self):
        """Run backup for an already-created record (called from portal).

        Honours ``self.ephemeral`` (on-demand path) and ``self.db_name``
        (multi-DB hosting). Layout:

        - Daily / legacy portal:   ``<partner>/<sub>/<db>/<name>.zip``
          (or ``<partner>/<db>/<name>.zip`` for non-hosting)
        - On-demand:                ``ondemand/<partner>/<sub>/<db>/<name>.zip``

        On-demand backups also get a 1-hour presigned URL and an
        ``expires_at`` timestamp so the cleanup cron can reap them.
        """
        self.ensure_one()
        instance = self.instance_id
        partner = instance.partner_id
        partner_folder = '%s_%s' % (
            partner.id, self._sanitize_name(partner.name),
        ) if partner else 'no_partner'
        db_name = self.db_name or instance.subdomain

        if self.ephemeral:
            object_key = '%s/%s/%s/%s/%s.zip' % (
                ONDEMAND_PREFIX, partner_folder, instance.subdomain,
                db_name, self.name,
            )
        elif instance.is_hosting:
            object_key = '%s/%s/%s/%s.zip' % (
                partner_folder, instance.subdomain, db_name, self.name,
            )
        else:
            object_key = '%s/%s/%s.zip' % (partner_folder, db_name, self.name)

        self.bucket_path = object_key

        try:
            size_bytes = self._create_and_upload_backup(
                instance, object_key, db_name=db_name,
            )
            ttl = ONDEMAND_URL_EXPIRY if self.ephemeral else PRESIGNED_URL_EXPIRY
            url = self._generate_presigned_url(expiry=ttl)
            now = fields.Datetime.now()
            vals = {
                'state': 'done',
                'size_mb': round(size_bytes / (1024 * 1024), 2),
                'download_url': url,
                'download_url_expiry': now + datetime.timedelta(seconds=ttl),
            }
            if self.ephemeral:
                vals['expires_at'] = now + datetime.timedelta(
                    seconds=ONDEMAND_URL_EXPIRY,
                )
            self.write(vals)
        except Exception as e:
            self.write({
                'state': 'failed',
                'error_message': str(e),
            })
            raise

    # Fixed retention for hosting backups, per the product spec. 7 days
    # per database — exactly what the customer sees in the portal.
    HOSTING_RETENTION_DAYS = 7

    @api.model
    def _cron_cleanup_ephemeral_backups(self):
        """Reap on-demand backups whose 1-hour window has elapsed.

        Deletes the bucket object and the local record. ``unlink()``
        already drops the bucket object via its ondelete handler, but
        we call ``_delete_from_bucket`` explicitly first so a deletion
        failure still removes the local record — we don't want a stuck
        object to keep us re-trying forever.
        """
        now = fields.Datetime.now()
        expired = self.search([
            ('ephemeral', '=', True),
            ('state', '=', 'done'),
            ('expires_at', '!=', False),
            ('expires_at', '<=', now),
        ])
        for backup in expired:
            try:
                if backup.bucket_path:
                    backup._delete_from_bucket()
            except Exception as e:
                _logger.warning(
                    "Ephemeral cleanup: bucket delete failed for %s: %s",
                    backup.bucket_path, e,
                )
            try:
                backup.with_context(_skip_bucket_delete=True).unlink()
            except Exception:
                _logger.exception(
                    "Ephemeral cleanup: unlink failed for backup %s",
                    backup.id,
                )

        # Also handle ephemeral backups stuck in 'running' for too long
        # (worker crash, network outage). 2 hours is generous.
        stuck_cutoff = now - datetime.timedelta(hours=2)
        stuck = self.search([
            ('ephemeral', '=', True),
            ('state', '=', 'running'),
            ('create_date', '<', stuck_cutoff),
        ])
        for backup in stuck:
            try:
                backup.unlink()
            except Exception:
                _logger.exception(
                    "Ephemeral cleanup: unlink stuck %s failed", backup.id,
                )

    @api.model
    def _cleanup_old_backups(self):
        """Trim old backups.

        - Service instances: keep at most ``plan.max_backups`` per
          instance (legacy behavior).
        - Hosting instances: keep 7 days per (instance, db_name).
        - Stale ``running`` backups older than 1 day are dropped.
        """
        # Clean up stale 'running' backups older than 1 day (stuck records)
        stale_cutoff = fields.Datetime.now() - datetime.timedelta(days=1)
        stale_backups = self.search([
            ('create_date', '<', stale_cutoff),
            ('state', '=', 'running'),
        ])
        for backup in stale_backups:
            try:
                backup.unlink()
            except Exception as e:
                _logger.error("Failed to cleanup stale backup %s: %s", backup.name, e)

        # --- Hosting: 7-day retention per (instance, db_name).
        # Ephemeral on-demand backups are handled by a separate cron
        # so they don't double-fire on the same record.
        hosting_cutoff = (
            fields.Datetime.now()
            - datetime.timedelta(days=self.HOSTING_RETENTION_DAYS)
        )
        hosting_old = self.search([
            ('state', '=', 'done'),
            ('ephemeral', '=', False),
            ('instance_id.is_hosting', '=', True),
            ('create_date', '<', hosting_cutoff),
        ])
        for backup in hosting_old:
            try:
                if backup.bucket_path:
                    backup._delete_from_bucket()
                backup.unlink()
            except Exception as e:
                _logger.error(
                    "Failed to cleanup hosting backup %s: %s", backup.name, e,
                )

        # --- Service instances: keep at most plan.max_backups per instance.
        # Ephemeral excluded for the same reason as hosting above.
        data = self._read_group(
            [
                ('state', '=', 'done'),
                ('ephemeral', '=', False),
                ('instance_id.is_hosting', '=', False),
            ],
            ['instance_id'],
            ['__count'],
        )
        for instance, count in data:
            # Get the actual limit from the plan (may be lower than
            # DEFAULT_MAX_BACKUPS after a downgrade)
            max_backups = DEFAULT_MAX_BACKUPS
            if instance.plan_id and instance.plan_id.max_backups > 0:
                max_backups = instance.plan_id.max_backups
            if count <= max_backups:
                continue
            backups = self.search([
                ('instance_id', '=', instance.id),
                ('state', '=', 'done'),
            ], order='create_date desc')
            excess = backups[max_backups:]
            for backup in excess:
                try:
                    if backup.bucket_path:
                        backup._delete_from_bucket()
                    backup.unlink()
                except Exception as e:
                    _logger.error("Failed to cleanup backup %s: %s", backup.name, e)

    def _cleanup_excess_for_instance(self, instance):
        """Remove excess backups for a single instance based on its plan limit.

        Called immediately after a plan downgrade to enforce the new
        lower backup limit without waiting for the daily cron.
        """
        max_backups = DEFAULT_MAX_BACKUPS
        if instance.plan_id and instance.plan_id.max_backups > 0:
            max_backups = instance.plan_id.max_backups
        backups = self.search([
            ('instance_id', '=', instance.id),
            ('state', '=', 'done'),
        ], order='create_date desc')
        if len(backups) <= max_backups:
            return
        excess = backups[max_backups:]
        for backup in excess:
            try:
                if backup.bucket_path:
                    backup._delete_from_bucket()
                backup.unlink()
            except Exception as e:
                _logger.error("Failed to cleanup backup %s: %s", backup.name, e)

    @staticmethod
    def _sanitize_name(name):
        if not name:
            return 'unknown'
        return ''.join(
            c if c.isalnum() or c in ('-', '_') else '_' for c in name
        ).strip('_')
