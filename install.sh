#!/usr/bin/env bash
set -euo pipefail

# Usage: sudo bash install.sh

DRY_RUN=0
FRESH=0
UNINSTALL=0
for a in "$@"; do
    if [[ "$a" == "--dry-run" ]]; then
        DRY_RUN=1
    elif [[ "$a" == "--uninstall" ]]; then
        UNINSTALL=1
    elif [[ "$a" == "--fresh" ]]; then
        FRESH=1
    fi
done

run() {
    if [[ "${DRY_RUN:-0}" == "1" ]]; then
        echo "[dry-run] $*"
    else
        "$@"
    fi
}

if [[ "$EUID" -ne 0 ]]; then
    echo "Error: this script must be run as root (use sudo)." >&2
    exit 1
fi

if [[ "$UNINSTALL" == "1" ]]; then
    run chmod +x uninstall.sh
    if [[ "$DRY_RUN" == "1" ]]; then
        ./uninstall.sh --dry-run
    else
        ./uninstall.sh
    fi
    exit 0
fi

restore_existing_routes() {
    if [[ -x /opt/wancontrol/venv/bin/python3 && -f /opt/wancontrol/wancontrol/network.py ]]; then
        if [[ "${DRY_RUN}" == "1" ]]; then
            echo "[dry-run] PYTHONPATH=/opt/wancontrol WANCONTROL_CONFIG=/etc/wancontrol/config.yaml /opt/wancontrol/venv/bin/python3 /opt/wancontrol/wancontrol/network.py --restore-routes"
        else
            PYTHONPATH=/opt/wancontrol WANCONTROL_CONFIG=/etc/wancontrol/config.yaml \
                /opt/wancontrol/venv/bin/python3 /opt/wancontrol/wancontrol/network.py --restore-routes || true
        fi
    fi
}

if [[ "$FRESH" == "1" ]]; then
    echo "Fresh install requested: stopping service, restoring routes, and wiping WANControl state."
    run systemctl stop wancontrol || true
    restore_existing_routes
    run rm -rf /etc/wancontrol /var/lib/wancontrol /opt/wancontrol /run/wancontrol
else
    # Stop service before updating code. Preserve the database because it may
    # contain route restore state needed after a crash or interrupted upgrade.
    echo "Stopping service for update..."
    run systemctl stop wancontrol || true
fi

# iputils-ping, bind9-dnsutils, and curl provide ping/dig/curl — required by the
# startup prerequisite check (wancontrol/network.py check_prerequisites). dig in
# particular is usually absent on minimal Debian, so omitting it breaks first boot.
run apt-get update && run apt-get install -y python3 python3-pip python3-venv iproute2 iputils-ping bind9-dnsutils curl nodejs npm

# Build frontend
echo "📦 Building frontend assets..."
if [[ -d "frontend" ]]; then
    (cd frontend && run npm install && run npm run build)
else
    echo "Warning: frontend directory not found, skipping build."
fi

# create system user
run bash -c "id -u wancontrol &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin wancontrol"

# copy project to /opt/wancontrol
run rm -rf /opt/wancontrol
run mkdir -p /opt/wancontrol
run cp -a . /opt/wancontrol/
run rm -f /opt/wancontrol/.env  # Prevent workspace .env from sabotaging /etc config

run python3 -m venv /opt/wancontrol/venv
run /opt/wancontrol/venv/bin/pip install --upgrade pip
run /opt/wancontrol/venv/bin/pip install -r /opt/wancontrol/requirements.txt

run mkdir -p /run/wancontrol /var/lib/wancontrol/logs /etc/wancontrol

# Snapshot current default routes before WANControl takes over
SNAPSHOT=/var/lib/wancontrol/route_snapshot.txt
if [[ ! -f "$SNAPSHOT" ]]; then
    if [[ "${DRY_RUN}" == "1" ]]; then
        echo "[dry-run] ip route show default > $SNAPSHOT"
    else
        ip route show default > "$SNAPSHOT" || true
        echo "Snapshotted default routes to $SNAPSHOT."
    fi
fi

run chown -R wancontrol:wancontrol /run/wancontrol /var/lib/wancontrol /etc/wancontrol

if [[ ! -f /etc/wancontrol/config.yaml ]]; then
    run cp /opt/wancontrol/config.yaml /etc/wancontrol/config.yaml
    SECRET=$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)
    if [[ "${DRY_RUN}" == "1" ]]; then
        echo "[dry-run] sed -i 's/REPLACE_ME_run_python_secrets_token_hex_32/<secret>/' /etc/wancontrol/config.yaml"
    else
        sed -i "s/REPLACE_ME_run_python_secrets_token_hex_32/$SECRET/" /etc/wancontrol/config.yaml || true
        sed -i "s/CHANGE_THIS_TO_A_RANDOM_STRING_MIN_32_CHARS/$SECRET/" /etc/wancontrol/config.yaml || true
    fi
    echo "Config written to /etc/wancontrol/config.yaml — edit interfaces and gateways before starting."
else
    echo "Config already exists at /etc/wancontrol/config.yaml — skipping."
fi

# NOTE: no sudoers fragment is installed — WANControl runs under systemd
# capabilities (CAP_NET_ADMIN / CAP_NET_RAW), so passwordless sudo is not used.
# Remove any stale fragment left behind by older installs.
run rm -f /etc/sudoers.d/wancontrol
run cp /opt/wancontrol/deploy/wancontrol.logrotate /etc/logrotate.d/wancontrol

run cp /opt/wancontrol/deploy/wancontrol.service /etc/systemd/system/wancontrol.service

# Initialize or reset first-run admin before service start so credentials are
# visible even if the controller cannot bind routes on the first attempt.
echo "Finalizing security setup..."
INIT_OUTPUT=$(run runuser -u wancontrol -- /opt/wancontrol/venv/bin/python3 /opt/wancontrol/init_admin.py)

# Install enabled-but-stopped. The operator must review /etc/wancontrol/config.yaml
# (interfaces, gateways, secret) and start the service manually. Starting before the
# config is correct risks tearing down the host's real default route (audit item 24).
run systemctl daemon-reload && run systemctl enable wancontrol

# Extract credentials if first-run admin setup was successful
if echo "$INIT_OUTPUT" | grep -q "INITIAL_SETUP_SUCCESS"; then
    ADMIN_USER=$(echo "$INIT_OUTPUT" | grep "ADMIN_USER:" | cut -d' ' -f2)
    ADMIN_PWD=$(echo "$INIT_OUTPUT" | grep "ADMIN_PWD:" | cut -d' ' -f2)

    echo ""
    echo "┌─────────────────────────────────────────────┐"
    echo "│  WANControl Installation Complete           │"
    echo "├─────────────────────────────────────────────┤"
    echo "│  Username : $ADMIN_USER"
    echo "│  Password : $ADMIN_PWD"
    echo "│  * Password reset required on first login.  │"
    echo "└─────────────────────────────────────────────┘"
    echo ""
else
    echo "✓ WANControl updated."
fi
echo "The service is ENABLED but NOT started."
echo "Next steps:"
echo "  1. Edit /etc/wancontrol/config.yaml (set interfaces, gateways, secret)."
echo "  2. Start it:   systemctl start wancontrol"
echo "  3. Watch logs: journalctl -u wancontrol -f"
echo ""
echo "Config: /etc/wancontrol/config.yaml"
