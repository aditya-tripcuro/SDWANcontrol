# WANControl v2 — Phase 0 Implementation Prompt

## Your Task

You are implementing **Phase 0** of WANControl v2: a production-grade SD-WAN
load-balancing controller for Linux dual-WAN systems. Phase 0 covers the
foundation that every other module depends on:

1. `config.yaml` — example configuration file
2. `wancontrol/config.py` — config loader, validator, hot-reload
3. `wancontrol/database.py` — SQLite data layer
4. `tests/unit/test_config.py` — config tests
5. `tests/unit/test_database.py` — database tests
6. `requirements.txt` — pinned dependencies
7. `wancontrol/__init__.py` — version constant only

**Do not implement any other modules.** Later phases will build on these.

---

## Project Context

WANControl manages two or more WAN interfaces on a Linux box (Debian/Ubuntu).
It supports two modes:

- **failover**: one active WAN at a time, switches on failure
- **load_balance**: all healthy WANs active simultaneously, weighted by
  `expected_speed_mbps`. When one fails its score drops below
  `hard_fail_threshold` and it is removed from the nexthop pool. Bandwidth
  degrades gracefully instead of going to zero.

Phase 0 has no networking, no Flask, no threads — pure config + data layer.

---

## Constraints (non-negotiable)

- Python 3.10+ only. Use `match` statements where they improve clarity.
- Allowed packages: `pyyaml`, `pytest`, `pytest-cov`. No others for Phase 0.
- No ORM. Raw `sqlite3` only.
- No async. Threading model only (later phases).
- Type hints on **every** function signature.
- Docstrings on every public class and method.
- No bare `except:`. Always catch specific exception types.
- Logging via stdlib `logging`. All log calls include
  `extra={"component": "config"}` or `extra={"component": "database"}`.
- All magic numbers come from config. No module-level numeric constants
  except schema version.
- All DB writes use parameterized queries — never string formatting.

---

## File 1: `config.yaml`

This is the example/default config. Every value in it must be referenced
somewhere in `config.py` validation. Include inline comments explaining
each section.

Required top-level keys:

```yaml
interfaces:          # list, minimum 2 entries
wan_mode:            # "failover" | "load_balance"
probes:              # probe timing and targets
scoring:             # penalty weights and thresholds
controller:          # loop timing, heartbeat
retention:           # data pruning windows
alerting:            # webhook notifications
server:              # Flask/gunicorn settings
lock_file:           # path string
heartbeat_file:      # path string
db_path:             # path string
log_dir:             # path string
```

Each interface entry must have:
```yaml
- name: "wan0"
  label: "Fiber Primary"
  expected_speed_mbps: 100
  gateway: "192.168.1.1"
  routing_table_id: 100   # must be unique, 1–252
```

`scoring` must include both failover hysteresis keys AND `recovery_margin`
(used by load_balance mode to re-add an interface after it recovers):
```yaml
scoring:
  latency_penalty_per_ms: 0.3
  loss_penalty_per_percent: 2.0
  dns_fail_penalty: 15
  http_fail_penalty: 20
  hard_fail_threshold: 20
  hysteresis_switch_to_backup: 25
  hysteresis_return_to_primary: 10
  recovery_margin: 10
```

`server.secret_key` must NOT be a placeholder — the validator rejects
placeholder strings. In the example config, use a comment telling the
user to generate one:
```yaml
server:
  secret_key: "REPLACE_ME_run_python_secrets_token_hex_32"
```
The validator must reject this exact string and any string shorter than 32
characters, with an actionable error message.

Valid `alerting.on_events` values:
```
link_down, link_up, gateway_switch,
interface_added_to_pool, interface_removed_from_pool, controller_error
```

---

## File 2: `wancontrol/config.py`

### Data classes (all `frozen=True` dataclasses)

