"""
wancontrol/watchdog.py
~~~~~~~~~~~~~~~~~~~~~~~
Watchdog thread for WANControl v2.

The Watchdog runs as a daemon thread inside the controller process and:
1. Writes heartbeat_file with current timestamp every heartbeat_interval_sec
2. Every 10 seconds, verifies kernel routing table matches expected state
3. Handles SIGTERM/SIGINT for clean shutdown
4. Registers atexit handler for abnormal exits
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
    3. Handle SIGTERM/SIGINT for clean shutdown
    4. Register atexit handler for abnormal exits
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

    def _run(self) -> None:
        """
        Main watchdog loop. Runs until _stop_event is set.

        Writes heartbeat every heartbeat_interval_sec.
        Calls _verify_routes() every 10 seconds.
        """
        heartbeat_interval = self._cfg.controller.heartbeat_interval_sec
        last_heartbeat_time = 0.0
        last_verify_time = 0.0

        while not self._stop_event.is_set():
            now = time.time()

            # Write heartbeat
            if now - last_heartbeat_time >= heartbeat_interval:
                self._write_heartbeat()
                last_heartbeat_time = now

            # Verify routes every 10 seconds
            if now - last_verify_time >= 10:
                self._verify_routes()
                last_verify_time = now

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
