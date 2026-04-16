"""
tests/unit/test_database.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for wancontrol.database.

Uses :memory: DBs for most tests; file-based (tmp_path) only where
in-memory is insufficient (WAL mode, file_size_bytes, thread safety).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from wancontrol.database import (
    AlertRow,
    ApiTokenRow,
    ControllerEventRow,
    Database,
    DbStats,
    MetricRow,
    SwitchEventRow,
    UserRow,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_db() -> Database:
    """In-memory DB, already initialized. Fastest for single-thread tests."""
    db = Database(":memory:")
    db.initialize()
    return db


@pytest.fixture
def file_db(tmp_path: Path) -> Database:
    """File-based DB needed for WAL mode, file_size, and thread-safety tests."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    return db


def _make_user(db: Database, username: str = "alice", role: str = "admin") -> int:
    return db.create_user(username, "hashed_pw", role)


# ── SETUP ─────────────────────────────────────────────────────────────────────

class TestSetup:
    def test_initialize_creates_all_tables(self, file_db: Database) -> None:
        conn = sqlite3.connect(str(file_db._path))
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        expected = {
            "schema_version", "metrics", "switch_events",
            "controller_events", "state", "users", "api_tokens", "alerts",
        }
        assert expected.issubset(tables)

    def test_initialize_is_idempotent(self, file_db: Database) -> None:
        file_db.initialize()  # second call — must not raise

    def test_schema_version_is_1_after_initialize(self, mem_db: Database) -> None:
        stats = mem_db.get_db_stats()
        assert stats.schema_version == 1

    def test_wal_mode_enabled(self, file_db: Database) -> None:
        conn = sqlite3.connect(str(file_db._path))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"


# ── METRICS ───────────────────────────────────────────────────────────────────

class TestMetrics:
    def test_insert_and_retrieve_via_get_latest(self, mem_db: Database) -> None:
        mem_db.insert_metric("wan0", 12.0, 1.0, 0.0, True, True, 95.0)
        row = mem_db.get_latest_metric("wan0")
        assert row is not None
        assert isinstance(row, MetricRow)
        assert row.interface == "wan0"
        assert row.latency_ms == 12.0
        assert row.score == 95.0

    def test_get_metrics_no_filter_newest_first(self, mem_db: Database) -> None:
        t0 = time.time() - 10
        mem_db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 90.0, timestamp=t0)
        mem_db.insert_metric("wan0", 20.0, 2.0, 0.0, True, True, 80.0, timestamp=t0 + 5)
        rows = mem_db.get_metrics()
        assert len(rows) >= 2
        # newest first — higher timestamp comes first
        assert rows[0].timestamp >= rows[1].timestamp

    def test_get_metrics_filter_by_interface(self, mem_db: Database) -> None:
        mem_db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 90.0)
        mem_db.insert_metric("wan1", 20.0, 2.0, 5.0, False, True, 70.0)
        rows = mem_db.get_metrics(interface="wan0")
        assert all(r.interface == "wan0" for r in rows)

    def test_get_metrics_filter_by_since(self, mem_db: Database) -> None:
        now = time.time()
        mem_db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 90.0, timestamp=now - 100)
        mem_db.insert_metric("wan0", 11.0, 1.0, 0.0, True, True, 91.0, timestamp=now - 10)
        rows = mem_db.get_metrics(since=now - 50)
        assert len(rows) == 1
        assert rows[0].latency_ms == 11.0

    def test_get_latest_metric_returns_none_for_unknown(self, mem_db: Database) -> None:
        assert mem_db.get_latest_metric("wan99") is None

    def test_dns_ok_and_http_ok_roundtrip_as_boolean(self, mem_db: Database) -> None:
        mem_db.insert_metric("wan0", 5.0, 0.5, 0.0, True, False, 88.0)
        row = mem_db.get_latest_metric("wan0")
        assert row is not None
        assert bool(row.dns_ok) is True
        assert bool(row.http_ok) is False


# ── SWITCH EVENTS ─────────────────────────────────────────────────────────────

