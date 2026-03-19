from odoo import fields, models


class SaasPlan(models.Model):
    _name = 'saas.plan'
    _description = 'SaaS Plan'
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Plan Name', required=True)
    cpu_limit = fields.Float(
        string='CPU Limit',
        default=1.0,
        help='CPU limit for the Docker container (e.g. 0.5 = half a core, 2.0 = two cores).',
    )
    ram_limit = fields.Char(
        string='RAM Limit',
        default='1g',
        help='RAM limit for the Docker container (e.g. 512m, 1g, 2g).',
    )
    storage_limit = fields.Float(
        string='Storage Limit (GB)',
        default=5.0,
        help='Maximum total storage (container disk + database) in GB. '
             'Instances exceeding this limit will be suspended.',
    )
    max_backups = fields.Integer(
        string='Max Backups',
        default=7,
        help='Maximum number of backups to keep per instance. '
             'Older backups are automatically deleted during cleanup.',
    )
    instance_count = fields.Integer(
        string='Instances',
        compute='_compute_instance_count',
    )

    def _compute_instance_count(self):
        data = self.env['saas.instance']._read_group(
            [('plan_id', 'in', self.ids)],
            ['plan_id'],
            ['__count'],
        )
        counts = {plan.id: count for plan, count in data}
        for rec in self:
            rec.instance_count = counts.get(rec.id, 0)
