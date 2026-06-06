"""
tests/unit/test_controller.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for wancontrol.controller and wancontrol.watchdog.

Covers:
  Controller: init, get_status, state machine, stop, apply_failover,
              apply_load_balance, fire_alert, master lock, deliver_webhooks
  Watchdog:   write_heartbeat, verify_routes, atexit handler, signal handling,
              start/stop lifecycle
"""

from __future__ import annotations

import fcntl
import os
import signal
import threading
import time
import unittest.mock as mock
from pathlib import Path

import pytest
import yaml

from wancontrol.config import Config
from wancontrol.controller import Controller, ControllerMode, InterfaceState, WanState
from wancontrol.database import Database
from wancontrol.monitor import InterfaceMetric
from wancontrol.watchdog import Watchdog


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cfg_dict(wan_mode: str = "failover", **overrides) -> dict:
    d: dict = {
        "interfaces": [
            {"name": "wan0", "label": "Primary", "expected_speed_mbps": 100,
             "gateway": "192.168.1.1", "routing_table_id": 100},
            {"name": "wan1", "label": "Backup", "expected_speed_mbps": 30,
             "gateway": "10.0.0.1", "routing_table_id": 101},
        ],
        "wan_mode": wan_mode,
        "probes": {
            "interval_sec": 1, "dns_targets": ["8.8.8.8"],
            "icmp_targets": ["8.8.8.8"], "http_targets": ["http://x.com"],
            "icmp_count": 3, "icmp_timeout_sec": 2,
            "dns_timeout_sec": 2, "http_timeout_sec": 3,
        },
        "scoring": {
            "latency_penalty_per_ms": 0.3, "loss_penalty_per_percent": 2.0,
            "dns_fail_penalty": 15, "http_fail_penalty": 20,
            "hard_fail_threshold": 20, "hysteresis_switch_to_backup": 25,
            "hysteresis_return_to_primary": 10, "recovery_margin": 10,
        },
        "controller": {
            "loop_interval_sec": 1, "benchmark_interval_sec": 300,
            "metric_collection_timeout_sec": 8,
            "heartbeat_interval_sec": 5, "heartbeat_stale_sec": 15,
        },
        "retention": {
            "metrics_hours": 72, "events_days": 30, "prune_interval_min": 60,
        },
        "alerting": {"enabled": False, "webhooks": []},
        "server": {
            "host": "0.0.0.0", "port": 5000, "secret_key": "a" * 32,
            "jwt_expiry_hours": 24, "session_timeout_minutes": 60,
        },
        "log_dir": "/tmp",
    }
    d.update(overrides)
    return d


def _load_cfg(tmp_path: Path, wan_mode: str = "failover", **overrides) -> object:
    # Build defaults; callers can override any key.
    defaults: dict = {
        "lock_file": str(tmp_path / "test.lock"),
        "heartbeat_file": str(tmp_path / "test.heartbeat"),
        "db_path": ":memory:",
    }
    defaults.update(overrides)
    d = _cfg_dict(wan_mode=wan_mode, **defaults)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(d))
    return Config(str(p)).load()


