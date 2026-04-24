# WANControl v2 - Complete Technical Documentation

## Document Information

- **Project**: WANControl v2
- **Version**: 2.0
- **Type**: SD-WAN Load-Balancing Controller
- **License**: See LICENSE file
- **Repository**: https://github.com/aditya-tripcuro/SDWANcontrol

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Requirements](#system-requirements)
3. [Installation Procedures](#installation-procedures)
4. [Architecture Deep Dive](#architecture-deep-dive)
5. [Module Reference](#module-reference)
6. [Database Schema](#database-schema)
7. [API Specification](#api-specification)
8. [Configuration Options](#configuration-options)
9. [Security Considerations](#security-considerations)
10. [Performance Tuning](#performance-tuning)
11. [Testing Strategy](#testing-strategy)
12. [Deployment Guide](#deployment-guide)
13. [Maintenance Procedures](#maintenance-procedures)
14. [Appendices](#appendices)

---

## Executive Summary

### Purpose

WANControl v2 is a production-ready SD-WAN controller that provides intelligent multi-WAN traffic management for Linux systems. It enables organizations to maximize network reliability and performance through automated failover and load balancing across multiple internet connections.

### Problem Statement

Organizations with multiple WAN connections face challenges in:
- Managing manual failover during outages
- Utilizing all available bandwidth efficiently
- Monitoring connection health continuously
- Making data-driven routing decisions

### Solution

WANControl v2 addresses these challenges through:
- Automated health monitoring (ICMP, DNS, HTTP)
- Dynamic scoring algorithm based on latency, loss, and connectivity
- Two operational modes: failover and load_balance
- Real-time visibility via web dashboard
- RESTful API for automation integration
- Persistent storage for historical analysis

### Key Metrics

- Probe interval: 1 second (configurable)
- Failover time: < 5 seconds typical
- Supported interfaces: Unlimited (practical limit ~10)
- Database: SQLite with WAL mode
- API response time: < 100ms typical

---

## System Requirements

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 1 core | 2+ cores |
| RAM | 512 MB | 1+ GB |
| Storage | 100 MB | 500 MB+ |
| Network | 2 interfaces | 3+ interfaces |

### Software Requirements

**Operating System:**
- Debian 11+ (Bullseye or later)
- Ubuntu 20.04+ (Focal or later)
- Other Linux distributions (untested, may require adjustments)

**Python:**
- Version: 3.10 or higher
- Required modules: See requirements.txt

**System Packages:**
```bash
iproute2        # Route and rule management
iputils-ping    # ICMP probing
bind9-dnsutils  # DNS querying (dig)
curl            # HTTP probing
sudo            # Privilege escalation
systemd         # Service management
```

**Optional (Frontend Development):**
```bash
npm >= 18.x     # Node.js package manager
node >= 18.x    # JavaScript runtime
```

### Network Requirements

- At least two WAN interfaces with distinct gateways
- Each interface must have:
  - Valid IP address
  - Reachable gateway
  - Internet connectivity
- Routing table IDs must be unique (1-252)
- Process requires CAP_NET_ADMIN and CAP_NET_RAW capabilities

---

## Installation Procedures

### Automated Installation (Recommended)

```bash
#!/bin/bash
# Quick install script

# Clone repository
git clone https://github.com/aditya-tripcuro/SDWANcontrol.git
cd SDWANcontrol

# Run installer as root
sudo ./install.sh

# Verify installation
sudo systemctl status wancontrol

# Check logs
journalctl -u wancontrol -f
```

### Manual Installation Steps

#### Step 1: Install System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    iproute2 \
    iputils-ping \
    bind9-dnsutils \
    curl \
    sudo \
    systemd
```

#### Step 2: Create System User

```bash
sudo useradd --system \
    --no-create-home \
    --shell /usr/sbin/nologin \
    wancontrol
```

#### Step 3: Deploy Application Files

```bash
sudo mkdir -p /opt/wancontrol
sudo cp -a . /opt/wancontrol/
sudo chown -R wancontrol:wancontrol /opt/wancontrol
```

#### Step 4: Create Python Virtual Environment

```bash
sudo python3 -m venv /opt/wancontrol/venv
sudo /opt/wancontrol/venv/bin/pip install --upgrade pip
sudo /opt/wancontrol/venv/bin/pip install -r /opt/wancontrol/requirements.txt
```

#### Step 5: Create Directory Structure

```bash
sudo mkdir -p \
    /run/wancontrol \
    /var/lib/wancontrol/logs \
    /etc/wancontrol

sudo chown -R wancontrol:wancontrol \
    /run/wancontrol \
    /var/lib/wancontrol \
    /etc/wancontrol
```

#### Step 6: Generate Configuration

```bash
# Copy default config
sudo cp /opt/wancontrol/config.yaml /etc/wancontrol/config.yaml

# Generate secret key
SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Update config with secret
sudo sed -i "s/REPLACE_ME_run_python_secrets_token_hex_32/$SECRET/" \
    /etc/wancontrol/config.yaml
```

#### Step 7: Configure Interfaces

Edit `/etc/wancontrol/config.yaml`:

```yaml
interfaces:
  - name: "enp2s0"
    label: "Primary ISP"
    expected_speed_mbps: 1000
    gateway: "192.168.1.1"
    routing_table_id: 100
    
  - name: "enp3s0"
    label: "Backup ISP"
    expected_speed_mbps: 500
    gateway: "192.168.2.1"
    routing_table_id: 101

wan_mode: "failover"  # or "load_balance"
```

#### Step 8: Install Deployment Assets

```bash
# Sudoers configuration
sudo cp /opt/wancontrol/deploy/wancontrol.sudoers /etc/sudoers.d/
sudo chmod 440 /etc/sudoers.d/wancontrol
sudo visudo -c -f /etc/sudoers.d/wancontrol  # Validate

# Logrotate configuration
sudo cp /opt/wancontrol/deploy/wancontrol.logrotate /etc/logrotate.d/wancontrol

# Systemd service
sudo cp /opt/wancontrol/deploy/wancontrol.service /etc/systemd/system/
sudo systemctl daemon-reload
```

#### Step 9: Enable and Start Service

```bash
sudo systemctl enable wancontrol
sudo systemctl start wancontrol
sudo systemctl status wancontrol
```

#### Step 10: Verify Operation

```bash
# Check service status
sudo systemctl status wancontrol

# View logs
journalctl -u wancontrol -n 50

# Access dashboard
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):5000"

# Get admin credentials from journal
journalctl -u wancontrol | grep "WANControl first-run"
```

---

## Architecture Deep Dive

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Interface Layer                        │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │   Web Browser    │  │   REST Clients   │  │  Automation      │  │
│  │   (Dashboard)    │  │   (API Calls)    │  │  (Scripts)       │  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  │
└───────────┼─────────────────────┼─────────────────────┼────────────┘
            │                     │                     │
            └─────────────────────┼─────────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │     Flask Application     │
                    │    (wancontrol/app.py)    │
                    │                           │
                    │  ┌─────────────────────┐  │
                    │  │ Authentication      │  │
                    │  │ - JWT Validation    │  │
                    │  │ - Role Checking     │  │
                    │  │ - API Token Auth    │  │
                    │  └─────────────────────┘  │
                    │                           │
                    │  ┌─────────────────────┐  │
                    │  │ REST Endpoints      │  │
                    │  │ - Status            │  │
                    │  │ - Metrics           │  │
                    │  │ - Events            │  │
                    │  │ - Alerts            │  │
                    │  │ - Config            │  │
                    │  └─────────────────────┘  │
                    │                           │
                    │  ┌─────────────────────┐  │
                    │  │ SSE Streaming       │  │
                    │  │ - Real-time Updates │  │
                    │  └─────────────────────┘  │
                    └─────────────┬─────────────┘
                                  │
            ┌─────────────────────┼─────────────────────┐
            │                     │                     │
┌───────────▼──────────┐ ┌────────▼────────┐ ┌────────▼────────┐
│   Controller Loop    │ │   Database      │ │   Frontend      │
│ (Background Thread)  │ │   (SQLite)      │ │   (Static)      │
│                      │ │                 │ │                 │
│ ┌──────────────────┐ │ │ ┌─────────────┐ │ │ ┌─────────────┐ │
│ │ Prober           │ │ │ │ Migrations  │ │ │ │ React App   │ │
│ │ - ICMP           │ │ │ │ Tables      │ │ │ │ - Dashboard │ │
│ │ - DNS            │ │ │ │ Queries     │ │ │ │ - Metrics   │ │
│ │ - HTTP           │ │ │ │ Retention   │ │ │ │ - Events    │ │
│ └──────────────────┘ │ │ │ Persistence │ │ │ │ - Config    │ │
│                      │ │ └─────────────┘ │ │ └─────────────┘ │
│ ┌──────────────────┐ │ │                 │ │                 │
│ │ Scorer           │ │ │ Tables:         │ │                 │
│ │ - Latency        │ │ │ - metrics       │ │                 │
│ │ - Loss           │ │ │ - events        │ │                 │
│ │ - Connectivity   │ │ │ - alerts        │ │                 │
│ │ - Weighted Score │ │ │ - users         │ │                 │
│ └──────────────────┘ │ │ - tokens        │ │                 │
│                      │ │ - state         │ │                 │
│ ┌──────────────────┐ │ └─────────────────┘ │                 │
│ │ Decision Engine  │ │                     │                 │
│ │ - Mode Logic     │ │                     │                 │
│ │ - Hysteresis     │ │                     │                 │
│ │ - Pool Mgmt      │ │                     │                 │
│ └──────────────────┘ │                     │                 │
│                      │                     │                 │
│ ┌──────────────────┐ │                     │                 │
│ │ Alert Manager    │ │                     │                 │
│ │ - Threshold      │ │                     │                 │
│ │ - Webhooks       │ │                     │                 │
│ │ - Notifications  │ │                     │                 │
│ └──────────────────┘ │                     │                 │
└───────────┬──────────┘                     │                 │
            │                                │                 │
            ▼                                │                 │
┌───────────────────────┐                   │                 │
│   Network Layer       │                   │                 │
│ (wancontrol/network.py)                   │                 │
│                       │                   │                 │
│ ┌───────────────────┐ │                   │                 │
│ │ Route Management  │ │                   │                 │
│ │ - Policy Rules    │ │                   │                 │
│ │ - Routing Tables  │ │                   │                 │
│ │ - Default Routes  │ │                   │                 │
│ └───────────────────┘ │                   │                 │
│                       │                   │                 │
│ ┌───────────────────┐ │                   │                 │
│ │ Socket Binding    │ │                   │                 │
│ │ - SO_BINDTODEVICE │ │                   │                 │
│ │ - Interface-aware │ │                   │                 │
│ └───────────────────┘ │                   │                 │
└───────────┬───────────┘                   │                 │
            │                               │                 │
            ▼                               │                 │
┌───────────────────────────────────────────────────────────────┐
│                    Linux Kernel Network Stack                 │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │   WAN 0     │  │   WAN 1     │  │   WAN 2     │          │
│  │  enp2s0     │  │  enp3s0     │  │  wlp5s0     │          │
│  │ 192.168.1.x │  │192.168.2.x  │  │192.168.3.x  │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
└─────────┼────────────────┼────────────────┼──────────────────┘
          │                │                │
          ▼                ▼                ▼
      [ISP 1]          [ISP 2]          [ISP 3]
```

### Data Flow

#### Health Probe Cycle

1. **Timer Trigger**: Controller loop wakes every `loop_interval_sec`
2. **Probe Dispatch**: For each interface:
   - Spawn ICMP ping probes (bound to interface)
   - Spawn DNS query probes (bound to interface)
   - Spawn HTTP request probes (bound to interface)
3. **Result Collection**: Gather probe results with timeout
4. **Score Calculation**: Apply penalty formula
5. **Decision Logic**: Evaluate mode-specific rules
6. **Action Execution**: Update routing if needed
7. **Persistence**: Store metrics in database
8. **Alert Evaluation**: Check thresholds and send notifications

#### Scoring Algorithm

```python
base_score = 100

# Latency penalty
latency_penalty = avg_latency_ms * latency_penalty_per_ms

# Packet loss penalty
loss_penalty = loss_pct * loss_penalty_per_percent

# DNS failure penalty
dns_penalty = 0 if dns_ok else dns_fail_penalty

# HTTP failure penalty
http_penalty = 0 if http_ok else http_fail_penalty

final_score = base_score - latency_penalty - loss_penalty - dns_penalty - http_penalty
```

#### Failover Decision Logic

```python
if wan_mode == "failover":
    if primary.score < (backup.score + hysteresis_switch_to_backup):
        switch_to(backup)
    elif primary.score > (backup.score + hysteresis_return_to_primary):
        switch_to(primary)
```

#### Load Balance Pool Management

```python
if wan_mode == "load_balance":
    for interface in interfaces:
        if interface.score >= hard_fail_threshold + recovery_margin:
            add_to_pool(interface)
        elif interface.score < hard_fail_threshold:
            remove_from_pool(interface)
```

---

## Module Reference

### wancontrol/__init__.py

Package initialization and version declaration.

**Exports:**
- `__version__`: Package version string

### wancontrol/__main__.py

Entry point for `python -m wancontrol` execution.

**Responsibilities:**
- Parse environment variables
- Initialize logging
- Load configuration
- Initialize database
- Start controller
- Launch Flask application
- Handle graceful shutdown

**Environment Variables:**
- `WANCONTROL_CONFIG`: Path to config file (default: `/etc/wancontrol/config.yaml`)
- `WANCONTROL_DRY_RUN`: Enable dry-run mode (default: `0`)

### wancontrol/app.py

Flask REST API application.

**Key Classes:**
- None (functional design)

**Key Functions:**

#### `require_auth(f)`
Decorator that validates authentication and injects `g.principal`.

#### `require_role(minimum_role)`
Decorator factory that enforces minimum role requirement.

#### Endpoint Handlers:
- `health()`: GET /api/health
- `login()`: POST /api/auth/login
- `logout()`: POST /api/auth/logout
- `change_password()`: POST /api/auth/change-password
- `get_status()`: GET /api/status
- `get_interfaces_status()`: GET /api/status/interfaces
- `get_metrics()`: GET /api/metrics
- `get_latest_metrics()`: GET /api/metrics/latest
- `get_switch_events()`: GET /api/events/switches
- `get_controller_events()`: GET /api/events/controller
- `get_alerts()`: GET /api/alerts
- `resolve_alert(alert_id)`: POST /api/alerts/<id>/resolve
- `list_users()`: GET /api/users
- `create_user()`: POST /api/users
- `get_user(user_id)`: GET /api/users/<id>
- `deactivate_user(user_id)`: POST /api/users/<id>/deactivate
- `update_role(user_id)`: POST /api/users/<id>/role
- `list_tokens()`: GET /api/tokens
- `create_token()`: POST /api/tokens
- `revoke_token(token_id)`: POST /api/tokens/<id>/revoke
- `reload_config()`: POST /api/config/reload
- `stream()`: GET /api/stream (SSE)

### wancontrol/auth.py

Authentication and authorization module.

**Classes:**

#### `AuthError(Exception)`
Authentication/authorization error with code and message.

**Codes:**
- `invalid_credentials`
- `token_expired`
- `token_invalid`
- `token_revoked`
- `insufficient_role`
- `user_inactive`
- `user_not_found`
- `username_taken`
- `weak_password`

#### `UserPrincipal`
Authenticated user representation.

**Fields:**
- `user_id`: int
- `username`: str
- `role`: str (viewer|operator|admin)
- `source`: str (jwt|session|api_token)

#### `TokenPair`
JWT token pair returned on login.

**Fields:**
- `access_token`: str
- `token_type`: str (always "bearer")
- `expires_in`: int (seconds)

#### `Auth`
Main authentication class.

**Methods:**
- `__init__(db, server_cfg)`: Initialize with database and server config
- `_hash_password(password)`: Hash password with bcrypt
- `_check_password(password, hashed)`: Verify password against hash
- `create_user(username, password, role, created_by_user_id)`: Create new user
- `authenticate(username, password)`: Authenticate and return token pair
- `change_password(user_id, old_password, new_password)`: Change user password
- `deactivate_user(user_id, deactivated_by_user_id)`: Deactivate account
- `update_role(user_id, new_role, updated_by_user_id)`: Update user role
- `list_users()`: List all users
- `ensure_admin_exists()`: Create admin user if none exist
- `issue_token(user)`: Generate JWT for user
- `verify_token(token)`: Validate JWT and return principal
- `create_api_token(user_id, label, expires_in_days)`: Generate API token
- `verify_api_token(raw_token)`: Validate API token and return principal
- `revoke_api_token(token_id, revoked_by_user_id)`: Revoke API token
- `list_api_tokens(user_id)`: List API tokens for user
- `require_role(principal, minimum_role)`: Check role hierarchy

**Constants:**
- `BCRYPT_ROUNDS = 12`
- `JWT_ALGORITHM = "HS256"`
- `ROLE_HIERARCHY = {"viewer": 1, "operator": 2, "admin": 3}`
- `_MIN_PASSWORD_LEN = 12`

### wancontrol/config.py

Configuration loading and validation.

**Classes:**

#### `ConfigError(Exception)`
Configuration validation error.

#### `InterfaceConfig`
Single interface configuration.

**Fields:**
- `name`: str (interface name)
- `label`: str (human-readable label)
- `expected_speed_mbps`: int
- `gateway`: str (IPv4)
- `routing_table_id`: int (1-252)

#### `ProbesConfig`
Health probe configuration.

**Fields:**
- `interval_sec`: int
- `dns_targets`: list[str]
- `icmp_targets`: list[str]
- `http_targets`: list[str]
- `icmp_count`: int
- `icmp_timeout_sec`: int
- `dns_timeout_sec`: int
- `http_timeout_sec`: int

#### `ScoringConfig`
Score calculation parameters.

**Fields:**
- `latency_penalty_per_ms`: float
- `loss_penalty_per_percent`: float
- `dns_fail_penalty`: int
- `http_fail_penalty`: int
- `hard_fail_threshold`: int
- `hysteresis_switch_to_backup`: int
- `hysteresis_return_to_primary`: int
- `recovery_margin`: int

#### `ControllerConfig`
Controller loop timing.

**Fields:**
- `loop_interval_sec`: int
- `benchmark_interval_sec`: int
- `metric_collection_timeout_sec`: int
- `heartbeat_interval_sec`: int
- `heartbeat_stale_sec`: int

#### `RetentionConfig`
Data retention policies.

**Fields:**
- `metrics_hours`: int
- `events_days`: int
- `prune_interval_min`: int

#### `WebhookConfig`
Webhook notification configuration.

**Fields:**
- `url`: str
- `method`: str
- `headers`: dict[str, str]
- `on_events`: list[str]

#### `AlertingConfig`
Alerting configuration.

**Fields:**
- `enabled`: bool
- `webhooks`: list[WebhookConfig]

#### `ServerConfig`
Web server configuration.

**Fields:**
- `host`: str
- `port`: int
- `secret_key`: str
- `jwt_expiry_hours`: int
- `session_timeout_minutes`: int

#### `AppConfig`
Complete application configuration.

**Fields:**
- `interfaces`: list[InterfaceConfig]
- `wan_mode`: str (failover|load_balance)
- `probes`: ProbesConfig
- `scoring`: ScoringConfig
- `controller`: ControllerConfig
- `retention`: RetentionConfig
- `alerting`: AlertingConfig
- `server`: ServerConfig
- `lock_file`: str
- `heartbeat_file`: str
- `db_path`: str
- `log_dir`: str

#### `Config`
Configuration loader.

**Methods:**
- `__init__(path)`: Initialize with config file path
- `load()`: Load and validate configuration
- `_parse_interfaces(data)`: Parse interface configurations
- `_validate()`: Validate complete configuration

### wancontrol/controller.py

Controller lifecycle management.

**Classes:**

#### `Controller`
Main controller class.

**Methods:**
- `__init__(config, db)`: Initialize with config and database
- `start()`: Start controller (snapshot routes, setup interfaces)
- `wait()`: Block until shutdown
- `shutdown()`: Graceful shutdown (teardown interfaces, restore routes)

**Functions:**
- `setup_signal_handlers(controller)`: Register SIGTERM/SIGINT handlers

### wancontrol/database.py

SQLite database layer.

**Row Dataclasses:**
- `MetricRow`: Metric record
- `SwitchEventRow`: WAN switch event
- `ControllerEventRow`: Controller event log
- `UserRow`: User account
- `ApiTokenRow`: API token
- `AlertRow`: Alert record
- `DbStats`: Database statistics

**Classes:**

#### `Database`
Thread-safe SQLite wrapper.

**Methods:**
- `__init__(db_path)`: Initialize with database path
- `initialize()`: Create schema, enable WAL, run migrations
- `insert_metric(...)`: Insert metric record
- `get_metrics(interface, limit, since)`: Query metrics
- `get_latest_metric(interface)`: Get latest metric for interface
- `insert_switch_event(...)`: Record switch event
- `get_switch_events(limit)`: Query switch events
- `log_event(...)`: Log controller event
- `get_events(limit, level)`: Query events
- `set_state(key, value)`: Set state value
- `get_state(key, default)`: Get state value
- `get_all_state()`: Get all state values
- `create_user(...)`: Create user
- `get_user_by_username(username)`: Get user by username
- `get_user_by_id(user_id)`: Get user by ID
- `update_user_last_login(user_id)`: Update last login timestamp
- `update_user_password(user_id, password_hash)`: Update password
- `deactivate_user(user_id)`: Deactivate user
- `update_user_role(user_id, role)`: Update role
- `list_users()`: List all users
- `count_users()`: Count users
- `create_api_token(...)`: Create API token
- `get_api_token_by_hash(token_hash)`: Get token by hash
- `touch_api_token(token_id)`: Update last used timestamp
- `revoke_api_token(token_id)`: Revoke token
- `list_api_tokens(user_id)`: List tokens for user
- `get_alerts(limit)`: Get recent alerts
- `insert_alert(...)`: Create alert
- `resolve_alert(alert_id)`: Mark alert resolved
- `prune_old_data(config)`: Apply retention policies
- `get_stats()`: Get database statistics

### wancontrol/network.py

Network operations module.

**Functions:**

#### `snapshot_default_routes(db)`
Save current default routes to database.

#### `restore_default_routes(db)`
Restore default routes from snapshot.

#### `get_interface_subnet(iface)`
Get IPv4 CIDR for interface.

#### `setup_interface_routing(iface_cfg)`
Create routing table and policy rule for interface.

#### `teardown_interface_routing(iface_cfg)`
Remove routing configuration for interface.

#### `setup_all_interfaces(interfaces)`
Setup routing for all interfaces.

#### `teardown_all_interfaces(interfaces)`
Teardown routing for all interfaces.

#### `bind_socket_to_interface(sock, iface_name)`
Bind socket to interface using SO_BINDTODEVICE.

#### `find_available_port(start, max_attempts)`
Find available TCP port.

### wancontrol/logging_config.py

Logging configuration.

**Functions:**

#### `setup_logging(config)`
Configure logging from YAML config.

#### `get_log_config()`
Get default logging configuration.

### wancontrol/monitor.py

Health monitoring module (probe implementation).

*Note: Full implementation details depend on completed probe logic.*

### wancontrol/watchdog.py

Process watchdog for standby/failover scenarios.

*Note: Full implementation details depend on HA features.*

### discover_interfaces.py

Interface discovery helper script.

**Usage:**
```bash
python3 discover_interfaces.py              # Table output
python3 discover_interfaces.py --yaml       # YAML output
```

---

## Database Schema

### Schema Version

Current version: 1

### Tables

#### schema_version

Tracks database schema version.

```sql
CREATE TABLE schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  REAL NOT NULL
);
```

#### metrics

Stores health probe results.

```sql
CREATE TABLE metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    interface   TEXT    NOT NULL,
    timestamp   REAL    NOT NULL,
    latency_ms  REAL    NOT NULL,
    jitter_ms   REAL    NOT NULL,
    loss_pct    REAL    NOT NULL,
    dns_ok      INTEGER NOT NULL,
    http_ok     INTEGER NOT NULL,
    score       REAL    NOT NULL
);

CREATE INDEX idx_metrics_iface_ts 
    ON metrics(interface, timestamp DESC);
```

**Columns:**
- `id`: Auto-incrementing primary key
- `interface`: Interface name (e.g., "enp2s0")
- `timestamp`: Unix timestamp (float)
- `latency_ms`: Average latency in milliseconds
- `jitter_ms`: Latency variance in milliseconds
- `loss_pct`: Packet loss percentage (0-100)
- `dns_ok`: DNS probe success (0/1)
- `http_ok`: HTTP probe success (0/1)
- `score`: Calculated health score (0-100)

#### switch_events

Records WAN failover and pool change events.

```sql
CREATE TABLE switch_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL    NOT NULL,
    from_interface  TEXT    NOT NULL,
    to_interface    TEXT    NOT NULL,
    reason          TEXT    NOT NULL,
    triggered_by    TEXT    NOT NULL DEFAULT 'controller',
    score_before    REAL    NOT NULL,
    score_after     REAL    NOT NULL
);

CREATE INDEX idx_switch_events_ts 
    ON switch_events(timestamp DESC);
```

**Columns:**
- `id`: Auto-incrementing primary key
- `timestamp`: Unix timestamp
- `from_interface`: Previous active interface
- `to_interface`: New active interface
- `reason`: Switch reason (e.g., "hard_fail", "hysteresis")
- `triggered_by`: Trigger source ("controller" or "manual")
- `score_before`: Score before switch
- `score_after`: Score after switch

#### controller_events

System event log.

```sql
CREATE TABLE controller_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,
    level       TEXT    NOT NULL,
    component   TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    user_id     INTEGER REFERENCES users(id)
);

CREATE INDEX idx_ctrl_events_ts 
    ON controller_events(timestamp DESC);
```

**Columns:**
- `id`: Auto-incrementing primary key
- `timestamp`: Unix timestamp
- `level`: Log level (DEBUG|INFO|WARNING|ERROR|CRITICAL)
- `component`: Source component (e.g., "controller", "network", "auth")
- `message`: Event description
- `user_id`: Associated user (nullable)

#### state

Key-value store for runtime state.

```sql
CREATE TABLE state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  REAL NOT NULL
);
```

**Common Keys:**
- `controller_status`: Current status (running|stopping|stopped)
- `active_interface`: Currently active WAN interface
- `pre_start_default_routes`: JSON snapshot of original routes
- `server_port`: Actual bound port (may differ from config)

#### users

User accounts.

```sql
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'viewer',
    created_at      REAL    NOT NULL,
    last_login      REAL,
    is_active       INTEGER NOT NULL DEFAULT 1
);
```

**Columns:**
- `id`: Auto-incrementing primary key
- `username`: Unique username
- `password_hash`: Bcrypt hash (12 rounds)
- `role`: User role (viewer|operator|admin)
- `created_at`: Account creation timestamp
- `last_login`: Last successful login
- `is_active`: Account status (0/1)

#### api_tokens

API tokens for automation.

```sql
CREATE TABLE api_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    token_hash  TEXT    NOT NULL UNIQUE,
    label       TEXT    NOT NULL,
    created_at  REAL    NOT NULL,
    last_used   REAL,
    expires_at  REAL,
    is_revoked  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_api_tokens_hash 
    ON api_tokens(token_hash);
```

**Columns:**
- `id`: Auto-incrementing primary key
- `user_id`: Owner user ID
- `token_hash`: SHA-256 hash of raw token
- `label`: Human-readable label
- `created_at`: Creation timestamp
- `last_used`: Last usage timestamp
- `expires_at`: Expiry timestamp (nullable)
- `is_revoked`: Revocation status (0/1)

#### alerts

System alerts.

```sql
CREATE TABLE alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,
    level       TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    resolved_at REAL,
    notified    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_alerts_ts 
    ON alerts(timestamp DESC);
```

**Columns:**
- `id`: Auto-incrementing primary key
- `timestamp`: Alert timestamp
- `level`: Severity (info|warning|error|critical)
- `title`: Short title
- `body`: Detailed description
- `resolved_at`: Resolution timestamp (nullable)
- `notified`: Notification sent flag (0/1)

---

## API Specification

### Base URL

```
http://<host>:5000/api
```

### Authentication

#### JWT Token

Obtain via `/auth/login`:

```bash
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"..."}'
```

Use in subsequent requests:

```bash
curl -H "Authorization: Bearer <access_token>" \
  http://localhost:5000/api/status
```

#### API Token

Create via `/tokens` endpoint, then use:

```bash
curl -H "X-API-Token: <raw_token>" \
  http://localhost:5000/api/status
```

### Response Format

All responses are JSON with appropriate HTTP status codes.

**Success Response:**
```json
{
  "status": "ok",
  "data": { ... }
}
```

**Error Response:**
```json
{
  "error": "error_code",
  "message": "Human-readable message"
}
```

### Endpoints

#### Health

**GET /api/health**

Check service liveness.

**Authentication:** Not required

**Response:**
```json
{
  "status": "ok",
  "version": "2.0.0",
  "timestamp": 1699900000.123
}
```

#### Authentication

**POST /api/auth/login**

Authenticate and obtain JWT tokens.

**Request:**
```json
{
  "username": "admin",
  "password": "secure_password"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

**POST /api/auth/logout**

Logout (acknowledgment only; JWTs are stateless).

**Authentication:** Required

**Response:**
```json
{
  "message": "logged out"
}
```

**POST /api/auth/change-password**

Change authenticated user's password.

**Authentication:** Required

**Request:**
```json
{
  "old_password": "current_password",
  "new_password": "new_secure_password"
}
```

**Response:**
```json
{
  "message": "password changed"
}
```

#### Status

**GET /api/status**

Get overall controller status.

**Authentication:** Viewer+

**Response:**
```json
{
  "mode": "load_balance",
  "active_interface": "enp2s0",
  "interfaces": {
    "enp2s0": {
      "wan_state": "active",
      "score": 95.5,
      "in_pool": true
    },
    "enp3s0": {
      "wan_state": "standby",
      "score": 88.2,
      "in_pool": true
    }
  },
  "uptime_seconds": 3600
}
```

**GET /api/status/interfaces**

Get per-interface status.

**Authentication:** Viewer+

**Response:**
```json
[
  {
    "name": "enp2s0",
    "label": "Primary ISP",
    "expected_speed_mbps": 1000,
    "gateway": "192.168.1.1",
    "routing_table_id": 100,
    "wan_state": "active",
    "score": 95.5,
    "in_pool": true
  }
]
```

#### Metrics

**GET /api/metrics**

Get historical metrics.

**Query Parameters:**
- `interface` (optional): Filter by interface name
- `limit` (optional): Max records (default: 200)
- `since` (optional): Unix timestamp filter

**Authentication:** Viewer+

**Response:**
```json
[
  {
    "id": 1234,
    "interface": "enp2s0",
    "timestamp": 1699900000.123,
    "latency_ms": 15.2,
    "jitter_ms": 2.1,
    "loss_pct": 0.0,
    "dns_ok": true,
    "http_ok": true,
    "score": 95.5
  }
]
```

**GET /api/metrics/latest**

Get latest metric per interface.

**Authentication:** Viewer+

**Response:**
```json
{
  "enp2s0": {
    "id": 1234,
    "interface": "enp2s0",
    "timestamp": 1699900000.123,
    "latency_ms": 15.2,
    "jitter_ms": 2.1,
    "loss_pct": 0.0,
    "dns_ok": true,
    "http_ok": true,
    "score": 95.5
  },
  "enp3s0": null
}
```

#### Events

**GET /api/events/switches**

Get WAN switch events.

**Query Parameters:**
- `limit` (optional): Max records (default: 50)

**Authentication:** Viewer+

**Response:**
```json
[
  {
    "id": 42,
    "timestamp": 1699900000.123,
    "from_interface": "enp3s0",
    "to_interface": "enp2s0",
    "reason": "hysteresis",
    "triggered_by": "controller",
    "score_before": 65.0,
    "score_after": 92.0
  }
]
```

**GET /api/events/controller**

Get controller events.

**Query Parameters:**
- `level` (optional): Filter by level
- `limit` (optional): Max records (default: 100)

**Authentication:** Viewer+

**Response:**
```json
[
  {
    "id": 100,
    "timestamp": 1699900000.123,
    "level": "INFO",
    "component": "controller",
    "message": "Controller started",
    "user_id": null
  }
]
```

#### Alerts

**GET /api/alerts**

Get recent alerts.

**Query Parameters:**
- `limit` (optional): Max records (default: 20)

**Authentication:** Viewer+

**Response:**
```json
[
  {
    "id": 15,
    "timestamp": 1699900000.123,
    "level": "warning",
    "title": "Link degraded",
    "body": "Interface enp3s0 score below threshold",
    "resolved_at": null,
    "notified": true
  }
]
```

**POST /api/alerts/:id/resolve**

Mark alert as resolved.

**Authentication:** Operator+

**Response:**
```json
{
  "resolved": true,
  "alert_id": 15
}
```

#### Users (Admin Only)

**GET /api/users**

List all users.

**Authentication:** Admin

**Response:**
```json
[
  {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "created_at": 1699800000.0,
    "last_login": 1699900000.0,
    "is_active": true
  }
]
```

**POST /api/users**

Create new user.

**Authentication:** Admin

**Request:**
```json
{
  "username": "operator1",
  "password": "secure_password_12_chars",
  "role": "operator"
}
```

**Response:**
```json
{
  "id": 2,
  "username": "operator1",
  "role": "operator"
}
```

**GET /api/users/:id**

Get user details.

**Authentication:** Admin

**Response:**
```json
{
  "id": 1,
  "username": "admin",
  "role": "admin",
  "created_at": 1699800000.0,
  "last_login": 1699900000.0,
  "is_active": true
}
```

**POST /api/users/:id/deactivate**

Deactivate user.

**Authentication:** Admin

**Response:**
```json
{
  "deactivated": true,
  "user_id": 2
}
```

**POST /api/users/:id/role**

Update user role.

**Authentication:** Admin

**Request:**
```json
{
  "role": "admin"
}
```

**Response:**
```json
{
  "updated": true,
  "user_id": 2,
  "new_role": "admin"
}
```

#### API Tokens (Admin Only)

**GET /api/tokens**

List API tokens.

**Authentication:** Admin

**Response:**
```json
[
  {
    "id": 1,
    "user_id": 1,
    "label": "Monitoring Script",
    "created_at": 1699800000.0,
    "last_used": 1699900000.0,
    "expires_at": null,
    "is_revoked": false
  }
]
```

**POST /api/tokens**

Create API token.

**Authentication:** Admin

**Request:**
```json
{
  "label": "Monitoring Script",
  "expires_in_days": 365
}
```

**Response:**
```json
{
  "id": 2,
  "token": "raw_token_here_show_once",
  "expires_at": 1731436000.0
}
```

**POST /api/tokens/:id/revoke**

Revoke API token.

**Authentication:** Admin

**Response:**
```json
{
  "revoked": true,
  "token_id": 2
}
```

#### Configuration

**POST /api/config/reload**

Reload configuration from disk.

**Authentication:** Admin

**Response:**
```json
{
  "reloaded": true,
  "timestamp": 1699900000.123
}
```

#### Streaming

**GET /api/stream**

Server-Sent Events stream for real-time updates.

**Authentication:** Viewer+

**Event Format:**
```
data: {"type": "metric", "interface": "enp2s0", "score": 95.5}

data: {"type": "switch", "from": "enp3s0", "to": "enp2s0"}

data: {"type": "alert", "level": "warning", "title": "Link degraded"}
```

---

*(Continued in next part due to length...)*
