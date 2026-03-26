import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaasRestoreRetainedWizard(models.TransientModel):
    _name = 'saas.restore.retained.wizard'
    _description = 'Restore Retained Backup to Instance'

    source_instance_id = fields.Many2one(
        'saas.instance',
        string='Source Instance',
        required=True,
        readonly=True,
        domain="[('retained_backup_path', '!=', False)]",
        help='Instance that holds the retained backup path. '
             'Can be cancelled or already reactivated.',
    )
    retained_backup_path = fields.Char(
        related='source_instance_id.retained_backup_path',
        string='Backup Path',
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='source_instance_id.partner_id',
        string='Customer',
        readonly=True,
    )
    target_instance_id = fields.Many2one(
        'saas.instance',
        string='Target Instance',
        required=True,
        domain="[('partner_id', '=', partner_id), "
               "('state', 'in', ('running', 'stopped'))]",
        help='The running or stopped instance where the backup will be '
             'restored. Must belong to the same customer. '
             'Can be the same instance after reactivation.',
    )
    restoration_fee = fields.Float(
        string='Restoration Fee',
        help='Fee to charge the customer. An invoice will be created '
             'and posted automatically. Set to 0 for no charge.',
    )
    delete_retained_after = fields.Boolean(
        string='Delete backup from cloud after restore',
        default=False,
        help='If checked, the retained backup file will be deleted from '
             'cloud storage after a successful restoration.',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'saas.instance':
            instance = self.env['saas.instance'].browse(
                self.env.context.get('active_id')
            )
            if instance.exists():
                res['source_instance_id'] = instance.id
        # Default fee from settings
        fee = float(self.env['ir.config_parameter'].sudo().get_param(
            'saas_master.data_restoration_fee', '0'
        ))
        res['restoration_fee'] = fee
        return res

    def action_restore_and_invoice(self):
        """Restore the retained backup to the target instance and create an invoice."""
        self.ensure_one()
        source = self.source_instance_id
        target = self.target_instance_id

        if not source.retained_backup_path:
            raise UserError(_(
                "No retained backup found for instance '%s'."
            ) % source.name)

        if target.state not in ('running', 'stopped'):
            raise UserError(_(
                "Target instance must be running or stopped (current: %s)."
            ) % target.state)

        if target.partner_id != source.partner_id:
            raise UserError(_(
                "Target instance must belong to the same customer."
            ))

        # --- Restore the backup ---
        _logger.info(
            "Admin restoring retained backup from %s to %s (path: %s)",
            source.name, target.name, source.retained_backup_path,
        )

        # Create a temporary backup record so _do_restore_backup can
        # use _generate_presigned_url() to download from cloud.
        Backup = self.env['saas.instance.backup']
        backup = Backup.create({
            'instance_id': target.id,
            'name': 'restored_from_%s' % (source.subdomain or source.id),
            'bucket_path': source.retained_backup_path,
            'state': 'done',
        })

        # Run restore SYNCHRONOUSLY so the admin sees the result
        # immediately (errors shown, not swallowed in a background thread).
        target._ensure_can_ssh()
        prev_state = target.state
        target.state = 'provisioning'
        target._append_log(
            "Restoring retained backup '%s'..." % backup.name
        )
        # Commit NOW so the client immediately sees 'provisioning' state
        # and the portal shows the spinner instead of the live instance.
        # Also ensures the backup record is visible to subsequent reads.
        self.env.cr.commit()

        try:
            target._do_restore_backup(backup.id)
        except Exception as e:
            # Restore failed — revert state and restart container
            target.state = prev_state
            if prev_state == 'running':
                try:
                    target._restart_container()
                except Exception:
                    _logger.exception(
                        "Failed to restart %s after restore failure",
                        target.subdomain,
                    )
            backup.unlink()
            self.env.cr.commit()
            raise UserError(_(
                "Backup restoration failed:\n%s"
            ) % str(e))

        # Clean up the temp backup record
        backup.unlink()

        # --- Create invoice if fee > 0 ---
        invoice = None
        if self.restoration_fee > 0:
            invoice = self._create_restoration_invoice(source, target)

        # --- Log and clean up ---
        invoice_note = _(" Invoice: %s") % invoice.name if invoice else ''
        if source == target:
            # Reactivated instance — source and target are the same record
            target._append_log(
                "Retained backup restored by admin %s.%s"
                % (self.env.user.name, invoice_note)
            )
            target.message_post(body=_(
                "Retained backup restored by %s.%s"
            ) % (self.env.user.name, invoice_note))
        else:
            source._append_log(
                "Retained backup restored to instance %s by admin %s.%s"
                % (target.name, self.env.user.name, invoice_note)
            )
            source.message_post(body=_(
                "Retained backup restored to <b>%s</b> by %s.%s"
            ) % (target.name, self.env.user.name, invoice_note))
            target._append_log(
                "Data restored from retained backup of %s.%s"
                % (source.name, invoice_note)
            )

        if self.delete_retained_after:
            self._delete_retained_from_cloud(source)

        # Return the target instance form
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'saas.instance',
            'res_id': target.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _create_restoration_invoice(self, source, target):
        """Create and post an invoice for the data restoration service."""
        self.ensure_one()
        product = target._get_billing_product()
        partner = target.partner_id

        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'origin': _('Data restoration: %s') % (
                target.name or target.subdomain
            ),
            'order_line': [(0, 0, {
                'product_id': product.id,
                'name': _(
                    'Data restoration — backup from %s restored to %s'
                ) % (
                    source.name or source.subdomain,
                    target.name or target.subdomain,
                ),
                'product_uom_qty': 1,
                'price_unit': self.restoration_fee,
            })],
        })
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()

        _logger.info(
            "Data restoration invoice %s created for %s (%.2f)",
            invoice.name, partner.name, self.restoration_fee,
        )
        return invoice

    def _delete_retained_from_cloud(self, source):
        """Delete the retained backup file from cloud storage."""
        try:
            Backup = self.env['saas.instance.backup']
            # Create a temp record just to use the cloud delete helpers
            temp = Backup.new({
                'instance_id': source.id,
                'bucket_path': source.retained_backup_path,
            })
            temp._delete_from_bucket()
            source.retained_backup_path = False
            source._append_log("Retained backup deleted from cloud storage.")
        except Exception:
            _logger.exception(
                "Failed to delete retained backup from cloud for %s",
                source.name,
            )
