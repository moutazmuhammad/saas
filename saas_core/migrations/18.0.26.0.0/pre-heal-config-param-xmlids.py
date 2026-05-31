"""Heal config params that exist by key but lost their ir.model.data xmlid.

When a setting with ``config_parameter='saas_master.X'`` is saved before
the module ever loaded the matching XML record, ``set_param`` creates the
``ir_config_parameter`` row WITHOUT an xmlid. On a later upgrade the
``noupdate`` data loader can't find the xmlid, tries to CREATE the row,
and hits ``ir_config_parameter_key_uniq`` — the upgrade crashes (observed
on saas.odex.sa with saas_master.max_instances_per_user).

Runs as a ``pre`` migration so it executes BEFORE data/ir_config_parameter.xml
is loaded this pass. We backfill the missing xmlid (rather than delete the
row) so the operator's configured value is preserved; the loader then
finds the xmlid and skips creation.

Only the params actually declared in data/ir_config_parameter.xml are
healed — creating an xmlid for anything else would make end-of-upgrade
orphan cleanup delete that param along with its value.
"""
import logging

_logger = logging.getLogger(__name__)

# Suffixes after "saas_master." — xmlid is "config_param_<suffix>".
# Mirrors data/ir_config_parameter.xml exactly.
_PARAM_SUFFIXES = [
    'default_instance_starting_port', 'trial_days', 'max_instances_per_user',
    'worker_price', 'storage_price_per_gb',
    'custom_plan_min_workers', 'custom_plan_max_workers',
    'custom_plan_min_storage', 'custom_plan_max_storage',
    'custom_plan_cpu_per_worker', 'custom_plan_ram_per_worker',
    'custom_plan_users_per_worker_min', 'custom_plan_users_per_worker_max',
    'custom_plan_yearly_discount_pct',
    'hosting_worker_price', 'hosting_storage_price_per_gb',
    'hosting_min_workers', 'hosting_max_workers',
    'hosting_min_storage', 'hosting_max_storage',
    'hosting_cpu_per_worker', 'hosting_ram_per_worker',
    'hosting_yearly_discount_pct', 'hosting_daily_backup_price',
]


def migrate(cr, version):
    healed = 0
    for suffix in _PARAM_SUFFIXES:
        key = 'saas_master.' + suffix
        name = 'config_param_' + suffix
        cr.execute(
            "SELECT id FROM ir_config_parameter WHERE key = %s", (key,))
        row = cr.fetchone()
        if not row:
            continue  # param not set on this DB → loader will create it cleanly
        param_id = row[0]
        cr.execute(
            "SELECT 1 FROM ir_model_data WHERE module = 'saas_core' AND name = %s",
            (name,))
        if cr.fetchone():
            continue  # xmlid already present → nothing to heal
        cr.execute(
            """INSERT INTO ir_model_data
                   (module, name, model, res_id, noupdate, create_date, write_date)
               VALUES ('saas_core', %s, 'ir.config_parameter', %s, true, now(), now())""",
            (name, param_id))
        healed += 1
    if healed:
        _logger.info("Healed %s orphaned saas_master config-param xmlid(s)", healed)
