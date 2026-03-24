import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Merge saas_container_physical_server, saas_psql_physical_server,
    and saas_proxy_server into the unified saas_server table."""
    if not version:
        return

    _logger.info("Pre-migration 18.0.8.0.0: unifying server models into saas_server")

    # ------------------------------------------------------------------
    # 1. Create the new saas_server table
    # ------------------------------------------------------------------
    cr.execute("""
        CREATE TABLE IF NOT EXISTS saas_server (
            id SERIAL PRIMARY KEY,
            sequence INTEGER DEFAULT 10,
            name VARCHAR NOT NULL,
            is_docker_host BOOLEAN DEFAULT FALSE,
            is_db_server BOOLEAN DEFAULT FALSE,
            is_proxy_server BOOLEAN DEFAULT FALSE,
            ssh_key_pair_id INTEGER,
            ssh_user VARCHAR DEFAULT 'root',
            ssh_port INTEGER DEFAULT 22,
            ip_v4 VARCHAR,
            private_ip_v4 VARCHAR,
            ssh_connect_using VARCHAR DEFAULT 'public_ip',
            docker_base_path VARCHAR DEFAULT '/home/odoo',
            psql_port INTEGER DEFAULT 5432,
            create_uid INTEGER,
            create_date TIMESTAMP,
            write_uid INTEGER,
            write_date TIMESTAMP
        )
    """)

    # ------------------------------------------------------------------
    # 2. Migrate Docker servers
    # ------------------------------------------------------------------
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'saas_container_physical_server' AND column_name = 'id'
    """)
    if cr.fetchone():
        _logger.info("Migrating Docker servers...")
        cr.execute("""
            INSERT INTO saas_server (
                id, sequence, name, is_docker_host,
                ssh_key_pair_id, ssh_user, ssh_port,
                ip_v4, private_ip_v4, ssh_connect_using,
                docker_base_path,
                create_uid, create_date, write_uid, write_date
            )
            SELECT
                id, sequence, name, TRUE,
                ssh_key_pair_id, ssh_user, ssh_port,
                ip_v4, private_ip_v4, ssh_connect_using,
                docker_base_path,
                create_uid, create_date, write_uid, write_date
            FROM saas_container_physical_server
        """)

    # ------------------------------------------------------------------
    # 3. Migrate DB servers — merge with existing if same IP
    # ------------------------------------------------------------------
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'saas_psql_physical_server' AND column_name = 'id'
    """)
    if cr.fetchone():
        _logger.info("Migrating DB servers...")

        # For DB servers that match an already-migrated Docker server by IP,
        # just enable the is_db_server flag and set psql_port.
        cr.execute("""
            UPDATE saas_server ss
            SET is_db_server = TRUE,
                psql_port = ps.psql_port
            FROM saas_psql_physical_server ps
            WHERE (
                (ss.ip_v4 IS NOT NULL AND ss.ip_v4 = ps.ip_v4)
                OR (ss.private_ip_v4 IS NOT NULL AND ss.private_ip_v4 = ps.private_ip_v4)
            )
        """)

        # For DB servers that don't match any existing Docker server, insert new rows.
        cr.execute("""
            INSERT INTO saas_server (
                sequence, name, is_db_server,
                ssh_key_pair_id, ssh_user, ssh_port,
                ip_v4, private_ip_v4, ssh_connect_using,
                psql_port,
                create_uid, create_date, write_uid, write_date
            )
            SELECT
                ps.sequence, ps.name, TRUE,
                ps.ssh_key_pair_id, ps.ssh_user, ps.ssh_port,
                ps.ip_v4, ps.private_ip_v4, ps.ssh_connect_using,
                ps.psql_port,
                ps.create_uid, ps.create_date, ps.write_uid, ps.write_date
            FROM saas_psql_physical_server ps
            WHERE NOT EXISTS (
                SELECT 1 FROM saas_server ss
                WHERE (
                    (ss.ip_v4 IS NOT NULL AND ss.ip_v4 = ps.ip_v4)
                    OR (ss.private_ip_v4 IS NOT NULL AND ss.private_ip_v4 = ps.private_ip_v4)
                )
            )
        """)

    # ------------------------------------------------------------------
    # 4. Migrate Proxy servers — merge with existing if same IP
    # ------------------------------------------------------------------
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'saas_proxy_server' AND column_name = 'id'
    """)
    if cr.fetchone():
        _logger.info("Migrating Proxy servers...")

        cr.execute("""
            UPDATE saas_server ss
            SET is_proxy_server = TRUE
            FROM saas_proxy_server pxs
            WHERE (
                (ss.ip_v4 IS NOT NULL AND ss.ip_v4 = pxs.ip_v4)
                OR (ss.private_ip_v4 IS NOT NULL AND ss.private_ip_v4 = pxs.private_ip_v4)
            )
        """)

        cr.execute("""
            INSERT INTO saas_server (
                sequence, name, is_proxy_server,
                ssh_key_pair_id, ssh_user, ssh_port,
                ip_v4, private_ip_v4, ssh_connect_using,
                create_uid, create_date, write_uid, write_date
            )
            SELECT
                pxs.sequence, pxs.name, TRUE,
                pxs.ssh_key_pair_id, pxs.ssh_user, pxs.ssh_port,
                pxs.ip_v4, pxs.private_ip_v4, pxs.ssh_connect_using,
                pxs.create_uid, pxs.create_date, pxs.write_uid, pxs.write_date
            FROM saas_proxy_server pxs
            WHERE NOT EXISTS (
                SELECT 1 FROM saas_server ss
                WHERE (
                    (ss.ip_v4 IS NOT NULL AND ss.ip_v4 = pxs.ip_v4)
                    OR (ss.private_ip_v4 IS NOT NULL AND ss.private_ip_v4 = pxs.private_ip_v4)
                )
            )
        """)

    # ------------------------------------------------------------------
    # 5. Fix sequence value for saas_server id
    # ------------------------------------------------------------------
    cr.execute("""
        SELECT setval('saas_server_id_seq',
                       COALESCE((SELECT MAX(id) FROM saas_server), 0) + 1,
                       false)
    """)

    # ------------------------------------------------------------------
    # 6. Re-point foreign keys on saas_instance
    # ------------------------------------------------------------------
    # docker_server_id already points to correct IDs (we preserved them)
    # db_server_id needs to be re-mapped from old psql server IDs to new saas_server IDs
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'saas_instance' AND column_name = 'db_server_id'
    """)
    if cr.fetchone():
        cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'saas_psql_physical_server' AND column_name = 'id'
        """)
        if cr.fetchone():
            _logger.info("Re-mapping db_server_id on saas_instance...")
            cr.execute("""
                UPDATE saas_instance si
                SET db_server_id = ss.id
                FROM saas_psql_physical_server ps
                JOIN saas_server ss ON (
                    ss.is_db_server = TRUE
                    AND (
                        (ss.ip_v4 IS NOT NULL AND ss.ip_v4 = ps.ip_v4)
                        OR (ss.private_ip_v4 IS NOT NULL AND ss.private_ip_v4 = ps.private_ip_v4)
                    )
                )
                WHERE si.db_server_id = ps.id
            """)

    # ------------------------------------------------------------------
    # 7. Re-point proxy_server_id on saas_based_domain
    # ------------------------------------------------------------------
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'saas_based_domain' AND column_name = 'proxy_server_id'
    """)
    if cr.fetchone():
        cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'saas_proxy_server' AND column_name = 'id'
        """)
        if cr.fetchone():
            _logger.info("Re-mapping proxy_server_id on saas_based_domain...")
            cr.execute("""
                UPDATE saas_based_domain bd
                SET proxy_server_id = ss.id
                FROM saas_proxy_server pxs
                JOIN saas_server ss ON (
                    ss.is_proxy_server = TRUE
                    AND (
                        (ss.ip_v4 IS NOT NULL AND ss.ip_v4 = pxs.ip_v4)
                        OR (ss.private_ip_v4 IS NOT NULL AND ss.private_ip_v4 = pxs.private_ip_v4)
                    )
                )
                WHERE bd.proxy_server_id = pxs.id
            """)

    # ------------------------------------------------------------------
    # 8. Re-point server_id on saas_docker_container
    # ------------------------------------------------------------------
    # server_id already references the same IDs as the old Docker server table
    # Just drop the old FK constraint so Odoo can create the new one
    cr.execute("""
        SELECT constraint_name FROM information_schema.table_constraints
        WHERE table_name = 'saas_docker_container'
          AND constraint_type = 'FOREIGN KEY'
          AND constraint_name LIKE '%%server_id%%'
    """)
    for row in cr.fetchall():
        cr.execute('ALTER TABLE saas_docker_container DROP CONSTRAINT IF EXISTS "%s"' % row[0])

    # ------------------------------------------------------------------
    # 9. Drop old FK constraints on saas_instance
    # ------------------------------------------------------------------
    cr.execute("""
        SELECT constraint_name FROM information_schema.table_constraints
        WHERE table_name = 'saas_instance'
          AND constraint_type = 'FOREIGN KEY'
          AND constraint_name LIKE '%%docker_server_id%%'
    """)
    for row in cr.fetchall():
        cr.execute('ALTER TABLE saas_instance DROP CONSTRAINT IF EXISTS "%s"' % row[0])

    cr.execute("""
        SELECT constraint_name FROM information_schema.table_constraints
        WHERE table_name = 'saas_instance'
          AND constraint_type = 'FOREIGN KEY'
          AND constraint_name LIKE '%%db_server_id%%'
    """)
    for row in cr.fetchall():
        cr.execute('ALTER TABLE saas_instance DROP CONSTRAINT IF EXISTS "%s"' % row[0])

    # Drop old FK on saas_based_domain
    cr.execute("""
        SELECT constraint_name FROM information_schema.table_constraints
        WHERE table_name = 'saas_based_domain'
          AND constraint_type = 'FOREIGN KEY'
          AND constraint_name LIKE '%%proxy_server_id%%'
    """)
    for row in cr.fetchall():
        cr.execute('ALTER TABLE saas_based_domain DROP CONSTRAINT IF EXISTS "%s"' % row[0])

    _logger.info("Pre-migration 18.0.8.0.0: completed")
