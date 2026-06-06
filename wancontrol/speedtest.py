"""
wancontrol/speedtest.py
~~~~~~~~~~~~~~~~~~~~~~~
Per-interface hourly speedtest scheduler.

A dedicated daemon thread invokes the Ookla ``speedtest`` CLI on each opted-in
interface every ``speedtest.interval_sec``. Each run is bound to the interface
device with ``--interface=<name>`` so policy routing doesn't matter.

Off by default. The opt-in set is the union of ``cfg.speedtest.enabled_interfaces``
(YAML defaults) and the DB state key ``speedtest.enabled_interfaces`` (runtime
UI toggle). DB takes precedence — i.e. once the user flips an interface on or
off from the UI, the YAML is no longer authoritative for that interface.

Running speedtests in this thread keeps the ~30s subprocess off the controller
probe loop (which has a 1s cadence and would otherwise stall a switch decision).
The thread also drains a queue of one-off "Run now" requests from the API.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import TYPE_CHECKING, Callable

from wancontrol.network import (
    SpeedtestResult,
    _resolve_speedtest_binary,
    run_speedtest,
)

if TYPE_CHECKING:
    from wancontrol.config import AppConfig
    from wancontrol.database import Database

logger = logging.getLogger(__name__)


# Listener gets (interface, result, timestamp) so the SSE generator can push.
SpeedtestListener = Callable[[str, SpeedtestResult, float], None]


# DB state key for the per-interface opt-in list (JSON array of interface names).
STATE_KEY = "speedtest.enabled_interfaces"


class SpeedtestRunner:
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
        self._on_demand: queue.Queue[str] = queue.Queue()
        self._last_run_ts: dict[str, float] = {}
        self._listeners: list[SpeedtestListener] = []
        self._binary_warned = False  # log "binary not found" at most once

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        # Seed last-run timestamps from the DB so a service restart doesn't
        # immediately re-run a test that already ran 10 minutes ago.
        for iface in self._cfg.interfaces:
            row = self._db.get_latest_speedtest(iface.name)
            if row is not None:
                self._last_run_ts[iface.name] = float(row.timestamp)
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="speedtest-runner",
        )
        self._thread.start()
        binary = _resolve_speedtest_binary(self._cfg.speedtest.binary_path)
        logger.info(
            "Speedtest runner started (binary=%s, interval=%ss, enabled=%s)",
            binary or "MISSING",
            self._cfg.speedtest.interval_sec,
            sorted(self._effective_enabled_set()),
            extra={"component": "speedtest"},
        )

    def stop(self) -> None:
        self._stop.set()
        # Push a sentinel so the queue.get() returns promptly.
        try:
            self._on_demand.put_nowait("__stop__")
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=10)
        logger.info("Speedtest runner stopped", extra={"component": "speedtest"})

    def update_config(self, cfg: "AppConfig") -> None:
        with self._cfg_lock:
            self._cfg = cfg

    def add_listener(self, fn: SpeedtestListener) -> None:
        self._listeners.append(fn)

    def _current_cfg(self) -> "AppConfig":
        with self._cfg_lock:
            return self._cfg

    # ── Opt-in management (DB-as-source-of-truth, YAML-as-default) ─────────

    def _stored_enabled_set(self) -> set[str]:
        raw = self._db.get_state(STATE_KEY)
        if not raw:
            return set()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return set()
        if not isinstance(parsed, list):
            return set()
        return {str(x) for x in parsed}

    def _persist_enabled_set(self, names: set[str]) -> None:
        self._db.set_state(STATE_KEY, json.dumps(sorted(names)))

    def _effective_enabled_set(self) -> set[str]:
        """Union of YAML-configured + DB-persisted opt-ins.

        DB-persisted takes precedence: if the user toggled an interface off in
        the UI, it stays off even if it's still in the YAML list (the runner
        persists the merged set on first run so subsequent toggles are
        authoritative).
        """
        raw = self._db.get_state(STATE_KEY)
        if raw is not None:
            return self._stored_enabled_set()
        # Cold start: seed from YAML and persist.
        seed = set(self._cfg.speedtest.enabled_interfaces)
        self._persist_enabled_set(seed)
        return seed

    def set_enabled(self, interface: str, enabled: bool) -> set[str]:
        """Toggle one interface's opt-in. Returns the new enabled set."""
        current = self._effective_enabled_set()
        if enabled:
            current.add(interface)
        else:
            current.discard(interface)
        self._persist_enabled_set(current)
        logger.info(
            "Speedtest opt-in updated: %s=%s (new set: %s)",
            interface, enabled, sorted(current),
            extra={"component": "speedtest"},
        )
        return current

    def get_enabled(self) -> set[str]:
        return self._effective_enabled_set()

    # ── On-demand "Run now" ────────────────────────────────────────────────

    def run_once(self, interface: str) -> None:
        """Queue an on-demand run. Returns immediately; the API call won't block."""
        self._on_demand.put(interface)
        logger.info(
            "Speedtest queued on demand: %s", interface,
            extra={"component": "speedtest"},
        )

    # ── Loop ───────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                # Wait briefly for an on-demand request; falling through every
                # ~5s lets us tick the scheduled-per-interface check.
                try:
                    iface_name = self._on_demand.get(timeout=5.0)
                except queue.Empty:
                    iface_name = None
                if iface_name == "__stop__":
                    return
                if iface_name is not None:
                    self._execute(iface_name, source="on_demand")
                # Scheduled check (skip if the binary is missing — log once).
                cfg = self._current_cfg()
                binary = _resolve_speedtest_binary(cfg.speedtest.binary_path)
                if not binary:
                    if not self._binary_warned:
                        logger.warning(
                            "Ookla speedtest binary not found; auto-run disabled "
                            "(set speedtest.binary_path or install the CLI)",
                            extra={"component": "speedtest"},
                        )
                        self._binary_warned = True
                    continue
                self._binary_warned = False
                self._scheduled_tick(cfg)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Speedtest loop error: %s", exc,
                    extra={"component": "speedtest"},
                )

    def _scheduled_tick(self, cfg: "AppConfig") -> None:
        enabled = self._effective_enabled_set()
        if not enabled:
            return
        now = time.time()
        interval = max(60, int(cfg.speedtest.interval_sec))
        for iface in cfg.interfaces:
            if iface.name not in enabled:
                continue
            last = self._last_run_ts.get(iface.name, 0.0)
            if now - last < interval:
                continue
            self._execute(iface.name, source="scheduled")

    def _execute(self, interface: str, *, source: str) -> None:
        cfg = self._current_cfg()
        binary = _resolve_speedtest_binary(cfg.speedtest.binary_path)
        if not binary:
            # Still record so the UI shows "binary missing" with a timestamp.
            result = SpeedtestResult(
                None, None, None, None, None, None, None,
                error="speedtest binary not found",
            )
        else:
            logger.info(
                "Running speedtest on %s (%s)", interface, source,
                extra={"component": "speedtest"},
            )
            result = run_speedtest(
                interface=interface,
                binary_path=binary,
                timeout_sec=cfg.speedtest.run_timeout_sec,
            )
        ts = time.time()
        try:
            self._db.insert_speedtest(
                interface=interface,
                download_mbps=result.download_mbps,
                upload_mbps=result.upload_mbps,
                ping_ms=result.ping_ms,
                jitter_ms=result.jitter_ms,
                packet_loss_pct=result.packet_loss_pct,
                server_name=result.server_name,
                isp=result.isp,
                error=result.error,
                timestamp=ts,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "insert_speedtest(%s) failed: %s", interface, exc,
                extra={"component": "speedtest"},
            )
        self._last_run_ts[interface] = ts
        if result.error:
            logger.warning(
                "Speedtest %s failed: %s", interface, result.error,
                extra={"component": "speedtest"},
            )
        else:
            logger.info(
                "Speedtest %s: down=%.1f Mbps up=%.1f Mbps ping=%.1f ms",
                interface,
                result.download_mbps or 0.0,
                result.upload_mbps or 0.0,
                result.ping_ms or 0.0,
                extra={"component": "speedtest"},
            )
        for fn in self._listeners:
            try:
                fn(interface, result, ts)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Speedtest listener raised: %s", exc,
                    extra={"component": "speedtest"},
                )
