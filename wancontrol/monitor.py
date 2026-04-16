"""
wancontrol/monitor.py
~~~~~~~~~~~~~~~~~~~~~
Parallel probe engine for WANControl v2.

The monitor runs as a called function from the controller loop (Phase 5).
It does not run its own thread or loop — it is called, does work, returns.
Threading is used internally for parallelism within a single call.
"""

from __future__ import annotations

import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, CancelledError
from dataclasses import dataclass
from typing import TYPE_CHECKING

from wancontrol.network import probe_icmp, probe_dns, probe_http, get_interface_ip

if TYPE_CHECKING:
    from wancontrol.config import InterfaceConfig, ProbeConfig, ScoringConfig
    from wancontrol.database import Database


logger = logging.getLogger(__name__)


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class ProbeResult:
    """Raw probe results for one interface from one collection cycle."""
    interface: str
    timestamp: float

    # ICMP
    icmp_avg_latency_ms: float    # 0.0 if all probes failed
    icmp_jitter_ms: float         # 0.0 if all probes failed
    icmp_loss_pct: float          # 100.0 if all probes failed
    icmp_targets_tried: int
    icmp_targets_ok: int

    # DNS
    dns_success_count: int
    dns_total_count: int
    dns_ok: bool                  # True if at least one DNS target resolved

    # HTTP
    http_success_count: int
    http_total_count: int
    http_ok: bool                 # True if at least one HTTP target succeeded
    http_avg_response_ms: float   # average of successful responses, 0.0 if none


@dataclass
class InterfaceMetric:
    """
    Scored metric for one interface. Ready to insert into the database.
    Derived from ProbeResult + ScoringConfig.
    """
    interface: str
    timestamp: float
    latency_ms: float
    jitter_ms: float
    loss_pct: float
    dns_ok: bool
    http_ok: bool
    score: float
    is_hard_fail: bool            # score < hard_fail_threshold


# ── Monitor class ──────────────────────────────────────────────────────────────