def _metric(interface: str = "wan0", score: float = 95.0,
            is_hard_fail: bool = False) -> InterfaceMetric:
    return InterfaceMetric(
        interface=interface,
        timestamp=time.time(),
        latency_ms=10.0,
        jitter_ms=1.0,
        loss_pct=0.0,
        dns_ok=True,
        http_ok=True,
        score=score,
        is_hard_fail=is_hard_fail,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_db() -> Database:
    db = Database(":memory:")
    db.initialize()
    return db


@pytest.fixture
def app_cfg(tmp_path: Path):
    return _load_cfg(tmp_path, wan_mode="failover")


@pytest.fixture
def lb_cfg(tmp_path: Path):
    return _load_cfg(tmp_path, wan_mode="load_balance",
                     lock_file=str(tmp_path / "lb.lock"),
                     heartbeat_file=str(tmp_path / "lb.heartbeat"))


@pytest.fixture
def ctrl(app_cfg, mem_db) -> Controller:
    return Controller(cfg=app_cfg, db=mem_db)


@pytest.fixture
def lb_ctrl(lb_cfg, mem_db) -> Controller:
    return Controller(cfg=lb_cfg, db=mem_db)


@pytest.fixture
def wd(app_cfg, mem_db, ctrl) -> Watchdog:
    return Watchdog(cfg=app_cfg, db=mem_db, controller=ctrl)


@pytest.fixture
def lb_wd(lb_cfg, mem_db, lb_ctrl) -> Watchdog:
    return Watchdog(cfg=lb_cfg, db=mem_db, controller=lb_ctrl)


# ── Controller: Init ──────────────────────────────────────────────────────────

class TestControllerInit:
    def test_failover_mode_sets_active_interface(self, ctrl):
        assert ctrl._active_interface == "wan0"

    def test_load_balance_mode_populates_nexthop_pool(self, lb_ctrl):
        assert set(lb_ctrl._nexthop_pool) == {"wan0", "wan1"}

    def test_mode_starts_as_stopped(self, ctrl):
        # A freshly-constructed, not-yet-started controller is STOPPED (it may
        # never start when auto_start is off), matching the DB state __main__ sets.
        assert ctrl._mode == ControllerMode.STOPPED

    def test_interface_states_created_for_all_interfaces(self, ctrl):
        assert "wan0" in ctrl._interface_states
        assert "wan1" in ctrl._interface_states

    def test_all_interfaces_start_stable(self, ctrl):
        for state in ctrl._interface_states.values():
            assert state.wan_state == WanState.STABLE

    def test_load_balance_all_interfaces_in_pool(self, lb_ctrl):
        for state in lb_ctrl._interface_states.values():
            assert state.in_nexthop_pool is True


# ── Controller: get_status() ──────────────────────────────────────────────────

class TestGetStatus:
    def test_returns_required_top_level_keys(self, ctrl):
        s = ctrl.get_status()
        for key in ("mode", "wan_mode", "interfaces", "active_interface",
                    "nexthop_pool", "timestamp"):
            assert key in s

    def test_mode_reflects_current_controller_mode(self, ctrl):
        assert ctrl.get_status()["mode"] == "STOPPED"

    def test_wan_mode_is_correct(self, ctrl, lb_ctrl):
        assert ctrl.get_status()["wan_mode"] == "failover"
        assert lb_ctrl.get_status()["wan_mode"] == "load_balance"

    def test_interfaces_dict_contains_all_interfaces(self, ctrl):
        ifaces = ctrl.get_status()["interfaces"]
        assert "wan0" in ifaces
        assert "wan1" in ifaces

    def test_interface_entry_has_required_fields(self, ctrl):
        entry = ctrl.get_status()["interfaces"]["wan0"]
        assert "wan_state" in entry
        assert "score" in entry
        assert "in_pool" in entry

    def test_active_interface_set_for_failover_mode(self, ctrl):
        assert ctrl.get_status()["active_interface"] == "wan0"

    def test_nexthop_pool_set_for_lb_mode(self, lb_ctrl):
        pool = lb_ctrl.get_status()["nexthop_pool"]
        assert set(pool) == {"wan0", "wan1"}

    def test_10_concurrent_readers_all_succeed(self, ctrl):
        errors: list[str] = []
        results: list[str] = []

        def reader() -> None:
            try:
                s = ctrl.get_status()
                assert "mode" in s
                assert "interfaces" in s
                results.append("ok")
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors
        assert len(results) == 10


# ── Controller: WAN state machine ─────────────────────────────────────────────

class TestWanStateMachine:
    """
    degraded_threshold = hard_fail_threshold(20)
                       + hysteresis_switch_to_backup(25)
                       + recovery_margin(10)
                       = 55  (for the default test config)
    """

    def _state(self, ctrl: Controller, wan_state: WanState,
               score: float = 100.0) -> InterfaceState:
        s = ctrl._interface_states["wan0"]
        s.wan_state = wan_state
        s.last_score = score
        s.stable_since = time.time()
        return s

    # STABLE transitions
    def test_stable_to_failed_on_hard_fail(self, ctrl):
        # Anti-flap (item 11): a single hard-fail sample holds in DEGRADED; the
        # link only becomes FAILED after `fail_confirmations` consecutive
        # hard-fail cycles (default 3).
        s = self._state(ctrl, WanState.STABLE, 95.0)
        ctrl._update_wan_state(s, _metric(score=0.0, is_hard_fail=True))
        assert s.wan_state == WanState.DEGRADED
        for _ in range(2):
            ctrl._update_wan_state(s, _metric(score=0.0, is_hard_fail=True))
        assert s.wan_state == WanState.FAILED

    def test_stable_to_degraded_when_score_below_threshold(self, ctrl):
        # score=50 < degraded_threshold=55
        s = self._state(ctrl, WanState.STABLE, 95.0)
        ctrl._update_wan_state(s, _metric(score=50.0, is_hard_fail=False))
        assert s.wan_state == WanState.DEGRADED

    def test_stable_stays_stable_when_score_good(self, ctrl):
        # score=95 >= degraded_threshold=55
        s = self._state(ctrl, WanState.STABLE, 95.0)
        ctrl._update_wan_state(s, _metric(score=95.0, is_hard_fail=False))
        assert s.wan_state == WanState.STABLE

    def test_stable_stays_stable_at_exact_threshold(self, ctrl):
        # score=55 == degraded_threshold=55 — stays STABLE (>= check)
        s = self._state(ctrl, WanState.STABLE, 95.0)
        ctrl._update_wan_state(s, _metric(score=55.0, is_hard_fail=False))
        assert s.wan_state == WanState.STABLE

    # DEGRADED transitions
    def test_degraded_to_failed_on_hard_fail(self, ctrl):
        # Anti-flap (item 11): FAILED only after `fail_confirmations` (default 3)
        # consecutive hard-fail cycles.
        s = self._state(ctrl, WanState.DEGRADED, 50.0)
        for _ in range(3):
            ctrl._update_wan_state(s, _metric(score=0.0, is_hard_fail=True))
        assert s.wan_state == WanState.FAILED

    def test_degraded_to_stable_when_score_recovers(self, ctrl):
        # score=95 >= degraded_threshold=55
        s = self._state(ctrl, WanState.DEGRADED, 50.0)
        ctrl._update_wan_state(s, _metric(score=95.0, is_hard_fail=False))
        assert s.wan_state == WanState.STABLE

    def test_degraded_stays_degraded_at_mid_score(self, ctrl):
        # score=50 < degraded_threshold=55
        s = self._state(ctrl, WanState.DEGRADED, 50.0)
        ctrl._update_wan_state(s, _metric(score=50.0, is_hard_fail=False))
        assert s.wan_state == WanState.DEGRADED

    # FAILED transitions
    def test_failed_to_degraded_when_score_above_hard_fail(self, ctrl):
        # score=50 >= hard_fail_threshold=20
        s = self._state(ctrl, WanState.FAILED, 0.0)
        ctrl._update_wan_state(s, _metric(score=50.0, is_hard_fail=False))
        assert s.wan_state == WanState.DEGRADED

    def test_failed_stays_failed_on_hard_fail(self, ctrl):
        s = self._state(ctrl, WanState.FAILED, 0.0)
        ctrl._update_wan_state(s, _metric(score=0.0, is_hard_fail=True))
        assert s.wan_state == WanState.FAILED

    def test_failed_stays_failed_when_score_still_low(self, ctrl):
        # score=5 < hard_fail_threshold=20
        s = self._state(ctrl, WanState.FAILED, 0.0)
        ctrl._update_wan_state(s, _metric(score=5.0, is_hard_fail=False))
        assert s.wan_state == WanState.FAILED

    # stable_since reset
    def test_stable_since_reset_when_entering_stable(self, ctrl):
        s = self._state(ctrl, WanState.DEGRADED, 50.0)
        s.stable_since = time.time() - 200
        old_since = s.stable_since
        ctrl._update_wan_state(s, _metric(score=95.0, is_hard_fail=False))
        assert s.wan_state == WanState.STABLE
        assert s.stable_since > old_since

    def test_stable_since_not_reset_when_staying_stable(self, ctrl):
        s = self._state(ctrl, WanState.STABLE, 95.0)
        s.stable_since = time.time() - 100
        old_since = s.stable_since
        ctrl._update_wan_state(s, _metric(score=95.0))
        assert abs(s.stable_since - old_since) < 1


# ── Controller: stop() ────────────────────────────────────────────────────────

class TestStop:
    @mock.patch("wancontrol.network.set_default_route")
    def test_stop_sets_mode_to_stopped(self, _mock_route, ctrl):
        # Graceful stop() ends in STOPPED (distinct from kill() -> KILLED).
        ctrl.stop()
        assert ctrl._mode == ControllerMode.STOPPED

    @mock.patch("wancontrol.network.set_default_route")
    def test_kill_sets_mode_to_killed(self, _mock_route, ctrl):
        # Emergency kill() ends in KILLED.
        ctrl.kill()
        assert ctrl._mode == ControllerMode.KILLED

    @mock.patch("wancontrol.network.set_default_route")
    def test_stopped_persisted_to_db(self, _mock_route, ctrl, mem_db):
        ctrl.stop()
        assert mem_db.get_state("controller_mode") == "STOPPED"

    @mock.patch("wancontrol.network.set_default_route")
    def test_get_status_returns_stopped_after_stop(self, _mock_route, ctrl):
        ctrl.stop()
        assert ctrl.get_status()["mode"] == "STOPPED"

    @mock.patch("wancontrol.network.set_default_route")
    def test_shutdown_event_logged_to_db(self, _mock_route, ctrl, mem_db):
        ctrl.stop()
        events = mem_db.get_events()
        assert any("shutdown" in e.message.lower() for e in events)

    def test_stop_restores_routes_via_snapshot(self, ctrl, app_cfg):
        # Route-restore fix (plan items 5-9): shutdown no longer hardcodes a
        # `set_default_route(primary.gateway, primary.name)`. It tears down the
        # managed interfaces and restores the ORIGINAL default-route snapshot via
        # network.emergency_cleanup -> restore_default_routes, so multipath /
        # multiple-default / metric-preserving restores all work and a stale
        # "primary" assumption can't clobber the real saved route.
        with mock.patch("wancontrol.network.emergency_cleanup") as mock_cleanup:
            ctrl.stop()
        mock_cleanup.assert_called_once_with(app_cfg.interfaces, ctrl._db)


# ── Controller: _apply_load_balance() ─────────────────────────────────────────

class TestApplyLoadBalance:
    def test_empty_pool_guard_does_not_call_set_route(self, lb_ctrl):
        lb_ctrl._mode = ControllerMode.RUNNING
        metrics = [
            _metric("wan0", score=0.0, is_hard_fail=True),
            _metric("wan1", score=0.0, is_hard_fail=True),
        ]
        with mock.patch("wancontrol.network.set_load_balance_route") as m:
            lb_ctrl._apply_load_balance(metrics)
        for call in m.call_args_list:
            assert len(call.args[0]) > 0, "set_load_balance_route called with empty pool"

    def test_no_pool_change_does_not_call_set_route(self, lb_ctrl):
        lb_ctrl._mode = ControllerMode.RUNNING
        metrics = [_metric("wan0", score=95.0), _metric("wan1", score=95.0)]
        with mock.patch("wancontrol.network.set_load_balance_route") as m:
            lb_ctrl._apply_load_balance(metrics)
        m.assert_not_called()

    def test_failed_interface_removed_from_pool(self, lb_ctrl):
        lb_ctrl._mode = ControllerMode.RUNNING
        metrics = [
            _metric("wan0", score=0.0, is_hard_fail=True),
            _metric("wan1", score=95.0),
        ]
        with mock.patch("wancontrol.network.set_load_balance_route"):
            lb_ctrl._apply_load_balance(metrics)
        assert not lb_ctrl._interface_states["wan0"].in_nexthop_pool
        assert lb_ctrl._interface_states["wan1"].in_nexthop_pool

    def test_recovered_interface_re_added_to_pool(self, lb_ctrl):
        lb_ctrl._mode = ControllerMode.RUNNING
        lb_ctrl._interface_states["wan0"].in_nexthop_pool = False
        # score > hard_fail_threshold(20) + recovery_margin(10) = 30
        metrics = [_metric("wan0", score=95.0), _metric("wan1", score=95.0)]
        with mock.patch("wancontrol.network.set_load_balance_route"):
            lb_ctrl._apply_load_balance(metrics)
        assert lb_ctrl._interface_states["wan0"].in_nexthop_pool

    def test_route_called_with_non_empty_nexthops(self, lb_ctrl):
        lb_ctrl._mode = ControllerMode.RUNNING
        # wan0 drops out, wan1 stays
        metrics = [
            _metric("wan0", score=0.0, is_hard_fail=True),
            _metric("wan1", score=95.0),
        ]
        with mock.patch("wancontrol.controller.set_load_balance_route") as m:
            lb_ctrl._apply_load_balance(metrics)
        m.assert_called_once()
        nexthops = m.call_args.args[0]
        assert len(nexthops) > 0

    def test_non_running_mode_skips_all(self, lb_ctrl):
        lb_ctrl._mode = ControllerMode.STARTING
        metrics = [
            _metric("wan0", score=0.0, is_hard_fail=True),
            _metric("wan1", score=0.0, is_hard_fail=True),
        ]
        with mock.patch("wancontrol.network.set_load_balance_route") as m:
            lb_ctrl._apply_load_balance(metrics)
        m.assert_not_called()

    def test_pool_updated_after_removal(self, lb_ctrl):
        lb_ctrl._mode = ControllerMode.RUNNING
        metrics = [
            _metric("wan0", score=0.0, is_hard_fail=True),
            _metric("wan1", score=95.0),
        ]
        with mock.patch("wancontrol.network.set_load_balance_route"):
            lb_ctrl._apply_load_balance(metrics)
        assert "wan0" not in lb_ctrl._nexthop_pool
        assert "wan1" in lb_ctrl._nexthop_pool


# ── Controller: _apply_failover() ─────────────────────────────────────────────

class TestApplyFailover:
    def test_switches_primary_to_backup_when_backup_much_better(self, ctrl):
        ctrl._mode = ControllerMode.RUNNING
        ctrl._active_interface = "wan0"
        # backup(90) > primary(10) + hysteresis(25) = 35 → switch
        metrics = [_metric("wan0", score=10.0), _metric("wan1", score=90.0)]
        with mock.patch("wancontrol.network.set_default_route"):
            ctrl._apply_failover(metrics)
        assert ctrl._active_interface == "wan1"

    def test_returns_to_primary_when_primary_recovered_and_stable(self, ctrl, mem_db):
        ctrl._mode = ControllerMode.RUNNING
        ctrl._active_interface = "wan1"
        ctrl._interface_states["wan0"].stable_since = time.time() - 31
        ctrl._interface_states["wan0"].wan_state = WanState.STABLE
        # primary(95) > backup(10) + hysteresis(10) = 20 → return
        metrics = [_metric("wan0", score=95.0), _metric("wan1", score=10.0)]
        with mock.patch("wancontrol.network.set_default_route"):
            ctrl._apply_failover(metrics)
        assert ctrl._active_interface == "wan0"

    def test_no_switch_when_mode_not_running(self, ctrl):
        ctrl._mode = ControllerMode.STARTING
        ctrl._active_interface = "wan0"
        metrics = [_metric("wan0", score=10.0), _metric("wan1", score=90.0)]
        with mock.patch("wancontrol.network.set_default_route") as m:
            ctrl._apply_failover(metrics)
        assert ctrl._active_interface == "wan0"
        m.assert_not_called()

    def test_no_switch_to_failed_backup(self, ctrl):
        ctrl._mode = ControllerMode.RUNNING
        ctrl._active_interface = "wan0"
        ctrl._interface_states["wan1"].wan_state = WanState.FAILED
        metrics = [_metric("wan0", score=10.0), _metric("wan1", score=90.0)]
        with mock.patch("wancontrol.network.set_default_route") as m:
            ctrl._apply_failover(metrics)
        assert ctrl._active_interface == "wan0"
        m.assert_not_called()

    def test_no_switch_when_score_difference_below_hysteresis(self, ctrl):
        ctrl._mode = ControllerMode.RUNNING
        ctrl._active_interface = "wan0"
        # backup(40) - primary(30) = 10 < hysteresis(25)
        metrics = [_metric("wan0", score=30.0), _metric("wan1", score=40.0)]
        with mock.patch("wancontrol.network.set_default_route") as m:
            ctrl._apply_failover(metrics)
        assert ctrl._active_interface == "wan0"
        m.assert_not_called()

    def test_no_return_to_primary_when_not_stable_long_enough(self, ctrl):
        ctrl._mode = ControllerMode.RUNNING
        ctrl._active_interface = "wan1"
        ctrl._interface_states["wan0"].stable_since = time.time() - 10  # only 10s, needs 30
        ctrl._interface_states["wan0"].wan_state = WanState.STABLE
        metrics = [_metric("wan0", score=95.0), _metric("wan1", score=10.0)]
        with mock.patch("wancontrol.network.set_default_route") as m:
            ctrl._apply_failover(metrics)
        assert ctrl._active_interface == "wan1"
        m.assert_not_called()

    def test_no_switch_when_backup_metric_missing(self, ctrl):
        """_apply_failover returns early when there is no backup metric."""
        ctrl._mode = ControllerMode.RUNNING
        ctrl._active_interface = "wan0"
        # Only wan0 metric provided — backup (wan1) metric is absent
        with mock.patch("wancontrol.controller.set_default_route") as m:
            ctrl._apply_failover([_metric("wan0", score=10.0)])
        m.assert_not_called()

    def test_switch_event_recorded_in_db(self, ctrl, mem_db):
        ctrl._mode = ControllerMode.RUNNING
        ctrl._active_interface = "wan0"
        metrics = [_metric("wan0", score=10.0), _metric("wan1", score=90.0)]
        with mock.patch("wancontrol.network.set_default_route"):
            ctrl._apply_failover(metrics)
        events = mem_db.get_switch_events()
        assert len(events) == 1
        assert events[0].from_interface == "wan0"
        assert events[0].to_interface == "wan1"


# ── Controller: _fire_alert() ─────────────────────────────────────────────────

class TestFireAlert:
    def test_disabled_alerting_inserts_nothing(self, ctrl, mem_db):
        ctrl._fire_alert("link_down", "wan0", 0.0, "interface failed")
        assert len(mem_db.get_recent_alerts()) == 0

    def test_invalid_event_does_not_raise(self, ctrl):
        ctrl._fire_alert("not_a_real_event", "wan0", 0.0, "test")

    def test_enabled_alerting_inserts_alert(self, app_cfg, mem_db):
        # Temporarily enable alerting for this test
        app_cfg_dict = _cfg_dict(
            wan_mode="failover",
            lock_file=str(app_cfg.lock_file),
            heartbeat_file=str(app_cfg.heartbeat_file),
            db_path=":memory:",
        )
        app_cfg_dict["alerting"] = {"enabled": True, "webhooks": []}
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            yaml.dump(app_cfg_dict, f)
            cfg_path = f.name
        import os as _os
        enabled_cfg = Config(cfg_path).load()
        _os.unlink(cfg_path)
        c = Controller(cfg=enabled_cfg, db=mem_db)
        c._fire_alert("link_down", "wan0", 0.0, "link failure")
        # Give the daemon thread a moment to not interfere
        time.sleep(0.05)
        alerts = mem_db.get_recent_alerts()
        assert len(alerts) == 1
        assert alerts[0].level == "CRITICAL"


# ── Controller: master lock ───────────────────────────────────────────────────

class TestMasterLock:
    def test_first_acquisition_succeeds(self, ctrl):
        result = ctrl._acquire_master_lock()
        assert result is True
        ctrl._release_master_lock()

    def test_release_removes_lock_file(self, ctrl, app_cfg):
        ctrl._acquire_master_lock()
        ctrl._release_master_lock()
        assert not Path(app_cfg.lock_file).exists()

    def test_second_controller_on_same_lock_file_fails(self, tmp_path, mem_db):
        d = _cfg_dict(
            wan_mode="failover",
            lock_file=str(tmp_path / "shared.lock"),
            heartbeat_file=str(tmp_path / "shared.heartbeat"),
            db_path=":memory:",
        )
        p = tmp_path / "shared.yaml"
        p.write_text(yaml.dump(d))
        cfg = Config(str(p)).load()

        c1 = Controller(cfg=cfg, db=mem_db)
        c2 = Controller(cfg=cfg, db=mem_db)

        assert c1._acquire_master_lock() is True
        assert c2._acquire_master_lock() is False

        c1._release_master_lock()

    def test_release_idempotent(self, ctrl):
        ctrl._acquire_master_lock()
        ctrl._release_master_lock()
        ctrl._release_master_lock()  # must not raise


# ── Controller: _deliver_webhooks() ──────────────────────────────────────────

class TestDeliverWebhooks:
    def test_no_webhooks_returns_immediately(self, ctrl, mem_db):
        """Empty webhook list — no urllib calls should happen."""
        payload = {"event": "link_down", "interface": "wan0", "score": 0.0,
                   "message": "test", "timestamp": time.time(), "alert_id": 1}
        with mock.patch("urllib.request.urlopen") as m:
            ctrl._deliver_webhooks(1, "link_down", payload)
        m.assert_not_called()

    def test_webhook_success_marks_notified(self, tmp_path, mem_db):
        d = _cfg_dict(
            wan_mode="failover",
            lock_file=str(tmp_path / "wh.lock"),
            heartbeat_file=str(tmp_path / "wh.heartbeat"),
            db_path=":memory:",
        )
        d["alerting"] = {
            "enabled": True,
            "webhooks": [{"url": "http://localhost/hook", "method": "POST",
                          "headers": {}, "on_events": ["link_down"]}],
        }
        p = tmp_path / "wh.yaml"
        p.write_text(yaml.dump(d))
        cfg = Config(str(p)).load()
        c = Controller(cfg=cfg, db=mem_db)

        alert_id = mem_db.insert_alert("CRITICAL", "Test Alert", "body")

        mock_response = mock.MagicMock()
        mock_response.__enter__ = mock.MagicMock(return_value=mock_response)
        mock_response.__exit__ = mock.MagicMock(return_value=False)
        mock_response.status = 200

        payload = {"event": "link_down", "interface": "wan0", "score": 0.0,
                   "message": "down", "timestamp": time.time(),
                   "alert_id": alert_id}

        with mock.patch("urllib.request.urlopen", return_value=mock_response):
            c._deliver_webhooks(alert_id, "link_down", payload)

        alert = mem_db.get_recent_alerts(limit=1)[0]
        assert alert.notified is True

    def test_webhook_failure_logs_warning_no_raise(self, tmp_path, mem_db):
        import urllib.error
        d = _cfg_dict(
            wan_mode="failover",
            lock_file=str(tmp_path / "wh2.lock"),
            heartbeat_file=str(tmp_path / "wh2.heartbeat"),
            db_path=":memory:",
        )
        d["alerting"] = {
            "enabled": True,
            "webhooks": [{"url": "http://localhost/hook", "method": "POST",
                          "headers": {}, "on_events": ["link_down"]}],
        }
        p = tmp_path / "wh2.yaml"
        p.write_text(yaml.dump(d))
        cfg = Config(str(p)).load()
        c = Controller(cfg=cfg, db=mem_db)

        payload = {"event": "link_down", "interface": "wan0", "score": 0.0,
                   "message": "down", "timestamp": time.time(), "alert_id": 1}

        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("connection refused")):
            with mock.patch("time.sleep"):  # skip retry backoff
                c._deliver_webhooks(1, "link_down", payload)  # must not raise


