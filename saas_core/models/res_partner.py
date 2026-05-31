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

    @api.model
    def _saas_normalize_phone(self, phone, country_id=None):
        """Return a phone in canonical E.164 form for storage + dedup.

        Trial farming abused the fact that ``+1 555-111-2222``,
        ``+15551112222`` and ``15551112222`` are different STRINGS — the
        old raw-string dedup let one person reformat the same number to
        pass the "phone already registered" check on each new free
        trial. Storing and comparing the E.164 form collapses them to
        one, so the phone (which must receive an OTP) becomes a real
        per-account cost.

        Falls back to the stripped raw string when the number can't be
        parsed (e.g. no/unknown country) — we never drop the customer's
        input, we just can't canonicalize it.
        """
        raw = (phone or '').strip()
        if not raw:
            return raw
        code = None
        phone_code = None
        if country_id:
            try:
                country = self.env['res.country'].sudo().browse(int(country_id))
                if country.exists():
                    code = country.code
                    phone_code = country.phone_code
            except (ValueError, TypeError):
                pass
        try:
            return phone_format(
                raw, code, phone_code,
                force_format='E164', raise_exception=True,
            )
        except Exception:
            return raw

    def _saas_uniqueness_applies(self, partner):
        """Whether the saas_core uniqueness checks apply to *partner*.

        Restrict to commercial customers (those with sales activity or
        explicitly flagged as customers) so non-SaaS uses of res.partner
        — multiple shipping addresses, accounting contacts, etc. — are
        not blocked. Subclass to broaden/narrow as needed.
        """
        return bool(partner.customer_rank)

    @api.constrains('email')
    def _check_unique_email(self):
        candidates = self.filtered(
            lambda p: p.email and self._saas_uniqueness_applies(p)
        )
        if not candidates:
            return
        emails = list({(p.email or '').lower() for p in candidates})
        # Single batched search for any partner outside *self* sharing
        # any of the candidate emails.
        duplicates = self.sudo().search([
            ('email', 'in', emails),
            ('id', 'not in', candidates.ids),
        ])
        # Map by lowercased email for O(1) per-record lookup.
        dup_emails = {(p.email or '').lower() for p in duplicates}
        # Also detect intra-batch duplicates.
        seen = {}
        for p in candidates:
            key = (p.email or '').lower()
            if key in dup_emails or key in seen:
                raise ValidationError(_(
                    "The email address '%s' is already used by another contact."
                ) % p.email)
            seen[key] = p.id

    @api.constrains('phone', 'country_id')
    def _check_phone_country(self):
        candidates = self.filtered(
            lambda p: p.phone and self._saas_uniqueness_applies(p)
        )
        if not candidates:
            return
        # Per-record format validation (cheap, in-memory).
        for partner in candidates:
            if partner.country_id:
                try:
                    phone_format(
                        partner.phone,
                        partner.country_id.code,
                        partner.country_id.phone_code,
                        force_format='E164',
                        raise_exception=True,
                    )
                except Exception as exc:
                    raise ValidationError(_(
                        "The phone number '%s' is not valid for %s: %s"
                    ) % (partner.phone, partner.country_id.name, exc))
        # Single batched uniqueness lookup.
        phones = list({p.phone for p in candidates})
        duplicates = self.sudo().search([
            ('phone', 'in', phones),
            ('id', 'not in', candidates.ids),
        ])
        dup_phones = {p.phone for p in duplicates}
        seen = {}
        for p in candidates:
            if p.phone in dup_phones or p.phone in seen:
                raise ValidationError(_(
                    "The phone number '%s' is already used by another contact."
                ) % p.phone)
            seen[p.phone] = p.id

    def _saas_has_paid_instance(self, hosting=False):
        """True if this partner already owns a paid (non-trial, non-cancelled)
        instance of the given type. Used to disqualify the partner from the
        free trial: once they pay for a server, the server is paid and the
        trial no longer applies.
        """
        self.ensure_one()
        return bool(self.env['saas.instance'].sudo().search_count([
            ('partner_id', '=', self.id),
            ('is_trial', '=', False),
            ('is_hosting', '=', bool(hosting)),
            ('state', 'not in', ('cancelled', 'cancelled_by_client')),
        ], limit=1))

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
