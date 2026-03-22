from odoo import http, _
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager


class SaasPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'instance_count' in counters:
            partner = request.env.user.partner_id
            Instance = request.env['saas.instance']
            values['instance_count'] = Instance.search_count([
                ('partner_id', '=', partner.id),
            ]) if Instance.has_access('read') else 0
        return values

    # ==================== Instance List ====================

    @http.route(
        ['/my/instances', '/my/instances/page/<int:page>'],
        type='http', auth='user', website=True,
    )
    def portal_my_instances(self, page=1, sortby=None, **kw):
        partner = request.env.user.partner_id
        Instance = request.env['saas.instance']
        domain = [('partner_id', '=', partner.id)]

        sortings = {
            'date': {'label': _('Newest'), 'order': 'create_date desc'},
            'name': {'label': _('Name'), 'order': 'subdomain asc'},
            'state': {'label': _('Status'), 'order': 'state asc'},
        }
        sortby = sortby if sortby in sortings else 'date'

        instance_count = Instance.search_count(domain)
        pager = portal_pager(
            url='/my/instances',
            total=instance_count,
            page=page,
            step=20,
            url_args={'sortby': sortby},
        )

        instances = Instance.search(
            domain,
            order=sortings[sortby]['order'],
            limit=20,
            offset=pager['offset'],
        )

        values = self._prepare_portal_layout_values()
        values.update({
            'instances': instances,
            'page_name': 'saas_instances',
            'pager': pager,
            'sortby': sortby,
            'searchbar_sortings': sortings,
            'default_url': '/my/instances',
        })
        return request.render('saas_website.portal_my_instances', values)

    # ==================== Instance Detail ====================

    @http.route(
        '/my/instances/<int:instance_id>',
        type='http', auth='user', website=True,
    )
    def portal_my_instance_detail(self, instance_id, access_token=None, **kw):
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        # Fetch backups for portal display
        backups = instance_sudo.backup_ids.filtered(
            lambda b: b.state == 'done'
        ).sorted('create_date', reverse=True)[:10]

        values = self._prepare_portal_layout_values()
        values.update({
            'instance': instance_sudo,
            'backups': backups,
            'page_name': 'saas_instance_detail',
        })
        return request.render('saas_website.portal_instance_detail', values)

    # ==================== Deployment Status Polling ====================

    @http.route(
        '/my/instances/<int:instance_id>/status',
        type='json', auth='user', website=True,
    )
    def portal_instance_status(self, instance_id, access_token=None, **kw):
        """JSON endpoint for polling deployment status."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return {'error': 'Access denied'}
        return instance_sudo._get_status_dict()

    # ==================== Portal Self-Service Actions ====================

    @http.route(
        '/my/instances/<int:instance_id>/restart',
        type='json', auth='user', website=True,
    )
    def portal_instance_restart(self, instance_id, access_token=None, **kw):
        """Restart an instance from the portal."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return {'error': 'Access denied'}
        try:
            instance_sudo.action_portal_restart()
            return {'success': True, 'message': _('Instance restart initiated.')}
        except UserError as e:
            return {'error': str(e)}

    @http.route(
        '/my/instances/<int:instance_id>/stop',
        type='json', auth='user', website=True,
    )
    def portal_instance_stop(self, instance_id, access_token=None, **kw):
        """Stop an instance from the portal."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return {'error': 'Access denied'}
        try:
            instance_sudo.action_portal_stop()
            return {'success': True, 'message': _('Instance stop initiated.')}
        except UserError as e:
            return {'error': str(e)}

    @http.route(
        '/my/instances/<int:instance_id>/start',
        type='json', auth='user', website=True,
    )
    def portal_instance_start(self, instance_id, access_token=None, **kw):
        """Start a stopped instance from the portal."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return {'error': 'Access denied'}
        try:
            instance_sudo.action_portal_start()
            return {'success': True, 'message': _('Instance start initiated.')}
        except UserError as e:
            return {'error': str(e)}

    # ==================== Backup Download Regeneration ====================

    @http.route(
        '/my/instances/<int:instance_id>/backup/<int:backup_id>/download',
        type='http', auth='user', website=True,
    )
    def portal_backup_download(self, instance_id, backup_id, access_token=None, **kw):
        """Regenerate and redirect to a backup download URL."""
        try:
            instance_sudo = self._document_check_access(
                'saas.instance', instance_id, access_token=access_token,
            )
        except (AccessError, MissingError):
            return request.redirect('/my/instances')

        backup = instance_sudo.backup_ids.filtered(
            lambda b: b.id == backup_id and b.state == 'done'
        )
        if not backup:
            return request.redirect('/my/instances/%s' % instance_id)

        # Regenerate presigned URL if expired or missing
        backup._refresh_download_url()
        if backup.download_url:
            return request.redirect(backup.download_url)
        return request.redirect('/my/instances/%s' % instance_id)