```python
InterfaceConfig(name, label, expected_speed_mbps, gateway, routing_table_id)
ProbeConfig(interval_sec, dns_targets, icmp_targets, http_targets,
            icmp_count, icmp_timeout_sec, dns_timeout_sec, http_timeout_sec)
ScoringConfig(latency_penalty_per_ms, loss_penalty_per_percent,
              dns_fail_penalty, http_fail_penalty, hard_fail_threshold,
              hysteresis_switch_to_backup, hysteresis_return_to_primary,
              recovery_margin)
ControllerConfig(loop_interval_sec, benchmark_interval_sec,
                 metric_collection_timeout_sec, heartbeat_interval_sec,
                 heartbeat_stale_sec)
RetentionConfig(metrics_hours, events_days, prune_interval_min)
WebhookConfig(url, method, headers, on_events)
AlertingConfig(enabled, webhooks)
ServerConfig(host, port, secret_key, jwt_expiry_hours, session_timeout_minutes)

AppConfig(interfaces, wan_mode, probes, scoring, controller, retention,
          alerting, server, lock_file, heartbeat_file, db_path, log_dir)
```

`AppConfig` must have these helper properties/methods:
```python
@property
def interface_names(self) -> list[str]: ...

def get_interface(self, name: str) -> InterfaceConfig | None: ...
```

### Exception

```python
class ConfigError(Exception):
    """Raised when config.yaml is missing required keys or has invalid values."""
```

### Validation rules

- `interfaces`: list, minimum 2 entries, no duplicate `name`, no duplicate
  `routing_table_id`, each `routing_table_id` must be int 1–252.
- `wan_mode`: must be `"failover"` or `"load_balance"`.
- All `*_sec`, `*_hours`, `*_days`, `*_min`, `*_count`, `*_mbps` fields:
  must be positive integers (cast from float if needed).
