"""Activate Arabic for instances upgrading to 18.0.5.1.0.

Pre-installed modules never run ``post_init_hook`` on later upgrades —
only on the original install — so we duplicate the activation here so
customers who already had ``saas_website`` installed when bilingual
support was added still get Arabic enabled. Idempotent.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        env['res.lang']._activate_lang('ar_001')
    except Exception:
        _logger.exception(
            "post-update 18.0.5.1.0: could not activate Arabic (ar_001).",
        )
        return

    lang = env.ref('base.lang_ar_001', raise_if_not_found=False)
    if not lang:
        _logger.warning(
            "post-update 18.0.5.1.0: ar_001 activated but xmlid "
            "base.lang_ar_001 not found — skipping website link.",
        )
        return

    try:
        env['website'].search([]).write({'language_ids': [(4, lang.id)]})
    except Exception:
        _logger.exception(
            "post-update 18.0.5.1.0: could not add Arabic to "
            "website.language_ids.",
        )

    # Apply our Arabic dictionary to every saas_website view.
    try:
        from odoo.addons.saas_website.i18n.ar_translations import (
            apply_arabic_translations,
        )
        apply_arabic_translations(env)
    except Exception:
        _logger.exception(
            "post-update 18.0.5.1.0: could not apply Arabic "
            "translation dictionary.",
        )
