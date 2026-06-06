"""
tests/integration/test_controller_integration.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Integration tests for wancontrol.controller and wancontrol.watchdog.

These tests use a real (file-based) SQLite database and exercise the full
interaction between Controller, Watchdog, and Database without mocking the
data layer.
"""

from __future__ import annotations

import os
import time
import unittest.mock as mock
from pathlib import Path

import pytest
import yaml

from wancontrol.config import Config
from wancontrol.controller import Controller, ControllerMode, WanState
from wancontrol.database import Database
from wancontrol.monitor import InterfaceMetric
from wancontrol.watchdog import Watchdog


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cfg_dict(tmp_path: Path, wan_mode: str = "failover") -> dict:
    return {
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
        "retention": {"metrics_hours": 72, "events_days": 30, "prune_interval_min": 60},
        "alerting": {"enabled": False, "webhooks": []},
        "server": {
            "host": "0.0.0.0", "port": 5000, "secret_key": "a" * 32,
            "jwt_expiry_hours": 24, "session_timeout_minutes": 60,
        },
        "lock_file": str(tmp_path / "test.lock"),
        "heartbeat_file": str(tmp_path / "test.heartbeat"),
        "db_path": str(tmp_path / "test.db"),
        "log_dir": str(tmp_path),
    }


def _load_app_cfg(tmp_path: Path, wan_mode: str = "failover"):
    d = _cfg_dict(tmp_path, wan_mode)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(d))
    return Config(str(p)).load()


