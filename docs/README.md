# WANControl v2 - Complete Documentation

## Table of Contents

1. [Introduction](#introduction)
2. [Architecture Overview](#architecture-overview)
3. [Installation Guide](#installation-guide)
4. [Configuration Reference](#configuration-reference)
5. [API Reference](#api-reference)
6. [Frontend Dashboard](#frontend-dashboard)
7. [Authentication & Authorization](#authentication--authorization)
8. [Database Schema](#database-schema)
9. [Network Operations](#network-operations)
10. [Monitoring & Health Checks](#monitoring--health-checks)
11. [Controller State Machine](#controller-state-machine)
12. [Deployment Guide](#deployment-guide)
13. [Troubleshooting](#troubleshooting)
14. [Development Guide](#development-guide)

---

## Introduction

WANControl v2 is a production-grade SD-WAN load-balancing controller designed for Linux dual-WAN systems. It provides intelligent traffic distribution across multiple WAN interfaces with continuous health monitoring, automatic failover, and graceful degradation.

### Key Features

- **Dual-WAN Support**: Failover and load_balance routing modes
- **Health Probing**: Continuous ICMP, DNS, and HTTP probes with weighted scoring
- **Unified Server**: Flask REST API plus React dashboard served from the same process
- **SQLite Persistence**: Metrics, alerts, events, users, and API tokens
- **Hot-Reloadable Config**: YAML configuration via SIGHUP or API endpoint
- **Production Ready**: systemd service, sudoers fragments, and logrotate integration
- **Security**: JWT authentication, bcrypt password hashing, role-based access control

### System Requirements

| Component | Requirement |
|-----------|-------------|
| OS | Debian/Ubuntu (recommended), other Linux distributions |
| Python | 3.10+ |
| Network Tools | iproute2, iputils-ping, bind9-dnsutils, curl |
| System Services | sudo, systemd |
| Frontend Build | npm (optional, for rebuilding frontend) |
| Hardware | At least two WAN interfaces |

---

## Architecture Overview

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        WANControl v2                            │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐ │
│  │   Flask     │◄──►│    Auth     │◄──►│     Database        │ │
│  │    App      │    │   Module    │    │   (SQLite)          │ │
│  │  (app.py)   │    │  (auth.py)  │    │  (database.py)      │ │
│  └──────┬──────┘    └─────────────┘    └─────────────────────┘ │
│         │                                                     │
│         ▼                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐ │
│  │  Controller │◄──►│   Monitor   │◄──►│     Network         │ │
│  │   Module    │    │   Module    │    │     Layer           │ │
│  │(controller.)│    │ (monitor.py)│    │   (network.py)      │ │
│  └──────┬──────┘    └─────────────┘    └──────────┬──────────┘ │
│         │                                          │            │
│         │                                          ▼            │
│         │                                   ┌─────────────┐     │
│         │                                   │   System    │     │
│         │                                   │   Commands  │     │
│         │                                   │  (ip, ping, │     │
│         │                                   │   dig, curl)│     │
│         │                                   └─────────────┘     │
│         ▼                                                       │
│  ┌─────────────┐                                                │
│  │  Watchdog   │                                                │
│  │  (watchdog. │                                                │
│  └─────────────┘                                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │      External Systems         │
              ├───────────────────────────────┤
              │  • WAN Interfaces (wan0, wan1)│
              │  • Webhooks (ntfy, etc.)      │
              │  • Systemd Service            │
              └───────────────────────────────┘
```

### Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `app.py` | Flask REST API layer, serves React frontend, handles authentication middleware |
| `auth.py` | User management, bcrypt password hashing, JWT tokens, API tokens, RBAC |
| `config.py` | YAML configuration parsing, validation, environment variable overrides |
| `controller.py` | Main state machine, scoring engine, route orchestration, master election, alerting |
| `database.py` | SQLite data layer with WAL mode, migrations, retention policies |
| `monitor.py` | Parallel probe engine for ICMP, DNS, HTTP health checks |
| `network.py` | All Linux subprocess calls for network operations (iproute2, ping, dig, curl) |
| `watchdog.py` | Process health monitoring and recovery |
| `logging_config.py` | Structured logging setup with file rotation |
| `__main__.py` | Application entry point, Gunicorn integration, signal handling |

### Execution Flow

1. **Startup**: `__main__.py` loads configuration, initializes database, sets up logging
2. **Web Server**: Gunicorn starts Flask app with configured workers
3. **Controller Thread**: Background thread runs the main control loop
4. **Monitor Cycle**: Controller calls Monitor to collect metrics from all interfaces
5. **Scoring**: Monitor applies scoring algorithm based on probe results
6. **Decision**: Controller evaluates WAN states and determines routing changes
7. **Action**: Network module applies route changes via sudo commands
8. **Persistence**: All metrics, events, and state changes stored in SQLite
9. **Alerting**: Webhooks triggered for significant events

---

## Installation Guide

### Quick Install

```bash
# Clone repository
git clone https://github.com/aditya-tripcuro/SDWANcontrol.git
cd SDWANcontrol

# Run installer as root
sudo ./install.sh

# Edit configuration
sudo nano /etc/wancontrol/config.yaml

# Start service
sudo systemctl start wancontrol
sudo systemctl enable wancontrol

# Check status
sudo systemctl status wancontrol
journalctl -u wancontrol -f
```

### Manual Installation

#### Step 1: Install System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv iproute2 iputils-ping bind9-dnsutils curl
```

#### Step 2: Create System User and Directories

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin wancontrol

sudo mkdir -p /opt/wancontrol
sudo mkdir -p /etc/wancontrol
sudo mkdir -p /var/lib/wancontrol/logs
sudo mkdir -p /run/wancontrol

sudo chown -R wancontrol:wancontrol /var/lib/wancontrol
sudo chown -R wancontrol:wancontrol /run/wancontrol
```

#### Step 3: Set Up Python Virtual Environment

```bash
cd /opt/wancontrol
sudo -u wancontrol python3 -m venv venv
sudo -u wancontrol ./venv/bin/pip install --upgrade pip
sudo -u wancontrol ./venv/bin/pip install -r /path/to/requirements.txt
```

#### Step 4: Copy Application Files

```bash
sudo cp -r /path/to/wancontrol /opt/wancontrol/
sudo cp /path/to/discover_interfaces.py /opt/wancontrol/
sudo chown -R root:wancontrol /opt/wancontrol
sudo chmod -R 750 /opt/wancontrol
```

#### Step 5: Configure sudo Access

Create `/etc/sudoers.d/wancontrol`:

```sudoers
Defaults:wancontrol !requiretty

wancontrol ALL=(root) NOPASSWD: /sbin/ip route add default via * dev *
wancontrol ALL=(root) NOPASSWD: /sbin/ip route add default nexthop *
wancontrol ALL=(root) NOPASSWD: /sbin/ip route del default
wancontrol ALL=(root) NOPASSWD: /sbin/ip route add * dev * src * table *
wancontrol ALL=(root) NOPASSWD: /sbin/ip route add default via * dev * table *
wancontrol ALL=(root) NOPASSWD: /sbin/ip route flush table *
wancontrol ALL=(root) NOPASSWD: /sbin/ip rule add from * table * priority *
wancontrol ALL=(root) NOPASSWD: /sbin/ip rule del priority *
wancontrol ALL=(root) NOPASSWD: /sbin/sysctl -w net.ipv4.ip_forward=1
wancontrol ALL=(root) NOPASSWD: /sbin/sysctl -w net.ipv4.conf.*.rp_filter=2
```

Validate with: `visudo -c -f /etc/sudoers.d/wancontrol`

#### Step 6: Install systemd Service

Create `/etc/systemd/system/wancontrol.service`:

```ini
[Unit]
Description=WANControl v2 — SD-WAN Load-Balancing Controller
Documentation=https://github.com/aditya-tripcuro/SDWANcontrol
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=wancontrol
Group=wancontrol
EnvironmentFile=-/etc/wancontrol/.env
Environment=WANCONTROL_CONFIG=/etc/wancontrol/config.yaml
WorkingDirectory=/opt/wancontrol
ExecStart=/opt/wancontrol/venv/bin/python -m wancontrol
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
```

#### Step 7: Configure Log Rotation

Create `/etc/logrotate.d/wancontrol`:

```logrotate
/var/lib/wancontrol/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 wancontrol wancontrol
}
```

### Building Frontend (Optional)

If you need to rebuild the React frontend:

```bash
cd frontend
npm install
npm run build
```

The built assets are served by Flask from the same process.

### Verification

```bash
# Check service status
sudo systemctl status wancontrol

# View logs
journalctl -u wancontrol -f

# Test API endpoint
curl http://localhost:5000/api/health
```

---

## Configuration Reference

### Configuration File Location

Default: `/etc/wancontrol/config.yaml`

Override via environment: `WANCONTROL_CONFIG=/custom/path/config.yaml`

### Full Configuration Example

```yaml
# ── WAN Interfaces ────────────────────────────────────────────────────────────
interfaces:
  - name: "wan0"
    label: "Fiber Primary"
    expected_speed_mbps: 100
    gateway: "192.168.1.1"
    routing_table_id: 100

  - name: "wan1"
    label: "BSNL Backup"
    expected_speed_mbps: 30
    gateway: "10.0.0.1"
    routing_table_id: 101

# ── WAN Mode ──────────────────────────────────────────────────────────────────
wan_mode: "load_balance"  # Options: "failover", "load_balance"

# ── Probes ────────────────────────────────────────────────────────────────────
probes:
  interval_sec: 1
  dns_targets:
    - "8.8.8.8"
    - "1.1.1.1"
    - "9.9.9.9"
  icmp_targets:
    - "8.8.8.8"
    - "1.1.1.1"
    - "94.140.14.14"
  http_targets:
    - "http://connectivitycheck.gstatic.com/generate_204"
    - "http://detectportal.firefox.com/success.txt"
  icmp_count: 5
  icmp_timeout_sec: 3
  dns_timeout_sec: 3
  http_timeout_sec: 5

# ── Scoring ───────────────────────────────────────────────────────────────────
scoring:
  latency_penalty_per_ms: 0.3
  loss_penalty_per_percent: 2.0
  dns_fail_penalty: 15
  http_fail_penalty: 20
  hard_fail_threshold: 20
  hysteresis_switch_to_backup: 25    # failover mode only
  hysteresis_return_to_primary: 10   # failover mode only
  recovery_margin: 10                # load_balance mode only

# ── Controller ────────────────────────────────────────────────────────────────
controller:
  loop_interval_sec: 1
  benchmark_interval_sec: 300
  metric_collection_timeout_sec: 8
  heartbeat_interval_sec: 5
  heartbeat_stale_sec: 15

# ── Data Retention ────────────────────────────────────────────────────────────
retention:
  metrics_hours: 72
  events_days: 30
  prune_interval_min: 60

# ── Alerting ──────────────────────────────────────────────────────────────────
alerting:
  enabled: true
  webhooks:
    - url: "http://your-ntfy-server/wancontrol"
      method: POST
      headers:
        Title: "WANControl Alert"
      on_events:
        - "link_down"
        - "link_up"
        - "gateway_switch"
        - "interface_added_to_pool"
        - "interface_removed_from_pool"
        - "controller_error"

# ── Web Server ────────────────────────────────────────────────────────────────
server:
  host: "0.0.0.0"
  port: 5000
  secret_key: "REPLACE_ME_run_python_secrets_token_hex_32"
  jwt_expiry_hours: 24
  session_timeout_minutes: 60

# ── File Paths ────────────────────────────────────────────────────────────────
lock_file: "/run/wancontrol/controller.lock"
heartbeat_file: "/run/wancontrol/controller.heartbeat"
db_path: "/var/lib/wancontrol/wan.db"
log_dir: "/var/lib/wancontrol/logs"
```

### Configuration Sections

#### interfaces (Required)

List of WAN interface configurations.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | System interface name (e.g., `eth0`, `wan0`) |
| `label` | string | No | Human-readable description |
| `expected_speed_mbps` | integer | No | Expected bandwidth for load balancing weights |
| `gateway` | string | Yes | Gateway IP address for this interface |
| `routing_table_id` | integer | Yes | Policy routing table ID (100-255 recommended) |

#### wan_mode (Required)

Overall controller operating mode.

- `failover`: One active WAN at a time; switches on failure
- `load_balance`: All healthy WANs active; weighted distribution

#### probes

Health check configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `interval_sec` | integer | 1 | Probe execution interval |
| `dns_targets` | list | - | DNS servers to query |
| `icmp_targets` | list | - | IP addresses to ping |
| `http_targets` | list | - | HTTP endpoints to fetch |
| `icmp_count` | integer | 5 | Number of ICMP echoes per target |
| `icmp_timeout_sec` | integer | 3 | ICMP probe timeout |
| `dns_timeout_sec` | integer | 3 | DNS query timeout |
| `http_timeout_sec` | integer | 5 | HTTP request timeout |

#### scoring

Scoring algorithm parameters.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `latency_penalty_per_ms` | float | 0.3 | Score reduction per ms latency |
| `loss_penalty_per_percent` | float | 2.0 | Score reduction per % packet loss |
| `dns_fail_penalty` | integer | 15 | Penalty when all DNS targets fail |
| `http_fail_penalty` | integer | 20 | Penalty when all HTTP targets fail |
| `hard_fail_threshold` | integer | 20 | Score below this marks interface as FAILED |
| `hysteresis_switch_to_backup` | integer | 25 | Threshold to switch to backup (failover) |
| `hysteresis_return_to_primary` | integer | 10 | Margin to return to primary (failover) |
| `recovery_margin` | integer | 10 | Score margin for rejoining pool (load_balance) |

#### controller

Controller behavior settings.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `loop_interval_sec` | integer | 1 | Main control loop interval |
| `benchmark_interval_sec` | integer | 300 | Benchmark recalculation interval |
| `metric_collection_timeout_sec` | integer | 8 | Timeout for metric collection |
| `heartbeat_interval_sec` | integer | 5 | Heartbeat write interval |
| `heartbeat_stale_sec` | integer | 15 | Time before heartbeat considered stale |

#### retention

Data retention policies.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `metrics_hours` | integer | 72 | Hours to retain metric records |
| `events_days` | integer | 30 | Days to retain event records |
| `prune_interval_min` | integer | 60 | Interval between pruning operations |

#### alerting

Webhook notification settings.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | true | Enable webhook notifications |
| `webhooks` | list | - | List of webhook configurations |

**Webhook configuration:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | Yes | Webhook endpoint URL |
| `method` | string | Yes | HTTP method (POST, PUT, etc.) |
| `headers` | object | No | Custom HTTP headers |
| `on_events` | list | Yes | Event types that trigger this webhook |

**Supported event types:**

- `link_down`: Interface marked as FAILED
- `link_up`: Interface recovered from FAILED
- `gateway_switch`: Active gateway changed (failover mode)
- `interface_added_to_pool`: Interface added to load balance pool
- `interface_removed_from_pool`: Interface removed from pool
- `controller_error`: Controller encountered an error

#### server

Web server configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | 0.0.0.0 | Bind address |
| `port` | integer | 5000 | Bind port |
| `secret_key` | string | - | JWT signing key (generate with `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `jwt_expiry_hours` | integer | 24 | JWT token validity period |
| `session_timeout_minutes` | integer | 60 | Session timeout |

### Environment Variable Overrides

| Environment Variable | Config Path | Description |
|---------------------|-------------|-------------|
| `WANCONTROL_CONFIG` | - | Path to config.yaml |
| `WANCONTROL_DB_PATH` | `db_path` | SQLite database location |
| `WANCONTROL_SECRET_KEY` | `server.secret_key` | JWT signing key |
| `WANCONTROL_HOST` | `server.host` | Bind address |
| `WANCONTROL_PORT` | `server.port` | Bind port |
| `WANCONTROL_LOG_LEVEL` | - | Logging level (DEBUG/INFO/WARNING/ERROR) |
| `WANCONTROL_LOG_DIR` | `log_dir` | Log directory |
| `WANCONTROL_DRY_RUN` | - | Skip network commands (1=enabled) |
| `WANCONTROL_DEBUG` | - | Flask debug mode (1=enabled) |

### Hot Reloading

Configuration can be reloaded without restarting the service:

```bash
# Via signal
sudo kill -HUP $(pgrep -f "python -m wancontrol")

# Via API
curl -X POST http://localhost:5000/api/config/reload \
  -H "Authorization: Bearer <token>"
```

Note: `db_path` cannot be hot-reloaded and requires a restart.

### Interface Discovery

Use the discovery helper to identify available interfaces:

```bash
# List interfaces
python3 /opt/wancontrol/discover_interfaces.py

# Generate YAML snippet
python3 /opt/wancontrol/discover_interfaces.py --yaml
```

---

## API Reference

### Base URL

`http://<host>:5000/api`

### Authentication

Most endpoints require authentication via one of two methods:

1. **JWT Bearer Token** (recommended for interactive sessions):
   ```
   Authorization: Bearer <jwt_token>
   ```

2. **API Token** (recommended for automation):
   ```
   X-API-Token: <raw_token>
   ```

### Authentication Endpoints

#### POST /api/auth/login

Authenticate and receive JWT token.

**Request:**
```json
{
  "username": "admin",
  "password": "secure_password"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

**Error Responses:**
- `401 Unauthorized`: Invalid credentials
- `403 Forbidden`: User inactive

#### POST /api/auth/logout

Invalidate current session (client-side token removal).

**Response (200 OK):**
```json
{
  "message": "Logged out successfully"
}
```

#### POST /api/auth/change-password

Change authenticated user's password.

**Request:**
```json
{
  "current_password": "old_password",
  "new_password": "new_secure_password"
}
```

**Response (200 OK):**
```json
{
  "message": "Password changed successfully"
}
```

### Status Endpoints

#### GET /api/health

Liveness and version check (no auth required).

**Response (200 OK):**
```json
{
  "status": "healthy",
  "version": "2.0.0"
}
```

#### GET /api/status

Overall controller status.

**Response (200 OK):**
```json
{
  "mode": "RUNNING",
  "wan_mode": "load_balance",
  "active_interface": "wan0",
  "nexthop_pool": ["wan0", "wan1"],
  "last_update": 1698765432.123,
  "uptime_seconds": 3600.5
}
```

#### GET /api/status/interfaces

Per-interface status summary.

**Response (200 OK):**
```json
{
  "interfaces": [
    {
      "name": "wan0",
      "label": "Fiber Primary",
      "state": "STABLE",
      "score": 95.5,
      "in_pool": true,
      "gateway": "192.168.1.1",
      "ip_address": "192.168.1.100"
    },
    {
      "name": "wan1",
      "label": "BSNL Backup",
      "state": "STABLE",
      "score": 88.2,
      "in_pool": true,
      "gateway": "10.0.0.1",
      "ip_address": "10.0.0.50"
    }
  ]
}
```

### Metrics Endpoints

#### GET /api/metrics

Historical metrics with optional filtering.

**Query Parameters:**
- `interface` (optional): Filter by interface name
- `start` (optional): Start timestamp (Unix epoch)
- `end` (optional): End timestamp (Unix epoch)
- `limit` (optional): Maximum records (default: 1000)

**Response (200 OK):**
```json
{
  "metrics": [
    {
      "id": 1,
      "interface": "wan0",
      "timestamp": 1698765432.123,
      "latency_ms": 12.5,
      "jitter_ms": 1.2,
      "loss_pct": 0.0,
      "dns_ok": true,
      "http_ok": true,
      "score": 95.5
    }
  ]
}
```

#### GET /api/metrics/latest

Latest metric for each interface.

**Response (200 OK):**
```json
{
  "latest": [
    {
      "interface": "wan0",
      "timestamp": 1698765432.123,
      "latency_ms": 12.5,
      "jitter_ms": 1.2,
      "loss_pct": 0.0,
      "dns_ok": true,
      "http_ok": true,
      "score": 95.5
    },
    {
      "interface": "wan1",
      "timestamp": 1698765432.456,
      "latency_ms": 45.3,
      "jitter_ms": 5.1,
      "loss_pct": 1.0,
      "dns_ok": true,
      "http_ok": true,
      "score": 88.2
    }
  ]
}
```

### Events Endpoints

#### GET /api/events/switches

Recent failover and pool events.

**Query Parameters:**
- `limit` (optional): Maximum records (default: 100)

**Response (200 OK):**
```json
{
  "events": [
    {
      "id": 1,
      "timestamp": 1698765432.123,
      "from_interface": "wan0",
      "to_interface": "wan1",
      "reason": "score_below_threshold",
      "triggered_by": "controller",
      "score_before": 18.5,
      "score_after": 88.2
    }
  ]
}
```

#### GET /api/events/controller

Controller event log.

**Query Parameters:**
- `level` (optional): Filter by log level (INFO, WARNING, ERROR)
- `limit` (optional): Maximum records (default: 100)

**Response (200 OK):**
```json
{
  "events": [
    {
      "id": 1,
      "timestamp": 1698765432.123,
      "level": "INFO",
      "component": "controller",
      "message": "Controller started in load_balance mode",
      "user_id": null
    }
  ]
}
```

### Alerts Endpoints

#### GET /api/alerts

Recent alerts.

**Query Parameters:**
- `unresolved_only` (optional): Boolean, default false
- `limit` (optional): Maximum records (default: 100)

**Response (200 OK):**
```json
{
  "alerts": [
    {
      "id": 1,
      "timestamp": 1698765432.123,
      "level": "WARNING",
      "title": "Interface Degraded",
      "body": "wan0 score dropped below threshold",
      "resolved_at": null,
      "notified": true
    }
  ]
}
```

#### POST /api/alerts/:alert_id/resolve

Mark an alert as resolved.

**Response (200 OK):**
```json
{
  "message": "Alert resolved successfully"
}
```

### User Management Endpoints (Admin Only)

#### GET /api/users

List all users.

**Response (200 OK):**
```json
{
  "users": [
    {
      "id": 1,
      "username": "admin",
      "role": "admin",
      "created_at": 1698765432.123,
      "last_login": 1698769032.456,
      "is_active": true
    }
  ]
}
```

#### POST /api/users

Create a new user.

**Request:**
```json
{
  "username": "operator1",
  "password": "secure_password",
  "role": "operator"
}
```

**Response (201 Created):**
```json
{
  "user_id": 2,
  "message": "User created successfully"
}
```

#### GET /api/users/:user_id

Get user details.

**Response (200 OK):**
```json
{
  "id": 1,
  "username": "admin",
  "role": "admin",
  "created_at": 1698765432.123,
  "last_login": 1698769032.456,
  "is_active": true
}
```

#### POST /api/users/:user_id/deactivate

Deactivate a user account.

**Response (200 OK):**
```json
{
  "message": "User deactivated successfully"
}
```

#### POST /api/users/:user_id/role

Update user role.

**Request:**
```json
{
  "role": "admin"
}
```

**Response (200 OK):**
```json
{
  "message": "User role updated successfully"
}
```

### API Token Management Endpoints

#### GET /api/tokens

List API tokens for authenticated user.

**Response (200 OK):**
```json
{
  "tokens": [
    {
      "id": 1,
      "user_id": 1,
      "label": "Monitoring Script",
      "created_at": 1698765432.123,
      "last_used": 1698769032.456,
      "expires_at": null,
      "is_revoked": false
    }
  ]
}
```

#### POST /api/tokens

Create a new API token.

**Request:**
```json
{
  "label": "Monitoring Script",
  "expires_in_days": 365
}
```

**Response (201 Created):**
```json
{
  "token_id": 2,
  "token": "raw_token_value_here",
  "message": "Token created successfully. Store this token securely; it cannot be retrieved again."
}
```

#### DELETE /api/tokens/:token_id

Revoke an API token.

**Response (200 OK):**
```json
{
  "message": "Token revoked successfully"
}
```

### Configuration Endpoints

#### GET /api/config/raw

Get raw configuration (sanitized, no secrets).

**Response (200 OK):**
```json
{
  "config": {
    "interfaces": [...],
    "wan_mode": "load_balance",
    ...
  }
}
```

#### POST /api/config/reload

Reload configuration from disk.

**Response (200 OK):**
```json
{
  "message": "Configuration reloaded successfully"
}
```

#### PUT /api/config/interfaces

Update interface configuration dynamically.

**Request:**
```json
{
  "interfaces": [
    {
      "name": "wan0",
      "label": "Fiber Primary",
      "expected_speed_mbps": 100,
      "gateway": "192.168.1.1",
      "routing_table_id": 100
    }
  ]
}
```

**Response (200 OK):**
```json
{
  "message": "Interface configuration updated successfully"
}
```

### Database Management Endpoints (Admin Only)

#### GET /api/db/stats

Get database statistics.

**Response (200 OK):**
```json
{
  "file_size_bytes": 1048576,
  "metrics_count": 50000,
  "switch_events_count": 15,
  "controller_events_count": 200,
  "alerts_count": 10,
  "users_count": 3,
  "schema_version": 1
}
```

#### POST /api/db/prune

Trigger manual data pruning.

**Response (200 OK):**
```json
{
  "message": "Pruning completed",
  "deleted_metrics": 5000,
  "deleted_events": 50
}
```

#### POST /api/db/flush

Flush all historical data (keeps users and config).

**Request:**
```json
{
  "confirm": true
}
```

**Response (200 OK):**
```json
{
  "message": "Database flushed successfully"
}
```

### Server-Sent Events

#### GET /api/stream

Real-time event stream (SSE).

**Response Content-Type:** `text/event-stream`

**Event Format:**
```
data: {"type": "metric", "interface": "wan0", "score": 95.5}

data: {"type": "state_change", "interface": "wan0", "from": "STABLE", "to": "DEGRADED"}

data: {"type": "alert", "level": "WARNING", "title": "Interface Degraded"}
```

**JavaScript Example:**
```javascript
const eventSource = new EventSource('/api/stream', {
  headers: { 'Authorization': 'Bearer ' + token }
});

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Received:', data);
};
```

### Role-Based Access Control

| Endpoint Pattern | viewer | operator | admin |
|-----------------|--------|----------|-------|
| GET /api/health | ✓ | ✓ | ✓ |
| GET /api/status* | ✓ | ✓ | ✓ |
| GET /api/metrics* | ✓ | ✓ | ✓ |
| GET /api/events* | ✓ | ✓ | ✓ |
| GET /api/alerts* | ✓ | ✓ | ✓ |
| POST /api/alerts/:id/resolve | ✗ | ✓ | ✓ |
| GET /api/users* | ✗ | ✗ | ✓ |
| POST /api/users* | ✗ | ✗ | ✓ |
| POST /api/users/:id/* | ✗ | ✗ | ✓ |
| GET /api/tokens* | ✓ | ✓ | ✓ |
| POST /api/tokens* | ✓ | ✓ | ✓ |
| DELETE /api/tokens/:id | ✗ | ✗ | ✓ (any token) |
| POST /api/config/reload | ✗ | ✓ | ✓ |
| PUT /api/config/interfaces | ✗ | ✓ | ✓ |
| GET /api/db/stats | ✗ | ✗ | ✓ |
| POST /api/db/prune | ✗ | ✗ | ✓ |
| POST /api/db/flush | ✗ | ✗ | ✓ |

---

## Frontend Dashboard

### Overview

The WANControl dashboard is a React-based single-page application (SPA) served by the Flask backend. It provides real-time visualization of WAN status, metrics, and events.

### Technology Stack

- **React 18** with TypeScript
- **React Router** for navigation
- **Recharts** for data visualization
- **Tailwind CSS** for styling
- **Vite** for build tooling
- **Vitest** for testing

### Pages

#### Login Page

- Username/password authentication
- Displays error messages for failed attempts
- Redirects to dashboard on success

#### Dashboard

Main overview page with:

- **Status Cards**: Current mode, active interface(s), uptime
- **Interface Status**: Real-time state and score for each WAN
- **Live Metrics**: Latency, jitter, packet loss graphs
- **Recent Events**: Switch events and controller logs
- **Active Alerts**: Unresolved alerts with resolve action

#### Interfaces Page

Detailed interface information:

- Configuration details
- Historical performance graphs
- State transition timeline
- Manual actions (if permitted by role)

#### Events Page

Filterable event log:

- Switch events with before/after scores
- Controller events with log levels
- Time range filtering
- Export functionality

#### Alerts Page

Alert management:

- List all alerts with severity indicators
- Filter by resolved/unresolved
- Resolve alerts manually
- Alert history

#### Settings Page (Admin Only)

System configuration:

- User management
- API token management
- Database statistics
- Configuration reload
- Data maintenance (prune, flush)

### Real-Time Updates

The dashboard connects to `/api/stream` via Server-Sent Events (SSE) for live updates:

- Metric updates every second
- State change notifications
- New alerts
- Controller events

### Building from Source

```bash
cd frontend
npm install
npm run build
```

Built assets are placed in `frontend/dist` and served by Flask.

### Development Mode

```bash
cd frontend
npm run dev
```

Configure Vite proxy to forward API requests to the backend.

---

## Authentication & Authorization

### User Roles

WANControl implements three user roles with hierarchical permissions:

| Role | Level | Capabilities |
|------|-------|--------------|
| `viewer` | 1 | Read-only access to status, metrics, events, alerts |
| `operator` | 2 | Viewer + resolve alerts, reload config, modify interfaces |
| `admin` | 3 | Full access including user management, database operations |

### Password Requirements

- Minimum length: 12 characters
- Hashed with bcrypt (cost factor 12)
- Stored securely in SQLite database

### JWT Tokens

- Algorithm: HS256
- Expiry: Configurable (default 24 hours)
- Claims: user_id, username, role, exp, iat
- Signed with `server.secret_key`

### API Tokens

- SHA-256 hashed storage
- Optional expiry
- Can be revoked without affecting user account
- Ideal for automation scripts and monitoring tools

### Creating Initial Admin User

On first startup, if no users exist, WANControl generates a temporary admin password and displays it in the logs:

```
┌────────────────────────────────────────────────────────────┐
│  FIRST RUN SETUP                                           │
│  Admin username: admin                                     │
│  Admin password: <random_password>                         │
│  Please change this password immediately after login.      │
└────────────────────────────────────────────────────────────┘
```

View the password with:

```bash
journalctl -u wancontrol -n 50
```

### Programmatic User Management

```python
from wancontrol.auth import Auth
from wancontrol.database import Database
from wancontrol.config import AppConfig

db = Database("/var/lib/wancontrol/wan.db")
db.initialize()

cfg = AppConfig.load("/etc/wancontrol/config.yaml")
auth = Auth(db, cfg.server)

# Create admin user
admin_id = auth.create_user("admin", "secure_password_123", "admin")

# Create operator
operator_id = auth.create_user("operator1", "another_password_456", "operator", created_by_user_id=admin_id)

# Create viewer
viewer_id = auth.create_user("viewer1", "password_789", "viewer", created_by_user_id=admin_id)
```

### Authentication Flow

1. Client sends credentials to `POST /api/auth/login`
2. Server validates against bcrypt hash
3. On success, returns JWT access token
4. Client includes token in `Authorization: Bearer` header
5. Server verifies token signature and expiry
6. Server extracts user principal and attaches to request context
7. Endpoint handlers check role requirements

---

## Database Schema

### Overview

WANControl uses SQLite with WAL (Write-Ahead Logging) mode for concurrent access. The database is located at `/var/lib/wancontrol/wan.db` by default.

### Tables

#### metrics

Stores historical probe results.

```sql
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interface TEXT NOT NULL,
    timestamp REAL NOT NULL,
    latency_ms REAL NOT NULL,
    jitter_ms REAL NOT NULL,
    loss_pct REAL NOT NULL,
    dns_ok INTEGER NOT NULL,
    http_ok INTEGER NOT NULL,
    score REAL NOT NULL
);

CREATE INDEX idx_metrics_interface ON metrics(interface);
CREATE INDEX idx_metrics_timestamp ON metrics(timestamp);
CREATE INDEX idx_metrics_interface_ts ON metrics(interface, timestamp);
```

#### switch_events

Records gateway switches and pool changes.

```sql
CREATE TABLE switch_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    from_interface TEXT,
    to_interface TEXT,
    reason TEXT NOT NULL,
    triggered_by TEXT NOT NULL,
    score_before REAL,
    score_after REAL
);

CREATE INDEX idx_switch_events_timestamp ON switch_events(timestamp);
```

#### controller_events

Controller activity log.

```sql
CREATE TABLE controller_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    level TEXT NOT NULL,
    component TEXT NOT NULL,
    message TEXT NOT NULL,
    user_id INTEGER
);

CREATE INDEX idx_controller_events_timestamp ON controller_events(timestamp);
CREATE INDEX idx_controller_events_level ON controller_events(level);
```

#### alerts

Alert notifications.

```sql
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    level TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    resolved_at REAL,
    notified INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_alerts_timestamp ON alerts(timestamp);
CREATE INDEX idx_alerts_resolved ON alerts(resolved_at);
```

#### users

User accounts.

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_login REAL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_users_username ON users(username);
```

#### api_tokens

API access tokens.

```sql
CREATE TABLE api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    label TEXT,
    created_at REAL NOT NULL,
    last_used REAL,
    expires_at REAL,
    is_revoked INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX idx_api_tokens_user ON api_tokens(user_id);
CREATE INDEX idx_api_tokens_hash ON api_tokens(token_hash);
```

#### state

Controller runtime state.

```sql
CREATE TABLE state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
```

Common state keys:
- `active_interface`: Currently active WAN (failover mode)
- `nexthop_pool`: Comma-separated list of interfaces in pool
- `controller_mode`: RUNNING, MAINTENANCE, etc.
- `schema_version`: Database schema version

### Migrations

Schema version is tracked in the `state` table. On initialization, the database runs any pending migrations automatically.

### Retention Policies

Automatic pruning removes old data:

- Metrics older than `retention.metrics_hours` (default 72 hours)
- Events older than `retention.events_days` (default 30 days)

Pruning runs every `retention.prune_interval_min` (default 60 minutes).

Manual pruning:

```bash
curl -X POST http://localhost:5000/api/db/prune \
  -H "Authorization: Bearer <token>"
```

### Backup and Restore

**Backup:**

```bash
sqlite3 /var/lib/wancontrol/wan.db ".backup '/backup/wan.db.backup'"
```

**Restore:**

```bash
systemctl stop wancontrol
cp /backup/wan.db.backup /var/lib/wancontrol/wan.db
chown wancontrol:wancontrol /var/lib/wancontrol/wan.db
systemctl start wancontrol
```

---

## Network Operations

### Overview

All network operations are encapsulated in `wancontrol/network.py`. This module handles:

- Interface information retrieval
- ICMP ping probes
- DNS resolution tests
- HTTP connectivity checks
- Route table manipulation
- Policy routing configuration
- System parameter tuning

### Dry Run Mode

For development and testing, set `WANCONTROL_DRY_RUN=1` to skip actual network commands:

```bash
WANCONTROL_DRY_RUN=1 python -m wancontrol
```

In dry run mode:
- All subprocess calls are logged but not executed
- Safe defaults are returned
- No system changes are made

### Interface Information

#### get_interface_ip(interface)

Returns the first IPv4 address of an interface.

```python
from wancontrol.network import get_interface_ip

ip = get_interface_ip("wan0")
# Returns: "192.168.1.100" or None
```

#### get_interface_gateway(interface)

Retrieves the default gateway for an interface.

```python
from wancontrol.network import get_interface_gateway

gateway = get_interface_gateway("wan0")
# Returns: "192.168.1.1" or None
```

### Health Probes

#### probe_icmp(target, interface, count, timeout)

Sends ICMP echo requests.

```python
from wancontrol.network import probe_icmp

success, avg_latency, jitter, loss_pct = probe_icmp(
    target="8.8.8.8",
    interface="wan0",
    count=5,
    timeout=3
)
```

#### probe_dns(server, interface, timeout)

Tests DNS resolution.

```python
from wancontrol.network import probe_dns

success, response_time = probe_dns(
    server="8.8.8.8",
    interface="wan0",
    timeout=3
)
```

#### probe_http(url, interface, timeout)

Fetches HTTP resource.

```python
from wancontrol.network import probe_http

success, response_time, status_code = probe_http(
    url="http://connectivitycheck.gstatic.com/generate_204",
    interface="wan0",
    timeout=5
)
```

### Route Management

#### set_default_route(gateway, interface)

Sets a single default route (failover mode).

```python
from wancontrol.network import set_default_route

set_default_route("192.168.1.1", "wan0")
# Executes: ip route add default via 192.168.1.1 dev wan0
```

#### set_load_balance_route(routes)

Configures weighted multipath routing (load_balance mode).

```python
from wancontrol.network import set_load_balance_route

routes = [
    {"gateway": "192.168.1.1", "interface": "wan0", "weight": 100},
    {"gateway": "10.0.0.1", "interface": "wan1", "weight": 30}
]

set_load_balance_route(routes)
# Executes: ip route add default nexthop via 192.168.1.1 dev wan0 weight 100 \
#                          nexthop via 10.0.0.1 dev wan1 weight 30
```

#### delete_default_route()

Removes the default route.

```python
from wancontrol.network import delete_default_route

delete_default_route()
# Executes: ip route del default
```

### Policy Routing

#### add_policy_route_table(table_id, interface, source_ip)

Creates a policy routing table.

```python
from wancontrol.network import add_policy_route_table, get_interface_ip

interface = "wan0"
table_id = 100
source_ip = get_interface_ip(interface)

add_policy_route_table(table_id, interface, source_ip)
# Executes: ip route add default via <gateway> dev wan0 src <ip> table 100
```

#### add_policy_rule(source_ip, table_id, priority)

Adds a policy rule.

```python
from wancontrol.network import add_policy_rule

add_policy_rule("192.168.1.100", 100, 100)
# Executes: ip rule add from 192.168.1.100 table 100 priority 100
```

#### delete_policy_rule(priority)

Removes a policy rule.

```python
from wancontrol.network import delete_policy_rule

delete_policy_rule(100)
# Executes: ip rule del priority 100
```

### System Configuration

#### enable_ip_forwarding()

Enables IPv4 forwarding.

```python
from wancontrol.network import enable_ip_forwarding

enable_ip_forwarding()
# Executes: sysctl -w net.ipv4.ip_forward=1
```

#### enable_rp_filter_loose()

Sets reverse path filter to loose mode.

```python
from wancontrol.network import enable_rp_filter_loose

enable_rp_filter_loose()
# Executes: sysctl -w net.ipv4.conf.all.rp_filter=2
#           sysctl -w net.ipv4.conf.default.rp_filter=2
```

### Prerequisites Check

Before starting, verify all required commands are available:

```python
from wancontrol.network import check_prerequisites

missing = check_prerequisites()
if missing:
    print(f"Missing commands: {missing}")
    exit(1)
```

Required commands:
- `ip` (iproute2)
- `ping` (iputils-ping)
- `dig` (bind9-dnsutils)
- `curl`
- `sudo`
- `sysctl`

### Sudo Configuration

WANControl requires passwordless sudo for network commands. The installer creates `/etc/sudoers.d/wancontrol` with appropriate rules.

Verify sudo configuration:

```bash
visudo -c -f /etc/sudoers.d/wancontrol
```

Test sudo access:

```bash
sudo -u wancontrol ip route show
```

---

## Monitoring & Health Checks

### Probe Types

WANControl uses three probe types to assess WAN health:

#### ICMP Probes

- **Purpose**: Measure basic connectivity and latency
- **Targets**: Multiple public IPs (e.g., 8.8.8.8, 1.1.1.1)
- **Metrics**: Average latency, jitter, packet loss percentage
- **Frequency**: Every `probes.interval_sec` (default 1 second)
- **Count**: `probes.icmp_count` echoes per target (default 5)

#### DNS Probes

- **Purpose**: Verify DNS resolution capability
- **Targets**: Public DNS servers (e.g., 8.8.8.8, 1.1.1.1, 9.9.9.9)
- **Query**: A record lookup for a well-known domain
- **Metrics**: Success/failure, response time
- **Timeout**: `probes.dns_timeout_sec` (default 3 seconds)

#### HTTP Probes

- **Purpose**: Confirm full internet connectivity
- **Targets**: Connectivity check endpoints (e.g., Google, Firefox)
- **Expected Response**: HTTP 204 or specific content
- **Metrics**: Success/failure, response time
- **Timeout**: `probes.http_timeout_sec` (default 5 seconds)

### Scoring Algorithm

Each interface receives a score from 0 to 100 based on probe results.

#### Base Score

Start with 100 points.

#### Penalties Applied

1. **Latency Penalty**: `latency_ms × latency_penalty_per_ms`
   - Default: 0.3 points per millisecond
   - Example: 50ms latency = 15 point penalty

2. **Packet Loss Penalty**: `loss_pct × loss_penalty_per_percent`
   - Default: 2.0 points per percent loss
   - Example: 5% loss = 10 point penalty

3. **DNS Failure Penalty**: Fixed penalty if all DNS targets fail
   - Default: 15 points

4. **HTTP Failure Penalty**: Fixed penalty if all HTTP targets fail
   - Default: 20 points

#### Score Calculation

```python
score = 100.0
score -= min(latency_ms * 0.3, 50)  # Cap latency penalty
score -= min(loss_pct * 2.0, 50)    # Cap loss penalty
if not dns_ok:
    score -= 15
if not http_ok:
    score -= 20
score = max(0.0, score)  # Floor at 0
```

### State Transitions

Based on score thresholds, interfaces transition between states:

| State | Condition | Description |
|-------|-----------|-------------|
| `STABLE` | score ≥ hard_fail_threshold + hysteresis | Fully operational |
| `DEGRADED` | hard_fail_threshold ≤ score < threshold + hysteresis | Performance issues |
| `FAILED` | score < hard_fail_threshold | Unusable, removed from service |
| `SWITCHING` | During failover transition | Temporary state during switchover |

#### Hysteresis

Prevents rapid state flapping:

- **Switch to Backup**: Requires score to drop below `hysteresis_switch_to_backup`
- **Return to Primary**: Requires score to exceed `hysteresis_return_to_primary` above backup

#### Recovery Margin (Load Balance Mode)

Interface must exceed `hard_fail_threshold + recovery_margin` to rejoin the nexthop pool.

### Parallel Probe Execution

Probes run in parallel using ThreadPoolExecutor:

- One thread per interface
- Within each interface, ICMP/DNS/HTTP probes run concurrently
- Hard timeout enforced per interface
- Timed-out interfaces receive hard-fail score (0.0)

### Metric Collection Flow

```
Controller Loop (every 1 second)
    ↓
Monitor.collect(interfaces, timeout_sec=8)
    ↓
For each interface (parallel):
    ├─ probe_icmp(targets) → latency, jitter, loss
    ├─ probe_dns(targets) → success/failure
    └─ probe_http(targets) → success/failure
    ↓
Apply scoring algorithm
    ↓
Insert MetricRow into database
    ↓
Return list[InterfaceMetric] to Controller
```

### Visualization

Metrics are visualized in the dashboard:

- **Latency Graph**: Line chart over time
- **Jitter Graph**: Variance in latency
- **Packet Loss**: Percentage over time
- **Score Trend**: Overall health indicator
- **Probe Success Rate**: DNS/HTTP availability

---

## Controller State Machine

### Overview

The Controller is the brain of WANControl, implementing a state machine that:

1. Collects metrics from the Monitor
2. Evaluates interface health
3. Makes routing decisions
4. Applies network changes
5. Manages master/standby election
6. Triggers alerts and webhooks

### Controller Modes

| Mode | Description |
|------|-------------|
| `STARTING` | Initializing, running prerequisites check |
| `RUNNING` | Normal operation, managing routes |
| `MAINTENANCE` | Paused, no route changes (manual intervention) |
| `KILLED` | Shutting down |

### WAN States

Per-interface state machine:

| State | Description | In Pool? |
|-------|-------------|----------|
| `STABLE` | Healthy, meeting all thresholds | Yes |
| `DEGRADED` | Performance issues, above fail threshold | Yes |
| `FAILED` | Below hard_fail_threshold | No |
| `SWITCHING` | Transitioning between states | Depends |

### Failover Mode Logic

```
Primary Interface (wan0)
    ↓
Score ≥ (hard_fail_threshold + hysteresis_switch_to_backup)?
    ├─ YES → Keep primary active
    └─ NO  → Switch to backup

Backup Interface (wan1)
    ↓
Score ≥ (hard_fail_threshold + hysteresis_return_to_primary)?
    ├─ YES → Consider switching back to primary
    └─ NO  → Stay on backup
```

### Load Balance Mode Logic

```
For each interface:
    ↓
Score ≥ hard_fail_threshold?
    ├─ YES → Add to nexthop pool (if not already)
    └─ NO  → Remove from pool (if present)

Nexthop Pool:
    ↓
Build weighted route:
    ip route add default nexthop via <gw1> dev <if1> weight <w1> \
                                 nexthop via <gw2> dev <if2> weight <w2>
```

Weights are derived from `expected_speed_mbps`.

### Master/Standby Election

For high-availability deployments with multiple WANControl instances:

1. **Lock File**: `/run/wancontrol/controller.lock`
2. **Heartbeat**: `/run/wancontrol/controller.heartbeat`
3. **Election Process**:
   - Instances attempt to acquire exclusive lock
   - Lock holder becomes Master
   - Others become Standby
   - Master writes heartbeat every 5 seconds
   - If heartbeat stale (>15 seconds), Standby takes over

### Control Loop

```python
while controller_mode == RUNNING:
    # 1. Collect metrics
    metrics = monitor.collect(interfaces, timeout_sec=8)
    
    # 2. Update interface states
    for metric in metrics:
        update_interface_state(metric)
    
    # 3. Make routing decision
    if wan_mode == FAILOVER:
        apply_failover_logic()
    elif wan_mode == LOAD_BALANCE:
        apply_load_balance_logic()
    
    # 4. Check for state changes
    if state_changed:
        log_switch_event()
        trigger_alerts()
        send_webhooks()
    
    # 5. Update heartbeat
    write_heartbeat()
    
    # 6. Sleep until next iteration
    sleep(controller.loop_interval_sec)
```

### Alert Conditions

Alerts are triggered for:

- **link_down**: Interface entered FAILED state
- **link_up**: Interface recovered from FAILED
- **gateway_switch**: Active gateway changed
- **interface_added_to_pool**: Interface joined load balance pool
- **interface_removed_from_pool**: Interface left pool
- **controller_error**: Controller encountered exception

### Webhook Delivery

Webhooks are sent asynchronously:

```python
def send_webhook(webhook_config, event_data):
    try:
        req = urllib.request.Request(
            webhook_config.url,
            data=json.dumps(event_data).encode(),
            headers=webhook_config.headers,
            method=webhook_config.method
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Webhook delivered successfully")
    except Exception as e:
        logger.error(f"Webhook delivery failed: {e}")
```

Event payload example:

```json
{
  "event_type": "link_down",
  "timestamp": 1698765432.123,
  "interface": "wan0",
  "score": 15.5,
  "previous_state": "STABLE",
  "current_state": "FAILED"
}
```

---

## Deployment Guide

### Production Checklist

- [ ] Generate secure `secret_key`
- [ ] Configure firewall rules
- [ ] Set up log rotation
- [ ] Configure sudoers correctly
- [ ] Test failover scenario
- [ ] Verify webhook delivery
- [ ] Create backup strategy
- [ ] Document interface assignments
- [ ] Set up monitoring alerts
- [ ] Test restore procedure

### Firewall Configuration

Allow outbound traffic for health probes:

```bash
# ICMP
iptables -A OUTPUT -p icmp --icmp-type echo-request -j ACCEPT

# DNS
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

# HTTP/HTTPS
iptables -A OUTPUT -p tcp --dport 80 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 443 -j ACCEPT

# API access (if remote management needed)
iptables -A INPUT -p tcp --dport 5000 -s <trusted_network> -j ACCEPT
```

### High Availability Setup

For redundant WANControl instances:

1. **Shared Storage**: Mount `/var/lib/wancontrol` on shared filesystem
2. **Lock Coordination**: Ensure lock file works across nodes
3. **Heartbeat Monitoring**: Configure appropriate stale threshold
4. **Network Redundancy**: Both instances must have access to all WAN interfaces

### Monitoring Integration

#### Prometheus Metrics

Export custom metrics via a sidecar or modify the code to expose a `/metrics` endpoint.

#### Grafana Dashboard

Import metrics from SQLite or use the API to populate dashboards.

#### Log Aggregation

Forward logs to central logging:

```bash
# rsyslog configuration
:programname, isequal, "wancontrol" /var/log/wancontrol-forward.log
```

### Backup Strategy

#### Automated Backups

```bash
#!/bin/bash
# /usr/local/bin/backup-wancontrol.sh

BACKUP_DIR="/backup/wancontrol"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup database
sqlite3 /var/lib/wancontrol/wan.db ".backup '$BACKUP_DIR/wan_$DATE.db'"

# Backup configuration
cp /etc/wancontrol/config.yaml "$BACKUP_DIR/config_$DATE.yaml"

# Keep last 30 days
find "$BACKUP_DIR" -name "*.db" -mtime +30 -delete
find "$BACKUP_DIR" -name "*.yaml" -mtime +30 -delete
```

Add to crontab:

```cron
0 2 * * * /usr/local/bin/backup-wancontrol.sh
```

### Disaster Recovery

1. **Stop Service**: `systemctl stop wancontrol`
2. **Restore Database**: Copy backup to `/var/lib/wancontrol/wan.db`
3. **Restore Config**: Copy backup to `/etc/wancontrol/config.yaml`
4. **Fix Permissions**: `chown wancontrol:wancontrol /var/lib/wancontrol/wan.db`
5. **Start Service**: `systemctl start wancontrol`
6. **Verify**: Check logs and API health endpoint

### Performance Tuning

#### Database Optimization

Enable WAL mode (already default):

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=10000;
```

#### Probe Tuning

Adjust based on network conditions:

- Increase `interval_sec` for stable networks
- Decrease timeouts for responsive detection
- Add more targets for redundancy

#### Resource Limits

Set systemd resource controls:

```ini
[Service]
MemoryMax=256M
CPUQuota=20%
```

---

## Troubleshooting

### Common Issues

#### Service Won't Start

**Symptoms**: `systemctl status wancontrol` shows failed state

**Diagnosis**:
```bash
journalctl -u wancontrol -n 100 --no-pager
```

**Common Causes**:
- Missing Python dependencies
- Incorrect file permissions
- Config file syntax errors
- Port already in use

**Solutions**:
```bash
# Check Python environment
/opt/wancontrol/venv/bin/pip list

# Verify config syntax
python3 -c "from wancontrol.config import AppConfig; AppConfig.load('/etc/wancontrol/config.yaml')"

# Check port availability
ss -tlnp | grep 5000

# Fix permissions
chown -R wancontrol:wancontrol /var/lib/wancontrol
chown -R root:wancontrol /opt/wancontrol
```

#### Routes Not Applying

**Symptoms**: Interfaces show as healthy but traffic not balancing

**Diagnosis**:
```bash
# Check sudo configuration
visudo -c -f /etc/sudoers.d/wancontrol

# Test sudo access
sudo -u wancontrol ip route show

# Check current routes
ip route show
ip route show table all
```

**Solutions**:
- Reinstall sudoers fragment: `sudo ./install.sh`
- Verify WANControl user has correct sudo privileges
- Check for conflicting route managers (NetworkManager, systemd-networkd)

#### High CPU Usage

**Symptoms**: WANControl consuming excessive CPU

**Diagnosis**:
```bash
top -p $(pgrep -f "python -m wancontrol")
```

**Common Causes**:
- Too frequent probe intervals
- Large number of targets
- Database locking issues

**Solutions**:
- Increase `probes.interval_sec`
- Reduce number of probe targets
- Check database for lock contention: `sqlite3 /var/lib/wancontrol/wan.db "PRAGMA busy_timeout;"`

#### Database Corruption

**Symptoms**: Errors about database locked or corrupted

**Diagnosis**:
```bash
sqlite3 /var/lib/wancontrol/wan.db "PRAGMA integrity_check;"
```

**Solutions**:
```bash
# Stop service
systemctl stop wancontrol

# Attempt recovery
sqlite3 /var/lib/wancontrol/wan.db ".recover" | sqlite3 /var/lib/wancontrol/wan_recovered.db

# Replace if successful
mv /var/lib/wancontrol/wan.db /var/lib/wancontrol/wan.db.corrupt
mv /var/lib/wancontrol/wan_recovered.db /var/lib/wancontrol/wan.db

# Restart
systemctl start wancontrol
```

#### Webhook Not Delivering

**Symptoms**: Alerts generated but webhooks not received

**Diagnosis**:
```bash
journalctl -u wancontrol -g "webhook" -n 50
```

**Common Causes**:
- Network unreachable
- Invalid URL
- Authentication failures
- Timeout

**Solutions**:
- Test webhook endpoint manually: `curl -X POST <url> -d '{}'`
- Check firewall rules
- Verify URL format in config
- Increase timeout if endpoint slow

#### JWT Authentication Failing

**Symptoms**: 401 Unauthorized on API requests

**Diagnosis**:
```bash
# Check token expiry
echo <token> | cut -d'.' -f2 | base64 -d 2>/dev/null | jq .exp

# Verify secret key matches
grep secret_key /etc/wancontrol/config.yaml
```

**Solutions**:
- Regenerate token via login endpoint
- Ensure secret_key hasn't changed
- Check system time synchronization

### Log Analysis

#### Log Locations

- **Journal**: `journalctl -u wancontrol`
- **File**: `/var/lib/wancontrol/logs/wancontrol.log`

#### Log Levels

- **DEBUG**: Detailed diagnostic information
- **INFO**: Normal operational messages
- **WARNING**: Potential issues
- **ERROR**: Errors requiring attention
- **CRITICAL**: Severe errors

#### Searching Logs

```bash
# Recent errors
journalctl -u wancontrol -p err -n 50

# Specific component
journalctl -u wancontrol -g "controller" -n 50

# Time range
journalctl -u wancontrol --since "2024-01-01 00:00:00" --until "2024-01-01 23:59:59"

# Follow live
journalctl -u wancontrol -f
```

### Debug Mode

Enable verbose logging:

```bash
# Environment variable
WANCONTROL_DEBUG=1 WANCONTROL_LOG_LEVEL=DEBUG systemctl restart wancontrol

# Or edit /etc/wancontrol/.env
WANCONTROL_DEBUG=1
WANCONTROL_LOG_LEVEL=DEBUG
```

### Getting Help

- **GitHub Issues**: https://github.com/aditya-tripcuro/SDWANcontrol/issues
- **Logs**: Always include recent logs when reporting issues
- **Configuration**: Share sanitized config.yaml (remove secrets)
- **Environment**: Include OS version, Python version, WANControl version

---

## Development Guide

### Setting Up Development Environment

#### Prerequisites

- Python 3.10+
- Node.js 18+ (for frontend)
- Git

#### Backend Setup

```bash
# Clone repository
git clone https://github.com/aditya-tripcuro/SDWANcontrol.git
cd SDWANcontrol

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run in dry-run mode (safe, no network changes)
WANCONTROL_DRY_RUN=1 python -m wancontrol
```

#### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Development server (with proxy to backend)
npm run dev

# Build for production
npm run build

# Run tests
npm test
```

### Running Tests

#### Backend Tests

```bash
# Activate virtual environment
source venv/bin/activate

# Run all tests
pytest

# With coverage
pytest --cov=wancontrol --cov-report=html

# Specific test file
pytest tests/unit/test_controller.py

# Verbose output
pytest -v
```

#### Frontend Tests

```bash
cd frontend

# Run tests
npm test

# Watch mode
npm run test:watch

# Coverage
npm test -- --coverage
```

### Code Style

#### Python

Follow PEP 8 with these conventions:

- Type hints for all function signatures
- Docstrings for all public modules, classes, and functions
- Maximum line length: 100 characters
- Use `black` for formatting
- Use `flake8` for linting

```bash
# Install tools
pip install black flake8 mypy

# Format code
black wancontrol/ tests/

# Lint
flake8 wancontrol/ tests/

# Type checking
mypy wancontrol/
```

#### TypeScript

- Strict mode enabled in `tsconfig.json`
- ESLint for linting
- Prettier for formatting

```bash
cd frontend

# Lint
npm run lint

# Format
npx prettier --write src/
```

### Adding New Features

#### Backend Feature Checklist

1. Add configuration option to `config.py`
2. Update config.yaml example
3. Implement logic in appropriate module
4. Add database migration if needed (update `database.py`)
5. Add API endpoint in `app.py`
6. Write unit tests
7. Update documentation

#### Frontend Feature Checklist

1. Create/new component in `src/components/`
2. Add route in `src/App.tsx`
3. Add API client in `src/api/`
4. Write component tests
5. Update documentation

### Debugging

#### Python Debugging

```bash
# Install debugger
pip install pdbpp

# Run with breakpoint
WANCONTROL_DRY_RUN=1 python -m wancontrol

# In code:
import pdb; pdb.set_trace()
```

#### VS Code Launch Configuration

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "WANControl Backend",
            "type": "python",
            "request": "launch",
            "module": "wancontrol",
            "env": {
                "WANCONTROL_DRY_RUN": "1",
                "WANCONTROL_CONFIG": "${workspaceFolder}/config.yaml"
            },
            "console": "integratedTerminal"
        },
        {
            "name": "WANControl Frontend",
            "type": "chrome",
            "request": "launch",
            "url": "http://localhost:5173",
            "webRoot": "${workspaceFolder}/frontend/src"
        }
    ]
}
```

### Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/my-feature`
3. Make changes with tests
4. Run test suite: `pytest && npm test`
5. Commit with descriptive messages
6. Push and open Pull Request

### Release Process

1. Update version in `wancontrol/__init__.py`
2. Update CHANGELOG.md
3. Tag release: `git tag -a v2.0.0 -m "Release 2.0.0"`
4. Push tag: `git push origin v2.0.0`
5. Build frontend: `npm run build`
6. Create GitHub release with notes

---

## Appendix

### Glossary

| Term | Definition |
|------|------------|
| **WAN** | Wide Area Network, typically your internet connection |
| **Failover** | Automatic switching to backup when primary fails |
| **Load Balance** | Distributing traffic across multiple paths |
| **Nexthop Pool** | Set of active gateways for load balancing |
| **Policy Routing** | Routing based on criteria beyond destination IP |
| **Hysteresis** | Delay mechanism to prevent rapid state changes |
| **SSE** | Server-Sent Events, one-way real-time communication |
| **JWT** | JSON Web Token, stateless authentication |

### Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0.0 | 2024 | Complete rewrite with React frontend, SQLite, JWT auth |
| 1.0.0 | 2023 | Initial release with basic failover |

### License

See [LICENSE](LICENSE) file for terms.

### Acknowledgments

- Uses Flask for REST API
- React for frontend
- SQLite for persistence
- bcrypt for password hashing
- PyJWT for token management

---

*Documentation generated for WANControl v2.0.0*
