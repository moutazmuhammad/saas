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

ERR_FILE="${PKG_DIR}/.pip_error"

if [ "$CURRENT_MD5" = "$STORED_MD5" ]; then
    echo "[pip-install] Packages up to date, skipping install."
else
    echo "[pip-install] Force-installing packages from requirements.txt..."
    # Capture output so a failure can be surfaced to the customer, and
    # force-reinstall so packages are always applied cleanly. Odoo still
    # starts even if install fails (so the instance stays reachable).
    PIP_OUT=$(pip3 install \
        --target="$PKG_DIR" \
        --upgrade \
        --force-reinstall \
        --no-warn-script-location \
        -r "$REQ_FILE" 2>&1)
    PIP_RC=$?
    echo "$PIP_OUT" | tail -25
    if [ "$PIP_RC" -eq 0 ]; then
        # Success: record checksum so we don't reinstall next boot, clear error.
        echo "$CURRENT_MD5" > "$CHECKSUM_FILE"
        rm -f "$ERR_FILE"
        echo "[pip-install] Done."
    else
        # Failure: keep the error for the platform to read; do NOT stamp the
        # checksum, so the next deploy retries the install.
        echo "$PIP_OUT" | tail -40 > "$ERR_FILE"
        echo "[pip-install] WARNING: pip install failed (rc=$PIP_RC). Odoo will still start."
    fi
fi

# Start Odoo via the light entrypoint
exec /entrypoint-light.sh odoo "$@"