class TestSwitchEvents:
    def test_insert_and_retrieve(self, mem_db: Database) -> None:
        mem_db.insert_switch_event("wan0", "wan1", "low_score", 18.0, 75.0)
        events = mem_db.get_switch_events()
        assert len(events) == 1
        e = events[0]
        assert isinstance(e, SwitchEventRow)
        assert e.from_interface == "wan0"
        assert e.to_interface == "wan1"
        assert e.reason == "low_score"

    def test_default_triggered_by_is_controller(self, mem_db: Database) -> None:
        mem_db.insert_switch_event("wan0", "wan1", "probe_fail", 15.0, 80.0)
        assert mem_db.get_switch_events()[0].triggered_by == "controller"

    def test_custom_triggered_by_preserved(self, mem_db: Database) -> None:
        mem_db.insert_switch_event("wan1", "wan0", "manual", 60.0, 90.0,
                                   triggered_by="api:admin")
        assert mem_db.get_switch_events()[0].triggered_by == "api:admin"

    def test_results_ordered_newest_first(self, mem_db: Database) -> None:
        now = time.time()
        mem_db.insert_switch_event("wan0", "wan1", "first", 10.0, 80.0, timestamp=now - 10)
        mem_db.insert_switch_event("wan1", "wan0", "second", 80.0, 90.0, timestamp=now)
        events = mem_db.get_switch_events()
        assert events[0].reason == "second"
        assert events[1].reason == "first"


# ── CONTROLLER EVENTS ─────────────────────────────────────────────────────────

class TestControllerEvents:
    def test_log_event_without_user_id(self, mem_db: Database) -> None:
        mem_db.log_event("INFO", "controller", "started")
        events = mem_db.get_events()
        assert len(events) == 1
        e = events[0]
        assert isinstance(e, ControllerEventRow)
        assert e.component == "controller"
        assert e.user_id is None

    def test_log_event_with_user_id(self, mem_db: Database) -> None:
        uid = _make_user(mem_db)
        mem_db.log_event("WARNING", "auth", "bad password", user_id=uid)
        events = mem_db.get_events()
        assert events[0].user_id == uid

    def test_get_events_filter_by_level(self, mem_db: Database) -> None:
        mem_db.log_event("INFO", "controller", "routine")
        mem_db.log_event("ERROR", "controller", "crashed")
        errors = mem_db.get_events(level="ERROR")
        assert all(e.level == "ERROR" for e in errors)
        assert len(errors) == 1

    def test_level_stored_uppercase(self, mem_db: Database) -> None:
        mem_db.log_event("error", "controller", "lower input")
        e = mem_db.get_events()[0]
        assert e.level == "ERROR"


# ── STATE ─────────────────────────────────────────────────────────────────────

class TestState:
    def test_set_and_get_roundtrip(self, mem_db: Database) -> None:
        mem_db.set_state("active_interface", "wan0")
        assert mem_db.get_state("active_interface") == "wan0"

    def test_get_state_returns_default_for_missing_key(self, mem_db: Database) -> None:
        assert mem_db.get_state("nonexistent") is None
        assert mem_db.get_state("nonexistent", default="fallback") == "fallback"

    def test_set_state_overwrites_existing(self, mem_db: Database) -> None:
        mem_db.set_state("mode", "failover")
        mem_db.set_state("mode", "load_balance")
        assert mem_db.get_state("mode") == "load_balance"

    def test_get_all_state_returns_all_keys(self, mem_db: Database) -> None:
        mem_db.set_state("k1", "v1")
        mem_db.set_state("k2", "v2")
        state = mem_db.get_all_state()
        assert state["k1"] == "v1"
        assert state["k2"] == "v2"

    def test_concurrent_set_state_no_corruption(self, file_db: Database) -> None:
        """5 threads each write a unique key; all must be present afterward."""
        errors: list[Exception] = []

        def _write(i: int) -> None:
            try:
                file_db.set_state(f"key_{i}", f"val_{i}")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Threads raised: {errors}"
        state = file_db.get_all_state()
        for i in range(5):
            assert state.get(f"key_{i}") == f"val_{i}"


