from odoo import http
from odoo.http import request


class SaasHome(http.Controller):

    @http.route('/', type='http', auth='public', website=True, sitemap=True)
    def home_page(self, **kw):
        """Render the CloudOdoo landing page."""
        services = request.env['saas.product'].sudo().search([
            ('is_published', '=', True),
            ('is_hosting', '=', False),
        ], order='sequence, id', limit=6)

        hosting_versions = request.env['saas.odoo.version'].sudo().search(
            [('is_hosting_version', '=', True)], order='name desc',
        )

        # Trial info
        trial_days = int(request.env['ir.config_parameter'].sudo().get_param(
            'saas_master.trial_days', '14',
        ))

        return request.render('saas_website.cloudodoo_home', {
            'services': services,
            'hosting_versions': hosting_versions,
            'trial_days': trial_days,
        })
