"""
wancontrol/controller.py
~~~~~~~~~~~~~~~~~~~~~~~~
Lifecycle manager for WANControl v2. Handles interface setup, monitoring loop,
failover/load-balance switching, and graceful shutdown.
"""
from __future__ import annotations

import fcntl
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from wancontrol.config import AppConfig
from wancontrol.database import Database
from wancontrol.monitor import Monitor, InterfaceMetric
from wancontrol import network

logger = logging.getLogger(__name__)

# Compatibility aliases used by older tests and integrations that patch these
# symbols on wancontrol.controller directly.
set_default_route = network.set_default_route
set_load_balance_route = network.set_load_balance_route


class ControllerMode(Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STANDBY = "STANDBY"
    KILLED = "KILLED"


class WanState(Enum):
    STABLE = "STABLE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass
class InterfaceState:
    """Runtime state for a single WAN interface."""
    interface: str
    wan_state: WanState = WanState.STABLE
    last_score: float = 100.0
    stable_since: float = field(default_factory=time.time)
    in_nexthop_pool: bool = True
    # Anti-flap debounce counters (item 11): a link only transitions to FAILED
    # after `fail_confirmations` consecutive hard-fail cycles and only recovers
    # after `recover_confirmations` consecutive healthy cycles. This prevents a
    # single false reading or a momentary drop from triggering a route switch.
    consecutive_fail: int = 0
    consecutive_ok: int = 0


class Controller:
    """
    Core SD-WAN logic. Manages the probe loop and routing table updates.
    """

    def __init__(self, cfg: AppConfig, db: Database) -> None:
        self._cfg = cfg
        self._db = db
        # A freshly-constructed controller is STOPPED: it has been instantiated
        # but not started, and with auto_start disabled it may never start. start()
        # flips it to STARTING, the loop to RUNNING/STANDBY, and shutdown() to
        # STOPPED (graceful) or KILLED (emergency). This matches the DB state that
        # __main__ writes ("controller_mode" = "STOPPED") when auto_start is off.
        self._mode = ControllerMode.STOPPED
        self._start_time = time.time()
        self._stop_event = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shutdown_called = False

        # Route-mutation lock (item 17): every kernel-routing-table mutation in
        # this controller — failover switches, load-balance pool rewrites, master
        # setup/teardown and config reloads — is serialized under this single
        # re-entrant lock. The watchdog also re-acquires it (see watchdog.py) so
        # the two threads can never rewrite routes concurrently. RLock is required
        # because reload/switch paths may nest route-guarded calls.
        self._route_lock = threading.RLock()

        # Lifecycle lock (item 20): serialize start()/shutdown() so a shutdown
        # racing a start cannot leave the controller half-initialized.
        self._lifecycle_lock = threading.Lock()
        self._shutting_down = False

        # Anti-flap (item 11): wall-clock of the last route switch; switches are
        # suppressed within `min_switch_interval_sec` of this timestamp.
        self._last_switch_ts: float = 0.0

        self._monitor = Monitor(cfg.probes, cfg.scoring, db)
        
        # Internal state for routing logic
        self._active_interface: str = cfg.interfaces[0].name
        self._nexthop_pool: list[str] = [iface.name for iface in cfg.interfaces]
        self._interface_states: dict[str, InterfaceState] = {
            iface.name: InterfaceState(interface=iface.name) for iface in cfg.interfaces
        }
        
        # Last known metrics for watchdog re-application
        self._last_metrics: list[InterfaceMetric] = []
        
        # Lock file handle
        self._lock_fh = None
        
        # Load balance mode starts with all in pool
        if cfg.wan_mode == "load_balance":
            for state in self._interface_states.values():
                state.in_nexthop_pool = True

        # Track whether the initial LB route has been pushed to the kernel
        self._lb_route_applied: bool = False

    @property
    def route_lock(self) -> threading.RLock:
        """Re-entrant lock guarding all kernel route mutations (item 17).

        Exposed so the watchdog can wrap its own route re-application in
        ``with controller.route_lock:`` and never race the controller loop.
        """
        return self._route_lock

    def _scoring(self, name: str, default: Any) -> Any:
        """Read a scoring-config value defensively (item 16).

        Anti-flap / hysteresis knobs (``fail_confirmations``,
        ``recover_confirmations``, ``min_switch_interval_sec``,
        ``return_stability_sec``) are added by the config owner; until that lands
        on every deployment we fall back to the documented default so old configs
        keep loading.
        """
        return getattr(self._cfg.scoring, name, default)

    def start(self) -> None:
        """Start the controller loop in a background thread (non-blocking)."""
        with self._lifecycle_lock:
            # Refuse to (re)start while a shutdown is in progress (item 20).
            if self._shutting_down:
                logger.info(
                    "start() ignored — controller is shutting down",
                    extra={"component": "controller"},
                )
                return
            # Block a *double* start once the loop is already live. The initial
            # STARTING (set in __init__) must NOT block the first start(); only a
            # controller that has already entered its RUNNING/PAUSED loop is a
            # genuine re-entry to ignore.
            if self._mode in {ControllerMode.RUNNING, ControllerMode.PAUSED}:
                return
            self._stop_event.clear()
            self._shutdown_called = False
            self._mode = ControllerMode.STARTING
            self._db.set_state("controller_mode", self._mode.value)
            self._db.set_state("controller_status", "running")

            t = threading.Thread(target=self.run, name="controller-main", daemon=True)
            t.start()

    def run(self) -> None:
        """Blocking loop. Normally called via start() in a thread."""
        if self._acquire_master_lock():
            self._run_master()
        else:
            self._run_standby()

    def wait(self) -> None:
        """Block until shutdown() is called."""
        self._stop_event.wait()

    def stop(self) -> None:
        """Gracefully stop route management and restore the saved route state.

        A graceful, operator-initiated stop ends in STOPPED (persisted as
        ``controller_mode == "STOPPED"``) — the same terminal state as a SIGTERM
        from ``systemctl stop``. This is distinct from kill(), which ends in
        KILLED to signal an emergency/unclean stop. The route-restoring teardown
        runs under the route lock via shutdown() either way.
        """
        self.shutdown(killed=False)

    def pause(self) -> None:
        """Freeze the current route selection while keeping status observable."""
        if self._mode == ControllerMode.RUNNING:
            self._mode = ControllerMode.PAUSED
            self._db.set_state("controller_mode", self._mode.value)
            self._db.set_state("controller_status", "paused")

    def resume(self) -> None:
        """Resume automatic route switching after pause."""
        if self._mode == ControllerMode.PAUSED:
            self._mode = ControllerMode.RUNNING
            self._db.set_state("controller_mode", self._mode.value)
            self._db.set_state("controller_status", "running")

    def kill(self) -> None:
        """Emergency best-effort cleanup and restore."""
        self.shutdown(killed=True)

    def shutdown(self, *, killed: bool = False) -> None:
        """Stop loops and restore system to original state.

        Serialized against start() under the lifecycle lock (item 20) so the two
        can never interleave, and the route-restoring teardown runs under the
        route lock (item 17) so it cannot race the controller/watchdog threads.
        """
        with self._lifecycle_lock:
            with self._shutdown_lock:
                if self._shutdown_called:
                    return
                self._shutdown_called = True
            # Mark shutting-down so a concurrent start() bails out (item 20).
            self._shutting_down = True

            self._mode = ControllerMode.KILLED if killed else ControllerMode.STOPPED
            self._db.set_state("controller_mode", self._mode.value)
            self._db.set_state("controller_status", "stopped")
            self._stop_event.set()

            logger.info("Shutting down controller...", extra={"component": "controller"})

            try:
                with self._route_lock:
                    network.emergency_cleanup(self._cfg.interfaces, self._db)
                self._db.log_event("INFO", "controller", "Controller shutdown complete")
            except Exception as exc:
                logger.error("Error during teardown: %s", exc, extra={"component": "controller"})
            finally:
                self._release_master_lock()
                self._shutting_down = False

    def get_status(self) -> dict[str, Any]:
        """Summary of current state for the API."""
        return {
            "mode": self._mode.name,
            "wan_mode": self._cfg.wan_mode,
            "timestamp": time.time(),
            "start_time": self._start_time,
            "active_interface": self._active_interface,
            "nexthop_pool": list(self._nexthop_pool),
            "restore_default_routes": self._db.get_state(network.STATE_PRE_START_DEFAULT_ROUTES),
            "route_management_active": self._db.get_state(network.STATE_ROUTE_MANAGEMENT_ACTIVE) == "1",
            "stale_managed_state_detected": self._db.get_state(network.STATE_STALE_MANAGED_STATE) == "1",
            "interfaces": {
                name: {
                    "wan_state": state.wan_state.name,
                    "score": state.last_score,
                    "in_pool": state.in_nexthop_pool
                } for name, state in self._interface_states.items()
            }
        }

    def update_config(self, cfg: AppConfig) -> None:
        """Apply a reloaded config to the running controller (items 21, 29).

        Diff-based, atomic reload: under the route lock we compute which
        interfaces were removed / added / changed, tear down ONLY the removed
        ones and (re)set up ONLY the added or changed ones — untouched interfaces
        keep their kernel routing tables undisturbed. The new ``cfg`` reference is
        built first and swapped in atomically so readers never observe a
        half-applied config.
        """
        old_cfg = self._cfg
        old_by_name = {iface.name: iface for iface in old_cfg.interfaces}
        new_by_name = {iface.name: iface for iface in cfg.interfaces}
        old_names = set(old_by_name)
        new_names = set(new_by_name)

        removed = old_names - new_names
        added = new_names - old_names
        # "Changed" = same name but any field differs (gateway, table id, v6, …).
        # InterfaceConfig is a frozen dataclass so value equality is well-defined.
        changed = {
            name for name in (old_names & new_names)
            if old_by_name[name] != new_by_name[name]
        }

        with self._route_lock:
            # 1. Tear down interfaces that no longer exist in the new config.
            for name in removed:
                try:
                    network.teardown_interface_routing(old_by_name[name])
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Failed to tear down removed interface %s: %s",
                        name, exc, extra={"component": "controller"},
                    )

            # 2. Atomic swap of the config reference (item 21): everything past
            #    this point observes the fully-built new config.
            self._cfg = cfg
            self._monitor.update_config(cfg.probes, cfg.scoring)

            for name in removed:
                self._interface_states.pop(name, None)
            for iface in cfg.interfaces:
                self._interface_states.setdefault(iface.name, InterfaceState(interface=iface.name))

            if self._active_interface not in new_names:
                self._active_interface = cfg.interfaces[0].name
                self._db.set_state("active_interface", self._active_interface)

            self._nexthop_pool = [
                name for name in self._nexthop_pool if name in new_names
            ] or [iface.name for iface in cfg.interfaces]
            # A changed interface may alter weights/gateways, so force the LB
            # multipath route to be recomputed on the next load-balance cycle.
            if added or changed or removed:
                self._lb_route_applied = False

            # 3. Set up only the interfaces that were added or whose config
            #    changed — never reapply the untouched ones (item 29).
            if self._mode in {ControllerMode.RUNNING, ControllerMode.PAUSED}:
                for name in sorted(added | changed):
                    try:
                        network.setup_interface_routing(new_by_name[name])
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "Failed to apply routing for %s after config reload: %s",
                            name, exc, extra={"component": "controller"},
                        )

        logger.info(
            "Controller config updated: mode=%s interfaces=%s "
            "(added=%s changed=%s removed=%s)",
            cfg.wan_mode,
            ",".join(cfg.interface_names),
            ",".join(sorted(added)) or "-",
            ",".join(sorted(changed)) or "-",
            ",".join(sorted(removed)) or "-",
            extra={"component": "controller"},
        )

    # ── Internal Logic ──────────────────────────────────────────────────────────

    def _acquire_master_lock(self) -> bool:
        """Attempt to become the active master via flock."""
        try:
            lock_path = Path(self._cfg.lock_file)
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._lock_fh = open(lock_path, "w")
            fcntl.flock(self._lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fh.write(str(threading.get_ident()))
            self._lock_fh.flush()
            return True
        except (IOError, OSError):
            if self._lock_fh:
                self._lock_fh.close()
                self._lock_fh = None
            return False

    def _release_master_lock(self) -> None:
        if self._lock_fh:
            try:
                fcntl.flock(self._lock_fh, fcntl.LOCK_UN)
                self._lock_fh.close()
                Path(self._cfg.lock_file).unlink(missing_ok=True)
            except Exception:
                pass
            finally:
                self._lock_fh = None

    def _run_master(self) -> None:
        """Master logic loop."""
        # Abort if a shutdown (graceful STOPPED or emergency KILLED) raced thread
        # startup. _stop_event is set by shutdown() and cleared by start(), so it
        # catches both terminal states — checking only KILLED would let a graceful
        # stop fall through into RUNNING (a zombie loop).
        if self._stop_event.is_set() or self._mode == ControllerMode.KILLED:
            return
        logger.info("Acting as MASTER", extra={"component": "controller"})
        self._mode = ControllerMode.RUNNING
        self._db.set_state("controller_mode", self._mode.value)

        # Shadow mode (Layer-1 dry-run): record every intended `ip` command to
        # the DB instead of mutating the kernel. Wire the recorder before any
        # route command runs so the very first snapshot/setup is captured too.
        if network._shadow_enabled():
            network.set_shadow_recorder(self._record_intended_route)
            logger.warning(
                "SHADOW MODE active — routing commands will be recorded, not applied",
                extra={"component": "controller"},
            )

        try:
            with self._route_lock:
                # Loosen rp_filter and enable forwarding before installing the
                # per-interface policy routing (items 12 + forwarding). Both are
                # idempotent in network.py.
                network.enable_rp_filter_loose()
                network.enable_ip_forwarding()

                if network.detect_stale_managed_state(self._db):
                    self._db.log_event("WARNING", "network", "Stale managed route state detected on startup; preserving original route snapshot")
                network.snapshot_default_routes(self._db)
                network.setup_all_interfaces(self._cfg.interfaces)
        except Exception as exc:
            logger.critical("Fatal setup error: %s", exc, extra={"component": "controller"})
            self.shutdown()
            return

        while self._mode in {ControllerMode.RUNNING, ControllerMode.PAUSED}:
            start_ts = time.time()
            try:
                metrics = self._monitor.collect(
                    self._cfg.interfaces, 
                    timeout_sec=self._cfg.controller.metric_collection_timeout_sec
                )
                self._last_metrics = metrics
                
                for m in metrics:
                    state = self._interface_states.get(m.interface)
                    if state:
                        self._update_wan_state(state, m)

                if self._mode == ControllerMode.RUNNING:
                    if self._cfg.wan_mode == "failover":
                        self._apply_failover(metrics)
                    else:
                        self._apply_load_balance(metrics)
                    
            except Exception as exc:
                logger.error("Error in master loop: %s", exc, extra={"component": "controller"})
            
            elapsed = time.time() - start_ts
            wait = max(0.1, self._cfg.controller.loop_interval_sec - elapsed)
            if self._stop_event.wait(timeout=wait):
                break

    def _run_standby(self) -> None:
        """Standby logic loop."""
        if self._stop_event.is_set() or self._mode == ControllerMode.KILLED:
            return
        self._mode = ControllerMode.STANDBY
        self._db.set_state("controller_mode", self._mode.value)
        logger.info("Acting as STANDBY", extra={"component": "controller"})
        
        while self._mode == ControllerMode.STANDBY:
            if self._stop_event.wait(timeout=self._cfg.controller.heartbeat_interval_sec):
                break
            if self._acquire_master_lock():
                self._run_master()
                break

    def _update_wan_state(self, state: InterfaceState, metric: InterfaceMetric) -> None:
        """Transition interface between STABLE, DEGRADED, FAILED.

        Anti-flap (item 11): a link is not declared FAILED on the strength of a
        single bad sample. ``consecutive_fail`` must reach ``fail_confirmations``
        before the link is CONFIRMED-failed, and once failed it must post
        ``recover_confirmations`` consecutive healthy samples before it leaves
        FAILED. While the fail counter is building it holds in DEGRADED rather
        than dancing between STABLE and FAILED on false readings or short drops.
        """
        old_state = state.wan_state
        state.last_score = metric.score

        fail_threshold = self._cfg.scoring.hard_fail_threshold
        degraded_threshold = (fail_threshold +
                              self._cfg.scoring.hysteresis_switch_to_backup +
                              self._cfg.scoring.recovery_margin)

        fail_confirmations = int(self._scoring("fail_confirmations", 3))
        recover_confirmations = int(self._scoring("recover_confirmations", 5))

        is_failing = metric.is_hard_fail or metric.score < fail_threshold
        is_healthy = (not metric.is_hard_fail) and metric.score >= degraded_threshold

        # Maintain consecutive-sample debounce counters.
        if is_failing:
            state.consecutive_fail += 1
            state.consecutive_ok = 0
        elif is_healthy:
            state.consecutive_ok += 1
            state.consecutive_fail = 0
        else:
            # In-between (degraded) sample breaks both streaks — neither a clean
            # failure nor a clean recovery.
            state.consecutive_fail = 0
            state.consecutive_ok = 0

        if old_state == WanState.FAILED:
            # Stay failed until a confirmed recovery streak (item 11).
            if state.consecutive_ok >= recover_confirmations:
                state.wan_state = WanState.STABLE
            elif not is_failing:
                state.wan_state = WanState.DEGRADED
            else:
                state.wan_state = WanState.FAILED
        else:
            if is_failing:
                # Only CONFIRMED failure flips to FAILED; otherwise hold DEGRADED.
                if state.consecutive_fail >= fail_confirmations:
                    state.wan_state = WanState.FAILED
                else:
                    state.wan_state = WanState.DEGRADED
            elif metric.score < degraded_threshold:
                state.wan_state = WanState.DEGRADED
            else:
                state.wan_state = WanState.STABLE

        if old_state != state.wan_state:
            state.stable_since = time.time()
            logger.info(
                "Interface %s state changed: %s -> %s (fail=%d ok=%d)",
                state.interface, old_state.name, state.wan_state.name,
                state.consecutive_fail, state.consecutive_ok,
                extra={"component": "controller"}
            )

    def _apply_failover(self, metrics: list[InterfaceMetric]) -> None:
        if self._mode != ControllerMode.RUNNING:
            return

        m_map = {m.interface: m for m in metrics}
        for m in metrics:
            if m.interface in self._interface_states:
                self._interface_states[m.interface].last_score = m.score
        primary_name = self._cfg.interfaces[0].name

        if primary_name not in m_map:
            return

        primary_m = m_map[primary_name]
        backups = [m for name, m in m_map.items() if name != primary_name]
        if not backups:
            return
        best_backup = max(backups, key=lambda m: m.score)

        fail_threshold = self._cfg.scoring.hard_fail_threshold
        hysteresis_switch = self._cfg.scoring.hysteresis_switch_to_backup
        # Honor the configured hysteresis/dwell instead of hardcoded values (item 16).
        hysteresis_return = self._scoring("hysteresis_return_to_primary",
                                          self._cfg.scoring.hysteresis_return_to_primary)
        stability_wait = float(self._scoring("return_stability_sec", 30.0))
        min_switch_interval = float(self._scoring("min_switch_interval_sec", 60.0))

        current = self._active_interface

        # All-links-failed sanity guard (item 11): if every link is failing this
        # cycle there is no better place to go — hold position and do not thrash.
        def _is_failing(m: InterfaceMetric) -> bool:
            return m.is_hard_fail or m.score < fail_threshold

        if all(_is_failing(m) for m in metrics):
            logger.warning(
                "All interfaces failing this cycle — holding on %s (no failover)",
                current, extra={"component": "controller"},
            )
            return

        # Anti-flap dwell (item 11): never switch within min_switch_interval_sec
        # of the previous switch.
        since_last_switch = time.time() - self._last_switch_ts
        if since_last_switch < min_switch_interval:
            logger.debug(
                "Suppressing failover — only %.1fs since last switch (min %.1fs)",
                since_last_switch, min_switch_interval,
                extra={"component": "controller"},
            )
            return

        if current == primary_name:
            primary_state = self._interface_states[primary_name]
            backup_state = self._interface_states[best_backup.interface]
            backup_ok = backup_state.wan_state != WanState.FAILED

            # CONFIRMED-failed primary: leave it immediately for the best link
            # that is not itself confirmed-failed, without waiting on the score
            # hysteresis margin (item 11 — switch on confirmed failure).
            if primary_state.wan_state == WanState.FAILED and backup_ok:
                self._switch_to(best_backup.interface)
            # Otherwise switch only when a backup is clearly better than primary.
            elif best_backup.score > (primary_m.score + hysteresis_switch) and backup_ok:
                self._switch_to(best_backup.interface)
        else:
            if primary_m.score > (m_map[current].score + hysteresis_return):
                state = self._interface_states[primary_name]
                if state.wan_state == WanState.STABLE and (time.time() - state.stable_since) >= stability_wait:
                    self._switch_to(primary_name)

    def _switch_to(self, interface: str) -> None:
        old = self._active_interface
        iface_cfg = self._cfg.get_interface(interface)

        # Serialize the route mutation (item 17) so the watchdog or a reload can
        # never rewrite the default route at the same time.
        with self._route_lock:
            self._active_interface = interface
            self._db.set_state("active_interface", interface)
            logger.info("Switching WAN: %s -> %s", old, interface, extra={"component": "controller"})

            set_default_route(iface_cfg.gateway, interface)

            # IPv6 (item 13): if this interface declares a v6 gateway, move the
            # v6 default with it; otherwise leave v6 untouched (snapshot/restore
            # of v6 is handled by network.py). gateway6 is read defensively in
            # case the config field has not landed everywhere yet.
            gateway6 = getattr(iface_cfg, "gateway6", None)
            if gateway6:
                try:
                    network.set_default_route(gateway6, interface)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Failed to set IPv6 default route via %s dev %s: %s",
                        gateway6, interface, exc, extra={"component": "controller"},
                    )

            # Flush the route cache (and conntrack if available) so existing
            # flows re-resolve onto the new path immediately (item 22).
            self._flush_route_cache()

        # Record the switch time for the anti-flap dwell guard (item 11).
        self._last_switch_ts = time.time()

        score_before = self._interface_states[old].last_score
        score_after = self._interface_states[interface].last_score

        self._db.insert_switch_event(
            from_interface=old,
            to_interface=interface,
            reason=f"Switched to {interface}",
            score_before=score_before,
            score_after=score_after
        )

    def _record_intended_route(self, cmd: list[str]) -> None:
        """Shadow-mode recorder: persist an intended `ip` command (Layer-1 dry-run).

        Wired as ``network.set_shadow_recorder`` at master start. Resolved
        defensively so shadow mode degrades to a log line if the DB method has
        not yet landed.
        """
        command = " ".join(cmd)
        record = getattr(self._db, "record_intended_route", None)
        if record is None:
            logger.info("SHADOW intended route: %s", command, extra={"component": "controller"})
            return
        try:
            record(command)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to record intended route %r: %s",
                command, exc, extra={"component": "controller"},
            )

    def _flush_route_cache(self) -> None:
        """Flush the kernel route cache after a route change (item 22).

        Delegates to ``network.flush_route_cache`` which runs
        ``ip route flush cache`` (plus ``conntrack -F`` when available) and never
        raises. Resolved defensively so a switch still succeeds if that helper
        has not yet landed in network.py.
        """
        flush = getattr(network, "flush_route_cache", None)
        if flush is None:
            return
        try:
            flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Route cache flush failed: %s", exc, extra={"component": "controller"},
            )

    def _apply_load_balance(self, metrics: list[InterfaceMetric]) -> None:
        if self._mode != ControllerMode.RUNNING:
            return

        changed = False
        fail_threshold = self._cfg.scoring.hard_fail_threshold
        recovery_threshold = fail_threshold + self._cfg.scoring.recovery_margin

        new_pool: list[str] = []
        for m in metrics:
            state = self._interface_states[m.interface]
            state.last_score = m.score
            was_in = state.in_nexthop_pool

            if was_in:
                if m.is_hard_fail or m.score < fail_threshold:
                    state.in_nexthop_pool = False
                    changed = True
                    logger.warning(
                        "Interface %s removed from LB pool (score=%.1f, hard_fail=%s)",
                        m.interface, m.score, m.is_hard_fail,
                        extra={"component": "controller"},
                    )
            else:
                if not m.is_hard_fail and m.score >= recovery_threshold:
                    state.in_nexthop_pool = True
                    changed = True
                    logger.info(
                        "Interface %s restored to LB pool (score=%.1f)",
                        m.interface, m.score,
                        extra={"component": "controller"},
                    )

            if state.in_nexthop_pool:
                new_pool.append(m.interface)

        # Apply route whenever pool membership changes OR on the very first call
        # (without this, the multipath route is never set when all interfaces
        # start healthy and no "changed" event ever fires on the first cycle).
        if changed or not self._lb_route_applied:
            if not new_pool:
                # Empty-pool blackhole guard (item 10): every link failed the
                # health check, so we must NOT install (or leave) a multipath
                # route — that would blackhole all traffic. Fail over to the
                # single least-bad link (highest score) so traffic keeps moving
                # on whatever path is least broken, rather than dropping it.
                self._fail_to_least_bad_link(metrics)
                return

            self._nexthop_pool = new_pool

            # Weight proportional to expected_speed_mbps so faster links carry
            # more traffic (e.g. 1000:100:100 Mbps → weights 10:1:1).
            min_speed = min(
                self._cfg.get_interface(name).expected_speed_mbps for name in new_pool
            )
            nexthops: list[tuple[str, str, int]] = []
            pool_desc: list[str] = []
            for name in new_pool:
                iface = self._cfg.get_interface(name)
                weight = max(1, iface.expected_speed_mbps // min_speed)
                nexthops.append((iface.gateway, name, weight))
                pool_desc.append(f"{name}(w={weight})")

            with self._route_lock:
                set_load_balance_route(nexthops)
                self._lb_route_applied = True
                self._flush_route_cache()
            logger.info("LB pool applied: %s", ", ".join(pool_desc), extra={"component": "controller"})

    def _fail_to_least_bad_link(self, metrics: list[InterfaceMetric]) -> None:
        """Install a single default route to the highest-scoring link (item 10).

        Used when the load-balance pool would otherwise be empty. We never leave
        a dead multipath default route blackholing traffic; instead we point the
        default at the least-bad link so connectivity degrades gracefully.
        """
        candidates = [m for m in metrics if self._cfg.get_interface(m.interface) is not None]
        if not candidates:
            logger.error(
                "All interfaces failed and none are configured — cannot install a fallback route",
                extra={"component": "controller"},
            )
            return

        best = max(candidates, key=lambda m: m.score)
        iface = self._cfg.get_interface(best.interface)
        logger.error(
            "All interfaces failed LB health check — failing to least-bad link %s "
            "(score=%.1f) instead of leaving a blackhole multipath route",
            best.interface, best.score, extra={"component": "controller"},
        )
        try:
            with self._route_lock:
                set_default_route(iface.gateway, iface.name)
                gateway6 = getattr(iface, "gateway6", None)
                if gateway6:
                    try:
                        network.set_default_route(gateway6, iface.name)
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "Failed to set IPv6 fallback default via %s dev %s: %s",
                            gateway6, iface.name, exc, extra={"component": "controller"},
                        )
                self._flush_route_cache()
            # The multipath route is gone; the next healthy cycle must re-install it.
            self._lb_route_applied = False
            self._nexthop_pool = [best.interface]
        except Exception as exc:  # noqa: BLE001
            logger.critical(
                "Failed to install least-bad fallback route via %s: %s",
                best.interface, exc, extra={"component": "controller"},
            )

    def _fire_alert(self, event_type: str, interface: str, score: float, message: str) -> None:
        if not self._cfg.alerting.enabled:
            return
        
        valid_events = {"link_down", "link_up", "gateway_switch", "controller_error"}
        if event_type not in valid_events:
            return
            
        level = "CRITICAL" if score < self._cfg.scoring.hard_fail_threshold else "WARNING"
        alert_id = self._db.insert_alert(level, event_type, interface, message)
        self._deliver_webhooks(alert_id, event_type, {"interface": interface, "score": score, "message": message})

    def _deliver_webhooks(self, alert_id: int, event_type: str, payload: dict) -> None:
        self._db.mark_alert_notified(alert_id)
