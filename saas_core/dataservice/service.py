"""DataService — the two stateful primitives the platform composes everything from.

    snapshot(instance)                     -> saas.instance.backup (full-instance restic snapshot)
    materialize(snapshot, target=None, …)  -> restore the snapshot onto target

backup / restore / clone / migrate / DR are all compositions of these two. v1 delegates
to the already-proven implementations (restic full-instance backup + the 5-step restore);
it does NOT reimplement them, so behavior — verified on real infra — is unchanged.
"""

from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


class DataService:
    """Constructed with an Odoo Environment; operates on saas.instance records."""

    def __init__(self, env):
        self.env = env

    # -- primitive 1 --------------------------------------------------------
    def snapshot(self, instance):
        """Create a full-instance snapshot (restic → object storage).

        Delegates to saas.instance.backup._perform_full_instance_backup (the same
        code path the daily cron + the test button use). Returns the resulting
        completed saas.instance.backup record.
        """
        instance.ensure_one()
        Backup = self.env['saas.instance.backup'].sudo()
        Backup._perform_full_instance_backup(instance)
        snap = Backup.search([
            ('instance_id', '=', instance.id),
            ('is_full_instance', '=', True),
            ('state', '=', 'done'),
        ], order='id desc', limit=1)
        if not snap:
            raise RuntimeError(
                "DataService.snapshot: no completed full-instance backup found "
                "for instance '%s'." % instance.subdomain)
        return snap

    # -- primitive 2 --------------------------------------------------------
    def materialize(self, snapshot, target=None, neutralize=False):
        """Restore ``snapshot`` onto ``target`` (default: the snapshot's own instance).

        Delegates to saas.instance._do_restore_full_instance (the proven 5-step
        restore: stop → wipe → restic FS restore → DB restore → up → nginx).
        ``neutralize`` (disable mail/cron for non-prod clones) is reserved for the
        clone primitive and not implemented yet.
        """
        snapshot.ensure_one()
        target = target or snapshot.instance_id
        target.ensure_one()
        if neutralize:
            raise NotImplementedError(
                "DataService.materialize(neutralize=True) is not implemented yet — "
                "it is wired with the clone primitive (Phase 1 later / Phase 7).")
        target._do_restore_full_instance(snapshot.id)
        return target