# ── Controller: start() / _run_master() / _run_standby() ─────────────────────

class TestStartAndLoops:
    def test_start_becomes_standby_when_lock_not_acquired(self, ctrl):
        with mock.patch.object(ctrl, "_acquire_master_lock", return_value=False):
            with mock.patch.object(ctrl, "_run_standby") as mock_standby:
                ctrl.start()
        mock_standby.assert_called_once()

    def test_start_runs_master_when_lock_acquired(self, ctrl):
        ctrl._mode = ControllerMode.KILLED  # so _run_master exits immediately
        with mock.patch.object(ctrl, "_acquire_master_lock", return_value=True), \
             mock.patch("wancontrol.network.enable_ip_forwarding"), \
             mock.patch("wancontrol.network.enable_rp_filter_loose"), \
             mock.patch("wancontrol.network.get_interface_ip", return_value="192.168.1.100"), \
             mock.patch("wancontrol.network.add_policy_route_table"), \
             mock.patch("wancontrol.network.add_policy_rule"), \
             mock.patch.object(ctrl, "_run_master") as mock_run:
            ctrl.start()
        mock_run.assert_called_once()

    def test_run_master_exits_immediately_when_killed(self, ctrl):
        ctrl._mode = ControllerMode.KILLED
        ctrl._run_master()  # must return, not loop

    def test_run_standby_exits_immediately_when_killed(self, ctrl):
        ctrl._mode = ControllerMode.KILLED
        ctrl._run_standby()  # must return, not loop

    def test_run_master_single_iteration_then_stop(self, ctrl, mem_db):
        ctrl._mode = ControllerMode.RUNNING
        call_count = [0]

        def fake_collect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 2:
                ctrl._mode = ControllerMode.KILLED
            return []

        with mock.patch.object(ctrl._monitor, "collect", side_effect=fake_collect), \
             mock.patch("time.sleep"):
            ctrl._run_master()

        assert call_count[0] >= 2

    def test_run_master_handles_exception_and_continues(self, ctrl, mem_db):
        ctrl._mode = ControllerMode.RUNNING
        call_count = [0]

        def raise_then_kill(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated error")
            ctrl._mode = ControllerMode.KILLED
            return []

        with mock.patch.object(ctrl._monitor, "collect", side_effect=raise_then_kill), \
             mock.patch("time.sleep"):
            ctrl._run_master()

        assert call_count[0] >= 2

    def test_run_standby_attempts_takeover_on_stale_heartbeat(self, ctrl, tmp_path):
        ctrl._mode = ControllerMode.RUNNING
        # Write a stale heartbeat
        hb_path = Path(ctrl._cfg.heartbeat_file)
        hb_path.write_text(str(time.time() - 9999))

        takeover_done = [False]

        def fake_acquire():
            takeover_done[0] = True
            ctrl._mode = ControllerMode.KILLED
            return True

        with mock.patch.object(ctrl, "_acquire_master_lock", side_effect=fake_acquire), \
             mock.patch.object(ctrl, "_run_master"), \
             mock.patch("time.sleep"):
            ctrl._run_standby()

        assert takeover_done[0]


# ── Watchdog: _write_heartbeat() ─────────────────────────────────────────────

class TestWatchdogHeartbeat:
    def test_creates_heartbeat_file(self, wd, app_cfg, tmp_path):
        hb_path = Path(app_cfg.heartbeat_file)
        if hb_path.exists():
            hb_path.unlink()
        before = time.time()
        wd._write_heartbeat()
        assert hb_path.exists()
        ts = float(hb_path.read_text().strip())
        assert ts >= before
        assert ts <= time.time() + 1

    def test_write_failure_does_not_raise(self, wd, tmp_path):
        # Point to an unwritable location
        bad_path = "/proc/wc_unreachable_heartbeat"
        wd._cfg = type("Cfg", (), {
            "heartbeat_file": bad_path,
            "controller": wd._cfg.controller,
        })()
        wd._write_heartbeat()  # must not raise


# ── Watchdog: _verify_routes() ───────────────────────────────────────────────

class TestWatchdogVerifyRoutes:
    def test_skips_verification_in_load_balance_mode(self, lb_wd):
        with mock.patch("wancontrol.watchdog.get_default_gateway") as m:
            lb_wd._verify_routes()
        m.assert_not_called()

    def test_no_reapply_when_route_matches(self, wd):
        wd._controller._active_interface = "wan0"
        with mock.patch("wancontrol.watchdog.get_default_gateway",
                        return_value=("192.168.1.1", "wan0")):
            with mock.patch.object(wd, "_reapply_routes") as m:
                wd._verify_routes()
        m.assert_not_called()

    def test_reapply_when_route_mismatches(self, wd, mem_db):
        wd._controller._active_interface = "wan0"
        with mock.patch("wancontrol.watchdog.get_default_gateway",
                        return_value=("10.0.0.1", "wan1")):
            with mock.patch.object(wd, "_reapply_routes") as m:
                wd._verify_routes()
        m.assert_called_once()

    def test_reapply_when_no_default_route(self, wd):
        wd._controller._active_interface = "wan0"
        with mock.patch("wancontrol.watchdog.get_default_gateway", return_value=None):
            with mock.patch.object(wd, "_reapply_routes") as m:
                wd._verify_routes()
        m.assert_called_once()


# ── Watchdog: signal handling / atexit ───────────────────────────────────────

class TestWatchdogSignals:
    def test_handle_signal_calls_controller_stop(self, wd):
        with mock.patch.object(wd._controller, "stop") as mock_ctrl_stop, \
             mock.patch.object(wd, "stop") as mock_wd_stop:
            wd._handle_signal(signal.SIGTERM, None)
        mock_ctrl_stop.assert_called_once()
        mock_wd_stop.assert_called_once()

    def test_atexit_handler_calls_stop(self, wd):
        with mock.patch.object(wd._controller, "stop") as mock_ctrl_stop, \
             mock.patch.object(wd, "stop") as mock_wd_stop:
            wd._atexit_handler()
        mock_ctrl_stop.assert_called_once()
        mock_wd_stop.assert_called_once()

    def test_atexit_handler_does_not_execute_twice(self, wd):
        call_count = [0]
        original_stop = wd.stop

        def counting_stop():
            call_count[0] += 1

        with mock.patch.object(wd, "stop", side_effect=counting_stop), \
             mock.patch.object(wd._controller, "stop"):
            wd._atexit_handler()
            wd._atexit_handler()  # second call must be a no-op

        assert call_count[0] == 1


# ── Watchdog: start/stop lifecycle ───────────────────────────────────────────

class TestWatchdogLifecycle:
    def test_start_creates_daemon_thread(self, wd):
        with mock.patch("signal.signal"):
            wd.start()
        assert wd._thread is not None
        assert wd._thread.is_alive()
        wd.stop()

    def test_start_twice_does_not_create_second_thread(self, wd):
        with mock.patch("signal.signal"):
            wd.start()
        thread_id = id(wd._thread)
        with mock.patch("signal.signal"):
            wd.start()  # second call — should warn, not spawn new thread
        assert id(wd._thread) == thread_id
        wd.stop()

    def test_stop_signals_thread_to_exit(self, wd):
        with mock.patch("signal.signal"):
            wd.start()
        wd.stop()
        if wd._thread is not None:
            assert not wd._thread.is_alive()
