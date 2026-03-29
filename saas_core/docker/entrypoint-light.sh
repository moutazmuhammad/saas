#!/bin/bash
set -e

# Odoo source is expected at /opt/odoo (mounted read-only)
ODOO_BIN="/opt/odoo/odoo-bin"

# Older versions (11, 12) use openerp-server or odoo.py
if [ ! -f "$ODOO_BIN" ]; then
    if [ -f "/opt/odoo/odoo.py" ]; then
        ODOO_BIN="/opt/odoo/odoo.py"
    elif [ -f "/opt/odoo/openerp-server" ]; then
        ODOO_BIN="/opt/odoo/openerp-server"
    else
        echo "ERROR: Odoo source not found at /opt/odoo"
        echo "Mount the Odoo source directory as a volume: -v /opt/odoo-source/18.0:/opt/odoo:ro"
        exit 1
    fi
fi

# Ensure data directories exist and have correct ownership
dirs="/var/lib/odoo /etc/odoo /mnt/extra-addons"
for dir in $dirs; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
    fi
    # Fix ownership if running as root (e.g., during init)
    if [ "$(id -u)" = "0" ]; then
        chown odoo:odoo "$dir"
    fi
done

if [ "$1" = "odoo" ] || [ "$1" = "odoo-bin" ]; then
    shift
    exec python3 "$ODOO_BIN" -c /etc/odoo/odoo.conf "$@"
fi

# Allow running arbitrary commands (e.g., shell, pip)
exec "$@"
