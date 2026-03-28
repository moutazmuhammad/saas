from odoo import api, fields, models


class SaasInstanceFolder(models.Model):
    _name = 'saas.instance.folder'
    _description = 'Instance Folder'
    _order = 'name asc'

    name = fields.Char(required=True, string='Folder Name')
    partner_id = fields.Many2one(
        'res.partner', string='Owner', required=True,
        ondelete='cascade', index=True,
    )
    instance_ids = fields.One2many(
        'saas.instance', 'folder_id', string='Instances',
    )
    instance_count = fields.Integer(
        compute='_compute_instance_count', string='Instances',
    )

    @api.depends('instance_ids')
    def _compute_instance_count(self):
        for folder in self:
            folder.instance_count = len(folder.instance_ids)
