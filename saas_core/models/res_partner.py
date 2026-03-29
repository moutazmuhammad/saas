from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from odoo.addons.phone_validation.tools.phone_validation import phone_format


class ResPartner(models.Model):
    _inherit = 'res.partner'

    saas_trial_used = fields.Boolean(
        string='Service Trial Used',
        default=False,
        help='Whether this client has already used their free service trial.',
    )
    saas_hosting_trial_used = fields.Boolean(
        string='Hosting Trial Used',
        default=False,
        help='Whether this client has already used their free hosting trial.',
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

    @api.constrains('email')
    def _check_unique_email(self):
        for partner in self:
            if not partner.email:
                continue
            duplicate = self.sudo().search([
                ('email', '=ilike', partner.email),
                ('id', '!=', partner.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    _("The email address '%s' is already used by another contact.",
                      partner.email)
                )

    @api.constrains('phone', 'country_id')
    def _check_phone_country(self):
        for partner in self:
            if not partner.phone:
                continue
            # Validate phone matches the partner's country
            if partner.country_id:
                try:
                    phone_format(
                        partner.phone,
                        partner.country_id.code,
                        partner.country_id.phone_code,
                        force_format='E164',
                        raise_exception=True,
                    )
                except Exception:
                    raise ValidationError(
                        _("The phone number '%s' is not valid for %s. "
                          "Please enter a phone number that matches your country.",
                          partner.phone, partner.country_id.name)
                    )
            # Check uniqueness
            duplicate = self.sudo().search([
                ('phone', '=', partner.phone),
                ('id', '!=', partner.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    _("The phone number '%s' is already used by another contact.",
                      partner.phone)
                )

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
