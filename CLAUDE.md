# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Python)

```bash
# Run in development mode — skips all network/routing subprocess calls, no root needed
WANCONTROL_DRY_RUN=1 python -m wancontrol

# Run all tests
pytest tests/

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# Run a single test file
pytest tests/unit/test_config.py

# Run with coverage
pytest --cov=wancontrol tests/
```

### Frontend (React/TypeScript)

```bash
cd frontend

# Install dependencies
npm install

# Start dev server (proxies /api to localhost:5000)
npm run dev

# Build production bundle → frontend/dist_app/  (served by Flask)
npm run build

# Run frontend tests (vitest)
npm test
```

### Install / Deploy

```bash
# Idempotent install — does NOT overwrite /etc/wancontrol/config.yaml if it exists
sudo ./install.sh

# Reload config without restart
sudo systemctl kill -s SIGHUP wancontrol
# or: POST /api/config/reload
```

### User / password management (terminal)

```bash
# Operates directly on the SQLite DB — no running server needed. Prompts for passwords.
python -m wancontrol.cli user add <name> --role admin|operator|viewer
python -m wancontrol.cli user passwd <name>      # reset password
python -m wancontrol.cli user role <name> <role>
python -m wancontrol.cli user deactivate <name>
python -m wancontrol.cli user list

# First-boot admin bootstrap (run by install.sh as the wancontrol user):
python init_admin.py   # creates a one-time admin password if no users exist
```

`auth.create_user` enforces a minimum password length, so the CLI rejects short passwords.

## Architecture

WANControl is a single-process Python daemon that bundles an SD-WAN routing controller with a Flask REST API and serves a compiled React SPA. The controller, watchdog, probe pool, and SSE all live in one process and share in-memory state, so the HTTP layer is **waitress** (`create_server` in `__main__.py`) — a multi-worker WSGI server like gunicorn would fork the controller and break that shared state. Do not swap it for a pre-fork server.

### Startup sequence (`wancontrol/__main__.py`)

1. Load `.env`, apply env overrides
2. Parse and validate `config.yaml` → `AppConfig` (immutable frozen dataclass)
3. Initialize SQLite database (`database.py`)
4. Check system prerequisites (`ip`, `ping`, `dig`, `curl`)
5. Instantiate `Controller` and `Watchdog`
6. Register SIGTERM/SIGINT (shutdown) and SIGHUP (config reload) handlers
7. Start Watchdog thread, optionally auto-start Controller
8. Create Flask app and serve it via `waitress.create_server`; SIGTERM calls `server.close()` so `server.run()` returns (waitress does not self-terminate on SIGTERM)

`python -m wancontrol --wait-for-network` is a separate, short-lived subcommand (used as the systemd `ExecStartPre`): it blocks until a configured gateway answers ping or `WANCONTROL_WAIT_FOR_NETWORK_TIMEOUT_SEC` elapses, then exits. This is an active boot-readiness gate, not a passive sleep, and is why the unit sets `TimeoutStartSec=180`.

### Core modules

| Module | Role |
|---|---|
| `wancontrol/config.py` | YAML → frozen `AppConfig` dataclass tree; thread-safe hot-reload via `Config.reload()` |
| `wancontrol/database.py` | SQLite WAL-mode data layer; versioned migrations (`CURRENT_SCHEMA_VERSION = 2`); all writes parameterized |
| `wancontrol/controller.py` | SD-WAN lifecycle (`ControllerMode`: STOPPED/STARTING/RUNNING/PAUSED/KILLED); owns the probe loop thread. `stop()`→STOPPED, `kill()`→KILLED (terminal). Per-interface `WanState` is STABLE/DEGRADED/FAILED (no SWITCHING). Two locks: `_lifecycle_lock` then `_route_lock` (always acquire in that order — never the reverse — to avoid the ABBA deadlock with the watchdog) |
| `wancontrol/monitor.py` | Parallel probe engine called synchronously from the controller loop; uses `ThreadPoolExecutor` internally |
| `wancontrol/network.py` | Wrappers around `ip route` / `ip rule` subprocesses. Snapshots pre-start v4+v6 default routes to the DB and restores them on stop (idempotent; `network.py --restore-routes` is the systemd `ExecStop`/`ExecStopPost`). Two dry-run layers: `WANCONTROL_DRY_RUN=1` skips all subprocess calls; `WANCONTROL_SHADOW=1` (Layer 1) records the intended command via `set_shadow_recorder()` and mutates nothing. Reads the iproute2 JSON `protocol` key (not `proto`) and handles multipath `nexthops`. `RULE_PRIORITY_BASE=10000` |
| `wancontrol/auth.py` | bcrypt passwords, PyJWT access tokens, SHA-256 hashed API tokens; no Flask dependency |
| `wancontrol/app.py` | Flask blueprint (`/api`); `create_app()` factory wires `AppConfig`, `Database`, `Controller`, `Auth` into `app.config`; serves `frontend/dist_app/` as SPA catchall |
| `wancontrol/watchdog.py` | Separate thread that monitors heartbeat file and restarts controller if stale |

### Flask app context

`app.config` keys: `CFG` (AppConfig), `CFG_LOADER` (Config), `DB` (Database), `CONTROLLER` (Controller), `AUTH` (Auth). Endpoints read these directly — no Flask globals or g-object patterns.

### Authentication

Two header mechanisms, checked in order: `X-API-Token` header → `Authorization: Bearer` JWT. The `?token=` query param was **removed** (item 31) so long-lived credentials never land in URLs or logs. Role hierarchy: `viewer < operator < admin`. `ROLE_REQUIREMENTS` dict in `app.py` maps `(METHOD, path)` → minimum role; `before_request` enforces it. JWTs carry an `rpc` claim (requires-password-change) that forces a password rotation before normal use.

