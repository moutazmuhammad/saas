from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    saas_trial_used = fields.Boolean(
        string='Free Trial Used',
        default=False,
        help='Whether this client has already used their one-time free trial.',
    )
    saas_trial_end_date = fields.Date(
        string='Trial Ends',
        help='Date when the free trial period expires. '
             'All trial instances are suspended after this date.',
    )
    saas_instance_count = fields.Integer(
        string='Instances',
        compute='_compute_saas_instance_count',
    )

    def _compute_saas_instance_count(self):
        data = self.env['saas.instance']._read_group(
            [('partner_id', 'in', self.ids)],
            ['partner_id'],
            ['__count'],
        )
        counts = {partner.id: count for partner, count in data}
        for rec in self:
            rec.saas_instance_count = counts.get(rec.id, 0)

    def action_view_saas_instances(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'SaaS Instances',
            'res_model': 'saas.instance',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }
