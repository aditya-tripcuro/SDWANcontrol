# WANControl v2

SD-WAN load-balancing controller for Linux multi-WAN systems.

## Features

- Multi-WAN `failover` and `load_balance` routing modes (supports 2+ interfaces)
- Continuous ICMP, DNS, and HTTP health probing with weighted scoring
- Flap damping — a route only changes after several consecutive confirmations, and never more often than a configurable minimum interval
- Restores the pre-existing default routes on stop/uninstall (IPv4 and IPv6)
- React dashboard with real-time charting (latency, jitter, loss, score)
- SQLite persistence for metrics, alerts, events, users, and API tokens
- Hot-reloadable YAML config via `SIGHUP` or API

## Requirements

- Debian or Ubuntu recommended
- Python 3.10+
- `iproute2`, `iputils-ping`, `bind9-dnsutils`, `curl`
- Two or more WAN interfaces

## Quick Install

```bash
git clone https://github.com/aditya-tripcuro/SDWANcontrol.git
cd SDWANcontrol
sudo ./install.sh
sudo nano /etc/wancontrol/config.yaml   # set interfaces and gateways
sudo systemctl restart wancontrol
```

`install.sh` is idempotent — it will not overwrite an existing `/etc/wancontrol/config.yaml`.

During installation, if no users exist yet, `install.sh` generates a one-time admin password and prints it to the console so you can log in immediately. Change it on first sign-in, or manage users from the terminal with `python -m wancontrol.cli user …`.

## Interface discovery

```bash
python3 /opt/wancontrol/discover_interfaces.py
python3 /opt/wancontrol/discover_interfaces.py --yaml
```

## Configuration

Edit `/etc/wancontrol/config.yaml`. Most values are hot-reloadable via `SIGHUP` or `POST /api/config/reload`. The path settings — `db_path`, `log_dir`, `lock_file`, and `heartbeat_file` — are read once at startup and require a restart to change (set them in the initial config or via the matching `WANCONTROL_*` environment variables).

### WAN modes

- `failover` — one active default route; switches to backup when primary degrades.
- `load_balance` — all healthy interfaces in a nexthop pool; traffic spread across them.

### Secret key

The installer generates a cryptographically secure `server.secret_key` on first install. To generate one manually:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Running

### As a systemd service

```bash
sudo systemctl start wancontrol
sudo systemctl status wancontrol
journalctl -u wancontrol -f
```

### Development mode (no root required)

```bash
WANCONTROL_DRY_RUN=1 python -m wancontrol
```

Network subprocess calls are skipped entirely in dry-run mode.

## API

Authentication: `POST /api/auth/login` returns a JWT bearer token. Pass it as `Authorization: Bearer <token>` or use a long-lived API token via `X-API-Token: <token>`.

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Liveness/version check (no auth) |
| `/api/status` | GET | Controller status |
| `/api/status/interfaces` | GET | Per-interface status |
| `/api/metrics` | GET | Historical metrics |
| `/api/metrics/latest` | GET | Latest metrics per interface |
| `/api/events/switches` | GET | Failover / pool events |
| `/api/events/controller` | GET | Controller event log |
| `/api/alerts` | GET | Recent alerts |
| `/api/stream` | GET | Server-sent events (status, metric, alert) |
| `/api/stream/ticket` | POST | Mint a short-lived, single-use ticket for the SSE stream |
| `/api/config/reload` | POST | Reload config.yaml |

A browser's `EventSource` cannot send auth headers, so SSE uses a ticket: `POST /api/stream/ticket` with normal auth, then open `GET /api/stream?ticket=<ticket>` (tickets are single-use and expire in 30s). Non-browser clients can skip the ticket and pass `Authorization`/`X-API-Token` headers directly to `/api/stream`.

Role hierarchy: `viewer` (read-only) < `operator` (can resolve alerts, reload config) < `admin` (full control).

## Dashboard

Open `http://<host>:<port>` after starting the service. The React SPA is served from `frontend/dist_app/` by the bundled waitress HTTP server.

## Updating

```bash
git pull
sudo ./install.sh
```

## Uninstalling

```bash
sudo ./install.sh --uninstall
```

Restores the pre-WANControl default routes, then removes `/opt/wancontrol`, the systemd unit, and the logrotate config. Preserves `/etc/wancontrol` and `/var/lib/wancontrol`. (No sudoers fragment is installed — the service runs under the `CAP_NET_ADMIN`/`CAP_NET_RAW` systemd capabilities.)

## Logs and troubleshooting

- `journalctl -u wancontrol -f` — live service logs
- `/var/lib/wancontrol/logs/wancontrol.log` — rotating application log

Common errors:

| Error | Fix |
|---|---|
| `config file not found` | Check `WANCONTROL_CONFIG` or `/etc/wancontrol/config.yaml` |
| `secret_key is still the default placeholder` | Generate a new key and set it in config or `WANCONTROL_SECRET_KEY` env var |
| `missing prerequisite command(s)` | Install the missing tool (`ip`, `ping`, `dig`, or `curl`) and restart |
| Routing / "permission denied" on `ip` | Confirm the service has its capabilities: `systemctl cat wancontrol \| grep Capabilities` should show `CAP_NET_ADMIN CAP_NET_RAW`. The service does not use sudoers. |