class Monitor:
    """
    Parallel probe engine for WAN interfaces.

    The Monitor class runs probes against configured targets for each interface,
    aggregates results, applies scoring, and persists metrics to the database.
    """

    def __init__(
        self,
        probe_cfg: ProbeConfig,
        scoring_cfg: ScoringConfig,
        db: Database,
    ) -> None:
        """
        Initialize the Monitor.

        Args:
            probe_cfg: Probe configuration with targets and timeouts.
            scoring_cfg: Scoring configuration with penalties and thresholds.
            db: Database instance for persisting metrics.
        """
        self._probe_cfg = probe_cfg
        self._scoring_cfg = scoring_cfg
        self._db = db

    # ── Public methods ─────────────────────────────────────────────────────

    def collect(
        self,
        interfaces: list[InterfaceConfig],
        timeout_sec: int,
    ) -> list[InterfaceMetric]:
        """
        Run all probes for all interfaces in parallel.

        Returns one InterfaceMetric per interface.
        Results are also persisted to the database via db.insert_metric().

        Parallelism model:
        - One future per interface in the outer executor
        - Each interface runs its own probes in parallel internally
        - Hard ceiling: timeout_sec enforced via Future.result(timeout=...)
        - If an interface future times out: log WARNING, return a
          hard-fail metric for that interface (all zeros, score=0.0)
        - If an interface future raises: log ERROR with traceback,
          return a hard-fail metric for that interface
        - Never let one interface failure prevent other interfaces from
          being collected

        The outer ThreadPoolExecutor max_workers = len(interfaces).

        Args:
            interfaces: List of InterfaceConfig to probe.
            timeout_sec: Maximum time to wait for all probes.

        Returns:
            List of InterfaceMetric, one per interface.
        """
        if not interfaces:
            return []

        metrics: list[InterfaceMetric] = []
        timestamp = time.time()

        with ThreadPoolExecutor(max_workers=len(interfaces)) as executor:
            future_to_iface = {
                executor.submit(self.collect_one, iface): iface
                for iface in interfaces
            }

            for future in future_to_iface:
                iface = future_to_iface[future]
                try:
                    probe_result = future.result(timeout=timeout_sec)
                    metric = self.score(probe_result)
                    self._db.insert_metric(
                        interface=metric.interface,
                        latency_ms=metric.latency_ms,
                        jitter_ms=metric.jitter_ms,
                        loss_pct=metric.loss_pct,
                        dns_ok=metric.dns_ok,
                        http_ok=metric.http_ok,
                        score=metric.score,
                        timestamp=metric.timestamp,
                    )
                    metrics.append(metric)
                except FuturesTimeoutError:
                    logger.warning(
                        "Probe timed out for interface %s",
                        iface.name,
                        extra={"component": "monitor"},
                    )
                    fail_metric = self.make_fail_metric(iface.name, timestamp)
                    self._db.insert_metric(
                        interface=fail_metric.interface,
                        latency_ms=fail_metric.latency_ms,
                        jitter_ms=fail_metric.jitter_ms,
                        loss_pct=fail_metric.loss_pct,
                        dns_ok=fail_metric.dns_ok,
                        http_ok=fail_metric.http_ok,
                        score=fail_metric.score,
                        timestamp=fail_metric.timestamp,
                    )
                    metrics.append(fail_metric)
                except CancelledError:
                    logger.warning(
                        "Probe cancelled for interface %s",
                        iface.name,
                        extra={"component": "monitor"},
                    )
                    fail_metric = self.make_fail_metric(iface.name, timestamp)
                    self._db.insert_metric(
                        interface=fail_metric.interface,
                        latency_ms=fail_metric.latency_ms,
                        jitter_ms=fail_metric.jitter_ms,
                        loss_pct=fail_metric.loss_pct,
                        dns_ok=fail_metric.dns_ok,
                        http_ok=fail_metric.http_ok,
                        score=fail_metric.score,
                        timestamp=fail_metric.timestamp,
                    )
                    metrics.append(fail_metric)
                except Exception as exc:
                    logger.error(
                        "Probe failed for interface %s: %s\\n%s",
                        iface.name,
                        exc,
                        traceback.format_exc(),
                        extra={"component": "monitor"},
                    )
                    fail_metric = self.make_fail_metric(iface.name, timestamp)
                    self._db.insert_metric(
                        interface=fail_metric.interface,
                        latency_ms=fail_metric.latency_ms,
                        jitter_ms=fail_metric.jitter_ms,
                        loss_pct=fail_metric.loss_pct,
                        dns_ok=fail_metric.dns_ok,
                        http_ok=fail_metric.http_ok,
                        score=fail_metric.score,
                        timestamp=fail_metric.timestamp,
                    )
                    metrics.append(fail_metric)

        return metrics

    def collect_one(
        self,
        iface: InterfaceConfig,
    ) -> ProbeResult:
        """
        Run all probes for a single interface.

        ICMP, DNS, and HTTP probes run in parallel internally using a
        ThreadPoolExecutor with max_workers=3.

        Each probe type aggregates results across all configured targets:
        - ICMP: probe all icmp_targets concurrently, average results
        - DNS:  probe all dns_targets concurrently, count successes
        - HTTP: probe all http_targets concurrently, count successes

        Individual probe failures are caught and counted as failures.
        No probe failure propagates as an exception.

        Args:
            iface: InterfaceConfig to probe.

        Returns:
            ProbeResult with aggregated probe data.
        """
        timestamp = time.time()
        iface_ip = get_interface_ip(iface.name)

        with ThreadPoolExecutor(max_workers=3) as executor:
            icmp_future = executor.submit(
                self._run_icmp_probes, iface, iface_ip
            )
            dns_future = executor.submit(
                self._run_dns_probes, iface, iface_ip
            )
            http_future = executor.submit(
                self._run_http_probes, iface
            )

            icmp_result = icmp_future.result()
            dns_result = dns_future.result()
            http_result = http_future.result()

        return ProbeResult(
            interface=iface.name,
            timestamp=timestamp,
            icmp_avg_latency_ms=icmp_result[0],
            icmp_jitter_ms=icmp_result[1],
            icmp_loss_pct=icmp_result[2],
            icmp_targets_tried=icmp_result[3],
            icmp_targets_ok=icmp_result[4],
            dns_success_count=dns_result[0],
            dns_total_count=dns_result[1],
            dns_ok=dns_result[0] > 0,
            http_success_count=http_result[0],
            http_total_count=http_result[1],
            http_ok=http_result[0] > 0,
            http_avg_response_ms=http_result[2],
        )

    def score(
        self,
        probe: ProbeResult,
    ) -> InterfaceMetric:
        """
        Apply scoring formula to a ProbeResult.

        Returns InterfaceMetric. Does not touch the database.

        Scoring formula:
            BASE_SCORE = 100.0
            score = BASE_SCORE
            score -= probe.icmp_avg_latency_ms * scoring.latency_penalty_per_ms
            score -= probe.icmp_loss_pct       * scoring.loss_penalty_per_percent
            score -= (0 if probe.dns_ok  else scoring.dns_fail_penalty)
            score -= (0 if probe.http_ok else scoring.http_fail_penalty)
            is_hard_fail = score < scoring.hard_fail_threshold

        Args:
            probe: ProbeResult to score.

        Returns:
            InterfaceMetric with computed score.
        """
        BASE_SCORE = 100.0
        score = BASE_SCORE
        score -= probe.icmp_avg_latency_ms * self._scoring_cfg.latency_penalty_per_ms
        score -= probe.icmp_loss_pct * self._scoring_cfg.loss_penalty_per_percent
        if not probe.dns_ok:
            score -= self._scoring_cfg.dns_fail_penalty
        if not probe.http_ok:
            score -= self._scoring_cfg.http_fail_penalty

        is_hard_fail = score < self._scoring_cfg.hard_fail_threshold

        return InterfaceMetric(
            interface=probe.interface,
            timestamp=probe.timestamp,
            latency_ms=probe.icmp_avg_latency_ms,
            jitter_ms=probe.icmp_jitter_ms,
            loss_pct=probe.icmp_loss_pct,
            dns_ok=probe.dns_ok,
            http_ok=probe.http_ok,
            score=score,
            is_hard_fail=is_hard_fail,
        )

    def make_fail_metric(
        self,
        interface: str,
        timestamp: float | None = None,
    ) -> InterfaceMetric:
        """
        Return a hard-fail InterfaceMetric with all zeros.

        Used when an interface probe times out or raises.
        score=0.0, is_hard_fail=True.

        Args:
            interface: Name of the interface.
            timestamp: Optional timestamp; uses current time if not provided.

        Returns:
            InterfaceMetric representing a hard failure.
        """
        ts = timestamp if timestamp is not None else time.time()
        return InterfaceMetric(
            interface=interface,
            timestamp=ts,
            latency_ms=0.0,
            jitter_ms=0.0,
            loss_pct=0.0,
            dns_ok=False,
            http_ok=False,
            score=0.0,
            is_hard_fail=True,
        )

    # ── Private probe aggregation methods ──────────────────────────────────

    def _run_icmp_probes(
        self,
        iface: InterfaceConfig,
        iface_ip: str,
    ) -> tuple[float, float, float, int, int]:
        """
        Run probe_icmp() for each icmp_target sequentially.

        Returns (avg_latency_ms, avg_jitter_ms, avg_loss_pct,
                 targets_tried, targets_ok).
        A target is "ok" if loss_pct < 100.0.
        Average latency/jitter computed only over ok targets.
        If all targets fail: return (0.0, 0.0, 100.0, N, 0).

        Args:
            iface: InterfaceConfig containing interface name.
            iface_ip: IP address of the interface (unused for ICMP).

        Returns:
            Tuple of (avg_latency_ms, avg_jitter_ms, avg_loss_pct,
                      targets_tried, targets_ok).
        """
        targets_tried = len(self._probe_cfg.icmp_targets)
        if targets_tried == 0:
            return (0.0, 0.0, 100.0, 0, 0)

        latencies: list[float] = []
        jitters: list[float] = []
        losses: list[float] = []
        targets_ok = 0

        for target in self._probe_cfg.icmp_targets:
            try:
                avg_lat, jitter, loss = probe_icmp(
                    interface=iface.name,
                    target=target,
                    count=self._probe_cfg.icmp_count,
                    timeout_sec=self._probe_cfg.icmp_timeout_sec,
                )
                latencies.append(avg_lat)
                jitters.append(jitter)
                losses.append(loss)
                if loss < 100.0:
                    targets_ok += 1
            except Exception:
                # Probe failed completely
                losses.append(100.0)
                latencies.append(0.0)
                jitters.append(0.0)

        if targets_ok == 0:
            return (0.0, 0.0, 100.0, targets_tried, 0)

        # Compute averages only over OK targets
        ok_latencies = [
            lat for lat, loss in zip(latencies, losses) if loss < 100.0
        ]
        ok_jitters = [
            jit for jit, loss in zip(jitters, losses) if loss < 100.0
        ]
        ok_losses = [loss for loss in losses if loss < 100.0]

        avg_latency = sum(ok_latencies) / len(ok_latencies) if ok_latencies else 0.0
        avg_jitter = sum(ok_jitters) / len(ok_jitters) if ok_jitters else 0.0
        avg_loss = sum(ok_losses) / len(ok_losses) if ok_losses else 0.0

        return (avg_latency, avg_jitter, avg_loss, targets_tried, targets_ok)

    def _run_dns_probes(
        self,
        iface: InterfaceConfig,
        iface_ip: str,
    ) -> tuple[int, int]:
        """
        Run probe_dns() for each dns_target sequentially.

        Returns (success_count, total_count).

        Args:
            iface: InterfaceConfig containing interface name.
            iface_ip: IP address of the interface for binding.

        Returns:
            Tuple of (success_count, total_count).
        """
        total_count = len(self._probe_cfg.dns_targets)
        if total_count == 0:
            return (0, 0)

        # If no interface IP, skip DNS probes
        if iface_ip is None:
            return (0, total_count)

        success_count = 0
        for target in self._probe_cfg.dns_targets:
            try:
                result = probe_dns(
                    interface=iface.name,
                    target=target,
                    timeout_sec=self._probe_cfg.dns_timeout_sec,
                    iface_ip=iface_ip,
                )
                if result:
                    success_count += 1
            except Exception:
                # Probe failed
                pass

        return (success_count, total_count)

    def _run_http_probes(
        self,
        iface: InterfaceConfig,
    ) -> tuple[int, int, float]:
        """
        Run probe_http() for each http_target sequentially.

        Returns (success_count, total_count, avg_response_ms).
        avg_response_ms is average over successful responses only.

        Args:
            iface: InterfaceConfig containing interface name.

        Returns:
            Tuple of (success_count, total_count, avg_response_ms).
        """
        total_count = len(self._probe_cfg.http_targets)
        if total_count == 0:
            return (0, 0, 0.0)

        success_count = 0
        response_times: list[float] = []

        for target in self._probe_cfg.http_targets:
            try:
                success, response_ms = probe_http(
                    interface=iface.name,
                    target=target,
                    timeout_sec=self._probe_cfg.http_timeout_sec,
                )
                if success:
                    success_count += 1
                    response_times.append(response_ms)
            except Exception:
                # Probe failed
                pass

        avg_response = sum(response_times) / len(response_times) if response_times else 0.0
        return (success_count, total_count, avg_response)