# ── USERS ─────────────────────────────────────────────────────────────────────

class TestUsers:
    def test_create_user_returns_int_id(self, mem_db: Database) -> None:
        uid = mem_db.create_user("alice", "hash", "admin")
        assert isinstance(uid, int)
        assert uid > 0

    def test_get_user_by_username(self, mem_db: Database) -> None:
        mem_db.create_user("bob", "hash", "viewer")
        row = mem_db.get_user_by_username("bob")
        assert isinstance(row, UserRow)
        assert row.username == "bob"
        assert row.role == "viewer"

    def test_get_user_by_username_returns_none_for_unknown(self, mem_db: Database) -> None:
        assert mem_db.get_user_by_username("nobody") is None

    def test_get_user_by_id(self, mem_db: Database) -> None:
        uid = mem_db.create_user("carol", "hash", "operator")
        row = mem_db.get_user_by_id(uid)
        assert row is not None
        assert row.id == uid
        assert row.username == "carol"

    def test_list_users_returns_all(self, mem_db: Database) -> None:
        mem_db.create_user("u1", "h", "viewer")
        mem_db.create_user("u2", "h", "admin")
        users = mem_db.list_users()
        names = [u.username for u in users]
        assert "u1" in names
        assert "u2" in names

    def test_update_user_password(self, mem_db: Database) -> None:
        uid = mem_db.create_user("dave", "old_hash", "viewer")
        mem_db.update_user_password(uid, "new_hash")
        row = mem_db.get_user_by_id(uid)
        assert row is not None
        assert row.password_hash == "new_hash"

    def test_update_user_last_login(self, mem_db: Database) -> None:
        uid = mem_db.create_user("eve", "hash", "viewer")
        before = time.time()
        mem_db.update_user_last_login(uid)
        after = time.time()
        row = mem_db.get_user_by_id(uid)
        assert row is not None
        assert row.last_login is not None
        assert before <= row.last_login <= after

    def test_update_user_role(self, mem_db: Database) -> None:
        uid = mem_db.create_user("frank", "hash", "viewer")
        mem_db.update_user_role(uid, "admin")
        row = mem_db.get_user_by_id(uid)
        assert row is not None
        assert row.role == "admin"

    def test_deactivate_user(self, mem_db: Database) -> None:
        uid = mem_db.create_user("grace", "hash", "viewer")
        mem_db.deactivate_user(uid)
        row = mem_db.get_user_by_id(uid)
        assert row is not None
        assert not row.is_active

    def test_count_users(self, mem_db: Database) -> None:
        assert mem_db.count_users() == 0
        mem_db.create_user("u1", "h", "viewer")
        mem_db.create_user("u2", "h", "viewer")
        assert mem_db.count_users() == 2

    def test_duplicate_username_raises_integrity_error(self, mem_db: Database) -> None:
        mem_db.create_user("henry", "hash", "viewer")
        with pytest.raises(sqlite3.IntegrityError):
            mem_db.create_user("henry", "hash2", "admin")


# ── API TOKENS ────────────────────────────────────────────────────────────────