- All penalty/threshold floats: must be >= 0.
- `hard_fail_threshold` can be any number (could theoretically be negative
  for "never hard fail" use cases — just validate it's a number).
- `server.secret_key`: reject placeholder strings and any string < 32 chars.
  Error message must include the `python -c "import secrets; ..."` command.
- `alerting.webhooks[n].method`: must be `GET`, `POST`, or `PUT`.
- `alerting.webhooks[n].on_events`: each value must be in `VALID_EVENTS` set.
- On any validation failure: raise `ConfigError` with a precise message
  including the key path (e.g. `"[interfaces[1]].routing_table_id"`).

### `Config` class (thread-safe)

```python
class Config:
    def __init__(self, path: str | Path) -> None: ...
    def load(self) -> AppConfig: ...          # initial load, raises on failure
    def reload(self) -> AppConfig: ...        # hot-reload: keeps old config on failure
    def register_sighup(self) -> None: ...   # SIGHUP → reload()
    def on_reload(self, callback: Callable[[AppConfig], None]) -> None: ...
    @property
    def current(self) -> AppConfig: ...      # raises RuntimeError if load() not called
```

`reload()` behaviour:
- On parse/validation failure: log ERROR, return existing config unchanged.
- On success: replace `_current`, call all registered callbacks, return new config.
- Thread-safe: use `threading.RLock` around `_current` reads/writes.

---

## File 3: `wancontrol/database.py`

### SQLite setup

- WAL journal mode (`PRAGMA journal_mode=WAL`)
- `PRAGMA foreign_keys=ON`
- `PRAGMA synchronous=NORMAL`
- Per-thread connection via `threading.local` (connections are not
  shared across threads but are reused within a thread)
- `isolation_level=None` (manual transaction management)

### Schema — version 1 migration

All schema created via the migration system. Never drop-and-recreate tables.

```sql
schema_version(version INTEGER PRIMARY KEY, applied_at REAL)

metrics(id, interface TEXT, timestamp REAL, latency_ms REAL,
        jitter_ms REAL, loss_pct REAL, dns_ok INTEGER,
        http_ok INTEGER, score REAL)
CREATE INDEX idx_metrics_iface_ts ON metrics(interface, timestamp DESC)

switch_events(id, timestamp REAL, from_interface TEXT, to_interface TEXT,
              reason TEXT, triggered_by TEXT DEFAULT 'controller',
              score_before REAL, score_after REAL)
CREATE INDEX idx_switch_events_ts ON switch_events(timestamp DESC)

controller_events(id, timestamp REAL, level TEXT, component TEXT,
                  message TEXT, user_id INTEGER REFERENCES users(id))
CREATE INDEX idx_ctrl_events_ts ON controller_events(timestamp DESC)

state(key TEXT PRIMARY KEY, value TEXT, updated_at REAL)

users(id, username TEXT UNIQUE, password_hash TEXT,
      role TEXT DEFAULT 'viewer', created_at REAL,
      last_login REAL, is_active INTEGER DEFAULT 1)

api_tokens(id, user_id INTEGER REFERENCES users(id),
           token_hash TEXT UNIQUE, label TEXT, created_at REAL,
           last_used REAL, expires_at REAL, is_revoked INTEGER DEFAULT 0)
CREATE INDEX idx_api_tokens_hash ON api_tokens(token_hash)

alerts(id, timestamp REAL, level TEXT, title TEXT, body TEXT,
       resolved_at REAL, notified INTEGER DEFAULT 0)
CREATE INDEX idx_alerts_ts ON alerts(timestamp DESC)
```

### Row dataclasses

```python
@dataclass
class MetricRow: id, interface, timestamp, latency_ms, jitter_ms, loss_pct, dns_ok, http_ok, score
class SwitchEventRow: id, timestamp, from_interface, to_interface, reason, triggered_by, score_before, score_after
class ControllerEventRow: id, timestamp, level, component, message, user_id
class UserRow: id, username, password_hash, role, created_at, last_login, is_active
class ApiTokenRow: id, user_id, token_hash, label, created_at, last_used, expires_at, is_revoked
class AlertRow: id, timestamp, level, title, body, resolved_at, notified

@dataclass
class DbStats:
    file_size_bytes: int
    metrics_count: int
    switch_events_count: int
    controller_events_count: int
    alerts_count: int
    users_count: int
    schema_version: int
```

### `Database` class — required public methods

```python
class Database:
    def __init__(self, db_path: str | Path) -> None: ...
    def initialize(self) -> None: ...  # WAL + migrations, call once at startup

    # Metrics
    def insert_metric(self, interface, latency_ms, jitter_ms, loss_pct,
                      dns_ok, http_ok, score, timestamp=None) -> None: ...
    def get_metrics(self, interface=None, limit=200, since=None) -> list[MetricRow]: ...
    def get_latest_metric(self, interface: str) -> MetricRow | None: ...

    # Switch events
    def insert_switch_event(self, from_interface, to_interface, reason,
                            score_before, score_after,
                            triggered_by="controller", timestamp=None) -> None: ...
    def get_switch_events(self, limit=50) -> list[SwitchEventRow]: ...

    # Controller events
    def log_event(self, level, component, message,
                  user_id=None, timestamp=None) -> None: ...
    def get_events(self, limit=100, level=None) -> list[ControllerEventRow]: ...

    # State — MUST use BEGIN EXCLUSIVE for IPC safety
    def set_state(self, key: str, value: str) -> None: ...
    def get_state(self, key: str, default=None) -> str | None: ...
    def get_all_state(self) -> dict[str, str]: ...

    # Users
    def create_user(self, username, password_hash, role) -> int: ...
    def get_user_by_username(self, username: str) -> UserRow | None: ...
    def get_user_by_id(self, user_id: int) -> UserRow | None: ...
    def list_users(self) -> list[UserRow]: ...
    def update_user_password(self, user_id: int, password_hash: str) -> None: ...
    def update_user_last_login(self, user_id: int) -> None: ...
    def update_user_role(self, user_id: int, role: str) -> None: ...
    def deactivate_user(self, user_id: int) -> None: ...
    def count_users(self) -> int: ...

    # API tokens
    def create_api_token(self, user_id, token_hash, label, expires_at) -> int: ...
    def get_api_token_by_hash(self, token_hash: str) -> ApiTokenRow | None: ...
    def touch_api_token(self, token_id: int) -> None: ...
    def revoke_api_token(self, token_id: int) -> None: ...
    def list_api_tokens(self, user_id=None) -> list[ApiTokenRow]: ...

    # Alerts
    def insert_alert(self, level, title, body, timestamp=None) -> int: ...
    def mark_alert_notified(self, alert_id: int) -> None: ...
    def resolve_alert(self, alert_id: int) -> None: ...
    def get_unnotified_alerts(self) -> list[AlertRow]: ...
    def get_recent_alerts(self, limit=20) -> list[AlertRow]: ...

    # Retention
    def prune_old_data(self, metrics_hours: int, events_days: int) -> dict[str, int]: ...
    def flush_all_data(self) -> None: ...  # preserves users, state, schema

    # Stats
    def get_db_stats(self) -> DbStats: ...
```

### Transaction rules

- All writes: acquire `self._write_lock` (threading.Lock) first, then open
  connection context.
- `set_state` and `get_state`: use `BEGIN EXCLUSIVE` explicitly (IPC safety
  between Master and Standby processes that may share the same DB file).
- Multi-row inserts: wrap in a single transaction.
- On `sqlite3.OperationalError`: log error, re-raise.

### Migration runner

```python
MIGRATIONS: dict[int, str] = {1: "...sql..."}
```

- On `initialize()`: create `schema_version` table if not exists, check which
  versions are applied, run missing ones in order.
- Each migration runs as a single `executescript()` call.
- Record applied version in `schema_version` after success.
- Future migrations (v2, v3...) must be addable without touching existing SQL.

---

## File 4: `tests/unit/test_config.py`

Cover these cases with `pytest`:

```
VALID CONFIG
- loads successfully with minimal valid config
- loads successfully with full config.yaml example
- interface_names property returns correct list
- get_interface() returns correct InterfaceConfig
- get_interface() returns None for unknown name

VALIDATION ERRORS — each must raise ConfigError with message containing
the relevant key path:
- missing 'interfaces' key
- interfaces list has only 1 entry
- duplicate interface name
- duplicate routing_table_id
- routing_table_id out of range (0, 253)
- routing_table_id is a string not int
- missing 'gateway' on an interface
- wan_mode set to unsupported value
- interval_sec = 0 (not positive)
- interval_sec = -1
- secret_key is the placeholder string
- secret_key is shorter than 32 chars
- secret_key is missing
- alerting webhook method is "DELETE"
- alerting on_events contains unknown event name
- probes.dns_targets is empty list

SECRET KEY
- valid 32-char key passes
- valid 64-char key passes

HOT RELOAD
- reload() with valid new config updates .current
- reload() with invalid YAML keeps old config and returns old config
- reload() with missing file keeps old config
- on_reload callback is called after successful reload
- on_reload callback is NOT called after failed reload

SIGHUP
- register_sighup() installs signal handler (verify via signal.getsignal)

THREAD SAFETY
- .current raises RuntimeError before load() is called
- concurrent reads of .current from 10 threads all return same object
```

Use `tmp_path` fixture for all file I/O. Do not write to `/etc` or `/var`.

---

## File 5: `tests/unit/test_database.py`

Cover these cases:

```
SETUP
- initialize() creates DB file and all tables
- initialize() is idempotent (safe to call twice)
- schema_version table has version=1 after initialize()
- DB file uses WAL mode (PRAGMA journal_mode returns 'wal')

METRICS
- insert_metric() stores a row retrievable by get_latest_metric()
- get_metrics() with no filters returns rows newest-first
- get_metrics(interface="wan0") filters correctly
- get_metrics(since=<ts>) filters correctly
- get_latest_metric() returns None for unknown interface
- dns_ok and http_ok are stored and retrieved as booleans

SWITCH EVENTS
- insert_switch_event() stores and get_switch_events() retrieves
- default triggered_by is "controller"
- custom triggered_by ("api:admin") is preserved
- results ordered newest-first

CONTROLLER EVENTS
- log_event() with and without user_id
- get_events(level="ERROR") filters correctly
- level stored as uppercase regardless of input case

STATE
- set_state/get_state round-trip
- get_state returns default when key missing
- set_state overwrites existing key
- get_all_state returns all keys
- concurrent set_state from 5 threads — no corruption (each thread
  writes a unique key, verify all are present after)

USERS
- create_user returns integer id
- get_user_by_username returns UserRow
- get_user_by_username returns None for unknown
- get_user_by_id works
- list_users returns all users
- update_user_password changes hash
- update_user_last_login sets timestamp
- update_user_role changes role
- deactivate_user sets is_active=False
- count_users returns correct count
- duplicate username raises sqlite3.IntegrityError

API TOKENS
- create_api_token returns id
- get_api_token_by_hash finds by hash
- get_api_token_by_hash returns None for unknown hash
- touch_api_token updates last_used
- revoke_api_token sets is_revoked=True
- list_api_tokens(user_id=X) filters correctly
- list_api_tokens() with no filter returns all

ALERTS
- insert_alert returns id
- mark_alert_notified sets notified=True
- resolve_alert sets resolved_at
- get_unnotified_alerts returns only notified=False rows
- get_recent_alerts returns newest-first

RETENTION
- prune_old_data deletes metrics older than metrics_hours
- prune_old_data deletes events older than events_days
- prune_old_data does NOT delete recent data
- prune_old_data returns dict with correct row counts
- flush_all_data deletes metrics/events but preserves users and state

STATS
- get_db_stats returns DbStats with correct counts
- get_db_stats.schema_version == 1
- get_db_stats.file_size_bytes > 0

MIGRATIONS
- applying migration twice does not duplicate tables or raise errors
- schema_version has exactly one row per applied migration

THREAD SAFETY
- 20 threads each inserting 50 metrics concurrently — all rows present
  (verify total count = 1000)
- no deadlock after 3 seconds
```

All tests use `:memory:` DB or `tmp_path` fixture. No filesystem side effects.

---

## File 6: `requirements.txt`

Pin exact versions. Separate dev dependencies with a comment.

```
# Runtime
PyYAML==6.0.2

# Dev / test only
pytest==8.3.4
pytest-cov==5.0.0
```

Do not add any other packages. Phase 0 has zero runtime dependencies beyond
the Python stdlib and PyYAML.

---

## File 7: `wancontrol/__init__.py`

```python
"""WANControl v2 — SD-WAN load-balancing controller for Linux."""

__version__ = "2.0.0-dev"
```

Nothing else. No imports.

---

## Exit Criteria

The following must pass with zero failures and zero errors:

```bash
pip install pyyaml pytest pytest-cov
pytest tests/unit/test_config.py tests/unit/test_database.py \
  -v --tb=short --cov=wancontrol --cov-report=term-missing
```

Coverage target: **≥ 90%** for `config.py` and `database.py`.

The following must also work:

```bash
python -c "
from wancontrol.config import Config, ConfigError
from wancontrol.database import Database

# Config smoke test (will fail on placeholder secret — that's correct)
try:
    cfg = Config('config.yaml')
    cfg.load()
    print('Config loaded:', cfg.current.wan_mode, len(cfg.current.interfaces), 'interfaces')
except ConfigError as e:
    print('ConfigError (expected if secret_key is placeholder):', e)

# Database smoke test
db = Database(':memory:')
db.initialize()
db.insert_metric('wan0', 10.0, 1.0, 0.0, True, True, 95.0)
m = db.get_latest_metric('wan0')
assert m is not None and m.interface == 'wan0'
stats = db.get_db_stats()
assert stats.metrics_count == 1
print('Database OK. Stats:', stats)
"
```

---

## What NOT to implement

Do not touch any of these — they are later phases:

- `auth.py` (Phase 2)
- `network.py` (Phase 3)
- `monitor.py` (Phase 4)
- `controller.py` (Phase 5)
- `watchdog.py` (Phase 5)
- `app.py` (Phase 6)
- `templates/` or `static/` (Phase 7)
- `install.sh` or `wancontrol.service` (Phase 9)

If you find yourself importing Flask, bcrypt, jwt, or requests: stop.

---

## Coding Style Notes

- Use `# ── Section name ───` comment headers to delimit logical sections
  within each file (keeps long files navigable).
- Prefer explicit `if x is None` over `if not x` when distinguishing
  None from empty string/zero.
- `timestamp` parameters default to `None` and fall back to `time.time()`
  inside the function — this makes testing with fixed timestamps easy.
- All `bool` fields stored in SQLite as `INTEGER` (0/1). Cast on retrieval.