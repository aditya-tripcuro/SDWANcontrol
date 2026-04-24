# WANControl v2

SD-WAN load-balancing controller for Linux multi-WAN systems.

## Features

- Multi-WAN `failover` and `load_balance` routing modes (supports 2+ interfaces)
- Continuous ICMP, DNS, and HTTP health probing with weighted scoring
- **v2 Industrial UI**: Premium React dashboard with responsive Sidebar/Header layout
- Real-time charting via Recharts for latency, jitter, and throughput
- SQLite persistence for metrics, alerts, events, users, and API tokens
- Hot-reloadable YAML config via `SIGHUP` or API
- Production deployment assets for `systemd`, `sudoers`, and `logrotate`

## Requirements

- Debian or Ubuntu recommended
- Python 3.10+
- `iproute2`, `iputils-ping`, `bind9-dnsutils`, `curl`
- `sudo`, `systemd`, and optionally `npm` to rebuild the frontend
- Two or more WAN interfaces on the target Linux host

## Quick Install

```bash
git clone https://github.com/aditya-tripcuro/SDWANcontrol.git
cd SDWANcontrol
sudo ./install.sh
# Edit interfaces and gateways
sudo nano /etc/wancontrol/config.yaml
# Restart to apply changes
sudo systemctl restart wancontrol
```

## Configuration

Edit `/etc/wancontrol/config.yaml` for interfaces, scoring, server binding, retention, and alerts.

### Secret Key
The installer automatically generates a cryptographically secure `server.secret_key` in `/etc/wancontrol/config.yaml` on first install. No manual action is required.

### Interface discovery

Use the helper before editing `interfaces`:

```bash
python3 /opt/wancontrol/discover_interfaces.py
python3 /opt/wancontrol/discover_interfaces.py --yaml
```

Example output:

```text
┌────────┬──────────────┬────────────┬──────────────┬──────────────┐
│ Name   │ IPv4         │ Gateway    │ Carrier      │ Speed (Mb/s) │
├────────┼──────────────┼────────────┼──────────────┼──────────────┤
│ wan0   │ 192.0.2.10   │ 192.0.2.1  │ yes          │ 1000         │
│ wan1   │ 198.51.100.9 │ 198.51.100.1│ yes         │ 500          │
└────────┴──────────────┴────────────┴──────────────┴──────────────┘
```

### WAN modes (failover vs load_balance)

- `failover` keeps one active default route and switches to the backup link when the primary degrades or fails.
- `load_balance` keeps healthy interfaces in a nexthop pool and spreads traffic across them.

### Scoring thresholds

- `hard_fail_threshold` marks a WAN as failed once its score drops below the threshold.
- `hysteresis_switch_to_backup` and `hysteresis_return_to_primary` prevent route flapping.
- `recovery_margin` controls how much healthier a link must be before it re-enters service.

## Running

### As a systemd service

```bash
sudo systemctl start wancontrol
sudo systemctl status wancontrol
journalctl -u wancontrol -f
```

On first boot, WANControl prints a one-time admin password banner to stdout/journal if no users exist yet.

### Development mode (DRY_RUN)

```bash
WANCONTROL_DRY_RUN=1 python -m wancontrol
```

This is safe on a non-router machine and does not require root because network subprocess calls are skipped.

## API

### Authentication

- `POST /api/auth/login` accepts username/password and returns a JWT bearer token.
- Most endpoints accept `Authorization: Bearer <token>`.
- Token-based automation can use `X-API-Token: <raw token>`.

### Key endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/health` | `GET` | Liveness/version check |
| `/api/status` | `GET` | Overall controller status |
| `/api/status/interfaces` | `GET` | Per-interface status summary |
| `/api/metrics` | `GET` | Historical metrics |
| `/api/metrics/latest` | `GET` | Latest metrics per interface |
| `/api/events/switches` | `GET` | Recent failover / pool events |
| `/api/events/controller` | `GET` | Controller event log |
| `/api/alerts` | `GET` | Recent alerts |
| `/api/stream` | `GET` | Server-sent events feed |
| `/api/config/reload` | `POST` | Reload `config.yaml` |

## Dashboard

The v2 dashboard is an "Industrial Precision" React application served by Flask. Open `http://<host>:5000` to access the full operations suite:

- **Dashboard**: Live health metrics and active connection tracking.
- **Metrics**: Detailed historical performance analysis and throughput charts.
- **Events**: Chronological system logs and audit trails.
- **Alerts**: Real-time incident management and resolution tracking.
- **Config**: Responsive management of system and interface settings.

The UI automatically adapts to desktop (Sidebar) and mobile (Bottom Nav) layouts.

## Updating

```bash
git pull
sudo ./install.sh
```

`install.sh` is idempotent. It will refresh code and service assets without overwriting your existing `/etc/wancontrol/config.yaml`.

## Uninstalling

```bash
sudo ./install.sh --uninstall
```

This removes `/opt/wancontrol`, the systemd unit, sudoers fragment, and logrotate config. It preserves `/etc/wancontrol` and `/var/lib/wancontrol`.

## Troubleshooting

### Logs

- `journalctl -u wancontrol -f` for live service logs
- `/var/lib/wancontrol/logs/wancontrol.log` for rotating application logs
- `sudo systemctl status wancontrol` for recent failures and restart information

### Common errors

- `config file not found`: verify `WANCONTROL_CONFIG` or `/etc/wancontrol/config.yaml`
- `secret_key is still the default placeholder`: generate a new secret and restart
- `Missing prerequisite command`: install the missing system package, then restart

### sudo permission errors

If `/etc/sudoers.d/wancontrol` is missing or invalid, network actions from `wancontrol/network.py` will fail with sudo-related errors and routing changes will not be applied. Reinstall the fragment with `sudo ./install.sh` and compare it with [deploy/wancontrol.sudoers](deploy/wancontrol.sudoers). The installer validates the fragment with `visudo -c` before installing it.
