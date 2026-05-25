import logging

from . import models
from . import controllers

_logger = logging.getLogger(__name__)


def _activate_arabic(env):
    """Activate Arabic (ar_001) and add it to every website.

    Hosted in a post-install hook rather than a ``<function>``
    invocation in a data file because Odoo's XML-data function-call
    plumbing has been inconsistent across versions about whether
    positional args supplied via ``eval`` actually reach the callee
    — calling the method from Python sidesteps that entirely.

    Idempotent: ``_activate_lang`` is a no-op if the language is
    already active, and ``(4, id)`` is a "link if not linked" command
    on a many2many.
    """
    try:
        env['res.lang']._activate_lang('ar_001')
    except Exception:
        _logger.exception("Could not activate Arabic (ar_001).")
        return

    lang = env.ref('base.lang_ar_001', raise_if_not_found=False)
    if not lang:
        _logger.warning(
            "Arabic activated but base.lang_ar_001 xmlid not found — "
            "skipping website language link.",
        )
        return

    Website = env.get('website')
    if Website is None:
        # ``website`` module not installed yet; nothing to link.
        return
    try:
        Website.search([]).write({'language_ids': [(4, lang.id)]})
    except Exception:
        _logger.exception(
            "Could not add Arabic to website.language_ids.",
        )
