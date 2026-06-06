"""
wancontrol/watchdog.py
~~~~~~~~~~~~~~~~~~~~~~~
Watchdog thread for WANControl v2.

The Watchdog runs as a daemon thread inside the controller process and:
1. Writes heartbeat_file with current timestamp every heartbeat_interval_sec
2. Every 10 seconds, verifies kernel routing table matches expected state
3. Detects a stale controller heartbeat and restarts the controller
4. Prunes old database rows on a configurable interval
5. Handles SIGTERM/SIGINT for clean shutdown
6. Registers atexit handler for abnormal exits
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from wancontrol.network import get_default_gateway

if TYPE_CHECKING:
    from wancontrol.config import AppConfig
    from wancontrol.database import Database
    from wancontrol.controller import Controller


logger = logging.getLogger(__name__)


class Watchdog:
    """
    Runs as a daemon thread inside the controller process.

    Responsibilities:
    1. Write heartbeat_file with current timestamp every heartbeat_interval_sec
    2. Every 10 seconds, verify kernel routing table matches expected state
    3. Detect a stale controller heartbeat and restart the controller
    4. Prune old database rows every retention.prune_interval_min
    5. Handle SIGTERM/SIGINT for clean shutdown
    6. Register atexit handler for abnormal exits
    """

    def __init__(
        self,
        cfg: "AppConfig",
        db: "Database",
        controller: "Controller",
    ) -> None:
        """
        Initialize the Watchdog.

        Args:
            cfg: Application configuration.
            db: Database instance.
            controller: Controller instance for route re-application.
        """
        self._cfg = cfg
        self._db = db
        self._controller = controller
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._atexit_registered = False
        self._signal_handlers_installed = False
        # Guards in-place swaps of self._cfg so the loop thread never reads a
        # config reference while update_config() is mid-replacement.
        self._cfg_lock = threading.Lock()
        # Bookkeeping for staleness detection (item 18) and scheduled pruning
        # (item 25). Initialized lazily inside _run().
        self._last_prune_time = 0.0
        self._last_restart_time = 0.0

    def start(self) -> None:
        """Start watchdog as a daemon thread. Returns immediately."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning(
                "Watchdog thread already running",
                extra={"component": "watchdog"},
            )
            return

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        # Register atexit handler
        self._register_atexit()

        logger.info(
            "Watchdog started",
            extra={"component": "watchdog"},
        )

    def stop(self) -> None:
        """Signal the watchdog thread to stop. Blocks until thread exits."""
        logger.info(
            "Watchdog stopping",
            extra={"component": "watchdog"},
        )

        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.warning(
                    "Watchdog thread did not exit cleanly",
                    extra={"component": "watchdog"},
                )

        logger.info(
            "Watchdog stopped",
            extra={"component": "watchdog"},
        )

    def update_config(self, cfg: "AppConfig") -> None:
        """
        Propagate a reloaded config into the running watchdog (item 19).

        Called from the SIGHUP / API reload path (wired by owner G) so the
        watchdog's heartbeat interval, staleness threshold, and retention
        settings stay in sync with the controller after a hot-reload. The swap
        is done under a lock so the loop thread always reads a consistent
        config reference.
        """
        with self._cfg_lock:
            self._cfg = cfg

        logger.info(
            "Watchdog config updated: heartbeat_interval=%ss heartbeat_stale=%ss "
            "prune_interval=%smin",
            getattr(cfg.controller, "heartbeat_interval_sec", "?"),
            getattr(cfg.controller, "heartbeat_stale_sec", "?"),
            getattr(getattr(cfg, "retention", None), "prune_interval_min", "?"),
            extra={"component": "watchdog"},
        )

    def _current_cfg(self) -> "AppConfig":
        """Return the current config reference under the cfg lock."""
        with self._cfg_lock:
            return self._cfg

    def _run(self) -> None:
        """
        Main watchdog loop. Runs until _stop_event is set.

        Writes heartbeat every heartbeat_interval_sec.
        Calls _verify_routes() every 10 seconds.
        Checks for a stale controller heartbeat every 10 seconds (item 18).
        Prunes old DB rows every retention.prune_interval_min (item 25).

        Config is re-read each iteration via _current_cfg() so a hot-reload
        (item 19 / update_config) takes effect without restarting the loop.
        """
        last_heartbeat_time = 0.0
        last_verify_time = 0.0
        last_stale_check_time = 0.0
        # Seed the prune clock to "now" so we don't immediately prune on the
        # very first iteration right after startup.
        self._last_prune_time = time.time()

        while not self._stop_event.is_set():
            now = time.time()
            cfg = self._current_cfg()
            heartbeat_interval = cfg.controller.heartbeat_interval_sec

            # Write heartbeat
            if now - last_heartbeat_time >= heartbeat_interval:
                self._write_heartbeat()
                last_heartbeat_time = now

            # Verify routes every 10 seconds
            if now - last_verify_time >= 10:
                self._verify_routes()
                last_verify_time = now

            # Detect a stale controller heartbeat every 10 seconds (item 18)
            if now - last_stale_check_time >= 10:
                self._check_heartbeat_staleness(cfg)
                last_stale_check_time = now

            # Scheduled pruning of old DB rows (item 25)
            prune_interval_min = getattr(
                getattr(cfg, "retention", None), "prune_interval_min", 60
            )
            prune_interval_sec = max(1, int(prune_interval_min)) * 60
            if now - self._last_prune_time >= prune_interval_sec:
                self._prune_old_data(cfg)
                self._last_prune_time = now

            # Sleep briefly to avoid busy-waiting
            time.sleep(0.5)

    def _write_heartbeat(self) -> None:
        """
        Write current timestamp (float as string) to heartbeat_file.

        Create parent dirs if needed. Log WARNING on failure but do not raise.
        """
        heartbeat_path = Path(self._cfg.heartbeat_file)

        try:
            heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp_str = str(time.time())
            heartbeat_path.write_text(timestamp_str)
            logger.debug(
                "Heartbeat written: %s", heartbeat_path,
                extra={"component": "watchdog"},
            )
        except OSError as exc:
            logger.warning(
                "Failed to write heartbeat file %s: %s",
                heartbeat_path, exc,
                extra={"component": "watchdog"},
            )

    def _verify_routes(self) -> None:
        """
        Compare get_default_gateway() result against controller.get_status().

        In failover mode: default gateway interface must match active_interface.
        In load_balance mode: skip verification (multipath routes are complex
        to verify — log DEBUG "route verification skipped in load_balance mode").

        If mismatch detected:
        - Log WARNING "Route mismatch detected — re-applying"
        - Call controller._apply_failover() or _apply_load_balance()
          with last known metrics (store on controller as _last_metrics)
        - Log to controller_events with level=WARNING
        """
        status = self._controller.get_status()
        wan_mode = status["wan_mode"]

        if wan_mode == "load_balance":
            logger.debug(
                "Route verification skipped in load_balance mode",
                extra={"component": "watchdog"},
            )
            return

        # Failover mode verification
        if wan_mode == "failover":
            expected_interface = status["active_interface"]
            current_route = get_default_gateway()

            if current_route is None:
                logger.warning(
                    "No default route found — re-applying failover",
                    extra={"component": "watchdog"},
                )
                self._reapply_routes()
                return

            current_gw, current_iface = current_route

            if current_iface != expected_interface:
                logger.warning(
                    "Route mismatch detected — expected %s, got %s — re-applying",
                    expected_interface, current_iface,
                    extra={"component": "watchdog"},
                )
                self._reapply_routes()
                self._db.log_event(
                    level="WARNING",
                    component="watchdog",
                    message=f"Route mismatch: expected {expected_interface}, got {current_iface}",
                )

    def _reapply_routes(self) -> None:
        """Re-apply routes using controller's last known metrics."""
        # Access controller's private _last_metrics for re-application
        # This is safe since we're in the same process
        try:
            last_metrics = getattr(self._controller, "_last_metrics", [])
            if not last_metrics:
                logger.debug(
                    "No cached metrics available for route re-application",
                    extra={"component": "watchdog"},
                )
                return

            wan_mode = self._cfg.wan_mode
            if wan_mode == "failover":
                # Call the controller's failover apply method
                apply_method = getattr(self._controller, "_apply_failover", None)
                if apply_method:
                    apply_method(last_metrics)
            elif wan_mode == "load_balance":
                # Call the controller's load balance apply method
                apply_method = getattr(self._controller, "_apply_load_balance", None)
                if apply_method:
                    apply_method(last_metrics)
        except Exception as exc:
            logger.error(
                "Failed to re-apply routes: %s", exc,
                extra={"component": "watchdog"},
            )

    def _heartbeat_age(self) -> float | None:
        """
        Return the age (seconds) of the controller heartbeat, or None if it
        cannot be determined (file missing/unreadable/unparseable).

        The heartbeat value is written by _write_heartbeat() as a float string;
        we prefer that timestamp but fall back to the file mtime if the
        contents cannot be parsed.
        """
        heartbeat_path = Path(self._cfg.heartbeat_file)
        try:
            raw = heartbeat_path.read_text().strip()
        except OSError as exc:
            logger.warning(
                "Cannot read heartbeat file %s: %s",
                heartbeat_path, exc,
                extra={"component": "watchdog"},
            )
            return None

        now = time.time()
        try:
            written_ts = float(raw)
        except ValueError:
            # Corrupt/partial contents — fall back to file mtime.
            try:
                written_ts = heartbeat_path.stat().st_mtime
            except OSError:
                return None

        age = now - written_ts
        # A heartbeat from the future (clock skew) is treated as fresh, not stale.
        return max(0.0, age)

    def _controller_loop_age(self) -> float | None:
        """
        Return how long (seconds) since the controller's master loop last made
        progress, or None if liveness cannot be determined.

        The controller's master loop refreshes ``_last_metrics`` every cycle,
        and each :class:`InterfaceMetric` carries a ``timestamp`` from that
        collection cycle. Reading the freshest of those timestamps gives a true
        liveness signal for the controller loop itself — unlike the heartbeat
        file, which this watchdog thread writes on its own schedule and would
        keep refreshing even if the controller loop had wedged.
        """
        metrics = getattr(self._controller, "_last_metrics", None)
        if not metrics:
            return None

        try:
            latest = max(float(getattr(m, "timestamp", 0.0)) for m in metrics)
        except (TypeError, ValueError):
            return None
        if latest <= 0.0:
            return None

        # A timestamp from the future (clock skew) is treated as fresh.
        return max(0.0, time.time() - latest)

    def _check_heartbeat_staleness(self, cfg: "AppConfig") -> None:
        """
        Detect a wedged controller and restart it if it has gone stale (item 18).

        Liveness is measured from the controller's master loop itself (its last
        metric-collection timestamp), falling back to the heartbeat file age.
        If the controller loop stops advancing for longer than
        ``heartbeat_stale_sec`` we tear the controller down and bring it back up.
        Any route-touching work is done under the controller's ``route_lock`` so
        we never race the controller's own route mutations (contract item
        17/20).

        We only act while the controller is supposed to be the active master —
        a standby/stopped controller legitimately makes no loop progress and
        must not trigger a restart loop.
        """
        stale_threshold = getattr(cfg.controller, "heartbeat_stale_sec", 0)
        if not stale_threshold or stale_threshold <= 0:
            return

        # Only an active master runs the loop; don't restart a controller that
        # isn't (or shouldn't be) running its master loop.
        if not self._controller_is_active():
            return

        # Prefer the controller loop's own progress; fall back to heartbeat file.
        age = self._controller_loop_age()
        source = "controller loop"
        if age is None:
            age = self._heartbeat_age()
            source = "heartbeat file"

        if age is None:
            # No readable liveness signal yet (e.g. just after start). Give the
            # controller a grace window equal to the stale threshold before
            # treating the missing signal as a fault.
            if (time.time() - self._controller_started_at()) > stale_threshold:
                logger.warning(
                    "Controller liveness signal missing for >%ss — restarting controller",
                    stale_threshold,
                    extra={"component": "watchdog"},
                )
                self._restart_controller("liveness signal missing")
            return

        if age > stale_threshold:
            logger.warning(
                "Controller stale (%s age=%.1fs > %ss) — restarting controller",
                source, age, stale_threshold,
                extra={"component": "watchdog"},
            )
            self._restart_controller(f"{source} stale ({age:.1f}s)")

    def _controller_is_active(self) -> bool:
        """
        Best-effort check that the controller is supposed to be running its
        master loop (and therefore writing heartbeats). Defensive across
        controller variants: prefers a public is_running()/is_active() if the
        controller exposes one, otherwise inspects the mode enum.
        """
        for attr in ("is_running", "is_active"):
            fn = getattr(self._controller, attr, None)
            if callable(fn):
                try:
                    return bool(fn())
                except Exception:  # noqa: BLE001 — never let this crash the loop
                    return False

        mode = getattr(self._controller, "_mode", None)
        mode_name = getattr(mode, "name", str(mode)).upper() if mode is not None else ""
        # RUNNING/PAUSED master loops keep the heartbeat alive; STANDBY/STOPPED/
        # KILLED/STARTING do not (yet) and must not trigger a restart.
        return mode_name in {"RUNNING", "PAUSED"}

    def _controller_started_at(self) -> float:
        """Return the controller's start_time, or now() if unavailable."""
        return float(getattr(self._controller, "_start_time", time.time()))

    def _restart_controller(self, reason: str) -> None:
        """
        Restart the controller after a stale heartbeat (item 18).

        Avoids a tight restart loop by enforcing a minimum interval between
        restarts (the stale threshold). Route-touching teardown/bring-up is done
        under the controller's route_lock so we never collide with the
        controller's own route mutations.
        """
        now = time.time()
        stale_threshold = getattr(self._cfg.controller, "heartbeat_stale_sec", 60)
        min_restart_interval = max(1, int(stale_threshold or 60))
        if (now - self._last_restart_time) < min_restart_interval:
            logger.debug(
                "Skipping controller restart (last restart %.1fs ago, min %ss)",
                now - self._last_restart_time, min_restart_interval,
                extra={"component": "watchdog"},
            )
            return
        self._last_restart_time = now

        try:
            self._db.log_event(
                level="WARNING",
                component="watchdog",
                message=f"Restarting controller: {reason}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to log controller restart event: %s", exc,
                extra={"component": "watchdog"},
            )

        # IMPORTANT: do NOT pre-acquire the controller's route_lock here.
        # shutdown()/start() acquire lifecycle_lock then route_lock internally
        # (order: lifecycle -> route). If the watchdog held route_lock first and
        # then called shutdown() (which wants lifecycle_lock), while an operator
        # stop held lifecycle_lock and wanted route_lock, the two would deadlock
        # (ABBA). Calling them lock-free lets the controller take both in the one
        # canonical order, matching the operator-stop path.
        try:
            self._do_controller_restart()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to restart controller: %s", exc,
                extra={"component": "watchdog"},
            )

    def _do_controller_restart(self) -> None:
        """Tear the controller down and bring it back up.

        Called WITHOUT holding route_lock — shutdown()/start() each take the
        controller's lifecycle_lock then route_lock internally, in that order.
        """
        logger.info(
            "Stopping stale controller before restart",
            extra={"component": "watchdog"},
        )
        self._controller.shutdown()
        logger.info(
            "Starting controller after stale-heartbeat restart",
            extra={"component": "watchdog"},
        )
        self._controller.start()
        # Reset the heartbeat clock so the freshly-started controller gets a
        # full grace window before the next staleness evaluation.
        self._last_restart_time = time.time()

    def _prune_old_data(self, cfg: "AppConfig") -> None:
        """
        Prune old metrics/events from the database on the scheduled interval
        (item 25). Retention thresholds come from config (default 72h / 30d).
        Never raises — pruning is best-effort maintenance.
        """
        retention = getattr(cfg, "retention", None)
        metrics_hours = getattr(retention, "metrics_hours", 72)
        events_days = getattr(retention, "events_days", 30)
        try:
            deleted = self._db.prune_old_data(
                metrics_hours=metrics_hours,
                events_days=events_days,
            )
            total = sum(deleted.values()) if isinstance(deleted, dict) else 0
            logger.info(
                "Scheduled prune complete: %d rows removed (metrics>%sh, events>%sd)",
                total, metrics_hours, events_days,
                extra={"component": "watchdog"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Scheduled prune failed: %s", exc,
                extra={"component": "watchdog"},
            )

    def _install_signal_handlers(self) -> None:
        """Install SIGTERM and SIGINT handlers."""
        if self._signal_handlers_installed:
            return

        def handler(signum: int, frame: object) -> None:
            self._handle_signal(signum, frame)

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)
        self._signal_handlers_installed = True

        logger.debug(
            "Signal handlers installed",
            extra={"component": "watchdog"},
        )

    def _handle_signal(self, signum: int, frame: object) -> None:
        """
        SIGTERM/SIGINT handler.

        1. Log INFO "Signal received, shutting down"
        2. Call controller.stop()
        3. Call self.stop()
        """
        sig_name = signal.Signals(signum).name
        logger.info(
            "Signal received (%s), shutting down", sig_name,
            extra={"component": "watchdog"},
        )

        # Stop controller first
        self._controller.stop()

        # Then stop watchdog
        self.stop()

    def _register_atexit(self) -> None:
        """Register atexit handler for abnormal exits."""
        if self._atexit_registered:
            return

        atexit.register(self._atexit_handler)
        self._atexit_registered = True

        logger.debug(
            "Atexit handler registered",
            extra={"component": "watchdog"},
        )

    def _atexit_handler(self) -> None:
        """
        Registered via atexit.register(). Same as _handle_signal but
        no signal number. Guards against double-execution with a flag.
        """
        # Guard against double-execution
        if not hasattr(self, "_atexit_executed"):
            self._atexit_executed = True
        else:
            return

        logger.info(
            "Atexit handler called — cleaning up",
            extra={"component": "watchdog"},
        )

        try:
            self._controller.stop()
        except Exception as exc:
            logger.error(
                "Error during atexit cleanup: %s", exc,
                extra={"component": "watchdog"},
            )

        try:
            self.stop()
        except Exception as exc:
            logger.error(
                "Error stopping watchdog in atexit: %s", exc,
                extra={"component": "watchdog"},
            )
