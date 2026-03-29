#!/bin/bash
# Safe pip installer for Odoo containers
# Installs to /var/lib/odoo/pip_packages (persisted via data volume)
# Skips if requirements haven't changed (checksum)

set -e

REQ_FILE="/etc/odoo/requirements.txt"
PKG_DIR="/var/lib/odoo/pip_packages"
CHECKSUM_FILE="${PKG_DIR}/.requirements.md5"

# Ensure package directory exists
mkdir -p "$PKG_DIR"

# Skip if requirements file is empty or missing
if [ ! -s "$REQ_FILE" ]; then
    exec /entrypoint-light.sh odoo "$@"
fi

# Check if requirements changed since last install
CURRENT_MD5=$(md5sum "$REQ_FILE" | awk '{print $1}')
STORED_MD5=""
if [ -f "$CHECKSUM_FILE" ]; then
    STORED_MD5=$(cat "$CHECKSUM_FILE")
fi

if [ "$CURRENT_MD5" = "$STORED_MD5" ]; then
    echo "[pip-install] Packages up to date, skipping install."
else
    echo "[pip-install] Installing packages from requirements.txt..."
    pip3 install \
        --target="$PKG_DIR" \
        --upgrade \
        --no-warn-script-location \
        -r "$REQ_FILE" 2>&1 | tail -20 || {
            echo "[pip-install] WARNING: Some packages may have failed."
            echo "[pip-install] Odoo will still start."
        }
    echo "$CURRENT_MD5" > "$CHECKSUM_FILE"
    echo "[pip-install] Done."
fi

# Start Odoo via the light entrypoint
exec /entrypoint-light.sh odoo "$@"
