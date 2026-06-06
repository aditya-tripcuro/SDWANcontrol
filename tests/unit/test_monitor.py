"""
tests/unit/test_monitor.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for wancontrol.monitor module.

Mocks all network calls to avoid real network access.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch, MagicMock

import pytest

from wancontrol.config import ProbeConfig, ScoringConfig, InterfaceConfig
from wancontrol.database import Database
from wancontrol.monitor import Monitor, ProbeResult, InterfaceMetric


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def probe_cfg() -> ProbeConfig:
    return ProbeConfig(
        interval_sec=1,
        dns_targets=["8.8.8.8", "1.1.1.1"],
        icmp_targets=["8.8.8.8", "1.1.1.1"],
        http_targets=["http://example.com", "http://test.com"],
        icmp_count=3,
        icmp_timeout_sec=2,
        dns_timeout_sec=2,
        http_timeout_sec=3,
    )


@pytest.fixture
def scoring_cfg() -> ScoringConfig:
    return ScoringConfig(
        latency_penalty_per_ms=0.3,
        loss_penalty_per_percent=2.0,
        dns_fail_penalty=15.0,
        http_fail_penalty=20.0,
        hard_fail_threshold=20.0,
        hysteresis_switch_to_backup=25.0,
        hysteresis_return_to_primary=10.0,
        recovery_margin=10.0,
    )


@pytest.fixture
def monitor(probe_cfg: ProbeConfig, scoring_cfg: ScoringConfig) -> Monitor:
    db = Database(":memory:")
    db.initialize()
    return Monitor(probe_cfg=probe_cfg, scoring_cfg=scoring_cfg, db=db)


@pytest.fixture
def iface() -> InterfaceConfig:
    return InterfaceConfig(
        name="wan0",
        label="Test WAN",
        expected_speed_mbps=100,
        gateway="192.168.1.1",
        routing_table_id=100,
    )


# ── SCORING tests ─────────────────────────────────────────────────────────────

class TestScoring:
    """Tests for the score() method."""

    def test_perfect_probes_score_100(self, monitor: Monitor):
        """Perfect probes (0ms latency, 0% loss, dns_ok, http_ok) → score=100.0"""
        probe = ProbeResult(
            interface="wan0",
            timestamp=time.time(),
            icmp_avg_latency_ms=0.0,
            icmp_jitter_ms=0.0,
            icmp_loss_pct=0.0,
            icmp_targets_tried=2,
            icmp_targets_ok=2,
            dns_success_count=2,
            dns_total_count=2,
            dns_ok=True,
            http_success_count=2,
            http_total_count=2,
            http_ok=True,
            http_avg_response_ms=50.0,
        )
        metric = monitor.score(probe)
        assert metric.score == 100.0
        assert metric.is_hard_fail is False

    def test_latency_penalty(self, monitor: Monitor):
        """Latency penalty: 10ms latency → score = 100 - (10 * 0.3) = 97.0"""
        probe = ProbeResult(
            interface="wan0",
            timestamp=time.time(),
            icmp_avg_latency_ms=10.0,
            icmp_jitter_ms=0.0,
            icmp_loss_pct=0.0,
            icmp_targets_tried=2,
            icmp_targets_ok=2,
            dns_success_count=2,
            dns_total_count=2,
            dns_ok=True,
            http_success_count=2,
            http_total_count=2,
            http_ok=True,
            http_avg_response_ms=50.0,
        )
        metric = monitor.score(probe)
        assert metric.score == 97.0
        assert metric.is_hard_fail is False

    def test_loss_penalty(self, monitor: Monitor):
        """Loss penalty: 50% loss → score = 100 - (50 * 2.0) = 0.0"""
        probe = ProbeResult(
            interface="wan0",
            timestamp=time.time(),
            icmp_avg_latency_ms=0.0,
            icmp_jitter_ms=0.0,
            icmp_loss_pct=50.0,
            icmp_targets_tried=2,
            icmp_targets_ok=1,
            dns_success_count=2,
            dns_total_count=2,
            dns_ok=True,
            http_success_count=2,
            http_total_count=2,
            http_ok=True,
            http_avg_response_ms=50.0,
        )
        metric = monitor.score(probe)
        assert metric.score == 0.0
        assert metric.is_hard_fail is True

    def test_dns_fail_penalty(self, monitor: Monitor):
        """DNS fail penalty: score -= 15"""
        probe = ProbeResult(
            interface="wan0",
            timestamp=time.time(),
            icmp_avg_latency_ms=0.0,
            icmp_jitter_ms=0.0,
            icmp_loss_pct=0.0,
            icmp_targets_tried=2,
            icmp_targets_ok=2,
            dns_success_count=0,
            dns_total_count=2,
            dns_ok=False,
            http_success_count=2,
            http_total_count=2,
            http_ok=True,
            http_avg_response_ms=50.0,
        )
        metric = monitor.score(probe)
        assert metric.score == 85.0
        assert metric.is_hard_fail is False

    def test_http_fail_penalty(self, monitor: Monitor):
        """HTTP fail penalty: score -= 20"""
        probe = ProbeResult(
            interface="wan0",
            timestamp=time.time(),
            icmp_avg_latency_ms=0.0,
            icmp_jitter_ms=0.0,
            icmp_loss_pct=0.0,
            icmp_targets_tried=2,
            icmp_targets_ok=2,
            dns_success_count=2,
            dns_total_count=2,
            dns_ok=True,
            http_success_count=0,
            http_total_count=2,
            http_ok=False,
            http_avg_response_ms=0.0,
        )
        metric = monitor.score(probe)
        assert metric.score == 80.0
        assert metric.is_hard_fail is False

    def test_all_failures_combined(self, monitor: Monitor):
        """All failures combined → correct combined score"""
        # 10ms latency, 50% loss, dns fail, http fail
        # score = 100 - (10 * 0.3) - (50 * 2.0) - 15 - 20
        # score = 100 - 3 - 100 - 15 - 20 = -38
        probe = ProbeResult(
            interface="wan0",
            timestamp=time.time(),
            icmp_avg_latency_ms=10.0,
            icmp_jitter_ms=0.0,
            icmp_loss_pct=50.0,
            icmp_targets_tried=2,
            icmp_targets_ok=1,
            dns_success_count=0,
            dns_total_count=2,
            dns_ok=False,
            http_success_count=0,
            http_total_count=2,
            http_ok=False,
            http_avg_response_ms=0.0,
        )
        metric = monitor.score(probe)
        assert metric.score == -38.0
        assert metric.is_hard_fail is True

    def test_score_can_go_below_zero(self, monitor: Monitor):
        """Score can go below zero (not clamped)"""
        probe = ProbeResult(
            interface="wan0",
            timestamp=time.time(),
            icmp_avg_latency_ms=100.0,
            icmp_jitter_ms=0.0,
            icmp_loss_pct=100.0,
            icmp_targets_tried=2,
            icmp_targets_ok=0,
            dns_success_count=0,
            dns_total_count=2,
            dns_ok=False,
            http_success_count=0,
            http_total_count=2,
            http_ok=False,
            http_avg_response_ms=0.0,
        )
        metric = monitor.score(probe)
        # score = 100 - (100 * 0.3) - (100 * 2.0) - 15 - 20 = 100 - 30 - 200 - 15 - 20 = -165
        assert metric.score == -165.0

    def test_is_hard_fail_true_when_below_threshold(self, monitor: Monitor):
        """is_hard_fail=True when score < hard_fail_threshold (20.0)"""
        probe = ProbeResult(
            interface="wan0",
            timestamp=time.time(),
            icmp_avg_latency_ms=0.0,
            icmp_jitter_ms=0.0,
            icmp_loss_pct=45.0,  # 100 - 90 = 10, which is < 20
            icmp_targets_tried=2,
            icmp_targets_ok=1,
            dns_success_count=2,
            dns_total_count=2,
            dns_ok=True,
            http_success_count=2,
            http_total_count=2,
            http_ok=True,
            http_avg_response_ms=50.0,
        )
        metric = monitor.score(probe)
        assert metric.score == 10.0
        assert metric.is_hard_fail is True

    def test_is_hard_fail_false_when_at_or_above_threshold(self, monitor: Monitor):
        """is_hard_fail=False when score >= hard_fail_threshold"""
        probe = ProbeResult(
            interface="wan0",
            timestamp=time.time(),
            icmp_avg_latency_ms=0.0,
            icmp_jitter_ms=0.0,
            icmp_loss_pct=40.0,  # 100 - 80 = 20, which is >= 20
            icmp_targets_tried=2,
            icmp_targets_ok=1,
            dns_success_count=2,
            dns_total_count=2,
            dns_ok=True,
            http_success_count=2,
            http_total_count=2,
            http_ok=True,
            http_avg_response_ms=50.0,
        )
        metric = monitor.score(probe)
        assert metric.score == 20.0
        assert metric.is_hard_fail is False


# ── ICMP PROBE AGGREGATION tests ──────────────────────────────────────────────

class TestIcmpProbeAggregation:
    """Tests for _run_icmp_probes()."""

    def test_all_targets_ok(self, monitor: Monitor, iface: InterfaceConfig):
        """All targets ok: averages latency and jitter correctly"""
        with patch("wancontrol.monitor.probe_icmp") as mock_probe:
            mock_probe.side_effect = [
                (10.0, 1.0, 0.0),  # target 1
                (20.0, 2.0, 0.0),  # target 2
            ]
            result = monitor._run_icmp_probes(iface, "192.168.1.100")
            # avg latency = (10 + 20) / 2 = 15.0
            # avg jitter = (1 + 2) / 2 = 1.5
            # avg loss = 0.0
            assert result[0] == 15.0  # avg_latency
            assert result[1] == 1.5   # avg_jitter
            assert result[2] == 0.0   # avg_loss
            assert result[3] == 2     # targets_tried
            assert result[4] == 2     # targets_ok

    def test_one_target_fails(self, monitor: Monitor, iface: InterfaceConfig):
        """One target fails (loss=100): latency/jitter use ok target only, but
        loss is averaged across ALL targets (item 15) so a partial outage shows."""
        with patch("wancontrol.monitor.probe_icmp") as mock_probe:
            mock_probe.side_effect = [
                (10.0, 1.0, 0.0),    # target 1 ok
                (0.0, 0.0, 100.0),   # target 2 failed
            ]
            result = monitor._run_icmp_probes(iface, "192.168.1.100")
            assert result[0] == 10.0  # avg_latency (only ok target — can't measure a dead one)
            assert result[1] == 1.0   # avg_jitter (only ok target)
            assert result[2] == 50.0  # avg_loss across ALL targets: (0 + 100) / 2
            assert result[3] == 2     # targets_tried
            assert result[4] == 1     # targets_ok

    def test_all_targets_fail(self, monitor: Monitor, iface: InterfaceConfig):
        """All targets fail: returns (0.0, 0.0, 100.0, N, 0)"""
        with patch("wancontrol.monitor.probe_icmp") as mock_probe:
            mock_probe.side_effect = [
                (0.0, 0.0, 100.0),
                (0.0, 0.0, 100.0),
            ]
            result = monitor._run_icmp_probes(iface, "192.168.1.100")
            assert result == (0.0, 0.0, 100.0, 2, 0)

    def test_targets_counts_correct(self, probe_cfg: ProbeConfig, scoring_cfg: ScoringConfig, iface: InterfaceConfig):
        """targets_tried and targets_ok counts are correct"""
        # Create a new monitor with 3 ICMP targets using replace() for frozen dataclass
        probe_cfg_3 = replace(probe_cfg, icmp_targets=["8.8.8.8", "1.1.1.1", "4.4.4.4"])
        db = Database(":memory:")
        db.initialize()
        monitor = Monitor(probe_cfg=probe_cfg_3, scoring_cfg=scoring_cfg, db=db)
        
        with patch("wancontrol.monitor.probe_icmp") as mock_probe:
            mock_probe.side_effect = [
                (10.0, 1.0, 0.0),    # ok
                (20.0, 2.0, 50.0),   # ok (loss < 100)
                (0.0, 0.0, 100.0),   # failed
            ]
            result = monitor._run_icmp_probes(iface, "192.168.1.100")
            assert result[3] == 3  # targets_tried
            assert result[4] == 2  # targets_ok


# ── DNS PROBE AGGREGATION tests ───────────────────────────────────────────────

class TestDnsProbeAggregation:
    """Tests for _run_dns_probes()."""

    def test_all_targets_succeed(self, monitor: Monitor, iface: InterfaceConfig):
        """All targets succeed: dns_ok=True, success_count=total"""
        with patch("wancontrol.monitor.probe_dns") as mock_probe:
            mock_probe.return_value = True
            result = monitor._run_dns_probes(iface, "192.168.1.100")
            assert result == (2, 2)

    def test_one_target_succeeds(self, monitor: Monitor, iface: InterfaceConfig):
        """One target succeeds: dns_ok=True"""
        with patch("wancontrol.monitor.probe_dns") as mock_probe:
            mock_probe.side_effect = [True, False]
            result = monitor._run_dns_probes(iface, "192.168.1.100")
            assert result == (1, 2)

    def test_all_targets_fail(self, monitor: Monitor, iface: InterfaceConfig):
        """All targets fail: dns_ok=False, success_count=0"""
        with patch("wancontrol.monitor.probe_dns") as mock_probe:
            mock_probe.return_value = False
            result = monitor._run_dns_probes(iface, "192.168.1.100")
            assert result == (0, 2)

    def test_no_interface_ip_skips_probes(self, monitor: Monitor, iface: InterfaceConfig):
        """No interface IP: DNS probes skipped, returns (0, total_count)"""
        with patch("wancontrol.monitor.probe_dns") as mock_probe:
            result = monitor._run_dns_probes(iface, None)
            assert result == (0, 2)
            mock_probe.assert_not_called()


# ── HTTP PROBE AGGREGATION tests ──────────────────────────────────────────────

class TestHttpProbeAggregation:
    """Tests for _run_http_probes()."""

    def test_all_targets_succeed(self, monitor: Monitor, iface: InterfaceConfig):
        """All targets succeed: http_ok=True, avg_response_ms correct"""
        with patch("wancontrol.monitor.probe_http") as mock_probe:
            mock_probe.side_effect = [
                (True, 50.0),
                (True, 100.0),
            ]
            result = monitor._run_http_probes(iface)
            assert result[0] == 2  # success_count
            assert result[1] == 2  # total_count
            assert result[2] == 75.0  # avg_response_ms = (50 + 100) / 2

    def test_one_target_fails(self, monitor: Monitor, iface: InterfaceConfig):
        """One target fails: http_ok=True if any succeed"""
        with patch("wancontrol.monitor.probe_http") as mock_probe:
            mock_probe.side_effect = [
                (True, 50.0),
                (False, 0.0),
            ]
            result = monitor._run_http_probes(iface)
            assert result[0] == 1  # success_count
            assert result[1] == 2  # total_count
            assert result[2] == 50.0  # avg_response_ms

    def test_all_targets_fail(self, monitor: Monitor, iface: InterfaceConfig):
        """All targets fail: http_ok=False, avg_response_ms=0.0"""
        with patch("wancontrol.monitor.probe_http") as mock_probe:
            mock_probe.return_value = (False, 0.0)
            result = monitor._run_http_probes(iface)
            assert result == (0, 2, 0.0)


# ── collect_one() tests ───────────────────────────────────────────────────────

class TestCollectOne:
    """Tests for collect_one() method."""

    def test_returns_probe_result_with_correct_interface_name(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Returns ProbeResult with correct interface name"""
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            result = monitor.collect_one(iface)

            assert result.interface == "wan0"

    def test_calls_probe_icmp_for_each_icmp_target(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Calls probe_icmp for each icmp_target"""
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            monitor.collect_one(iface)

            assert mock_icmp.call_count == 2  # 2 icmp_targets

    def test_calls_probe_dns_for_each_dns_target(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Calls probe_dns for each dns_target"""
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            monitor.collect_one(iface)

            assert mock_dns.call_count == 2  # 2 dns_targets

    def test_calls_probe_http_for_each_http_target(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Calls probe_http for each http_target"""
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            monitor.collect_one(iface)

            assert mock_http.call_count == 2  # 2 http_targets

    def test_iface_ip_none_skips_dns_probes(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """iface_ip=None (get_interface_ip returns None): DNS probes skipped, dns_ok=False"""
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = None

            result = monitor.collect_one(iface)

            mock_dns.assert_not_called()
            assert result.dns_ok is False
            assert result.dns_success_count == 0
            assert result.dns_total_count == 2

    def test_all_probe_futures_complete_within_timeout(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """All probe futures complete within timeout"""
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            start = time.time()
            result = monitor.collect_one(iface)
            elapsed = time.time() - start

            assert elapsed < 5.0  # Should complete quickly
            assert isinstance(result, ProbeResult)


# ── collect() tests ───────────────────────────────────────────────────────────

class TestCollect:
    """Tests for collect() method."""

    def test_returns_one_metric_per_interface(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Returns one InterfaceMetric per interface"""
        iface2 = InterfaceConfig(
            name="wan1",
            label="Backup WAN",
            expected_speed_mbps=50,
            gateway="10.0.0.1",
            routing_table_id=101,
        )
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            metrics = monitor.collect([iface, iface2], timeout_sec=8)

            assert len(metrics) == 2
            assert {m.interface for m in metrics} == {"wan0", "wan1"}

    def test_inserts_metric_into_db(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Inserts metric into DB (verify via db.get_latest_metric)"""
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            monitor.collect([iface], timeout_sec=8)

            latest = monitor._db.get_latest_metric("wan0")
            assert latest is not None
            assert latest.interface == "wan0"

    def test_metrics_for_both_interfaces_present(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Metrics for both interfaces present after collect([wan0, wan1])"""
        iface2 = InterfaceConfig(
            name="wan1",
            label="Backup WAN",
            expected_speed_mbps=50,
            gateway="10.0.0.1",
            routing_table_id=101,
        )
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            monitor.collect([iface, iface2], timeout_sec=8)

            metric0 = monitor._db.get_latest_metric("wan0")
            metric1 = monitor._db.get_latest_metric("wan1")
            assert metric0 is not None
            assert metric1 is not None

    def test_metric_score_matches_expected_calculation(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Metric.score matches expected calculation"""
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            metrics = monitor.collect([iface], timeout_sec=8)

            # score = 100 - (10 * 0.3) - 0 - 0 - 0 = 97.0
            assert metrics[0].score == 97.0

    def test_metric_is_hard_fail_set_correctly(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Metric.is_hard_fail set correctly"""
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            metrics = monitor.collect([iface], timeout_sec=8)

            assert metrics[0].is_hard_fail is False


# ── FAILURE HANDLING tests ────────────────────────────────────────────────────

class TestFailureHandling:
    """Tests for failure handling in collect()."""

    def test_interface_future_timeout_returns_fail_metric(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Interface future timeout → make_fail_metric() returned for that interface"""
        iface2 = InterfaceConfig(
            name="wan1",
            label="Backup WAN",
            expected_speed_mbps=50,
            gateway="10.0.0.1",
            routing_table_id=101,
        )

        def slow_collect_one(_iface):
            time.sleep(10)  # Will timeout
            return ProbeResult(
                interface=_iface.name,
                timestamp=time.time(),
                icmp_avg_latency_ms=0.0,
                icmp_jitter_ms=0.0,
                icmp_loss_pct=0.0,
                icmp_targets_tried=0,
                icmp_targets_ok=0,
                dns_success_count=0,
                dns_total_count=0,
                dns_ok=False,
                http_success_count=0,
                http_total_count=0,
                http_ok=False,
                http_avg_response_ms=0.0,
            )

        with patch.object(monitor, "collect_one", side_effect=slow_collect_one):
            metrics = monitor.collect([iface, iface2], timeout_sec=1)

            # Both should be fail metrics due to timeout
            assert len(metrics) == 2
            for m in metrics:
                assert m.is_hard_fail is True
                assert m.score == 0.0

    def test_interface_future_exception_returns_fail_metric(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Interface future exception → make_fail_metric() returned, ERROR logged"""
        iface2 = InterfaceConfig(
            name="wan1",
            label="Backup WAN",
            expected_speed_mbps=50,
            gateway="10.0.0.1",
            routing_table_id=101,
        )

        def raise_exception(_iface):
            raise RuntimeError("Simulated probe failure")

        with patch.object(monitor, "collect_one", side_effect=raise_exception):
            metrics = monitor.collect([iface, iface2], timeout_sec=8)

            # Both should be fail metrics due to exception
            assert len(metrics) == 2
            for m in metrics:
                assert m.is_hard_fail is True
                assert m.score == 0.0

    def test_one_interface_failure_does_not_abort_other(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """One interface failure does not abort the other interface"""
        iface2 = InterfaceConfig(
            name="wan1",
            label="Backup WAN",
            expected_speed_mbps=50,
            gateway="10.0.0.1",
            routing_table_id=101,
        )

        def selective_failure(_iface):
            if _iface.name == "wan0":
                raise RuntimeError("wan0 failure")
            return ProbeResult(
                interface=_iface.name,
                timestamp=time.time(),
                icmp_avg_latency_ms=0.0,
                icmp_jitter_ms=0.0,
                icmp_loss_pct=0.0,
                icmp_targets_tried=2,
                icmp_targets_ok=2,
                dns_success_count=2,
                dns_total_count=2,
                dns_ok=True,
                http_success_count=2,
                http_total_count=2,
                http_ok=True,
                http_avg_response_ms=50.0,
            )

        with patch.object(monitor, "collect_one", side_effect=selective_failure):
            metrics = monitor.collect([iface, iface2], timeout_sec=8)

            assert len(metrics) == 2
            wan0_metric = next(m for m in metrics if m.interface == "wan0")
            wan1_metric = next(m for m in metrics if m.interface == "wan1")
            assert wan0_metric.is_hard_fail is True
            assert wan1_metric.is_hard_fail is False
            assert wan1_metric.score == 100.0

    def test_make_fail_metric_returns_hard_failure(self, monitor: Monitor):
        """make_fail_metric() returns score=0.0, is_hard_fail=True, 100% loss"""
        metric = monitor.make_fail_metric("wan0")
        assert metric.score == 0.0
        assert metric.is_hard_fail is True
        assert metric.latency_ms == 0.0
        assert metric.jitter_ms == 0.0
        assert metric.loss_pct == 100.0
        assert metric.dns_ok is False
        assert metric.http_ok is False

    def test_make_fail_metric_inserts_into_db(self, monitor: Monitor):
        """make_fail_metric() inserts fail metric into DB"""
        metric = monitor.make_fail_metric("wan0")
        monitor._db.insert_metric(
            interface=metric.interface,
            latency_ms=metric.latency_ms,
            jitter_ms=metric.jitter_ms,
            loss_pct=metric.loss_pct,
            dns_ok=metric.dns_ok,
            http_ok=metric.http_ok,
            score=metric.score,
            timestamp=metric.timestamp,
        )
        latest = monitor._db.get_latest_metric("wan0")
        assert latest is not None
        assert latest.score == 0.0


# ── DB PERSISTENCE tests ──────────────────────────────────────────────────────

class TestDbPersistence:
    """Tests for database persistence."""

    def test_collect_calls_insert_metric_for_each_interface(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """collect() calls db.insert_metric() for each interface"""
        iface2 = InterfaceConfig(
            name="wan1",
            label="Backup WAN",
            expected_speed_mbps=50,
            gateway="10.0.0.1",
            routing_table_id=101,
        )
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            monitor.collect([iface, iface2], timeout_sec=8)

            metric0 = monitor._db.get_latest_metric("wan0")
            metric1 = monitor._db.get_latest_metric("wan1")
            assert metric0 is not None
            assert metric1 is not None

    def test_failed_interface_metric_persisted(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Failed interface metric is also persisted"""

        def raise_on_wan0(_iface):
            if _iface.name == "wan0":
                raise RuntimeError("failure")
            return ProbeResult(
                interface=_iface.name,
                timestamp=time.time(),
                icmp_avg_latency_ms=0.0,
                icmp_jitter_ms=0.0,
                icmp_loss_pct=0.0,
                icmp_targets_tried=2,
                icmp_targets_ok=2,
                dns_success_count=2,
                dns_total_count=2,
                dns_ok=True,
                http_success_count=2,
                http_total_count=2,
                http_ok=True,
                http_avg_response_ms=50.0,
            )

        iface2 = InterfaceConfig(
            name="wan1",
            label="Backup WAN",
            expected_speed_mbps=50,
            gateway="10.0.0.1",
            routing_table_id=101,
        )

        with patch.object(monitor, "collect_one", side_effect=raise_on_wan0):
            monitor.collect([iface, iface2], timeout_sec=8)

            metric0 = monitor._db.get_latest_metric("wan0")
            metric1 = monitor._db.get_latest_metric("wan1")
            assert metric0 is not None
            assert metric0.score == 0.0
            assert metric1 is not None
            assert metric1.score == 100.0

    def test_timestamp_on_metric_matches_probe_result(
        self, monitor: Monitor, iface: InterfaceConfig
    ):
        """Timestamp on metric matches ProbeResult timestamp"""
        with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
             patch("wancontrol.monitor.probe_dns") as mock_dns, \
             patch("wancontrol.monitor.probe_http") as mock_http, \
             patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
            mock_icmp.return_value = (10.0, 1.0, 0.0)
            mock_dns.return_value = True
            mock_http.return_value = (True, 50.0)
            mock_get_ip.return_value = "192.168.1.100"

            before = time.time()
            metrics = monitor.collect([iface], timeout_sec=8)
            after = time.time()

            assert before <= metrics[0].timestamp <= after


# ── THREAD SAFETY tests ───────────────────────────────────────────────────────

class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_collect_calls(self, probe_cfg: ProbeConfig, scoring_cfg: ScoringConfig, iface: InterfaceConfig):
        """collect([wan0, wan1]) called 5 times concurrently — no deadlock, no exception"""
        iface2 = InterfaceConfig(
            name="wan1",
            label="Backup WAN",
            expected_speed_mbps=50,
            gateway="10.0.0.1",
            routing_table_id=101,
        )
        results: list[list[InterfaceMetric]] = []
        errors: list[Exception] = []

        def run_collect():
            try:
                # Each thread gets its own database instance
                db = Database(":memory:")
                db.initialize()
                monitor = Monitor(probe_cfg=probe_cfg, scoring_cfg=scoring_cfg, db=db)
                
                with patch("wancontrol.monitor.probe_icmp") as mock_icmp, \
                     patch("wancontrol.monitor.probe_dns") as mock_dns, \
                     patch("wancontrol.monitor.probe_http") as mock_http, \
                     patch("wancontrol.monitor.get_interface_ip") as mock_get_ip:
                    mock_icmp.return_value = (10.0, 1.0, 0.0)
                    mock_dns.return_value = True
                    mock_http.return_value = (True, 50.0)
                    mock_get_ip.return_value = "192.168.1.100"

                    metrics = monitor.collect([iface, iface2], timeout_sec=8)
                    results.append(metrics)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=run_collect) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 5
        for r in results:
            assert len(r) == 2
            assert {m.interface for m in r} == {"wan0", "wan1"}
