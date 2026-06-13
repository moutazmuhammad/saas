from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# ----------------------------------------------------------------------
# Customer wallet / account credit (A4).
#
# A wallet holds NON-REFUNDABLE, NON-WITHDRAWABLE platform credit. It is
# the single mechanism that guarantees a customer NEVER loses prepaid
# subscription value: whenever a subscription period is ended early
# (upgrade, monthly<->yearly switch) the unused value is converted into
# wallet credit instead of being forfeited, and every future SaaS invoice
# automatically consumes the available balance before charging the card.
#
# The wallet is an append-only LEDGER: each movement is a
# ``saas.wallet.transaction`` row carrying a SIGNED amount (+credit /
# -consumption) and a ``balance_after`` snapshot, so the history always
# reconciles to the stored balance. Balance is never edited directly.
# ----------------------------------------------------------------------


class SaasWallet(models.Model):
    _name = 'saas.wallet'
    _description = 'SaaS Customer Wallet (account credit)'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, ondelete='cascade',
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    balance = fields.Monetary(
        string='Wallet Balance', currency_field='currency_id',
        compute='_compute_balance', store=True, readonly=True,
        help='Available, non-refundable platform credit. Automatically '
             'consumed by future invoices.',
    )
    transaction_ids = fields.One2many(
        'saas.wallet.transaction', 'wallet_id', string='Ledger',
    )
    transaction_count = fields.Integer(compute='_compute_transaction_count')

    _sql_constraints = [
        ('partner_uniq', 'unique(partner_id)',
         'A customer can only have one wallet.'),
    ]

    @api.depends('transaction_ids.amount')
    def _compute_balance(self):
        for wallet in self:
            wallet.balance = round(
                sum(wallet.transaction_ids.mapped('amount')), 2)

    @api.depends('transaction_ids')
    def _compute_transaction_count(self):
        for wallet in self:
            wallet.transaction_count = len(wallet.transaction_ids)

    # ------------------------------------------------------------------
    # Lookup / creation
    # ------------------------------------------------------------------
    @api.model
    def _for_partner(self, partner, create=True):
        """Return the wallet for ``partner`` (the commercial entity), or an
        empty recordset. Creates it on demand when ``create`` is True.

        Credit always attaches to the COMMERCIAL partner so contacts under
        the same company share one balance."""
        if not partner:
            return self.browse()
        commercial = partner.commercial_partner_id or partner
        wallet = self.sudo().search(
            [('partner_id', '=', commercial.id)], limit=1)
        if not wallet and create:
            wallet = self.sudo().create({
                'partner_id': commercial.id,
                'currency_id': (
                    commercial.currency_id
                    or self.env.company.currency_id
                ).id,
            })
        return wallet

    def _lock(self):
        """Row-lock this wallet so concurrent credit/consume calls (renewal
        cron + portal action) can't race on the balance."""
        self.ensure_one()
        # Make sure a just-created wallet is in the DB before we lock its row.
        self.flush_recordset()
        self.env.cr.execute(
            "SELECT id FROM saas_wallet WHERE id = %s FOR UPDATE", (self.id,))
        self.invalidate_recordset(['balance'])

    # ------------------------------------------------------------------
    # Movements — the ONLY way the balance changes
    # ------------------------------------------------------------------
    def _credit(self, amount, origin, reason='', move=None, instance=None):
        """Add ``amount`` (>0) of credit to the wallet. Returns the
        transaction. Used to convert unused subscription value into
        credit (upgrade surplus, period switch) and to refund a consumed
        credit when its invoice is cancelled."""
        self.ensure_one()
        amount = round(amount or 0.0, 2)
        if amount <= 0:
            return self.env['saas.wallet.transaction']
        self._lock()
        return self.env['saas.wallet.transaction'].sudo().create({
            'wallet_id': self.id,
            'amount': amount,
            'balance_after': round(self.balance + amount, 2),
            'origin': origin,
            'reason': reason,
            'move_id': move.id if move else False,
            'instance_id': instance.id if instance else False,
        })

    def _consume(self, amount, origin='invoice_consumption', reason='',
                 move=None, instance=None):
        """Spend up to ``amount`` of credit. Spends MIN(amount, balance) so
        it never goes negative. Returns the amount actually consumed (>=0).

        Wallet credit may ONLY be spent on platform purchases — there is no
        withdraw / cash-out path anywhere in the codebase, by design
        (balances are non-refundable, non-withdrawable)."""
        self.ensure_one()
        amount = round(amount or 0.0, 2)
        if amount <= 0:
            return 0.0
        self._lock()
        spend = min(self.balance, amount)
        if spend <= 0:
            return 0.0
        self.env['saas.wallet.transaction'].sudo().create({
            'wallet_id': self.id,
            'amount': -spend,
            'balance_after': round(self.balance - spend, 2),
            'origin': origin,
            'reason': reason,
            'move_id': move.id if move else False,
            'instance_id': instance.id if instance else False,
        })
        return round(spend, 2)

    def _refund_move(self, move, reason=''):
        """Return any credit that was consumed by ``move`` back to the
        wallet (used when an unpaid invoice carrying a wallet line is
        cancelled). Idempotent: a move is only refunded once."""
        self.ensure_one()
        if not move:
            return 0.0
        Txn = self.env['saas.wallet.transaction'].sudo()
        consumed = sum(Txn.search([
            ('wallet_id', '=', self.id),
            ('move_id', '=', move.id),
            ('origin', '=', 'invoice_consumption'),
        ]).mapped('amount'))  # negative
        already = sum(Txn.search([
            ('wallet_id', '=', self.id),
            ('move_id', '=', move.id),
            ('origin', '=', 'refund'),
        ]).mapped('amount'))  # positive
        refundable = round(-consumed - already, 2)
        if refundable <= 0:
            return 0.0
        self._credit(
            refundable, origin='refund',
            reason=reason or _('Refund of wallet credit (invoice %s cancelled)')
            % (move.name or ''),
            move=move)
        return refundable

    def action_view_transactions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Wallet Ledger'),
            'res_model': 'saas.wallet.transaction',
            'view_mode': 'list,form',
            'domain': [('wallet_id', '=', self.id)],
            'context': {'default_wallet_id': self.id},
        }


