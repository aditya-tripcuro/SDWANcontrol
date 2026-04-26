#!/usr/bin/env bash
set -euo pipefail

# Usage: sudo bash install.sh

DRY_RUN=0
for a in "$@"; do
    if [[ "$a" == "--dry-run" ]]; then
        DRY_RUN=1
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

run apt-get update && run apt-get install -y python3 python3-pip python3-venv iproute2 nodejs

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

run python3 -m venv /opt/wancontrol/venv
run /opt/wancontrol/venv/bin/pip install --upgrade pip
run /opt/wancontrol/venv/bin/pip install -r /opt/wancontrol/requirements.txt

run mkdir -p /run/wancontrol /var/lib/wancontrol/logs /etc/wancontrol
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

run cp /opt/wancontrol/deploy/wancontrol.sudoers /etc/sudoers.d/wancontrol
run chmod 440 /etc/sudoers.d/wancontrol
run cp /opt/wancontrol/deploy/wancontrol.logrotate /etc/logrotate.d/wancontrol

cat > /etc/systemd/system/wancontrol.service <<'UNIT'
[Unit]
Description=WANControl v2 SD-WAN Controller
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=wancontrol
Group=wancontrol
ExecStart=/opt/wancontrol/venv/bin/python3 -m wancontrol
ExecStop=/opt/wancontrol/venv/bin/python3 /opt/wancontrol/wancontrol/network.py --restore-routes
WorkingDirectory=/opt/wancontrol
Environment=WANCONTROL_CONFIG=/etc/wancontrol/config.yaml
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

run systemctl daemon-reload && run systemctl enable wancontrol && run systemctl start wancontrol

sleep 2

PORT=$(python3 - <<'PY'
import sys
sys.path.insert(0, '/opt/wancontrol')
from wancontrol.database import Database
db = Database('/var/lib/wancontrol/wan.db')
try:
        db.initialize()
except Exception:
        pass
print(db.get_state('server_port', '5000'))
PY
)

PRIMARY_IP=$(hostname -I | awk '{print $1}')

echo "✓ WANControl installed and running."
echo "Access: http://${PRIMARY_IP}:${PORT}"
echo "Logs:   journalctl -u wancontrol -f"
echo "Config: /etc/wancontrol/config.yaml"
