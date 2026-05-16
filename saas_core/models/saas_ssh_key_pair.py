from odoo import fields, models


class SaasSshKeyPair(models.Model):
    _name = 'saas.ssh.key.pair'
    _description = 'SSH Key Pair'
    _order = 'name'

    name = fields.Char(
        string='Name',
        required=True,
        help='Descriptive label for this key pair (e.g. "Production EU Key").',
    )
    private_key_filename = fields.Char(
        string='Key Filename',
        default='id_rsa',
        help='Original filename of the private key (e.g. id_rsa, id_ed25519). '
             'Used when writing the key to a temporary file for SSH connections.',
    )
    type = fields.Selection(
        selection=[
            ('rsa', 'RSA'),
            ('dsa', 'DSA'),
            ('ecdsa', 'ECDSA'),
            ('ed25519', 'ED25519'),
        ],
        string='Key Type',
        default='rsa',
        help='Cryptographic algorithm of the private key. '
             'Must match the actual key file format.',
    )
    private_key_file = fields.Binary(
        string='Private Key File',
        groups='saas_core.group_saas_manager',
        help='PEM-encoded private key file. Restricted to SaaS Managers; '
             'never expose this field to regular users via JSON-RPC.',
    )
    private_key_file_name = fields.Char(
        string='Upload Filename',
        help='Filename detected during upload (internal use).',
    )