class TestApiTokens:
    @pytest.fixture(autouse=True)
    def _user(self, mem_db: Database) -> None:
        self.uid = _make_user(mem_db, "tokenuser")
        self.db = mem_db

    def test_create_api_token_returns_id(self) -> None:
        tid = self.db.create_api_token(self.uid, "hash_abc", "CLI token", None)
        assert isinstance(tid, int)
        assert tid > 0

    def test_get_api_token_by_hash(self) -> None:
        self.db.create_api_token(self.uid, "unique_hash", "Test", None)
        row = self.db.get_api_token_by_hash("unique_hash")
        assert isinstance(row, ApiTokenRow)
        assert row.token_hash == "unique_hash"
        assert row.user_id == self.uid

    def test_get_api_token_by_hash_returns_none_for_unknown(self) -> None:
        assert self.db.get_api_token_by_hash("nonexistent") is None

    def test_touch_api_token_updates_last_used(self) -> None:
        tid = self.db.create_api_token(self.uid, "touch_hash", "Test", None)
        before = time.time()
        self.db.touch_api_token(tid)
        after = time.time()
        row = self.db.get_api_token_by_hash("touch_hash")
        assert row is not None
        assert row.last_used is not None
        assert before <= row.last_used <= after

    def test_revoke_api_token_sets_is_revoked(self) -> None:
        tid = self.db.create_api_token(self.uid, "revoke_hash", "Test", None)
        self.db.revoke_api_token(tid)
        row = self.db.get_api_token_by_hash("revoke_hash")
        assert row is not None
        assert bool(row.is_revoked) is True

    def test_list_api_tokens_filtered_by_user(self) -> None:
        uid2 = _make_user(self.db, "other_user")
        self.db.create_api_token(self.uid, "h1", "mine", None)
        self.db.create_api_token(uid2, "h2", "theirs", None)
        tokens = self.db.list_api_tokens(user_id=self.uid)
        assert all(t.user_id == self.uid for t in tokens)
        assert len(tokens) == 1

    def test_list_api_tokens_no_filter_returns_all(self) -> None:
        uid2 = _make_user(self.db, "second_user")
        self.db.create_api_token(self.uid, "h_a", "A", None)
        self.db.create_api_token(uid2, "h_b", "B", None)
        tokens = self.db.list_api_tokens()
        assert len(tokens) == 2


# ── ALERTS ────────────────────────────────────────────────────────────────────

class TestAlerts:
    def test_insert_alert_returns_id(self, mem_db: Database) -> None:
        aid = mem_db.insert_alert("WARNING", "Link flap", "wan0 went down")
        assert isinstance(aid, int)
        assert aid > 0

    def test_mark_alert_notified(self, mem_db: Database) -> None:
        aid = mem_db.insert_alert("INFO", "Test", "body")
        mem_db.mark_alert_notified(aid)
        alerts = mem_db.get_recent_alerts()
        alert = next(a for a in alerts if a.id == aid)
        assert bool(alert.notified) is True

    def test_resolve_alert_sets_resolved_at(self, mem_db: Database) -> None:
        aid = mem_db.insert_alert("ERROR", "Down", "wan1 failed")
        before = time.time()
        mem_db.resolve_alert(aid)
        after = time.time()
        alerts = mem_db.get_recent_alerts()
        alert = next(a for a in alerts if a.id == aid)
        assert alert.resolved_at is not None
        assert before <= alert.resolved_at <= after

    def test_get_unnotified_alerts_excludes_notified(self, mem_db: Database) -> None:
        aid1 = mem_db.insert_alert("INFO", "A", "body")
        aid2 = mem_db.insert_alert("INFO", "B", "body")
        mem_db.mark_alert_notified(aid1)
        unnotified = mem_db.get_unnotified_alerts()
        ids = [a.id for a in unnotified]
        assert aid1 not in ids
        assert aid2 in ids

    def test_get_recent_alerts_newest_first(self, mem_db: Database) -> None:
        now = time.time()
        mem_db.insert_alert("INFO", "old", "body", timestamp=now - 100)
        mem_db.insert_alert("INFO", "new", "body", timestamp=now)
        alerts = mem_db.get_recent_alerts()
        assert alerts[0].title == "new"
        assert alerts[1].title == "old"


# ── RETENTION ─────────────────────────────────────────────────────────────────