**SSE auth exception:** a browser `EventSource` cannot send auth headers, so `GET /api/stream` accepts a short-lived (`TTL_SEC=30`), single-use `?ticket=` minted by `POST /api/stream/ticket` (normal header auth). Tickets live in `app.config["STREAM_TICKETS"]` (`_StreamTicketStore`, thread-safe) and are consumed on first use. Header auth still works on `/api/stream` for non-browser clients.

### Scoring algorithm

```
score = 100
      - (latency_ms × latency_penalty_per_ms)
      - (loss_pct   × loss_penalty_per_percent)
      - (dns_fail   ? dns_fail_penalty  : 0)
      - (http_fail  ? http_fail_penalty : 0)
```

An interface is marked failed when `score < hard_fail_threshold`. In `failover` mode, hysteresis thresholds (`hysteresis_switch_to_backup`, `hysteresis_return_to_primary`) prevent flapping. In `load_balance` mode, `recovery_margin` controls re-entry into the nexthop pool.

**Anti-flap (debounce) layer** on top of scoring, in `ScoringConfig`: a link must score bad for `fail_confirmations` (default 3) consecutive cycles before it is failed out, and good for `recover_confirmations` (default 5) before it returns; `min_switch_interval_sec` (60) rate-limits route changes and `return_stability_sec` (30) holds a recovered link before trusting it. When **all** links fail, the controller holds the least-bad link rather than blackholing. A single bad probe never moves a route.

### Frontend

- React 18 + TypeScript + Vite + Tailwind CSS + Recharts
- Path alias: `@/` → `frontend/src/`
- Dev proxy: Vite forwards `/api/*` to `http://localhost:5000`
- Production build goes to `frontend/dist_app/` — Flask serves this directory
- SSE stream (`/api/stream`) pushes `status`, `metric`, and `alert` events every 5 seconds. `frontend/src/api/sse.ts` first POSTs `/api/stream/ticket` (authenticated) then opens `EventSource("/api/stream?ticket=…")`, re-minting a fresh ticket on every reconnect
- Auth wiring: `main.tsx` wraps `<App>` in `<AuthProvider>`; `App.tsx` gates routes (loading → `/login` public → `ProtectedRoute` → `AppShell`) only when `/api/auth/config` reports `auth_enabled: true`, otherwise the SPA is reachable directly (backend network allow-list is the gate). `api/client.ts` holds the bearer token in a module variable (seeded from `localStorage`, kept in sync via `setAuthToken`) and attaches it to every `apiFetch`; a 401 on a non-`/api/auth/` call fires the registered logout. Auth state: `frontend/src/auth/AuthContext.tsx`; timezone: `frontend/src/context/TimezoneContext.tsx`

### Configuration hot-reload

`Config.reload()` re-parses `config.yaml`. On failure it keeps the existing config unchanged. `_sync_reloaded_config()` in `app.py` propagates the new `AppConfig` to Flask's `app.config`, `Auth`, and `Controller.update_config()`.

## Testing

All tests set `WANCONTROL_DRY_RUN=1` (via `conftest.py`). Unit tests use an in-memory SQLite database (`:memory:`). Integration tests spin up a full Flask test client with a `ControllerStub`. bcrypt rounds are patched to 4 in all tests for speed.

Key fixtures in `tests/conftest.py`:
- `mem_db` — initialized in-memory `Database`
- `app_cfg` — parsed `AppConfig` from a temp YAML file
- `flask_app` — Flask app with `ControllerStub`
- `seeded_client` — test client with admin/operator/viewer pre-created

## Environment variables

| Variable | Effect |
|---|---|
| `WANCONTROL_DRY_RUN=1` | Skip all network subprocess calls entirely (essential for dev/test) |
| `WANCONTROL_SHADOW=1` | Layer-1 dry-run: record intended `ip` commands via the shadow recorder, mutate nothing (use to preview route changes against real links without touching them) |
| `WANCONTROL_CONFIG` | Override config file path (default: `/etc/wancontrol/config.yaml`) |
| `WANCONTROL_SECRET_KEY` | Override `server.secret_key` from config |
| `WANCONTROL_DB_PATH` | Override SQLite database path |
| `WANCONTROL_PORT` | Override listen port |
| `WANCONTROL_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, etc. |
| `WANCONTROL_JSON_LOGS` | Emit JSON-structured log lines |

## Production paths

| Asset | Path |
|---|---|
| Config | `/etc/wancontrol/config.yaml` |
| Database | `/var/lib/wancontrol/wan.db` |
| App install | `/opt/wancontrol/` |
| Logs | `/var/lib/wancontrol/logs/wancontrol.log` |
| Systemd unit | `/etc/systemd/system/wancontrol.service` |

The service no longer uses a sudoers fragment. Route mutation is granted via systemd `AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW` (with `CapabilityBoundingSet` matching and `ProtectSystem=strict`); the old `deploy/wancontrol.sudoers` was deleted. Don't reintroduce a sudoers grant.

## Code guidelines

- Touch only what the task requires — don't refactor adjacent code or reformat unrelated lines.
- Match existing style: type hints throughout, `logger` with `extra={"component": "..."}`, specific exceptions (`ConfigError`, `AuthError`) rather than bare `Exception`.
- Every changed line should trace directly to the user's request. If you notice unrelated dead code, mention it rather than deleting it.
- When editing `network.py`, always verify the change works under `WANCONTROL_DRY_RUN=1` first.
- Config validation lives in `config.py` `_parse_*` functions — add new fields there, not inline in endpoints.
