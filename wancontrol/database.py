"""
wancontrol/database.py
~~~~~~~~~~~~~~~~~~~~~~
SQLite data layer. WAL mode, versioned migrations, retention policies.

All writes use parameterized queries. Multi-row writes use transactions.
Inter-process state reads/writes use BEGIN EXCLUSIVE to prevent races
between Master and Standby processes.

Usage::

    db = Database("/var/lib/wancontrol/wan.db")
    db.initialize()   # runs migrations, sets WAL mode

    db.insert_metric("wan0", latency_ms=12.3, jitter_ms=1.1,
                     loss_pct=0.0, dns_ok=True, http_ok=True, score=95.0)

    db.set_state("active_interface", "wan0")
    iface = db.get_state("active_interface")
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)

# ── Schema version ────────────────────────────────────────────────────────────

CURRENT_SCHEMA_VERSION = 2

# ── Row dataclasses ───────────────────────────────────────────────────────────

@dataclass
class MetricRow:
    id: int
    interface: str
    timestamp: float
    latency_ms: float
    jitter_ms: float
    loss_pct: float
    dns_ok: bool
    http_ok: bool
    score: float


@dataclass
class SwitchEventRow:
    id: int
    timestamp: float
    from_interface: str
    to_interface: str
    reason: str
    triggered_by: str
    score_before: float
    score_after: float


@dataclass
class ControllerEventRow:
    id: int
    timestamp: float
    level: str
    component: str
    message: str
    user_id: int | None


@dataclass
class UserRow:
    id: int
    username: str
    password_hash: str
    role: str
    created_at: float
    last_login: float | None
    is_active: bool
    requires_password_change: bool


@dataclass
class ApiTokenRow:
    id: int
    user_id: int
    token_hash: str
    label: str
    created_at: float
    last_used: float | None
    expires_at: float | None
    is_revoked: bool


@dataclass
class AlertRow:
    id: int
    timestamp: float
    level: str
    title: str
    body: str
    resolved_at: float | None
    notified: bool


@dataclass
class IntendedRouteRow:
    id: int
    ts: float
    command: str


@dataclass
class DbStats:
    file_size_bytes: int
    metrics_count: int
    switch_events_count: int
    controller_events_count: int
    alerts_count: int
    users_count: int
    schema_version: int


# ── Row constructors (bool-safe) ──────────────────────────────────────────────
# SQLite stores booleans as INTEGER (0/1). Python's dataclasses don't coerce
# types, so we cast explicitly to preserve isinstance(x, bool) guarantees.

def _metric_from_row(r: sqlite3.Row) -> "MetricRow":
    return MetricRow(
        id=r[0], interface=r[1], timestamp=r[2],
        latency_ms=r[3], jitter_ms=r[4], loss_pct=r[5],
        dns_ok=bool(r[6]), http_ok=bool(r[7]), score=r[8],
    )


def _user_from_row(r: sqlite3.Row) -> "UserRow":
    return UserRow(
        id=r[0], username=r[1], password_hash=r[2], role=r[3],
        created_at=r[4], last_login=r[5], is_active=bool(r[6]),
        requires_password_change=bool(r[7]),
    )


def _token_from_row(r: sqlite3.Row) -> "ApiTokenRow":
    return ApiTokenRow(
        id=r[0], user_id=r[1], token_hash=r[2], label=r[3],
        created_at=r[4], last_used=r[5], expires_at=r[6], is_revoked=bool(r[7]),
    )


def _alert_from_row(r: sqlite3.Row) -> "AlertRow":
    return AlertRow(
        id=r[0], timestamp=r[1], level=r[2], title=r[3],
        body=r[4], resolved_at=r[5], notified=bool(r[6]),
    )


def _intended_route_from_row(r: sqlite3.Row) -> "IntendedRouteRow":
    return IntendedRouteRow(id=r[0], ts=r[1], command=r[2])


# ── Migrations ────────────────────────────────────────────────────────────────

MIGRATIONS: dict[int, str] = {
    1: """
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            applied_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS metrics (
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
        CREATE INDEX IF NOT EXISTS idx_metrics_iface_ts
            ON metrics(interface, timestamp DESC);

        CREATE TABLE IF NOT EXISTS switch_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       REAL    NOT NULL,
            from_interface  TEXT    NOT NULL,
            to_interface    TEXT    NOT NULL,
            reason          TEXT    NOT NULL,
            triggered_by    TEXT    NOT NULL DEFAULT 'controller',
            score_before    REAL    NOT NULL,
            score_after     REAL    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_switch_events_ts
            ON switch_events(timestamp DESC);

        CREATE TABLE IF NOT EXISTS controller_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   REAL    NOT NULL,
            level       TEXT    NOT NULL,
            component   TEXT    NOT NULL,
            message     TEXT    NOT NULL,
            user_id     INTEGER REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_ctrl_events_ts
            ON controller_events(timestamp DESC);

        CREATE TABLE IF NOT EXISTS state (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    NOT NULL UNIQUE,
            password_hash   TEXT    NOT NULL,
            role            TEXT    NOT NULL DEFAULT 'viewer',
            created_at      REAL    NOT NULL,
            last_login      REAL,
            is_active       INTEGER NOT NULL DEFAULT 1,
            requires_password_change INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS api_tokens (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            token_hash  TEXT    NOT NULL UNIQUE,
            label       TEXT    NOT NULL,
            created_at  REAL    NOT NULL,
            last_used   REAL,
            expires_at  REAL,
            is_revoked  INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_api_tokens_hash
            ON api_tokens(token_hash);

        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   REAL    NOT NULL,
            level       TEXT    NOT NULL,
            title       TEXT    NOT NULL,
            body        TEXT    NOT NULL,
            resolved_at REAL,
            notified    INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_ts
            ON alerts(timestamp DESC);
    """,
    # Migration 2 reconciles CURRENT_SCHEMA_VERSION (=2) with a real migration
    # (item 37 — previously the constant was 2 but only migration 1 existed) and
    # adds the shadow-mode intended-routes ledger. Shadow mode (dry-run Layer 1)
    # records every intended `ip` command instead of mutating the kernel.
    2: """
        CREATE TABLE IF NOT EXISTS intended_routes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL    NOT NULL,
            command     TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_intended_routes_ts
            ON intended_routes(ts DESC);
    """,
}


# ── Database class ────────────────────────────────────────────────────────────

class Database:
    """
    Thread-safe SQLite wrapper.

    A single Database instance may be shared across threads; each
    operation acquires a short-lived connection from the pool (one
    per thread via threading.local).
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._local = threading.local()
        self._write_lock = threading.Lock()  # serialise writes across threads
        # The in-memory connection is SHARED across threads, so the check-then-
        # BEGIN sequence in _conn() can race (two threads both see no open
        # transaction and both issue BEGIN -> "cannot start a transaction within
        # a transaction"). This re-entrant lock makes the begin/commit atomic for
        # the shared connection. File DBs use per-thread connections and do not
        # take this lock.
        self._mem_txn_lock = threading.RLock()
        # In-memory databases use a single persistent connection shared across
        # threads so that close() → reconnect does not destroy schema and data.
        # WAL mode is not supported for :memory:; foreign_keys and synchronous
        # are still applied.  Thread safety for concurrent access is provided
        # by _write_lock (writes) and SQLite's internal serialised locking.
        self._mem_conn: sqlite3.Connection | None = None
        if str(db_path) == ":memory:":
            self._mem_conn = sqlite3.connect(
                ":memory:", check_same_thread=False, isolation_level=None
            )
            self._mem_conn.execute("PRAGMA foreign_keys=ON")
            self._mem_conn.execute("PRAGMA synchronous=NORMAL")
            self._mem_conn.execute("PRAGMA busy_timeout=5000")
            self._mem_conn.row_factory = sqlite3.Row

    # ── Setup ──────────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Create DB file, enable WAL, run pending migrations. Call once at startup."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # PRAGMAs are set by _conn() on first connection creation (outside any
        # transaction); calling them again inside a BEGIN would raise OperationalError.
        self._run_migrations()
        # The DB (and its WAL/SHM sidecars) may contain credential hashes and
        # API token hashes; default umask can leave them world-readable. Tighten
        # to owner rw / group r (item 35).
        self._restrict_file_permissions()
        logger.info(
            "Database initialized",
            extra={"component": "database", "path": str(self._path)},
        )

    def _restrict_file_permissions(self) -> None:
        """``chmod 0640`` the database file and any WAL/SHM sidecars (item 35).

        No-op for in-memory databases. Best-effort: a chmod failure (e.g. the
        file is owned by another user) is logged, not raised, so startup is not
        blocked by a permissions hiccup.
        """
        if self._mem_conn is not None:
            return
        for suffix in ("", "-wal", "-shm"):
            target = Path(str(self._path) + suffix)
            if not target.exists():
                continue
            try:
                os.chmod(target, 0o640)
            except OSError as exc:
                logger.warning(
                    "Could not chmod 0640 %s: %s",
                    target, exc,
                    extra={"component": "database"},
                )

    # ── Metrics ────────────────────────────────────────────────────────────

    def insert_metric(
        self,
        interface: str,
        latency_ms: float,
        jitter_ms: float,
        loss_pct: float,
        dns_ok: bool,
        http_ok: bool,
        score: float,
        timestamp: float | None = None,
    ) -> None:
        """Insert a single metric row."""
        ts = timestamp or time.time()
        with self._write_lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO metrics
                    (interface, timestamp, latency_ms, jitter_ms, loss_pct,
                     dns_ok, http_ok, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (interface, ts, latency_ms, jitter_ms, loss_pct,
                 int(dns_ok), int(http_ok), score),
            )

    def get_metrics(
        self,
        interface: str | None = None,
        limit: int = 200,
        since: float | None = None,
    ) -> list[MetricRow]:
        """Fetch recent metrics, optionally filtered by interface and time window."""
        clauses: list[str] = []
        params: list[Any] = []
        if interface:
            clauses.append("interface = ?")
            params.append(interface)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT id, interface, timestamp, latency_ms, jitter_ms, "
                f"loss_pct, dns_ok, http_ok, score "
                f"FROM metrics {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [_metric_from_row(r) for r in rows]

    def get_latest_metric(self, interface: str) -> MetricRow | None:
        """Return the most recent metric for one interface."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, interface, timestamp, latency_ms, jitter_ms, "
                "loss_pct, dns_ok, http_ok, score "
                "FROM metrics WHERE interface = ? ORDER BY timestamp DESC LIMIT 1",
                (interface,),
            ).fetchone()
        return _metric_from_row(row) if row else None

    # ── Switch events ──────────────────────────────────────────────────────

    def insert_switch_event(
        self,
        from_interface: str,
        to_interface: str,
        reason: str,
        score_before: float,
        score_after: float,
        triggered_by: str = "controller",
        timestamp: float | None = None,
    ) -> None:
        ts = timestamp or time.time()
        with self._write_lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO switch_events
                    (timestamp, from_interface, to_interface, reason,
                     triggered_by, score_before, score_after)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, from_interface, to_interface, reason,
                 triggered_by, score_before, score_after),
            )
        logger.info(
            "Switch event recorded: %s → %s (%s)",
            from_interface, to_interface, reason,
            extra={"component": "database"},
        )

    def get_switch_events(self, limit: int = 50) -> list[SwitchEventRow]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, from_interface, to_interface, reason, "
                "triggered_by, score_before, score_after "
                "FROM switch_events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [SwitchEventRow(*r) for r in rows]

    # ── Controller events ──────────────────────────────────────────────────

    def log_event(
        self,
        level: str,
        component: str,
        message: str,
        user_id: int | None = None,
        timestamp: float | None = None,
    ) -> None:
        """Append a controller event. level: DEBUG | INFO | WARNING | ERROR | CRITICAL"""
        ts = timestamp or time.time()
        with self._write_lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO controller_events
                    (timestamp, level, component, message, user_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ts, level.upper(), component, message, user_id),
            )

    def get_events(
        self,
        limit: int = 100,
        level: str | None = None,
    ) -> list[ControllerEventRow]:
        params: list[Any] = []
        where = ""
        if level:
            where = "WHERE level = ?"
            params.append(level.upper())
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT id, timestamp, level, component, message, user_id "
                f"FROM controller_events {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [ControllerEventRow(*r) for r in rows]

    # ── State (key-value, exclusive for IPC) ──────────────────────────────

    def set_state(self, key: str, value: str) -> None:
        """Write a state value. Uses BEGIN EXCLUSIVE to prevent IPC races."""
        with self._write_lock, self._conn(exclusive=True) as conn:
            conn.execute(
                "INSERT INTO state(key, value, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (key, value, time.time()),
            )

    def get_state(self, key: str, default: str | None = None) -> str | None:
        """Read a state value.

        Uses a non-exclusive (deferred) read transaction: in WAL mode a reader
        sees the last committed value without acquiring the write lock, so the
        high-frequency status/SSE reads don't contend with the metric writer
        (item 13). set_state() remains BEGIN EXCLUSIVE + _write_lock for writes.
        """
        with self._conn(exclusive=False) as conn:
            row = conn.execute(
                "SELECT value FROM state WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else default

    def get_all_state(self) -> dict[str, str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM state").fetchall()
        return dict(rows)

    # ── Users ──────────────────────────────────────────────────────────────

    def create_user(
        self,
        username: str,
        password_hash: str,
        role: str,
        requires_password_change: bool = False,
    ) -> int:
        with self._write_lock, self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO users(username, password_hash, role, created_at, requires_password_change) "
                "VALUES(?, ?, ?, ?, ?)",
                (username, password_hash, role, time.time(), int(requires_password_change)),
            )
        return cur.lastrowid  # type: ignore[return-value]

    def get_user_by_username(self, username: str) -> UserRow | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, role, created_at, "
                "last_login, is_active, requires_password_change FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return _user_from_row(row) if row else None

    def get_user_by_id(self, user_id: int) -> UserRow | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, role, created_at, "
                "last_login, is_active, requires_password_change FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return _user_from_row(row) if row else None

    def list_users(self) -> list[UserRow]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, username, password_hash, role, created_at, "
                "last_login, is_active, requires_password_change FROM users ORDER BY created_at"
            ).fetchall()
        return [_user_from_row(r) for r in rows]

    def update_user_password(self, user_id: int, password_hash: str) -> None:
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, user_id),
            )

    def update_user_last_login(self, user_id: int) -> None:
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (time.time(), user_id),
            )

    def update_user_role(self, user_id: int, role: str) -> None:
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "UPDATE users SET role = ? WHERE id = ?",
                (role, user_id),
            )

    def set_requires_password_change(self, user_id: int, value: bool) -> None:
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "UPDATE users SET requires_password_change = ? WHERE id = ?",
                (1 if value else 0, user_id),
            )

    def deactivate_user(self, user_id: int) -> None:
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "UPDATE users SET is_active = 0 WHERE id = ?",
                (user_id,),
            )

    def count_users(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # ── API Tokens ─────────────────────────────────────────────────────────

    def create_api_token(
        self,
        user_id: int,
        token_hash: str,
        label: str,
        expires_at: float | None,
    ) -> int:
        with self._write_lock, self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO api_tokens(user_id, token_hash, label, created_at, expires_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (user_id, token_hash, label, time.time(), expires_at),
            )
        return cur.lastrowid  # type: ignore[return-value]

    def get_api_token_by_hash(self, token_hash: str) -> ApiTokenRow | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, user_id, token_hash, label, created_at, "
                "last_used, expires_at, is_revoked "
                "FROM api_tokens WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        return _token_from_row(row) if row else None

    def touch_api_token(self, token_id: int) -> None:
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "UPDATE api_tokens SET last_used = ? WHERE id = ?",
                (time.time(), token_id),
            )

    def revoke_api_token(self, token_id: int) -> None:
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "UPDATE api_tokens SET is_revoked = 1 WHERE id = ?",
                (token_id,),
            )

    def list_api_tokens(self, user_id: int | None = None) -> list[ApiTokenRow]:
        params: list[Any] = []
        where = ""
        if user_id is not None:
            where = "WHERE user_id = ?"
            params.append(user_id)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT id, user_id, token_hash, label, created_at, "
                f"last_used, expires_at, is_revoked "
                f"FROM api_tokens {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [_token_from_row(r) for r in rows]

    # ── Alerts ─────────────────────────────────────────────────────────────

    def insert_alert(
        self,
        level: str,
        title: str,
        body: str,
        timestamp: float | None = None,
    ) -> int:
        ts = timestamp or time.time()
        with self._write_lock, self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO alerts(timestamp, level, title, body) VALUES(?, ?, ?, ?)",
                (ts, level, title, body),
            )
        return cur.lastrowid  # type: ignore[return-value]

    def mark_alert_notified(self, alert_id: int) -> None:
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "UPDATE alerts SET notified = 1 WHERE id = ?", (alert_id,)
            )

    def resolve_alert(self, alert_id: int) -> None:
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "UPDATE alerts SET resolved_at = ? WHERE id = ?",
                (time.time(), alert_id),
            )

    def get_unnotified_alerts(self) -> list[AlertRow]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, level, title, body, resolved_at, notified "
                "FROM alerts WHERE notified = 0 ORDER BY timestamp"
            ).fetchall()
        return [_alert_from_row(r) for r in rows]

    def get_recent_alerts(self, limit: int = 20) -> list[AlertRow]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, level, title, body, resolved_at, notified "
                "FROM alerts ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_alert_from_row(r) for r in rows]

    # ── Shadow mode (intended routes) ──────────────────────────────────────

    def record_intended_route(self, command: str) -> None:
        """
        Append an intended (but not executed) routing command.

        Used by shadow mode (dry-run Layer 1): instead of mutating the kernel,
        network.py records each `ip` command it *would* have run so operators
        can review intended-vs-current route diffs before going live.
        """
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO intended_routes(ts, command) VALUES(?, ?)",
                (time.time(), command),
            )

    def list_intended_routes(self, limit: int = 100) -> list[IntendedRouteRow]:
        """Return the most recently recorded intended routing commands."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, ts, command "
                "FROM intended_routes ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_intended_route_from_row(r) for r in rows]

    # ── Retention / pruning ────────────────────────────────────────────────

    def prune_old_data(
        self,
        metrics_hours: int,
        events_days: int,
    ) -> dict[str, int]:
        """
        Delete rows older than retention thresholds.
        Returns dict of {table: rows_deleted}.
        """
        now = time.time()
        metrics_cutoff = now - (metrics_hours * 3600)
        events_cutoff = now - (events_days * 86400)

        deleted: dict[str, int] = {}
        with self._write_lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM metrics WHERE timestamp < ?", (metrics_cutoff,)
            )
            deleted["metrics"] = cur.rowcount

            cur = conn.execute(
                "DELETE FROM controller_events WHERE timestamp < ?", (events_cutoff,)
            )
            deleted["controller_events"] = cur.rowcount

            cur = conn.execute(
                "DELETE FROM switch_events WHERE timestamp < ?", (events_cutoff,)
            )
            deleted["switch_events"] = cur.rowcount

            cur = conn.execute(
                "DELETE FROM alerts WHERE timestamp < ? AND resolved_at IS NOT NULL",
                (events_cutoff,),
            )
            deleted["alerts"] = cur.rowcount

        total = sum(deleted.values())
        if total > 0:
            logger.info(
                "Pruned %d rows: %s",
                total, deleted,
                extra={"component": "database"},
            )
        return deleted

    def flush_all_data(self) -> None:
        """Delete all metrics and events. Preserves users, state, and schema."""
        with self._write_lock, self._conn() as conn:
            conn.execute("DELETE FROM metrics")
            conn.execute("DELETE FROM controller_events")
            conn.execute("DELETE FROM switch_events")
            conn.execute("DELETE FROM alerts")
        logger.warning("All metrics and events flushed", extra={"component": "database"})

    # ── Stats ──────────────────────────────────────────────────────────────

    def get_db_stats(self) -> DbStats:
        """Return row counts and file size for the dashboard."""
        _TABLES = (
            "metrics", "switch_events", "controller_events", "alerts", "users"
        )
        with self._conn() as conn:
            counts = {
                t: conn.execute(
                    "SELECT COUNT(*) FROM "
                    + t  # table names are internal constants, not user input
                ).fetchone()[0]
                for t in _TABLES
            }
            version_row = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            version = version_row[0] if version_row and version_row[0] else 0

        file_size = self._path.stat().st_size if self._path.exists() else 0

        return DbStats(
            file_size_bytes=file_size,
            metrics_count=counts["metrics"],
            switch_events_count=counts["switch_events"],
            controller_events_count=counts["controller_events"],
            alerts_count=counts["alerts"],
            users_count=counts["users"],
            schema_version=version,
        )

    def close(self) -> None:
        """
        Close the thread-local SQLite connection for the calling thread.

        Call this from each thread before it exits, and from the main thread
        on SIGTERM/SIGINT to ensure clean shutdown. Safe to call multiple times.

        For :memory: databases the persistent connection is intentionally kept
        open so that callers can still query the database after close().
        """
        if self._mem_conn is not None:
            # Keep the in-memory connection alive — closing it would destroy
            # all data and schema, making subsequent queries fail.
            logger.debug(
                "close() skipped for in-memory database",
                extra={"component": "database"},
            )
            return
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error as exc:
                logger.warning(
                    "Error closing DB connection: %s", exc,
                    extra={"component": "database"},
                )
            finally:
                self._local.conn = None
        logger.debug(
            "Database connection closed for thread",
            extra={"component": "database"},
        )

    # ── Migrations ─────────────────────────────────────────────────────────

    def _run_migrations(self) -> None:
        with self._write_lock, self._conn() as conn:
            # schema_version table might not exist yet
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                "version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
            )
            applied = {
                r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()
            }

        for version, sql in sorted(MIGRATIONS.items()):
            if version in applied:
                continue
            logger.info(
                "Applying migration v%d", version, extra={"component": "database"}
            )
            with self._write_lock, self._conn() as conn:
                conn.executescript(sql)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES(?, ?)",
                    (version, time.time()),
                )
            logger.info(
                "Migration v%d applied", version, extra={"component": "database"}
            )

        self._ensure_requires_password_change_column()

    def _ensure_requires_password_change_column(self) -> None:
        """Repair older v1 databases created before first-login reset support."""
        with self._write_lock, self._conn() as conn:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
            if "requires_password_change" not in columns:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN requires_password_change "
                    "INTEGER NOT NULL DEFAULT 0"
                )

    # ── Connection management ──────────────────────────────────────────────

    @contextmanager
    def _conn(self, exclusive: bool = False) -> Generator[sqlite3.Connection, None, None]:
        """
        Return a per-thread SQLite connection with manual transaction management.
        The connection is reused across calls within the same thread.

        Parameters
        ----------
        exclusive:
            When True, starts a ``BEGIN EXCLUSIVE`` transaction instead of the
            default ``BEGIN`` (deferred).  Use for IPC-safe key-value state
            access shared between Master and Standby processes.
        """
        # In-memory databases share a single persistent connection; file-based
        # databases use a per-thread connection via threading.local().
        if self._mem_conn is not None:
            conn = self._mem_conn
        else:
            if not hasattr(self._local, "conn") or self._local.conn is None:
                self._local.conn = sqlite3.connect(
                    str(self._path),
                    check_same_thread=False,
                    isolation_level=None,  # autocommit; we manage transactions manually
                )
                # PRAGMAs must be set outside any transaction.
                self._local.conn.execute("PRAGMA journal_mode=WAL")
                self._local.conn.execute("PRAGMA foreign_keys=ON")
                self._local.conn.execute("PRAGMA synchronous=NORMAL")
                # Wait up to 5s for a contended lock (e.g. the ExecStop
                # --restore-routes process vs the dying main process) instead of
                # failing immediately with "database is locked".
                self._local.conn.execute("PRAGMA busy_timeout=5000")
                self._local.conn.row_factory = sqlite3.Row
            conn = self._local.conn
        # The shared in-memory connection needs the check-then-BEGIN to be atomic
        # across threads (see __init__). Per-thread file connections are not
        # shared, so they take no lock. RLock allows nested _conn() on one thread.
        shared_lock = self._mem_txn_lock if self._mem_conn is not None else None
        if shared_lock is not None:
            shared_lock.acquire()
        try:
            # If the caller is already inside a transaction (e.g. nested _conn
            # calls), just yield without opening another BEGIN.
            if conn.in_transaction:
                yield conn
            else:
                begin = "BEGIN EXCLUSIVE" if exclusive else "BEGIN"
                conn.execute(begin)
                try:
                    yield conn
                    # executescript() issues an implicit COMMIT; guard before
                    # trying to commit again to avoid OperationalError.
                    if conn.in_transaction:
                        conn.execute("COMMIT")
                except sqlite3.Error:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
        except sqlite3.OperationalError as exc:
            logger.error(
                "SQLite error: %s", exc, extra={"component": "database"}
            )
            raise
        finally:
            if shared_lock is not None:
                shared_lock.release()
