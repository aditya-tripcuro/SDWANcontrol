# WANControl v2 Wiki

Welcome to the WANControl v2 wiki — your comprehensive knowledge base for the SD-WAN load-balancing controller.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Core Components](#core-components)
- [Installation Guide](#installation-guide)
- [Configuration Reference](#configuration-reference)
- [API Reference](#api-reference)
- [Frontend Dashboard](#frontend-dashboard)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

---

## Overview

### What is WANControl?

WANControl v2 is an industrial-grade SD-WAN (Software-Defined Wide Area Network) controller designed for Linux systems with multiple WAN (Wide Area Network) interfaces. It provides intelligent traffic management through:

- **Failover Mode**: Automatically switches to backup connections when primary fails
- **Load Balance Mode**: Distributes traffic across multiple healthy connections
- **Health Monitoring**: Continuous ICMP, DNS, and HTTP probing with weighted scoring
- **Real-time Dashboard**: Premium React-based UI for monitoring and management

### Key Features

| Feature | Description |
|---------|-------------|
| Multi-WAN Support | Manage 2+ WAN interfaces simultaneously |
| Health Probing | ICMP ping, DNS resolution, HTTP connectivity checks |
| Weighted Scoring | Dynamic interface scoring based on latency, loss, and connectivity |
| Route Management | Automatic routing table and policy rule configuration |
| SQLite Persistence | Metrics, events, alerts, users, and API tokens stored locally |
| Hot Reload | Configuration changes via SIGHUP or API without restart |
| JWT Authentication | Secure API access with role-based permissions |
| Server-Sent Events | Real-time dashboard updates via SSE streaming |

---

## Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     WANControl v2 System                        │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   Frontend  │  │   Flask     │  │    Controller Loop      │  │
│  │  (React)    │◄─┤    API      │◄─┤  (Probe & Decision)     │  │
│  │  Port 5000  │  │  (REST)     │  │                         │  │
│  └─────────────┘  └──────┬──────┘  └───────────┬─────────────┘  │
│                          │                     │                │
│                   ┌──────▼──────┐       ┌──────▼──────┐        │
│                   │   SQLite    │       │   Network   │        │
│                   │  Database   │       │   Layer     │        │
│                   │  (wan.db)   │       │  (iproute2) │        │
│                   └─────────────┘       └──────┬──────┘        │
│                                                │                │
└────────────────────────────────────────────────┼────────────────┘
                                                 │
                    ┌────────────────────────────┼────────────────┐
                    │                            │                │
              ┌─────▼─────┐               ┌──────▼──────┐  ┌──────▼──────┐
              │  WAN 0    │               │   WAN 1     │  │   WAN 2     │
              │ enp2s0    │               │  enp3s0     │  │  wlp5s0     │
              └───────────┘               └─────────────┘  └─────────────┘
```

### Component Interaction Flow

1. **Prober** sends ICMP/DNS/HTTP requests bound to specific interfaces
2. **Scorer** calculates health scores based on probe results
3. **Controller** makes routing decisions based on scores and mode
4. **Network Layer** applies routing table and policy rule changes
5. **Database** persists all metrics, events, and state
6. **API** exposes data and control endpoints to frontend and clients
7. **Frontend** displays real-time status and accepts user input

---

## Core Components

### wancontrol/app.py (Flask API)

The REST API layer that handles all HTTP requests.

**Key Responsibilities:**
- JWT and API token authentication
- Role-based access control (admin, operator, viewer)
- Endpoint routing for status, metrics, events, alerts, config
- Server-Sent Events (SSE) streaming for real-time updates
- Static file serving for the React frontend

**Authentication Methods:**
- `Authorization: Bearer <jwt>` — For user sessions
- `X-API-Token: <raw>` — For automation and scripts

### wancontrol/controller.py (Lifecycle Manager)

Manages the controller startup and shutdown sequence.

**Responsibilities:**
- Snapshot default routes before making changes
- Setup per-interface routing tables
- Register signal handlers (SIGTERM, SIGINT)
- Restore routes on shutdown
- Find available port for web server

### wancontrol/network.py (Network Operations)

Handles all network configuration operations.

**Key Functions:**
- `snapshot_default_routes()` — Save current default routes to DB
- `restore_default_routes()` — Restore routes from snapshot
- `setup_interface_routing()` — Create routing table and policy rule
- `teardown_interface_routing()` — Remove routing configuration
- `bind_socket_to_interface()` — Bind socket using SO_BINDTODEVICE
- `find_available_port()` — Find open TCP port starting from configured

### wancontrol/database.py (SQLite Layer)

Thread-safe SQLite wrapper with WAL mode and migrations.

**Tables:**
- `metrics` — Probe results (latency, jitter, loss, score)
- `switch_events` — WAN failover and pool change events
- `controller_events` — System event log
- `state` — Key-value store for runtime state
- `users` — User accounts with bcrypt password hashes
- `api_tokens` — SHA-256 hashed API tokens
- `alerts` — System alerts with resolution tracking

### wancontrol/auth.py (Authentication)

User management and token handling.

**Features:**
- Bcrypt password hashing (12 rounds)
- JWT access tokens (HS256 algorithm)
- SHA-256 hashed API tokens
- Role hierarchy: viewer (1) < operator (2) < admin (3)
- Timing-attack resistant authentication

### wancontrol/config.py (Configuration)

YAML configuration loader and validator.

**Hot-Reloadable Settings:**
- All settings except `db_path` can be changed without restart
- Trigger reload via `SIGHUP` signal or `POST /api/config/reload`

### frontend/ (React Dashboard)

Industrial Precision UI built with:
- **Vite** — Build tool and dev server
- **TypeScript** — Type safety
- **Tailwind CSS** — Utility-first styling
- **Recharts** — Data visualization
- **React Router** — Client-side routing

---

## Installation Guide

### Prerequisites

- Debian or Ubuntu Linux (recommended)
- Python 3.10 or higher
- Two or more WAN interfaces
- Root/sudo access

### Required System Packages

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv \
    iproute2 iputils-ping bind9-dnsutils curl sudo systemd
```

### Quick Install

```bash
# Clone repository
git clone https://github.com/aditya-tripcuro/SDWANcontrol.git
cd SDWANcontrol

# Run installer (must use sudo)
sudo ./install.sh

# Edit configuration
sudo nano /etc/wancontrol/config.yaml

# Restart to apply changes
sudo systemctl restart wancontrol
```

### Manual Installation

1. **Create system user:**
   ```bash
   sudo useradd --system --no-create-home --shell /usr/sbin/nologin wancontrol
   ```

2. **Copy application files:**
   ```bash
   sudo mkdir -p /opt/wancontrol
   sudo cp -a . /opt/wancontrol/
   ```

3. **Create virtual environment:**
   ```bash
   sudo python3 -m venv /opt/wancontrol/venv
   sudo /opt/wancontrol/venv/bin/pip install --upgrade pip
   sudo /opt/wancontrol/venv/bin/pip install -r /opt/wancontrol/requirements.txt
   ```

4. **Create directories:**
   ```bash
   sudo mkdir -p /run/wancontrol /var/lib/wancontrol/logs /etc/wancontrol
   sudo chown -R wancontrol:wancontrol /run/wancontrol /var/lib/wancontrol /etc/wancontrol
   ```

5. **Generate secret key:**
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   # Copy output and replace REPLACE_ME_run_python_secrets_token_hex_32 in config.yaml
   ```

6. **Install systemd service:**
   ```bash
   sudo cp deploy/wancontrol.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable wancontrol
   sudo systemctl start wancontrol
   ```

### Development Mode (DRY_RUN)

For testing without root privileges or actual network changes:

```bash
WANCONTROL_DRY_RUN=1 python -m wancontrol
```

This mode:
- Skips network subprocess calls
- Does not require root
- Safe for non-router machines

---

## Configuration Reference

### Configuration File Location

- Production: `/etc/wancontrol/config.yaml`
- Development: `./config.yaml` (project root)

### Interface Discovery

Use the helper script before editing interfaces:

```bash
python3 /opt/wancontrol/discover_interfaces.py
python3 /opt/wancontrol/discover_interfaces.py --yaml
```

### Configuration Sections

#### interfaces (Required)

List of WAN interfaces to manage.

```yaml
interfaces:
  - name: "enp2s0"           # System interface name
    label: "LAN-1 (Primary)"  # Human-readable label
    expected_speed_mbps: 1000 # Expected bandwidth for load balancing
    gateway: "192.168.1.1"    # Gateway IP address
    routing_table_id: 100     # Unique routing table ID (1-252)
```

#### wan_mode (Required)

Operating mode for multi-WAN routing.

| Value | Description |
|-------|-------------|
| `failover` | One active WAN at a time; switch on failure |
| `load_balance` | All healthy WANs active; traffic weighted by speed |

#### probes

Health check configuration.

```yaml
probes:
  interval_sec: 1                  # Seconds between probe cycles
  dns_targets:                     # DNS servers to query
    - "8.8.8.8"
    - "1.1.1.1"
  icmp_targets:                    # IPs to ping
    - "8.8.8.8"
    - "1.1.1.1"
  http_targets:                    # URLs to fetch
    - "http://connectivitycheck.gstatic.com/generate_204"
  icmp_count: 5                    # Ping packets per target
  icmp_timeout_sec: 3              # Ping timeout
  dns_timeout_sec: 3               # DNS query timeout
  http_timeout_sec: 5              # HTTP request timeout
```

#### scoring

Health score calculation parameters.

```yaml
scoring:
  latency_penalty_per_ms: 0.3         # Points deducted per ms latency
  loss_pct_penalty_per_percent: 2.0   # Points deducted per % packet loss
  dns_fail_penalty: 15                # Points deducted on DNS failure
  http_fail_penalty: 20               # Points deducted on HTTP failure
  hard_fail_threshold: 20             # Score below this = interface failed
  
  # Failover mode only:
  hysteresis_switch_to_backup: 25     # Primary must drop 25 points to switch
  hysteresis_return_to_primary: 10    # Primary must improve 10 points to return
  
  # Load balance mode only:
  recovery_margin: 10                 # Interface must exceed threshold + margin to rejoin pool
```

#### controller

Main control loop timing.

```yaml
controller:
  loop_interval_sec: 1                 # Main loop frequency
  benchmark_interval_sec: 300          # Full benchmark cycle
  metric_collection_timeout_sec: 8     # Timeout for collecting probe results
  heartbeat_interval_sec: 5            # Heartbeat file update frequency
  heartbeat_stale_sec: 15              # Time before heartbeat considered stale
```

#### retention

Data retention policies.

```yaml
retention:
  metrics_hours: 72           # Keep metrics for 72 hours
  events_days: 30             # Keep events for 30 days
  prune_interval_min: 60      # Run cleanup every 60 minutes
```

#### alerting

Webhook notifications.

```yaml
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
```

#### server

Web server configuration.

```yaml
server:
  host: "0.0.0.0"              # Bind address
  port: 5000                   # Bind port
  secret_key: "<32-char-hex>"  # JWT signing key (generate with secrets.token_hex(32))
  jwt_expiry_hours: 24         # JWT token lifetime
  session_timeout_minutes: 60  # Web session timeout
```

#### File Paths

```yaml
lock_file: "./controller.lock"      # PID lock file
heartbeat_file: "./controller.heartbeat"  # Heartbeat file
db_path: "./wan.db"                 # SQLite database path
log_dir: "./logs"                   # Log directory
```

---

## API Reference

### Base URL

```
http://<host>:5000/api
```

### Authentication

All endpoints (except `/health` and `/auth/login`) require authentication.

**JWT Token:**
```bash
curl -H "Authorization: Bearer <jwt_token>" http://localhost:5000/api/status
```

**API Token:**
```bash
curl -H "X-API-Token: <raw_token>" http://localhost:5000/api/status
```

### Endpoints

#### Health & Status

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Service liveness check |
| `/status` | GET | Viewer | Overall controller status |
| `/status/interfaces` | GET | Viewer | Per-interface status summary |

#### Metrics

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/metrics` | GET | Viewer | Historical metrics (params: `interface`, `limit`, `since`) |
| `/metrics/latest` | GET | Viewer | Latest metric per interface |

#### Events

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/events/switches` | GET | Viewer | WAN switch events (param: `limit`) |
| `/events/controller` | GET | Viewer | Controller events (params: `level`, `limit`) |

#### Alerts

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/alerts` | GET | Viewer | Recent alerts (param: `limit`) |
| `/alerts/<id>/resolve` | POST | Operator | Mark alert as resolved |

#### Streaming

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/stream` | GET | Viewer | Server-Sent Events feed |

#### Configuration

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/config/reload` | POST | Admin | Reload config.yaml |

#### Authentication

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/auth/login` | POST | No | Get JWT tokens |
| `/auth/logout` | POST | Yes | Logout (acknowledgment) |
| `/auth/change-password` | POST | Yes | Change password |

#### Users (Admin Only)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/users` | GET | Admin | List all users |
| `/users` | POST | Admin | Create user |
| `/users/<id>` | GET | Admin | Get user details |
| `/users/<id>/deactivate` | POST | Admin | Deactivate user |
| `/users/<id>/role` | POST | Admin | Update user role |

#### API Tokens (Admin Only)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/tokens` | GET | Admin | List API tokens |
| `/tokens` | POST | Admin | Create API token |
| `/tokens/<id>/revoke` | POST | Admin | Revoke API token |

### Example: Login

```bash
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_password"}'
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

---

## Frontend Dashboard

### Access

Open `http://<host>:5000` in a web browser.

### Layout

The dashboard uses a responsive design:
- **Desktop**: Sidebar navigation with header
- **Mobile**: Bottom navigation bar

### Pages

#### Dashboard (Home)

- Live health metrics for all interfaces
- Active connection tracking
- Quick status overview
- Real-time score indicators

#### Metrics

- Historical performance charts
- Latency, jitter, and packet loss graphs
- Throughput analysis
- Time range selection

#### Events

- Chronological system logs
- Filter by level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Audit trail for administrative actions
- Export functionality

#### Alerts

- Real-time incident list
- Alert severity levels
- Resolution tracking
- Acknowledge and resolve actions

#### Config

- View current configuration
- Interface management
- System settings
- Config reload trigger

### Design System

See [DESIGN.md](DESIGN.md) for complete design tokens and component strategy.

**Visual Identity:** Industrial Precision
- Dark mode by default (#020617 canvas)
- High contrast for readability
- Restricted slate palette
- Semantic color usage (red for errors)

---

## Troubleshooting

### Logs

**Service logs:**
```bash
journalctl -u wancontrol -f
```

**Application logs:**
```bash
tail -f /var/lib/wancontrol/logs/wancontrol.log
```

**Status check:**
```bash
sudo systemctl status wancontrol
```

### Common Issues

#### Config file not found

**Error:** `config file not found`

**Solution:**
1. Verify config exists at `/etc/wancontrol/config.yaml`
2. Check `WANCONTROL_CONFIG` environment variable
3. Ensure file permissions allow reading

#### Secret key is default placeholder

**Error:** `secret_key is still the default placeholder`

**Solution:**
```bash
# Generate new secret
python3 -c "import secrets; print(secrets.token_hex(32))"

# Edit config and replace placeholder
sudo nano /etc/wancontrol/config.yaml

# Restart service
sudo systemctl restart wancontrol
```

#### Missing prerequisite command

**Error:** `Missing prerequisite command: ip`

**Solution:**
```bash
sudo apt-get install iproute2 iputils-ping bind9-dnsutils curl
sudo systemctl restart wancontrol
```

#### Sudo permission errors

**Error:** Routing changes fail with sudo-related errors

**Solution:**
1. Verify sudoers fragment exists:
   ```bash
   ls -la /etc/sudoers.d/wancontrol
   ```
2. Validate syntax:
   ```bash
   sudo visudo -c -f /etc/sudoers.d/wancontrol
   ```
3. Reinstall if needed:
   ```bash
   sudo ./install.sh
   ```

#### Socket binding fails

**Error:** `Binding socket to device failed`

**Solution:**
- Ensure process has `CAP_NET_RAW` and `CAP_NET_ADMIN` capabilities
- Run as root or with sudo
- Check systemd service has `AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW`

#### No metrics appearing

**Possible causes:**
1. Probes failing due to network issues
2. Interface names incorrect in config
3. Firewall blocking ICMP/DNS/HTTP

**Debugging:**
```bash
# Check interface status
ip addr show

# Test manual ping
ping -I enp2s0 8.8.8.8

# Check controller logs
journalctl -u wancontrol --since "10 minutes ago"
```

#### Database locked

**Error:** `database is locked`

**Solution:**
- Usually resolves automatically (WAL mode)
- Check for zombie processes:
  ```bash
  ps aux | grep wancontrol
  ```
- Restart service if needed:
  ```bash
  sudo systemctl restart wancontrol
  ```

---

## FAQ

### Q: How many WAN interfaces are supported?

**A:** There is no hard limit. The system supports 2+ interfaces. Performance depends on hardware capacity and probe configuration.

### Q: Can I use WANControl on a single-WAN system?

**A:** Yes, but it's primarily designed for multi-WAN scenarios. On single-WAN, it will monitor health and alert on failures.

### Q: Does WANControl modify iptables/nftables rules?

**A:** No. WANControl uses `ip route` and `ip rule` commands only. It does not touch firewall rules.

### Q: How often are health checks performed?

**A:** By default, probe cycles run every 1 second (`probes.interval_sec`). Each cycle sends ICMP, DNS, and HTTP probes.

### Q: Can I disable certain probe types?

**A:** Currently all three probe types (ICMP, DNS, HTTP) run together. You can set empty target lists to effectively disable specific types, but this is not recommended for accurate health assessment.

### Q: What happens during a failover?

**A:** In failover mode:
1. Primary interface score drops below threshold
2. Hysteresis condition met (prevents flapping)
3. Default route switched to backup interface
4. Event logged to database
5. Alert sent if webhook configured

### Q: How does load balancing work?

**A:** In load_balance mode:
1. All healthy interfaces added to nexthop pool
2. Traffic distributed proportionally to `expected_speed_mbps`
3. Unhealthy interfaces (score < threshold) removed from pool
4. Pool updated dynamically as scores change

### Q: Is the database backed up automatically?

**A:** No automatic backup is provided. Recommended to add cron job:
```bash
0 2 * * * cp /var/lib/wancontrol/wan.db /backup/wan.db.$(date +\%F)
```

### Q: Can I integrate with external monitoring systems?

**A:** Yes. Options include:
- Webhook alerts to ntfy, Slack, Discord, etc.
- REST API polling for metrics
- Server-Sent Events stream for real-time data
- Direct SQLite database queries (read-only while service running)

### Q: How do I uninstall WANControl?

**A:** Use the uninstall script:
```bash
sudo ./uninstall.sh
```

Or manually:
```bash
sudo systemctl stop wancontrol
sudo systemctl disable wancontrol
sudo rm -rf /opt/wancontrol
sudo rm /etc/systemd/system/wancontrol.service
sudo rm /etc/sudoers.d/wancontrol
sudo rm /etc/logrotate.d/wancontrol
sudo systemctl daemon-reload
# Optional: remove config and data
# sudo rm -rf /etc/wancontrol /var/lib/wancontrol
```

### Q: Where can I get help?

**A:** 
- Check this wiki and README.md
- Review DESIGN.md for UI details
- Examine source code in `/opt/wancontrol/wancontrol/`
- Check GitHub issues for known problems
