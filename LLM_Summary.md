# WANControl v2 — LLM Project Summary

## Overview
WANControl v2 is a production-grade SD-WAN load-balancing controller for Linux (Debian/Ubuntu). It manages two or more WAN interfaces (multi-WAN) to provide high availability and optimal bandwidth utilization through `failover` (active-passive) and `load_balance` (active-active) modes.


## Tech Stack
- **Backend:** Python 3.10+, Flask 3.1, Gunicorn, SQLite 3 (WAL mode).
- **Frontend:** React 18, TypeScript, Vite, TailwindCSS, Recharts.
- **Networking:** Linux `iproute2` (routing tables, policy rules), `ping`, `dig`, `curl`.
- **Security:** JWT (PyJWT), bcrypt, API tokens, per-interface socket binding (`SO_BINDTODEVICE`).

## Core Architecture

### 1. Configuration (`wancontrol/config.py`)
- **AppConfig**: Central dataclass capturing all settings (probes, scoring, retention, etc.).
- **Hot-Reload**: Supports `SIGHUP` and API-triggered reloads without process restart.
- **Validation**: Strict validation of network parameters and security keys.

### 2. Data Layer (`wancontrol/database.py`)
- **SQLite**: Optimized with Write-Ahead Logging (WAL) and exclusive locking for IPC safety.
- **Schema**: Versioned migrations (currently v1). Stores metrics, switch events, logs, alerts, and user/token data.
- **Retention**: Automated pruning of old metrics and events.

### 3. Probe Engine (`wancontrol/monitor.py`)
- **Parallelism**: Uses `ThreadPoolExecutor` to probe all interfaces and targets (ICMP, DNS, HTTP) concurrently.
- **Scoring**: Computes a 0–100 health score based on latency, jitter, and packet loss.
- **Hard Fail**: Interfaces dropping below a configurable threshold are marked as hard-fail.

### 4. Controller & Watchdog (`wancontrol/controller.py`, `wancontrol/watchdog.py`)
- **Lifecycle**: `Controller` manages startup (routing table setup, route snapshot) and shutdown (route restoration, cleanup).
- **Integrity**: `Watchdog` (daemon thread) maintains a heartbeat and periodically verifies that the kernel routing table matches the controller's intended state.
- **State Machine**: (In development/Integration) Supports `STABLE`, `DEGRADED`, `FAILED`, and `SWITCHING` states for each WAN interface.

### 5. Network Utilities (`wancontrol/network.py`)
- **Policy Routing**: Manages per-interface routing tables (IDs 100+) and `ip rule` priority-based routing.
- **Port Discovery**: Dynamically finds available ports for the web server.
- **Dry Run**: Supports `WANCONTROL_DRY_RUN=1` for safe testing on non-gateway machines.

### 6. REST API & Real-time Stream (`wancontrol/app.py`)
- **API**: Comprehensive endpoints for status, config management, metrics history, and user administration.
- **SSE**: Server-Sent Events (`/api/stream`) pushes live status, metrics, and alerts to the frontend every 5 seconds.
- **Auth**: Flexible JWT-based sessions or persistent API tokens with role-based access control (Admin, Operator, Viewer).

## Frontend Design (`frontend/`, `DESIGN.md`)
- **Aesthetic**: "Industrial Precision" — a Slate-based dark mode optimized for technical density.
- **Pages**: Dashboard (live status), Metrics (charts), Events, Alerts, Users, and Config.
- **SSE Integration**: `sse.ts` manages resilient EventSource connections with exponential backoff.

## Deployment (`install.sh`, `deploy/`)
- **System Integration**: Deploys as a `systemd` service under a dedicated `wancontrol` system user.
- **Security**: Includes `sudoers` fragment for `iproute2` operations and `logrotate` for log management.

## Development & Testing
- **Unit Tests**: Located in `tests/unit/`, covering all core backend logic.
- **Integration Tests**: `tests/integration/` verifies the interaction between API, database, and controller stub.
- **Verification Fix**: `test_network.py` recently updated to use `s.listen(1)` for reliable port collision testing.

## Current Maintenance Notes
- **Controller Alignment**: A known discrepancy exists between the `Controller` implementation (lifecycle-focused) and `test_controller.py` (state-machine-focused). This indicates an ongoing transition towards the full Phase 5/6 master loop implementation.
- **Attribute Fixes**: Recent critical fixes resolved `AttributeError` in the shutdown path and removed shadowed `main()` functions in `__main__.py`.
