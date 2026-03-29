#!/bin/bash
set -e

# Odoo source is mounted at /opt/odoo (read-only)
# Structure: /opt/odoo/odoo-bin, /opt/odoo/odoo/, /opt/odoo/addons/

# Verify the source is mounted
if [ ! -d "/opt/odoo/odoo" ]; then
    echo "================================================================"
    echo "ERROR: Odoo source not found at /opt/odoo"
    echo ""
    echo "Mount the Odoo source directory as a volume:"
    echo "  -v /opt/odoo-source/18.0:/opt/odoo:ro"
    echo "================================================================"
    exit 1
fi

# Find the correct entry point
# odoo-bin exists in 10.0+ from git source
if [ -f "/opt/odoo/odoo-bin" ]; then
    ODOO_BIN="/opt/odoo/odoo-bin"
elif [ -f "/opt/odoo/openerp-server" ]; then
    ODOO_BIN="/opt/odoo/openerp-server"
else
    # Fallback: use the odoo package directly
    ODOO_BIN=""
fi

# Wait for PostgreSQL (reuse logic from original entrypoint if available)
: ${DB_HOST:=${PGHOST:='db'}}
: ${DB_PORT:=${PGPORT:='5432'}}
: ${DB_USER:=${PGUSER:='odoo'}}
: ${DB_PASSWORD:=${PGPASSWORD:='odoo'}}

# Simple wait-for-db (original entrypoint does this too)
if [ -n "$DB_HOST" ] && [ "$DB_HOST" != "false" ]; then
    for i in $(seq 1 30); do
        if python3 -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('$DB_HOST', $DB_PORT)); s.close()" 2>/dev/null; then
            break
        fi
        echo "Waiting for PostgreSQL at $DB_HOST:$DB_PORT... ($i/30)"
        sleep 1
    done
fi

if [ "$1" = "odoo" ] || [ "$1" = "odoo-bin" ] || [ -z "$1" ]; then
    shift 2>/dev/null || true
    if [ -n "$ODOO_BIN" ]; then
        exec python3 "$ODOO_BIN" -c /etc/odoo/odoo.conf "$@"
    else
        exec python3 -c "import odoo; odoo.cli.main()" "$@"
    fi
fi

# Allow arbitrary commands (shell, pip, etc.)
exec "$@"
