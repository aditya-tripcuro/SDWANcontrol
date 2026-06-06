"""
wancontrol/usage.py
~~~~~~~~~~~~~~~~~~~
Per-interface rx/tx throughput sampler.

A dedicated daemon thread reads /proc/net/dev counters every
``usage.sample_interval_sec`` and derives instantaneous Mbps by diffing
against the previous snapshot for each interface. Results are written to
``interface_usage`` so the dashboard can render a Windows-Task-Manager-style
chart.

This runs in its own thread (not inside the 1s controller probe loop) so a
slow /proc read can never stall route decisions. Lifecycle mirrors
:class:`wancontrol.watchdog.Watchdog`.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable

from wancontrol.network import read_interface_counters

if TYPE_CHECKING:
    from wancontrol.config import AppConfig
    from wancontrol.database import Database

logger = logging.getLogger(__name__)


# Listener callback gets (interface, rx_mbps, tx_mbps, rx_bytes_total,
# tx_bytes_total, timestamp). Used by the Flask SSE generator to push live
# throughput to the dashboard without a polling fetch.
UsageListener = Callable[[str, float, float, int, int, float], None]


class UsageSampler:
    def __init__(
        self,
        cfg: "AppConfig",
        db: "Database",
    ) -> None:
        self._cfg = cfg
        self._db = db
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cfg_lock = threading.Lock()
        # interface -> (rx_bytes, tx_bytes, monotonic_ts) of previous read.
        # The first sample after start (or after a restart of this thread) is
        # used only to seed the baseline; we don't persist a rate from it.
        self._prev: dict[str, tuple[int, int, float]] = {}
        self._listeners: list[UsageListener] = []

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if not self._cfg.usage.enabled:
            logger.info(
                "Usage sampler disabled in config",
                extra={"component": "usage"},
            )
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="usage-sampler")
        self._thread.start()
        logger.info(
            "Usage sampler started (interval=%ss)",
            self._cfg.usage.sample_interval_sec,
            extra={"component": "usage"},
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("Usage sampler stopped", extra={"component": "usage"})

    def update_config(self, cfg: "AppConfig") -> None:
        """Hot-swap config. The next iteration picks up the new interval / set."""
        with self._cfg_lock:
            self._cfg = cfg

    def add_listener(self, fn: UsageListener) -> None:
        self._listeners.append(fn)

    def _current_cfg(self) -> "AppConfig":
        with self._cfg_lock:
            return self._cfg

    # ── Loop ───────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            cfg = self._current_cfg()
            interval = max(1, int(cfg.usage.sample_interval_sec))
            try:
                self._tick(cfg)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Usage tick failed: %s", exc,
                    extra={"component": "usage"},
                )
            # Sleep-with-wakeup so stop() interrupts promptly.
            self._stop.wait(interval)

    def _tick(self, cfg: "AppConfig") -> None:
        now_wall = time.time()
        now_mono = time.monotonic()
        for iface in cfg.interfaces:
            counters = read_interface_counters(iface.name)
            if counters is None:
                # Interface disappeared (hot-plug, removed) — drop its baseline
                # so a re-attach doesn't compute a huge spike off a stale prior.
                self._prev.pop(iface.name, None)
                continue
            rx_bytes, tx_bytes, _rx_pkts, _tx_pkts = counters
            prev = self._prev.get(iface.name)
            self._prev[iface.name] = (rx_bytes, tx_bytes, now_mono)
            if prev is None:
                continue  # baseline only
            prev_rx, prev_tx, prev_mono = prev
            dt = max(0.001, now_mono - prev_mono)
            # Guard against counter reset (interface bounce) — would otherwise
            # show as a giant negative rate. Treat as a fresh baseline.
            if rx_bytes < prev_rx or tx_bytes < prev_tx:
                continue
            rx_mbps = (rx_bytes - prev_rx) * 8.0 / 1_000_000.0 / dt
            tx_mbps = (tx_bytes - prev_tx) * 8.0 / 1_000_000.0 / dt
            try:
                self._db.insert_usage(
                    interface=iface.name,
                    rx_mbps=rx_mbps,
                    tx_mbps=tx_mbps,
                    rx_bytes_total=rx_bytes,
                    tx_bytes_total=tx_bytes,
                    timestamp=now_wall,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "insert_usage(%s) failed: %s", iface.name, exc,
                    extra={"component": "usage"},
                )
                continue
            for fn in self._listeners:
                try:
                    fn(iface.name, rx_mbps, tx_mbps, rx_bytes, tx_bytes, now_wall)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Usage listener raised: %s", exc,
                        extra={"component": "usage"},
                    )
