"""
wancontrol/controller.py
~~~~~~~~~~~~~~~~~~~~~~~~
Controller lifecycle: startup and shutdown handlers.

Only startup/shutdown are implemented here (no probe loop).
"""
from __future__ import annotations

import atexit
import logging
import signal
import threading
from typing import Optional

from wancontrol.config import AppConfig
from wancontrol.database import Database
from wancontrol.network import (
    snapshot_default_routes,
    setup_all_interfaces,
    teardown_all_interfaces,
    restore_default_routes,
    find_available_port,
)

logger = logging.getLogger(__name__)


def setup_signal_handlers(controller: "Controller") -> None:
    """Register SIGTERM and SIGINT to trigger controller.shutdown()."""

    def _handler(signum: int, frame: object) -> None:  # noqa: ARG002
        try:
            controller.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.error("Error during shutdown handler: %s", exc, extra={"component": "controller"})

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


class Controller:
    """Lifecycle manager for WANControl.

    Responsibilities implemented here:
    - snapshot default routes at start
    - setup per-interface routing tables
    - teardown on shutdown and restore default routes
    """

    def __init__(self, config: AppConfig, db: Database) -> None:
        self._config = config
        self._db = db
        self._shutdown_called = False
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start controller: snapshot routes, setup interfaces, write state."""
        snapshot_default_routes(self._db)
        setup_all_interfaces(self._config.interfaces)
        self._db.set_state("controller_status", "running")

        # find an available port starting from configured port
        try:
            port = find_available_port(self._config.server.port)
            self._db.set_state("server_port", str(port))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not determine available port: %s", exc, extra={"component": "controller"})

        atexit.register(self.shutdown)
        logger.info("Controller started", extra={"component": "controller"})

    def wait(self) -> None:
        """Block until shutdown() is called from another thread."""
        self._stop_event.wait()

    def shutdown(self) -> None:
        """Shutdown controller: teardown interfaces, restore routes, update state.

        Safe to call multiple times (idempotent).
        """
        if self._shutdown_called:
            return
        self._shutdown_called = True

        try:
            self._db.set_state("controller_status", "stopping")
        except Exception:
            pass

        try:
            teardown_all_interfaces(self._config.interfaces)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error tearing down interfaces: %s", exc, extra={"component": "controller"})

        try:
            restore_default_routes(self._db)
        except Exception as exc:  # noqa: BLE001
            logger.critical("Error restoring default routes: %s", exc, extra={"component": "controller"})

        try:
            self._db.set_state("controller_status", "stopped")
        except Exception:
            pass

        logger.info("Controller stopped. Default routes restored.", extra={"component": "controller"})
        try:
            self._stop_event.set()
        except Exception:
            pass