class TestRetention:
    def test_prune_deletes_old_metrics(self, mem_db: Database) -> None:
        old_ts = time.time() - (5 * 3600)  # 5 hours ago
        mem_db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 90.0, timestamp=old_ts)
        result = mem_db.prune_old_data(metrics_hours=2, events_days=30)
        assert result["metrics"] == 1
        assert mem_db.get_latest_metric("wan0") is None

    def test_prune_deletes_old_controller_events(self, mem_db: Database) -> None:
        old_ts = time.time() - (40 * 86400)  # 40 days ago
        mem_db.log_event("INFO", "controller", "old event", timestamp=old_ts)
        result = mem_db.prune_old_data(metrics_hours=72, events_days=30)
        assert result["controller_events"] == 1

    def test_prune_does_not_delete_recent_data(self, mem_db: Database) -> None:
        mem_db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 90.0)
        mem_db.log_event("INFO", "controller", "recent")
        result = mem_db.prune_old_data(metrics_hours=72, events_days=30)
        assert result["metrics"] == 0
        assert result["controller_events"] == 0

    def test_prune_returns_dict_with_counts(self, mem_db: Database) -> None:
        result = mem_db.prune_old_data(metrics_hours=72, events_days=30)
        assert "metrics" in result
        assert "controller_events" in result
        assert "switch_events" in result
        assert "alerts" in result

    def test_flush_all_data_removes_metrics_and_events(self, mem_db: Database) -> None:
        mem_db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 90.0)
        mem_db.log_event("INFO", "controller", "msg")
        mem_db.insert_switch_event("wan0", "wan1", "fail", 10.0, 80.0)
        mem_db.insert_alert("INFO", "test", "body")

        mem_db.flush_all_data()

        stats = mem_db.get_db_stats()
        assert stats.metrics_count == 0
        assert stats.controller_events_count == 0
        assert stats.switch_events_count == 0
        assert stats.alerts_count == 0

    def test_flush_preserves_users_and_state(self, mem_db: Database) -> None:
        _make_user(mem_db, "survivor")
        mem_db.set_state("key", "value")
        mem_db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 90.0)

        mem_db.flush_all_data()

        assert mem_db.count_users() == 1
        assert mem_db.get_state("key") == "value"


# ── STATS ─────────────────────────────────────────────────────────────────────

class TestStats:
    def test_get_db_stats_returns_dbstats(self, mem_db: Database) -> None:
        assert isinstance(mem_db.get_db_stats(), DbStats)

    def test_get_db_stats_correct_counts(self, mem_db: Database) -> None:
        mem_db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 90.0)
        mem_db.insert_metric("wan0", 11.0, 1.0, 0.0, True, True, 91.0)
        mem_db.insert_switch_event("wan0", "wan1", "fail", 10.0, 80.0)
        mem_db.log_event("INFO", "controller", "msg")
        mem_db.insert_alert("INFO", "t", "b")
        _make_user(mem_db)

        stats = mem_db.get_db_stats()
        assert stats.metrics_count == 2
        assert stats.switch_events_count == 1
        assert stats.controller_events_count == 1
        assert stats.alerts_count == 1
        assert stats.users_count == 1

    def test_get_db_stats_schema_version_is_1(self, mem_db: Database) -> None:
        assert mem_db.get_db_stats().schema_version == 1

    def test_get_db_stats_file_size_bytes_positive(self, file_db: Database) -> None:
        file_db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 90.0)
        stats = file_db.get_db_stats()
        assert stats.file_size_bytes > 0


# ── MIGRATIONS ────────────────────────────────────────────────────────────────

class TestMigrations:
    def test_double_initialize_does_not_duplicate_tables(self, file_db: Database) -> None:
        file_db.initialize()  # second init
        conn = sqlite3.connect(str(file_db._path))
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        conn.close()
        assert len(tables) == len(set(tables)), "Duplicate table names found"

    def test_schema_version_has_one_row_per_migration(self, file_db: Database) -> None:
        conn = sqlite3.connect(str(file_db._path))
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
        conn.close()
        versions = [r[0] for r in rows]
        # Exactly one row for version 1
        assert versions.count(1) == 1


# ── THREAD SAFETY ─────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_inserts_all_rows_present(self, file_db: Database) -> None:
        """20 threads × 50 inserts = 1000 metric rows, no deadlock."""
        errors: list[Exception] = []

        def _insert_batch() -> None:
            try:
                for _ in range(50):
                    file_db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 90.0)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_insert_batch) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        # Verify no thread is still alive (deadlock check)
        alive = [t for t in threads if t.is_alive()]
        assert alive == [], f"{len(alive)} threads still alive — possible deadlock"

        assert errors == [], f"Threads raised: {errors}"
        stats = file_db.get_db_stats()
        assert stats.metrics_count == 1000
