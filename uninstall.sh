#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   sudo bash uninstall.sh              # remove service/binaries, prompt for data
#   sudo bash uninstall.sh --yes        # remove service/binaries without prompts, keep data
#   sudo bash uninstall.sh --purge      # remove service/binaries and all WANControl data
#   sudo bash uninstall.sh --dry-run

DRY_RUN=0
YES=0
PURGE=0

for a in "$@"; do
    case "$a" in
        --dry-run) DRY_RUN=1 ;;
        -y|--yes) YES=1 ;;
        --purge|--fresh) PURGE=1; YES=1 ;;
    esac
done

run() {
    if [[ "${DRY_RUN}" == "1" ]]; then
        echo "[dry-run] $*"
    else
        "$@"
    fi
}

if [[ "$EUID" -ne 0 ]]; then
    echo "Error: this script must be run as root (use sudo)." >&2
    exit 1
fi

restore_routes() {
    SNAPSHOT=/var/lib/wancontrol/route_snapshot.txt

    if [[ -f "$SNAPSHOT" && -s "$SNAPSHOT" ]]; then
        # Restore from bash-level snapshot — no Python required
        if [[ "${DRY_RUN}" == "1" ]]; then
            echo "[dry-run] Restore default routes from $SNAPSHOT:"
            cat "$SNAPSHOT" | sed 's/^/[dry-run]   ip route replace /'
        else
            # $route_line is intentionally UNQUOTED so each "default via ... dev
            # ... metric ..." line splits into separate args for `ip`. Disable
            # globbing first so a stray glob char can't expand to filenames.
            # Best-effort (|| true): some `ip route show` attributes (e.g.
            # proto dhcp) may not round-trip; the Python --restore-routes
            # fallback below handles those correctly.
            set -f
            while IFS= read -r route_line; do
                [[ -z "$route_line" ]] && continue
                # Each line is e.g. "default via 192.168.1.1 dev eth0 proto dhcp metric 100"
                ip route replace $route_line 2>/dev/null || true
            done < "$SNAPSHOT"
            set +f
            echo "Default routes restored from snapshot."
        fi
    elif [[ -x /opt/wancontrol/venv/bin/python3 && -f /opt/wancontrol/wancontrol/network.py ]]; then
        # Fallback: use Python + DB if snapshot file is missing
        if [[ "${DRY_RUN}" == "1" ]]; then
            echo "[dry-run] PYTHONPATH=/opt/wancontrol WANCONTROL_CONFIG=/etc/wancontrol/config.yaml /opt/wancontrol/venv/bin/python3 /opt/wancontrol/wancontrol/network.py --restore-routes"
        else
            PYTHONPATH=/opt/wancontrol WANCONTROL_CONFIG=/etc/wancontrol/config.yaml \
                /opt/wancontrol/venv/bin/python3 /opt/wancontrol/wancontrol/network.py --restore-routes || true
        fi
    else
        echo "Warning: no route snapshot found and Python env unavailable — default routes not restored." >&2
    fi
}

run systemctl stop wancontrol || true
restore_routes
run systemctl disable wancontrol || true

run rm -f /etc/systemd/system/wancontrol.service
run rm -f /etc/sudoers.d/wancontrol
run rm -f /etc/logrotate.d/wancontrol
run systemctl daemon-reload

run rm -rf /opt/wancontrol
run rm -rf /run/wancontrol

if [[ "$PURGE" == "1" ]]; then
    run rm -rf /etc/wancontrol /var/lib/wancontrol
else
    if [[ "$YES" == "0" ]]; then
        read -rp "Delete /etc/wancontrol config? [y/N] " ans
        [[ "$ans" == "y" || "$ans" == "Y" ]] && run rm -rf /etc/wancontrol

        read -rp "Delete /var/lib/wancontrol database and logs? [y/N] " ans
        [[ "$ans" == "y" || "$ans" == "Y" ]] && run rm -rf /var/lib/wancontrol
    fi
fi

run userdel wancontrol || true

echo "WANControl uninstalled. Saved routes were restored before files were removed."