class SaasWalletTransaction(models.Model):
    _name = 'saas.wallet.transaction'
    _description = 'SaaS Wallet Ledger Entry'
    _order = 'create_date desc, id desc'

    wallet_id = fields.Many2one(
        'saas.wallet', string='Wallet', required=True, ondelete='cascade',
        index=True,
    )
    partner_id = fields.Many2one(
        related='wallet_id.partner_id', store=True, string='Customer',
    )
    currency_id = fields.Many2one(
        related='wallet_id.currency_id', store=True,
    )
    amount = fields.Monetary(
        string='Amount', currency_field='currency_id', required=True,
        help='Signed: positive = credit added, negative = credit consumed.',
    )
    balance_after = fields.Monetary(
        string='Balance After', currency_field='currency_id', readonly=True,
        help='Running wallet balance immediately after this movement.',
    )
    origin = fields.Selection([
        ('subscription_credit', 'Unused subscription value'),
        ('upgrade_surplus', 'Upgrade surplus credit'),
        ('period_switch', 'Billing period switch credit'),
        ('invoice_consumption', 'Applied to invoice'),
        ('refund', 'Refund of consumed credit'),
        ('promo', 'Promotional credit'),
        ('manual', 'Manual adjustment'),
    ], string='Type', required=True, default='manual', index=True)
    reason = fields.Char(string='Description')
    move_id = fields.Many2one(
        'account.move', string='Invoice', ondelete='set null', index=True,
    )
    instance_id = fields.Many2one(
        'saas.instance', string='Instance', ondelete='set null',
    )

    def write(self, vals):
        # Ledger entries are immutable once written (audit integrity). Allow
        # only the framework-managed move_id cleanup (ondelete=set null).
        protected = set(vals) - {'move_id', 'instance_id'}
        if protected and any(t.id for t in self):
            raise UserError(_(
                "Wallet ledger entries are immutable and cannot be edited. "
                "Post a compensating entry instead."))
        return super().write(vals)

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount == 0:
                raise ValidationError(_("A ledger entry cannot be zero."))
