#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$SCRIPT_DIR"
INSTALL_ROOT="/opt/wancontrol"
VENV_PATH="$INSTALL_ROOT/venv"
SERVICE_FILE="/etc/systemd/system/wancontrol.service"
SUDOERS_FILE="/etc/sudoers.d/wancontrol"
LOGROTATE_FILE="/etc/logrotate.d/wancontrol"
CONFIG_FILE="/etc/wancontrol/config.yaml"
LOGGING_FILE="/etc/wancontrol/logging.yaml"

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "install.sh must be run as root." >&2
        exit 1
    fi
}

warn_os() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        if [[ "${ID:-}" != "debian" && "${ID:-}" != "ubuntu" && "${ID_LIKE:-}" != *"debian"* ]]; then
            echo "Warning: install.sh is designed for Debian/Ubuntu; continuing anyway." >&2
        fi
    else
        echo "Warning: /etc/os-release not found; unable to verify OS." >&2
    fi
}

check_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Python 3.10+ is required, but python3 was not found." >&2
        exit 1
    fi

    python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required.")
PY
}

uninstall() {
    if systemctl list-unit-files | grep -q '^wancontrol\.service'; then
        systemctl stop wancontrol || true
        systemctl disable wancontrol || true
    fi

    rm -rf "$INSTALL_ROOT"
    rm -f "$SUDOERS_FILE" "$LOGROTATE_FILE" "$SERVICE_FILE"
    systemctl daemon-reload

    cat <<'EOF'
WANControl v2 has been uninstalled from /opt and systemd integration removed.
/etc/wancontrol and /var/lib/wancontrol were preserved.
EOF
}

install_packages() {
    apt-get install -y iproute2 iputils-ping bind9-dnsutils curl
}

ensure_user() {
    if ! id wancontrol >/dev/null 2>&1; then
        useradd --system --no-create-home --shell /usr/sbin/nologin wancontrol
    fi
}

create_dirs() {
    install -d -m 0750 -o root -g wancontrol /etc/wancontrol
    install -d -m 0750 -o wancontrol -g wancontrol /var/lib/wancontrol
    install -d -m 0750 -o wancontrol -g wancontrol /var/lib/wancontrol/logs
    install -d -m 0750 -o wancontrol -g wancontrol /run/wancontrol
    install -d -m 0750 -o root -g wancontrol "$INSTALL_ROOT"
}

install_python_deps() {
    python3 -m venv "$VENV_PATH"
    "$VENV_PATH/bin/pip" install --upgrade pip
    "$VENV_PATH/bin/pip" install -r "$APP_ROOT/requirements.txt"
}

copy_app() {
    rm -rf "$INSTALL_ROOT/wancontrol" "$INSTALL_ROOT/frontend"
    cp -r "$APP_ROOT/wancontrol" "$INSTALL_ROOT/"
    cp "$APP_ROOT/discover_interfaces.py" "$INSTALL_ROOT/"
    cp "$APP_ROOT/logging.yaml" "$INSTALL_ROOT/"
    chown -R root:wancontrol "$INSTALL_ROOT"
    chmod -R 750 "$INSTALL_ROOT"
}

build_frontend() {
    if ! command -v npm >/dev/null 2>&1; then
        echo "Warning: npm not found; skipping frontend build." >&2
        return
    fi

    (
        cd "$APP_ROOT/frontend"
        npm ci
        npm run build
    )

    mkdir -p "$INSTALL_ROOT/frontend"
    rm -rf "$INSTALL_ROOT/frontend/dist"
    cp -r "$APP_ROOT/frontend/dist" "$INSTALL_ROOT/frontend/dist"
    chown -R root:wancontrol "$INSTALL_ROOT/frontend"
    chmod -R 750 "$INSTALL_ROOT/frontend"
}

install_config() {
    if [[ ! -f "$CONFIG_FILE" ]]; then
        cp "$APP_ROOT/config.yaml" "$CONFIG_FILE"
        chown root:wancontrol "$CONFIG_FILE"
        chmod 0640 "$CONFIG_FILE"
    fi

    if [[ ! -f "$LOGGING_FILE" ]]; then
        cp "$APP_ROOT/logging.yaml" "$LOGGING_FILE"
        chown root:wancontrol "$LOGGING_FILE"
        chmod 0640 "$LOGGING_FILE"
    fi
}

install_sudoers() {
    local ip_bin
    local sysctl_bin
    local tmp_file

    ip_bin="$(command -v ip)"
    sysctl_bin="$(command -v sysctl)"
    tmp_file="$(mktemp)"

    sed \
        -e "s#/sbin/ip#${ip_bin}#g" \
        -e "s#/sbin/sysctl#${sysctl_bin}#g" \
        "$APP_ROOT/deploy/wancontrol.sudoers" > "$tmp_file"

    chmod 0440 "$tmp_file"
    visudo -c -f "$tmp_file"
    cp "$tmp_file" "$SUDOERS_FILE"
    chmod 0440 "$SUDOERS_FILE"
    rm -f "$tmp_file"
}

install_logrotate() {
    cp "$APP_ROOT/deploy/wancontrol.logrotate" "$LOGROTATE_FILE"
}

install_service() {
    cp "$APP_ROOT/deploy/wancontrol.service" "$SERVICE_FILE"
    systemctl daemon-reload
    systemctl enable wancontrol
}

warn_secret_key() {
    if grep -q 'REPLACE_ME_run_python_secrets_token_hex_32' "$CONFIG_FILE"; then
        cat <<'EOF' >&2
WARNING: /etc/wancontrol/config.yaml still contains the placeholder secret_key.
Set a real 32+ character secret before starting WANControl.
EOF
    fi
}

print_next_steps() {
    cat <<'EOF'
┌─────────────────────────────────────────────────────────┐
│  WANControl v2 installed successfully                   │
│                                                         │
│  Next steps:                                            │
│  1. Edit /etc/wancontrol/config.yaml                    │
│     - Set a real secret_key (32+ chars)                 │
│     - Configure your WAN interfaces                     │
│  2. Run interface discovery:                            │
│     python3 /opt/wancontrol/discover_interfaces.py      │
│  3. Start the service:                                  │
│     systemctl start wancontrol                          │
│  4. Check status:                                       │
│     systemctl status wancontrol                         │
│     journalctl -u wancontrol -f                         │
└─────────────────────────────────────────────────────────┘
EOF
}

main() {
    require_root

    if [[ "${1:-}" == "--uninstall" ]]; then
        uninstall
        exit 0
    fi

    warn_os
    check_python
    install_packages
    ensure_user
    create_dirs
    install_python_deps
    copy_app
    build_frontend
    install_config
    install_sudoers
    install_logrotate
    install_service
    warn_secret_key
    print_next_steps
}

main "$@"
