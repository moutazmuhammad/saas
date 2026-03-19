import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    _logger.info("saas_core: pre-migrate 18.0.4.0.0 — converting port fields to integer")

    # Convert xmlrpc_port and longpolling_port from varchar to integer
    # First, set any non-numeric or empty values to NULL
    cr.execute("""
        UPDATE saas_instance
        SET xmlrpc_port = NULL
        WHERE xmlrpc_port IS NOT NULL
          AND xmlrpc_port !~ '^[0-9]+$'
    """)
    cr.execute("""
        UPDATE saas_instance
        SET longpolling_port = NULL
        WHERE longpolling_port IS NOT NULL
          AND longpolling_port !~ '^[0-9]+$'
    """)

    # Now alter the column types
    cr.execute("""
        ALTER TABLE saas_instance
        ALTER COLUMN xmlrpc_port TYPE integer USING xmlrpc_port::integer
    """)
    cr.execute("""
        ALTER TABLE saas_instance
        ALTER COLUMN longpolling_port TYPE integer USING longpolling_port::integer
    """)

    _logger.info("saas_core: port fields converted to integer successfully")

    # Add max_backups column to saas_plan with default value
    cr.execute("""
        ALTER TABLE saas_plan
        ADD COLUMN IF NOT EXISTS max_backups integer DEFAULT 7
    """)

    _logger.info("saas_core: pre-migrate 18.0.4.0.0 complete")
