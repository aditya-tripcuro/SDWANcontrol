"""
wancontrol/controller.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Controller state machine, scoring engine, route orchestration, master election,
and alerting for WANControl v2.

This module implements the main control loop that:
- Collects metrics from the Monitor
- Updates interface WAN states
- Applies routing decisions (failover or load_balance mode)
- Manages master/standby election via file locks
- Fires alerts and delivers webhooks
"""

from __future__ import annotations

import fcntl
import logging
import os
import signal
import threading
import time
import traceback
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from wancontrol.config import AppConfig, InterfaceConfig, VALID_EVENTS
from wancontrol.monitor import Monitor, InterfaceMetric
from wancontrol.network import (
    set_default_route,
    set_load_balance_route,
    get_default_gateway,
    enable_ip_forwarding,
    enable_rp_filter_loose,
    add_policy_route_table,
    add_policy_rule,
    get_interface_ip,
)

if TYPE_CHECKING:
    from wancontrol.database import Database


logger = logging.getLogger(__name__)


# ── State enums ────────────────────────────────────────────────────────────────

class ControllerMode(str, Enum):
    """Overall controller operating mode. Persisted in DB state table."""
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    MAINTENANCE = "MAINTENANCE"
    KILLED = "KILLED"


class WanState(str, Enum):
    """Health state of a single WAN interface."""
    STABLE = "STABLE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    SWITCHING = "SWITCHING"


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class InterfaceState:
    """Runtime state for one WAN interface."""
    config: InterfaceConfig
    wan_state: WanState = WanState.STABLE
    last_score: float = 100.0
    stable_since: float = field(default_factory=time.time)
    in_nexthop_pool: bool = True  # load_balance mode only


# ── Controller class ───────────────────────────────────────────────────────────