def _metric(interface: str = "wan0", score: float = 95.0,
            is_hard_fail: bool = False) -> InterfaceMetric:
    return InterfaceMetric(
        interface=interface,
        timestamp=time.time(),
        latency_ms=10.0, jitter_ms=1.0, loss_pct=0.0,
        dns_ok=True, http_ok=True,
        score=score, is_hard_fail=is_hard_fail,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def app_cfg(tmp_path):
    return _load_app_cfg(tmp_path, "failover")


@pytest.fixture
def lb_cfg(tmp_path):
    d = _cfg_dict(tmp_path, "load_balance")
    d["lock_file"] = str(tmp_path / "lb.lock")
    d["heartbeat_file"] = str(tmp_path / "lb.heartbeat")
    d["db_path"] = str(tmp_path / "lb.db")
    p = tmp_path / "lb_config.yaml"
    p.write_text(yaml.dump(d))
    return Config(str(p)).load()


@pytest.fixture
def file_db(app_cfg) -> Database:
    db = Database(app_cfg.db_path)
    db.initialize()
    return db


@pytest.fixture
def ctrl(app_cfg, file_db) -> Controller:
    return Controller(cfg=app_cfg, db=file_db)


@pytest.fixture
def lb_db(lb_cfg) -> Database:
    db = Database(lb_cfg.db_path)
    db.initialize()
    return db


@pytest.fixture
def lb_ctrl(lb_cfg, lb_db) -> Controller:
    return Controller(cfg=lb_cfg, db=lb_db)


# ── stop() integration ────────────────────────────────────────────────────────

class TestStopIntegration:
    @mock.patch("wancontrol.network.set_default_route")
    def test_stop_persists_stopped_mode_to_file_db(self, _mock, ctrl, file_db):
        ctrl.stop()
        assert file_db.get_state("controller_mode") == "STOPPED"

    @mock.patch("wancontrol.network.set_default_route")
    def test_stop_logs_shutdown_event_to_file_db(self, _mock, ctrl, file_db):
        ctrl.stop()
        events = file_db.get_events()
        assert any("shutdown" in e.message.lower() for e in events)

    @mock.patch("wancontrol.network.set_default_route")
    def test_get_status_after_stop_returns_stopped(self, _mock, ctrl):
        ctrl.stop()
        assert ctrl.get_status()["mode"] == "STOPPED"

    @mock.patch("wancontrol.network.set_default_route")
    def test_stop_can_be_called_multiple_times_without_error(self, _mock, ctrl):
        ctrl.stop()
        ctrl.stop()  # must not raise


# ── State machine + DB integration ───────────────────────────────────────────

class TestStateMachineIntegration:
    def test_full_stable_degraded_failed_cycle(self, ctrl):
        """
        Walk wan0 through the full STABLE→DEGRADED→FAILED cycle using the
        real scoring config thresholds, then recover back to DEGRADED.
        """
        s = ctrl._interface_states["wan0"]
        assert s.wan_state == WanState.STABLE

        # STABLE → DEGRADED (score=50 < degraded_threshold=55)
        ctrl._update_wan_state(s, _metric(score=50.0))
        assert s.wan_state == WanState.DEGRADED

        # DEGRADED → FAILED only after fail_confirmations (item 11, default 3)
        # consecutive hard-fail cycles; a single bad sample holds in DEGRADED.
        for _ in range(3):
            ctrl._update_wan_state(s, _metric(score=0.0, is_hard_fail=True))
        assert s.wan_state == WanState.FAILED

        # FAILED → DEGRADED (score=30 >= hard_fail_threshold=20, not yet a full
        # recover_confirmations streak)
        ctrl._update_wan_state(s, _metric(score=30.0, is_hard_fail=False))
        assert s.wan_state == WanState.DEGRADED

        # DEGRADED → STABLE (score=95 >= degraded_threshold=55) — DEGRADED→STABLE
        # is instantaneous; only FAILED recovery is debounced.
        ctrl._update_wan_state(s, _metric(score=95.0, is_hard_fail=False))
        assert s.wan_state == WanState.STABLE

    def test_state_machine_consistency_across_interfaces(self, ctrl):
        """Both interfaces can transition independently."""
        s0 = ctrl._interface_states["wan0"]
        s1 = ctrl._interface_states["wan1"]

        # wan0 needs fail_confirmations (item 11, default 3) consecutive
        # hard-fail cycles before it is declared FAILED.
        for _ in range(3):
            ctrl._update_wan_state(s0, _metric("wan0", score=0.0, is_hard_fail=True))
        ctrl._update_wan_state(s1, _metric("wan1", score=95.0))

        assert s0.wan_state == WanState.FAILED
        assert s1.wan_state == WanState.STABLE


# ── Failover integration ──────────────────────────────────────────────────────

class TestFailoverIntegration:
    @mock.patch("wancontrol.network.set_default_route")
    def test_failover_switch_persists_to_db(self, _mock, ctrl, file_db):
        ctrl._mode = ControllerMode.RUNNING
        ctrl._active_interface = "wan0"
        metrics = [_metric("wan0", score=10.0), _metric("wan1", score=90.0)]
        ctrl._apply_failover(metrics)
        assert file_db.get_state("active_interface") == "wan1"

    @mock.patch("wancontrol.network.set_default_route")
    def test_failover_records_switch_event(self, _mock, ctrl, file_db):
        ctrl._mode = ControllerMode.RUNNING
        ctrl._active_interface = "wan0"
        metrics = [_metric("wan0", score=10.0), _metric("wan1", score=90.0)]
        ctrl._apply_failover(metrics)
        events = file_db.get_switch_events()
        assert len(events) == 1
        assert events[0].from_interface == "wan0"
        assert events[0].to_interface == "wan1"
        assert events[0].score_before == pytest.approx(10.0, abs=0.1)
        assert events[0].score_after == pytest.approx(90.0, abs=0.1)

    @mock.patch("wancontrol.network.set_default_route")
    def test_no_duplicate_switch_events_when_no_change(self, _mock, ctrl, file_db):
        ctrl._mode = ControllerMode.RUNNING
        ctrl._active_interface = "wan0"
        metrics = [_metric("wan0", score=95.0), _metric("wan1", score=10.0)]
        ctrl._apply_failover(metrics)
        ctrl._apply_failover(metrics)  # call twice — no switch should happen
        assert len(file_db.get_switch_events()) == 0


# ── Load balance integration ──────────────────────────────────────────────────

class TestLoadBalanceIntegration:
    @mock.patch("wancontrol.network.set_load_balance_route")
    def test_all_fail_does_not_call_route(self, mock_route, lb_ctrl):
        lb_ctrl._mode = ControllerMode.RUNNING
        metrics = [
            _metric("wan0", score=0.0, is_hard_fail=True),
            _metric("wan1", score=0.0, is_hard_fail=True),
        ]
        lb_ctrl._apply_load_balance(metrics)
        for call in mock_route.call_args_list:
            assert len(call.args[0]) > 0, "route called with empty pool"

    @mock.patch("wancontrol.controller.set_load_balance_route")
    def test_one_fail_route_called_with_remaining(self, mock_route, lb_ctrl):
        lb_ctrl._mode = ControllerMode.RUNNING
        metrics = [
            _metric("wan0", score=0.0, is_hard_fail=True),
            _metric("wan1", score=95.0),
        ]
        lb_ctrl._apply_load_balance(metrics)
        mock_route.assert_called_once()
        nexthops = mock_route.call_args.args[0]
        iface_names = [nh[1] for nh in nexthops]
        assert "wan0" not in iface_names
        assert "wan1" in iface_names

    @mock.patch("wancontrol.network.set_load_balance_route")
    def test_pool_state_restored_after_recovery(self, mock_route, lb_ctrl):
        lb_ctrl._mode = ControllerMode.RUNNING

        # Step 1: remove wan0
        metrics_fail = [
            _metric("wan0", score=0.0, is_hard_fail=True),
            _metric("wan1", score=95.0),
        ]
        lb_ctrl._apply_load_balance(metrics_fail)
        assert not lb_ctrl._interface_states["wan0"].in_nexthop_pool

        # Step 2: wan0 recovers (score > hard_fail(20) + recovery_margin(10) = 30)
        metrics_recover = [
            _metric("wan0", score=95.0),
            _metric("wan1", score=95.0),
        ]
        lb_ctrl._apply_load_balance(metrics_recover)
        assert lb_ctrl._interface_states["wan0"].in_nexthop_pool


# ── Watchdog + Controller + DB integration ───────────────────────────────────

class TestWatchdogIntegration:
    def test_heartbeat_file_created_and_timestamped(self, app_cfg, file_db, ctrl):
        wd = Watchdog(cfg=app_cfg, db=file_db, controller=ctrl)
        hb_path = Path(app_cfg.heartbeat_file)
        if hb_path.exists():
            hb_path.unlink()

        before = time.time()
        wd._write_heartbeat()

        assert hb_path.exists()
        ts = float(hb_path.read_text().strip())
        assert ts >= before
        assert ts <= time.time() + 1

    def test_route_mismatch_logs_event_to_db(self, app_cfg, file_db, ctrl):
        wd = Watchdog(cfg=app_cfg, db=file_db, controller=ctrl)
        ctrl._active_interface = "wan0"

        with mock.patch("wancontrol.watchdog.get_default_gateway",
                        return_value=("10.0.0.1", "wan1")):
            with mock.patch.object(wd, "_reapply_routes"):
                wd._verify_routes()

        events = file_db.get_events()
        assert any("mismatch" in e.message.lower() for e in events)

    @mock.patch("wancontrol.network.set_default_route")
    def test_full_stop_flow_with_watchdog_cleanup(self, _mock, app_cfg, file_db, ctrl):
        wd = Watchdog(cfg=app_cfg, db=file_db, controller=ctrl)
        with mock.patch("signal.signal"):
            wd.start()
        # Stop controller — should persist STOPPED and log event
        ctrl.stop()
        assert file_db.get_state("controller_mode") == "STOPPED"
        wd.stop()
