#!/usr/bin/env bash
set -euo pipefail

# Usage: sudo bash uninstall.sh

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

run systemctl stop wancontrol || true
run systemctl disable wancontrol || true

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "[dry-run] python3 /opt/wancontrol/wancontrol/network.py --restore-routes || true"
else
  python3 /opt/wancontrol/wancontrol/network.py --restore-routes || true
fi

# remove ip rules for routing_table_ids 100-252
if [[ "${DRY_RUN}" == "1" ]]; then
  echo "[dry-run] ip rule list | grep -E \"lookup (1[0-9]{2}|2[0-4][0-9]|25[0-2])\" | while read -r rule; do ip rule del \\$(echo \"$rule\" | sed 's/^[0-9]*:\\s*//') || true; done"
else
  ip rule list | grep -E "lookup (1[0-9]{2}|2[0-4][0-9]|25[0-2])" | while read -r rule; do
    ip rule del $(echo "$rule" | sed 's/^[0-9]*:\s*//') || true
  done
fi

run rm -f /etc/systemd/system/wancontrol.service
run rm -f /etc/sudoers.d/wancontrol
run rm -f /etc/logrotate.d/wancontrol
run systemctl daemon-reload

read -rp "Delete /etc/wancontrol/config.yaml? This cannot be undone. [y/N] " ans
[[ "$ans" == "y" || "$ans" == "Y" ]] && run rm -rf /etc/wancontrol || true

read -rp "Delete /var/lib/wancontrol/ (database + logs)? [y/N] " ans
[[ "$ans" == "y" || "$ans" == "Y" ]] && run rm -rf /var/lib/wancontrol || true

run rm -rf /opt/wancontrol
run rm -rf /run/wancontrol

run userdel wancontrol || true

echo "✓ WANControl uninstalled. Default routes have been restored."
