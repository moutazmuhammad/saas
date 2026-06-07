from datetime import date
from dateutil.relativedelta import relativedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSnapshotBilling(TransactionCase):
    """Merge-snapshot-into-renewal billing (M1-M4).

    The snapshot add-on is ALWAYS monthly. When the merge toggle is ON it
    rides on the renewal invoice ONLY for the month whose backup date is
    due on/before that renewal; otherwise it stays on its own monthly
    cycle. The single ``daily_backup_next_invoice_date`` is the source of
    truth, so a month can never be billed twice.
    """

    def setUp(self):
        super().setUp()
        self.icp = self.env['ir.config_parameter'].sudo()
        self.icp.set_param('saas_master.snapshot_price_per_gb', '5.0')
        self.icp.set_param('saas_master.hosting_worker_price', '10.0')
        self.icp.set_param('saas_master.hosting_storage_price_per_gb', '0.3')
        self.product = self.env['saas.product'].sudo().search(
            [('is_hosting', '=', True)], limit=1)
        if not self.product:
            self.product = self.env['saas.product'].sudo().create({
                'name': 'TEST Hosting', 'is_hosting': True, 'is_published': True,
            })
        self.plan = self.env['saas.plan'].sudo().create({
            'name': 'TEST Snap Plan', 'is_custom': True,
            'workers': 4, 'storage_limit': 50, 'cpu_limit': 2.0, 'ram_limit': '2g',
            'price': 55.0, 'yearly_price': 528.0,
            'currency_id': self.env.company.currency_id.id,
            'saas_product_ids': [(6, 0, [self.product.id])],
        })
        self.partner = self.env['res.partner'].sudo().search([], limit=1)
        self.domain = self.env['saas.based.domain'].sudo().search([], limit=1) \
            or self.env['saas.based.domain'].sudo().create({'name': 'snap.example.com'})
        self.bp = self.env['product.product'].sudo()  # resolved lazily below

    def _backup_product(self):
        return self.env['product.product'].sudo().search(
            [('default_code', '=', 'SAAS-BACKUP-ADDON')], limit=1)

    def _mk(self, sub, billing, snap_next, due=None):
        due = due or date(2026, 1, 1)
        inst = self.env['saas.instance'].sudo().create({
            'subdomain': sub, 'domain_id': self.domain.id,
            'partner_id': self.partner.id, 'saas_product_id': self.product.id,
            'plan_id': self.plan.id, 'billing_period': billing,
            'state': 'running', 'next_invoice_date': due,
        })
        inst.write({
            'daily_backup_enabled': True,
            'daily_backup_next_invoice_date': snap_next,
            'total_storage_bytes': 50 * (1024 ** 3),
        })
        return inst

    def _renewal_snapshot_lines(self, inst):
        bp = self._backup_product()
        so = self.env['sale.order'].sudo().search(
            [('origin', '=', 'SAAS:RENEWAL:%s' % inst.name)],
            order='id desc', limit=1)
        return [l for l in so.order_line if bp and l.product_id == bp]

    def test_merge_off_never_adds_snapshot(self):
        """Flag OFF: a renewal never carries a snapshot line (current
        behaviour), even when the backup month is due."""
        self.icp.set_param('saas_master.merge_snapshot_into_renewal_invoice', 'False')
        inst = self._mk('snapoff', 'monthly', date(2026, 1, 1))
        before = inst.daily_backup_next_invoice_date
        inst._generate_renewal_invoice()
        self.assertFalse(self._renewal_snapshot_lines(inst))
        self.assertEqual(inst.daily_backup_next_invoice_date, before)

    def test_merge_when_due(self):
        """Flag ON + backup due on the renewal date: one snapshot line
        (qty 1) is merged and the backup date advances by one month."""
        self.icp.set_param('saas_master.merge_snapshot_into_renewal_invoice', 'True')
        inst = self._mk('snapdue', 'monthly', date(2026, 1, 1))
        inst._generate_renewal_invoice()
        lines = self._renewal_snapshot_lines(inst)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].product_uom_qty, 1)
        self.assertAlmostEqual(lines[0].price_unit, 5.0, places=2)
        self.assertEqual(inst.daily_backup_next_invoice_date, date(2026, 2, 1))

    def test_no_merge_when_not_due(self):
        """Flag ON but the backup is due NEXT month: no snapshot line on
        this renewal, backup date untouched (standalone cron bills it)."""
        self.icp.set_param('saas_master.merge_snapshot_into_renewal_invoice', 'True')
        snap_next = date(2026, 2, 1)
        inst = self._mk('snapnd', 'monthly', snap_next, due=date(2026, 1, 1))
        inst._generate_renewal_invoice()
        self.assertFalse(self._renewal_snapshot_lines(inst))
        self.assertEqual(inst.daily_backup_next_invoice_date, snap_next)

    def test_yearly_merges_one_month(self):
        """Flag ON, yearly plan, backup due on the annual renewal: exactly
        ONE month merged (never 12x), backup date +1 month."""
        self.icp.set_param('saas_master.merge_snapshot_into_renewal_invoice', 'True')
        inst = self._mk('snapyr', 'yearly', date(2026, 1, 1))
        inst._generate_renewal_invoice()
        lines = self._renewal_snapshot_lines(inst)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].product_uom_qty, 1)  # one month, not 12
        self.assertEqual(inst.daily_backup_next_invoice_date, date(2026, 2, 1))

    def test_disabled_backup_omits_line(self):
        """Backups off: no snapshot line regardless of the flag."""
        self.icp.set_param('saas_master.merge_snapshot_into_renewal_invoice', 'True')
        inst = self._mk('snapxoff', 'monthly', date(2026, 1, 1))
        inst.daily_backup_enabled = False
        inst._generate_renewal_invoice()
        self.assertFalse(self._renewal_snapshot_lines(inst))

    def test_merged_renewal_counts_as_unpaid_backup(self):
        """M4: an unpaid renewal carrying a snapshot line is recognised by
        _daily_backup_unpaid_invoices (so it can pause snapshots)."""
        self.icp.set_param('saas_master.merge_snapshot_into_renewal_invoice', 'True')
        inst = self._mk('snapunp', 'monthly', date(2026, 1, 1))
        inst._generate_renewal_invoice()
        unpaid = inst._daily_backup_unpaid_invoices()
        # the merged renewal is unpaid and carries the backup line:
        self.assertTrue(unpaid)
        bp = self._backup_product()
        self.assertTrue(any(
            any(l.product_id == bp for l in m.invoice_line_ids)
            for m in unpaid
        ))
