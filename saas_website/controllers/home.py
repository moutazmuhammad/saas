from odoo import http
from odoo.http import request


class SaasHome(http.Controller):

    @http.route('/', type='http', auth='public', website=True, sitemap=True)
    def home_page(self, **kw):
        """Render the CloudOdoo landing page."""
        return request.render('saas_website.cloudodoo_home', {})
