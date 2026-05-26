"""Re-fire the Arabic activation + translation pass.

The 18.0.5.1.0 migration may have run during an earlier failed
upgrade and not be replayed by Odoo on subsequent upgrades — bumping
the manifest version to 18.0.5.1.1 forces this script to run, and we
duplicate the activation + translation logic here so Arabic is
guaranteed to be on, linked to every website, and applied to every
view.

Logs are deliberately verbose so we can read the server log and see
which step succeeded / which failed.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _logger.info("====== saas_website 18.0.5.1.1 post-update START ======")

    # 1. Activate ar_001.
    try:
        env['res.lang']._activate_lang('ar_001')
        _logger.info(
            "[saas_website] _activate_lang('ar_001') OK.",
        )
    except Exception:
        _logger.exception(
            "[saas_website] _activate_lang('ar_001') FAILED.",
        )
        return

    # 2. Confirm the language record exists and find its id.
    lang = env.ref('base.lang_ar_001', raise_if_not_found=False)
    if not lang:
        _logger.error(
            "[saas_website] env.ref('base.lang_ar_001') returned no "
            "record — bailing.",
        )
        return
    _logger.info(
        "[saas_website] Arabic language record id=%s active=%s "
        "url_code=%r direction=%s",
        lang.id, lang.active, lang.url_code, lang.direction,
    )

    # 3. Link Arabic to every website.
    websites = env['website'].search([])
    if not websites:
        _logger.warning(
            "[saas_website] No website records found — language not "
            "linked to any website.",
        )
    else:
        for w in websites:
            try:
                w.write({'language_ids': [(4, lang.id)]})
                _logger.info(
                    "[saas_website] Linked Arabic to website %s "
                    "(id=%s). language_ids now: %s",
                    w.name, w.id, w.language_ids.mapped('code'),
                )
            except Exception:
                _logger.exception(
                    "[saas_website] Could not link Arabic to website %s.",
                    w.name,
                )

    # 4. Apply Arabic dictionary to every saas_website view.
    try:
        from odoo.addons.saas_website.i18n.ar_translations import (
            apply_arabic_translations,
        )
        apply_arabic_translations(env)
        _logger.info(
            "[saas_website] apply_arabic_translations() returned.",
        )
    except Exception:
        _logger.exception(
            "[saas_website] apply_arabic_translations() FAILED.",
        )

    _logger.info("====== saas_website 18.0.5.1.1 post-update END ======")
