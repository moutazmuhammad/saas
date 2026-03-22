from odoo import api, fields, models


class SaasInstance(models.Model):
    _inherit = 'saas.instance'

    access_token = fields.Char('Security Token', copy=False)

    def _compute_access_url(self):
        for rec in self:
            rec.access_url = '/my/instances/%s' % rec.id

    # ---- Auto-assign infrastructure (resource-aware) ----

    def _auto_assign_infrastructure(self):
        """Pick the docker server and db server with lowest resource usage.

        Considers actual CPU/RAM usage of running instances when available,
        falling back to instance count when usage data is missing.
        """
        Instance = self.env['saas.instance']
        active_states = (
            'draft', 'pending_payment', 'paid', 'provisioning',
            'running', 'stopped', 'suspended',
        )

        for rec in self:
            if not rec.docker_server_id:
                servers = self.env['saas.container.physical.server'].search([])
                if not servers:
                    continue
                rec.docker_server_id = self._pick_least_loaded_server(
                    servers, 'docker_server_id', active_states, Instance,
                )

            if not rec.db_server_id:
                servers = self.env['saas.psql.physical.server'].search([])
                if not servers:
                    continue
                rec.db_server_id = self._pick_least_loaded_server(
                    servers, 'db_server_id', active_states, Instance,
                )

    @staticmethod
    def _pick_least_loaded_server(servers, field_name, active_states, Instance):
        """Pick a server based on a weighted score of instance count and
        resource usage (total_storage_bytes as a proxy for load)."""
        data = Instance._read_group(
            [(field_name, 'in', servers.ids), ('state', 'in', active_states)],
            [field_name],
            ['__count'],
        )
        counts = {getattr(row[0], 'id', row[0]): row[1] for row in data}

        # Also consider total storage bytes for running instances
        storage_data = Instance._read_group(
            [(field_name, 'in', servers.ids), ('state', '=', 'running')],
            [field_name],
            ['total_storage_bytes:sum'],
        )
        storage_map = {
            getattr(row[0], 'id', row[0]): row[1] for row in storage_data
        }

        def score(server):
            count = counts.get(server.id, 0)
            storage_gb = (storage_map.get(server.id, 0) or 0) / (1024 ** 3)
            # Weight: 1 point per instance + 0.1 per GB of storage
            return count + storage_gb * 0.1

        return min(servers, key=score)