class Controller:
    """
    Main controller for WANControl v2.

    The Controller manages the state machine for WAN interfaces, applies
    routing decisions based on scoring, handles master/standby election,
    and fires alerts when conditions change.
    """

    def __init__(self, cfg: AppConfig, db: "Database") -> None:
        """
        Initialize the Controller.

        Args:
            cfg: Application configuration.
            db: Database instance for state persistence.
        """
        self._cfg = cfg
        self._db = db
        self._monitor = Monitor(cfg.probes, cfg.scoring, db)
        self._state_lock = threading.RLock()
        self._mode = ControllerMode.STARTING
        self._active_interface: str | None = None  # failover mode
        self._nexthop_pool: list[str] = []  # load_balance mode
        self._last_metrics: list[InterfaceMetric] = []  # for watchdog verification
        self._lock_fd: int | None = None  # file descriptor for master lock
        self._alerting_thread: threading.Thread | None = None
        self._stop_alerting = threading.Event()

        # Build InterfaceState for each interface
        self._interface_states: dict[str, InterfaceState] = {}
        for iface_cfg in cfg.interfaces:
            self._interface_states[iface_cfg.name] = InterfaceState(config=iface_cfg)

        # Track last valid nexthop pool to avoid empty routes
        self._last_valid_nexthops: list[tuple[str, str, int]] = []

        # Pruning tracking
        self._last_prune_time: float = 0.0

        # Initialize nexthop pool for load_balance mode
        if cfg.wan_mode == "load_balance":
            self._nexthop_pool = [iface.name for iface in cfg.interfaces]
            for iface_name in self._nexthop_pool:
                self._interface_states[iface_name].in_nexthop_pool = True

        # Set initial active interface for failover mode
        if cfg.wan_mode == "failover" and cfg.interfaces:
            self._active_interface = cfg.interfaces[0].name

    # ── Public methods ─────────────────────────────────────────────────────

    def start(self) -> None:
        """
        Full startup sequence.

        1. Acquire master lock via _acquire_master_lock()
           — if not acquired, become Standby and call _run_standby()
        2. enable_ip_forwarding()
        3. For each interface: enable_rp_filter_loose(), add_policy_route_table(),
           add_policy_rule() using get_interface_ip()
        4. Set mode=RUNNING in DB state table
        5. Call _run_master()
        """
        logger.info(
            "Controller starting",
            extra={"component": "controller"},
        )

        # Step 1: Try to acquire master lock
        if not self._acquire_master_lock():
            logger.warning(
                "Could not acquire master lock — becoming Standby",
                extra={"component": "controller"},
            )
            self._run_standby()
            return

        # We are Master — continue with startup
        logger.info(
            "Acquired master lock — running as Master",
            extra={"component": "controller"},
        )

        # Step 2: Enable IP forwarding
        enable_ip_forwarding()
        logger.info(
            "IP forwarding enabled",
            extra={"component": "controller"},
        )

        # Step 3: Configure each interface
        for iface_cfg in self._cfg.interfaces:
            iface_name = iface_cfg.name
            enable_rp_filter_loose(iface_name)
            iface_ip = get_interface_ip(iface_name)
            if iface_ip:
                add_policy_route_table(
                    table_id=iface_cfg.routing_table_id,
                    interface=iface_name,
                    gateway=iface_cfg.gateway,
                    iface_ip=iface_ip,
                    network_cidr=f"{iface_ip}/32",
                )
                add_policy_rule(
                    table_id=iface_cfg.routing_table_id,
                    iface_ip=iface_ip,
                )
            logger.info(
                "Interface %s configured", iface_name,
                extra={"component": "controller"},
            )

        # Step 4: Set mode=RUNNING in DB
        self._mode = ControllerMode.RUNNING
        self._db.set_state("controller_mode", self._mode.value)

        # Initialize nexthop pool for load_balance mode
        if self._cfg.wan_mode == "load_balance":
            self._nexthop_pool = [iface.name for iface in self._cfg.interfaces]
            for iface_name in self._nexthop_pool:
                self._interface_states[iface_name].in_nexthop_pool = True

        # Set initial active interface for failover mode
        if self._cfg.wan_mode == "failover" and self._cfg.interfaces:
            self._active_interface = self._cfg.interfaces[0].name
            self._db.set_state("active_interface", self._active_interface)

        logger.info(
            "Controller mode set to RUNNING",
            extra={"component": "controller"},
        )

        # Step 5: Run master loop
        self._run_master()

    def stop(self) -> None:
        """
        Clean shutdown.

        1. Set _mode = KILLED, persist to DB
        2. Restore primary interface as default route
        3. Remove lock file
        4. db.close()
        5. Log shutdown to controller_events
        """
        logger.info(
            "Controller stopping",
            extra={"component": "controller"},
        )

        # Step 1: Set mode=KILLED
        with self._state_lock:
            self._mode = ControllerMode.KILLED
        self._db.set_state("controller_mode", ControllerMode.KILLED.value)

        # Step 2: Restore primary interface as default route
        if self._cfg.interfaces:
            primary = self._cfg.interfaces[0]
            set_default_route(primary.gateway, primary.name)
            logger.info(
                "Restored default route to %s (%s)",
                primary.name, primary.gateway,
                extra={"component": "controller"},
            )

        # Step 3: Remove lock file
        self._release_master_lock()

        # Step 4: Close database
        self._db.close()

        # Step 5: Log shutdown event
        self._db.log_event(
            level="INFO",
            component="controller",
            message="Controller shutdown complete",
        )

        logger.info(
            "Controller stopped",
            extra={"component": "controller"},
        )

    def get_status(self) -> dict:
        """
        Return current status dict for the API layer (Phase 6).
        Thread-safe read of all state.

        Returns:
            {
                "mode": str,
                "wan_mode": str,
                "active_interface": str | None,    # failover mode
                "nexthop_pool": list[str],         # load_balance mode
                "interfaces": {
                    "<name>": {
                        "wan_state": str,
                        "score": float,
                        "in_pool": bool,
                    }
                },
                "timestamp": float,
            }
        """
        with self._state_lock:
            mode_val = self._mode.value
            wan_mode = self._cfg.wan_mode
            active_iface = self._active_interface
            nexthop_pool = list(self._nexthop_pool)

            interfaces_status: dict[str, dict] = {}
            for name, state in self._interface_states.items():
                interfaces_status[name] = {
                    "wan_state": state.wan_state.value,
                    "score": state.last_score,
                    "in_pool": state.in_nexthop_pool,
                }

        return {
            "mode": mode_val,
            "wan_mode": wan_mode,
            "active_interface": active_iface,
            "nexthop_pool": nexthop_pool,
            "interfaces": interfaces_status,
            "timestamp": time.time(),
        }

    # ── Master loop ────────────────────────────────────────────────────────

    def _run_master(self) -> None:
        """
        Main control loop. Runs until _mode == KILLED.

        Each iteration:
        1. Collect metrics via monitor.collect()
        2. Update interface scores and WAN states
        3. Apply routing decision based on wan_mode
        4. Prune DB if prune interval elapsed
        5. Sleep loop_interval_sec

        On any unhandled exception: log ERROR with full traceback,
        insert into controller_events, sleep 5 seconds, retry.
        Never crash the process.
        """
        logger.info(
            "Master loop started",
            extra={"component": "controller"},
        )

        while True:
            with self._state_lock:
                if self._mode == ControllerMode.KILLED:
                    break

            try:
                # Step 1: Collect metrics
                metrics = self._monitor.collect(
                    interfaces=self._cfg.interfaces,
                    timeout_sec=self._cfg.controller.metric_collection_timeout_sec,
                )
                self._last_metrics = metrics

                # Step 2: Update interface scores and WAN states
                metric_by_iface = {m.interface: m for m in metrics}
                for iface_name, iface_state in self._interface_states.items():
                    if iface_name in metric_by_iface:
                        metric = metric_by_iface[iface_name]
                        iface_state.last_score = metric.score
                        self._update_wan_state(iface_state, metric)

                # Step 3: Apply routing decision
                if self._cfg.wan_mode == "failover":
                    self._apply_failover(metrics)
                elif self._cfg.wan_mode == "load_balance":
                    self._apply_load_balance(metrics)

                # Step 4: Prune DB if interval elapsed
                now = time.time()
                prune_interval_sec = self._cfg.retention.prune_interval_min * 60
                if now - self._last_prune_time >= prune_interval_sec:
                    self._db.prune_old_data(
                        metrics_hours=self._cfg.retention.metrics_hours,
                        events_days=self._cfg.retention.events_days,
                    )
                    self._last_prune_time = now

                # Step 5: Sleep
                time.sleep(self._cfg.controller.loop_interval_sec)

            except Exception as exc:
                # Unhandled exception — log and retry
                tb_str = traceback.format_exc()
                logger.error(
                    "Master loop error: %s\n%s",
                    exc, tb_str,
                    extra={"component": "controller"},
                )
                self._db.log_event(
                    level="ERROR",
                    component="controller",
                    message=f"Master loop error: {exc}",
                )
                time.sleep(5)

    # ── Failover mode logic ────────────────────────────────────────────────

    def _apply_failover(self, metrics: list[InterfaceMetric]) -> None:
        """
        Failover switching logic. Called each loop iteration in failover mode.

        Switching rules:
        - Do not switch if mode != RUNNING
        - Primary = interfaces[0], Backup = interfaces[1]
        - Switch FROM primary TO backup when:
            backup.score > primary.score + hysteresis_switch_to_backup
            AND backup.wan_state != FAILED
        - Return TO primary when:
            primary.score > backup.score + hysteresis_return_to_primary
            AND primary.wan_state != FAILED
            AND primary has been STABLE for >= 30 seconds
        - On switch: call set_default_route(), insert switch_event,
          fire alert, update _active_interface
        - Log reason string including both scores on every switch
        """
        with self._state_lock:
            if self._mode != ControllerMode.RUNNING:
                return

            if len(self._cfg.interfaces) < 2:
                return

            primary_cfg = self._cfg.interfaces[0]
            backup_cfg = self._cfg.interfaces[1]

            primary_state = self._interface_states[primary_cfg.name]
            backup_state = self._interface_states[backup_cfg.name]

            primary_metric = next(
                (m for m in metrics if m.interface == primary_cfg.name), None
            )
            backup_metric = next(
                (m for m in metrics if m.interface == backup_cfg.name), None
            )

            if primary_metric is None or backup_metric is None:
                return

            primary_score = primary_metric.score
            backup_score = backup_metric.score

            hysteresis_to_backup = self._cfg.scoring.hysteresis_switch_to_backup
            hysteresis_to_primary = self._cfg.scoring.hysteresis_return_to_primary

            current_active = self._active_interface

            # Switch from primary to backup
            if current_active == primary_cfg.name:
                if (backup_score > primary_score + hysteresis_to_backup
                        and backup_state.wan_state != WanState.FAILED):
                    reason = (
                        f"Backup score ({backup_score:.1f}) > "
                        f"Primary score ({primary_score:.1f}) + hysteresis ({hysteresis_to_backup:.1f})"
                    )
                    self._do_failover_switch(
                        from_iface=primary_cfg.name,
                        to_iface=backup_cfg.name,
                        from_gw=primary_cfg.gateway,
                        to_gw=backup_cfg.gateway,
                        reason=reason,
                        score_before=primary_score,
                        score_after=backup_score,
                    )

            # Return from backup to primary
            elif current_active == backup_cfg.name:
                stable_duration = time.time() - primary_state.stable_since
                if (primary_score > backup_score + hysteresis_to_primary
                        and primary_state.wan_state != WanState.FAILED
                        and stable_duration >= 30):
                    reason = (
                        f"Primary score ({primary_score:.1f}) > "
                        f"Backup score ({backup_score:.1f}) + hysteresis ({hysteresis_to_primary:.1f}), "
                        f"stable for {stable_duration:.1f}s"
                    )
                    self._do_failover_switch(
                        from_iface=backup_cfg.name,
                        to_iface=primary_cfg.name,
                        from_gw=backup_cfg.gateway,
                        to_gw=primary_cfg.gateway,
                        reason=reason,
                        score_before=backup_score,
                        score_after=primary_score,
                    )

    def _do_failover_switch(
        self,
        from_iface: str,
        to_iface: str,
        from_gw: str,
        to_gw: str,
        reason: str,
        score_before: float,
        score_after: float,
    ) -> None:
        """Execute a failover switch."""
        logger.info(
            "Switching default route: %s → %s (%s)",
            from_iface, to_iface, reason,
            extra={"component": "controller"},
        )

        # Set new default route
        set_default_route(to_gw, to_iface)

        # Update state
        with self._state_lock:
            self._active_interface = to_iface

        # Persist to DB
        self._db.set_state("active_interface", to_iface)

        # Insert switch event
        self._db.insert_switch_event(
            from_interface=from_iface,
            to_interface=to_iface,
            reason=reason,
            score_before=score_before,
            score_after=score_after,
        )

        # Fire alert
        self._fire_alert(
            event="gateway_switch",
            interface=to_iface,
            score=score_after,
            message=f"Gateway switched from {from_iface} to {to_iface}: {reason}",
        )

    # ── Load balance mode logic ────────────────────────────────────────────

    def _apply_load_balance(self, metrics: list[InterfaceMetric]) -> None:
        """
        Nexthop pool management. Called each loop iteration in load_balance mode.

        Pool rules:
        - Interface added to pool when:
            score >= hard_fail_threshold + recovery_margin
            AND was previously removed (not in pool)
        - Interface removed from pool when:
            score < hard_fail_threshold
        - On pool change: call set_load_balance_route() with updated pool,
          fire appropriate alert (interface_added_to_pool /
          interface_removed_from_pool)
        - Weights derived from expected_speed_mbps
        - If pool becomes empty: log CRITICAL, do NOT call
          set_load_balance_route() with empty list (would kill connectivity)
        - Update _nexthop_pool
        """
        with self._state_lock:
            if self._mode != ControllerMode.RUNNING:
                return

        hard_fail = self._cfg.scoring.hard_fail_threshold
        recovery_margin = self._cfg.scoring.recovery_margin

        metric_by_iface = {m.interface: m for m in metrics}
        pool_changed = False
        removed_ifaces: list[str] = []
        added_ifaces: list[str] = []

        for iface_name, iface_state in self._interface_states.items():
            metric = metric_by_iface.get(iface_name)
            if metric is None:
                continue

            score = metric.score

            # Check for removal
            if iface_state.in_nexthop_pool and score < hard_fail:
                iface_state.in_nexthop_pool = False
                pool_changed = True
                removed_ifaces.append(iface_name)
                logger.info(
                    "Removing %s from nexthop pool (score %.1f < threshold %.1f)",
                    iface_name, score, hard_fail,
                    extra={"component": "controller"},
                )

            # Check for re-addition
            elif not iface_state.in_nexthop_pool and score >= hard_fail + recovery_margin:
                iface_state.in_nexthop_pool = True
                pool_changed = True
                added_ifaces.append(iface_name)
                logger.info(
                    "Adding %s back to nexthop pool (score %.1f >= threshold+margin %.1f)",
                    iface_name, score, hard_fail + recovery_margin,
                    extra={"component": "controller"},
                )

        if not pool_changed:
            return

        # Build new nexthop pool
        with self._state_lock:
            self._nexthop_pool = [
                name for name, state in self._interface_states.items()
                if state.in_nexthop_pool
            ]

        # Guard against empty pool
        if not self._nexthop_pool:
            logger.critical(
                "Nexthop pool is empty — NOT removing default route to preserve connectivity",
                extra={"component": "controller"},
            )
            return

        # Build nexthops with weights
        nexthops: list[tuple[str, str, int]] = []
        for iface_name in self._nexthop_pool:
            iface_cfg = self._interface_states[iface_name].config
            metric = metric_by_iface.get(iface_name)
            if metric is None:
                continue
            # Weight derived from expected_speed_mbps
            weight = max(1, iface_cfg.expected_speed_mbps // 10)
            nexthops.append((iface_cfg.gateway, iface_name, weight))

        if not nexthops:
            logger.critical(
                "No valid nexthops after filtering — preserving last known route",
                extra={"component": "controller"},
            )
            return

        # Apply new route
        set_load_balance_route(nexthops)
        self._last_valid_nexthops = nexthops

        # Fire alerts for pool changes
        for iface_name in removed_ifaces:
            metric = metric_by_iface.get(iface_name)
            score = metric.score if metric else 0.0
            self._fire_alert(
                event="interface_removed_from_pool",
                interface=iface_name,
                score=score,
                message=f"Interface {iface_name} removed from load balance pool",
            )

        for iface_name in added_ifaces:
            metric = metric_by_iface.get(iface_name)
            score = metric.score if metric else 0.0
            self._fire_alert(
                event="interface_added_to_pool",
                interface=iface_name,
                score=score,
                message=f"Interface {iface_name} added back to load balance pool",
            )

    # ── WAN state machine ──────────────────────────────────────────────────

    def _update_wan_state(
        self,
        iface_state: InterfaceState,
        metric: InterfaceMetric,
    ) -> None:
        """
        Transition WAN state based on new metric. Use match statement.

        Transitions:
        STABLE   → DEGRADED  : score dropped but not hard_fail
        STABLE   → FAILED    : is_hard_fail
        DEGRADED → STABLE    : score recovered above hard_fail_threshold
        DEGRADED → FAILED    : is_hard_fail
        FAILED   → DEGRADED  : score recovered above hard_fail_threshold
                               (not directly to STABLE — must prove stability)
        FAILED   → FAILED    : still hard_fail (no-op)
        SWITCHING → STABLE   : after route change completes

        On STABLE→FAILED or DEGRADED→FAILED: fire link_down alert
        On FAILED→DEGRADED: fire link_up alert (recovered but not stable yet)
        Reset stable_since when entering STABLE.
        """
        old_state = iface_state.wan_state
        new_state: WanState

        # Determine new state based on current state and metric
        match old_state:
            case WanState.STABLE:
                if metric.is_hard_fail:
                    new_state = WanState.FAILED
                elif metric.score < self._cfg.scoring.hard_fail_threshold:
                    new_state = WanState.DEGRADED
                else:
                    new_state = WanState.STABLE

            case WanState.DEGRADED:
                if metric.is_hard_fail:
                    new_state = WanState.FAILED
                elif metric.score >= self._cfg.scoring.hard_fail_threshold:
                    new_state = WanState.STABLE
                else:
                    new_state = WanState.DEGRADED

            case WanState.FAILED:
                if metric.score >= self._cfg.scoring.hard_fail_threshold:
                    new_state = WanState.DEGRADED
                else:
                    new_state = WanState.FAILED

            case WanState.SWITCHING:
                if not metric.is_hard_fail and metric.score >= self._cfg.scoring.hard_fail_threshold:
                    new_state = WanState.STABLE
                else:
                    new_state = old_state

            case _:
                new_state = old_state

        # Handle state transitions
        if new_state != old_state:
            logger.info(
                "WAN state transition: %s %s → %s (score=%.1f)",
                iface_state.config.name, old_state.value, new_state.value, metric.score,
                extra={"component": "controller"},
            )

            # Fire alerts on specific transitions
            if old_state in (WanState.STABLE, WanState.DEGRADED) and new_state == WanState.FAILED:
                self._fire_alert(
                    event="link_down",
                    interface=iface_state.config.name,
                    score=metric.score,
                    message=f"Link down: {iface_state.config.name} entered FAILED state",
                )
            elif old_state == WanState.FAILED and new_state == WanState.DEGRADED:
                self._fire_alert(
                    event="link_up",
                    interface=iface_state.config.name,
                    score=metric.score,
                    message=f"Link up: {iface_state.config.name} recovered from FAILED to DEGRADED",
                )

        # Update state
        iface_state.wan_state = new_state

        # Reset stable_since when entering STABLE
        if new_state == WanState.STABLE and old_state != WanState.STABLE:
            iface_state.stable_since = time.time()

    # ── Master election ────────────────────────────────────────────────────

    def _acquire_master_lock(self) -> bool:
        """
        Try to acquire exclusive lock on cfg.lock_file using fcntl.

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        Returns True if acquired (this process is Master).
        Returns False if already held by another process (become Standby).
        Stores the open file descriptor — do not close it until stop().
        """
        lock_path = Path(self._cfg.lock_file)
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fd = fd
            return True
        except (OSError, BlockingIOError):
            if fd is not None:
                os.close(fd)
            return False

    def _release_master_lock(self) -> None:
        """Release the master lock file."""
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            finally:
                self._lock_fd = None

        # Remove lock file
        try:
            Path(self._cfg.lock_file).unlink(missing_ok=True)
        except OSError:
            pass

    def _run_standby(self) -> None:
        """
        Standby loop. Poll heartbeat_file mtime every heartbeat_interval_sec.

        If mtime is older than heartbeat_stale_sec:
        - Log WARNING: "Heartbeat stale — attempting master takeover"
        - Unlink lock_file
        - Call _acquire_master_lock() again
        - If acquired: log WARNING "Master takeover successful", call _run_master()
        - If not acquired: continue polling
        """
        logger.info(
            "Running as Standby — monitoring heartbeat",
            extra={"component": "controller"},
        )

        heartbeat_path = Path(self._cfg.heartbeat_file)
        lock_path = Path(self._cfg.lock_file)
        poll_interval = self._cfg.controller.heartbeat_interval_sec
        stale_threshold = self._cfg.controller.heartbeat_stale_sec

        while True:
            with self._state_lock:
                if self._mode == ControllerMode.KILLED:
                    break

            try:
                # Check heartbeat age
                if heartbeat_path.exists():
                    mtime = heartbeat_path.stat().st_mtime
                    age = time.time() - mtime

                    if age > stale_threshold:
                        logger.warning(
                            "Heartbeat stale (age=%.1fs > %.1fs) — attempting master takeover",
                            age, stale_threshold,
                            extra={"component": "controller"},
                        )

                        # Try to remove lock file
                        try:
                            lock_path.unlink(missing_ok=True)
                        except OSError:
                            pass

                        # Try to acquire lock
                        if self._acquire_master_lock():
                            logger.warning(
                                "Master takeover successful",
                                extra={"component": "controller"},
                            )
                            self._run_master()
                            return
                else:
                    # No heartbeat file — try to acquire lock immediately
                    if self._acquire_master_lock():
                        logger.warning(
                            "No heartbeat found — taking over as Master",
                            extra={"component": "controller"},
                        )
                        self._run_master()
                        return

            except Exception as exc:
                logger.error(
                    "Standby loop error: %s", exc,
                    extra={"component": "controller"},
                )

            time.sleep(poll_interval)

    # ── Alerting ───────────────────────────────────────────────────────────

    def _fire_alert(
        self,
        event: str,
        interface: str,
        score: float,
        message: str,
    ) -> None:
        """
        Fire an alert.

        1. Insert into alerts table (notified=False)
        2. Launch a daemon thread to deliver webhooks
        3. Return immediately — never block the controller loop

        event must be one of VALID_EVENTS from config.py.
        Only fires if alerting.enabled == True.
        """
        if not self._cfg.alerting.enabled:
            return

        if event not in VALID_EVENTS:
            logger.warning(
                "Invalid alert event: %s", event,
                extra={"component": "controller"},
            )
            return

        # Determine severity level based on event type
        level_map = {
            "link_down": "CRITICAL",
            "link_up": "INFO",
            "gateway_switch": "WARNING",
            "interface_added_to_pool": "INFO",
            "interface_removed_from_pool": "WARNING",
            "controller_error": "ERROR",
        }
        level = level_map.get(event, "WARNING")

        # Insert alert into DB
        alert_id = self._db.insert_alert(
            level=level,
            title=f"WANControl Alert: {event}",
            body=message,
        )

        logger.info(
            "Alert fired: %s (id=%d, level=%s)",
            event, alert_id, level,
            extra={"component": "controller"},
        )

        # Launch background thread for webhook delivery
        payload = {
            "alert_id": alert_id,
            "event": event,
            "interface": interface,
            "score": score,
            "message": message,
            "timestamp": time.time(),
        }

        thread = threading.Thread(
            target=self._deliver_webhooks,
            args=(alert_id, event, payload),
            daemon=True,
        )
        thread.start()

    def _deliver_webhooks(
        self,
        alert_id: int,
        event: str,
        payload: dict,
    ) -> None:
        """
        Deliver webhooks in background thread.

        For each webhook in alerting.webhooks where event in on_events:
        - POST/GET/PUT the payload as JSON using urllib.request (not requests)
        - On failure: retry up to 3 times with 5 second backoff
        - On all retries exhausted: log WARNING
        - On success: call db.mark_alert_notified(alert_id)
        Never raises. All exceptions caught and logged.
        """
        webhooks = self._cfg.alerting.webhooks
        if not webhooks:
            return

        for webhook in webhooks:
            if event not in webhook.on_events:
                continue

            url = webhook.url
            method = webhook.method
            headers = webhook.headers.copy()
            headers["Content-Type"] = "application/json"

            json_data = None
            if method in ("POST", "PUT"):
                json_data = payload

            success = False
            for attempt in range(3):
                try:
                    req = urllib.request.Request(url, data=None)
                    if json_data is not None:
                        import json
                        data = json.dumps(json_data).encode("utf-8")
                        req = urllib.request.Request(url, data=data, method=method)
                    else:
                        req = urllib.request.Request(url, method=method)

                    for key, value in headers.items():
                        req.add_header(key, value)

                    with urllib.request.urlopen(req, timeout=10) as response:
                        if 200 <= response.status < 300:
                            success = True
                            break

                except urllib.error.URLError as exc:
                    logger.debug(
                        "Webhook delivery attempt %d failed: %s",
                        attempt + 1, exc.reason,
                        extra={"component": "controller"},
                    )
                except Exception as exc:
                    logger.debug(
                        "Webhook delivery attempt %d failed: %s",
                        attempt + 1, exc,
                        extra={"component": "controller"},
                    )

                if attempt < 2:
                    time.sleep(5)

            if success:
                self._db.mark_alert_notified(alert_id)
                logger.info(
                    "Webhook delivered successfully to %s", url,
                    extra={"component": "controller"},
                )
            else:
                logger.warning(
                    "Webhook delivery failed after 3 attempts: %s", url,
                    extra={"component": "controller"},
                )
