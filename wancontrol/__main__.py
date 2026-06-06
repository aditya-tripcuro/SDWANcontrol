"""Entry point: python3 -m wancontrol"""
from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """
    Load key/value pairs from a local .env file into the process environment.

    - Optional override path via WANCONTROL_DOTENV.
    - Does not overwrite existing environment variables.
    - Intentionally minimal parser: KEY=VALUE, optional 'export ' prefix,
      ignores blank lines and '#'-comments.
    """
    override = os.environ.get("WANCONTROL_DOTENV")
    dotenv_path = Path(override).expanduser() if override else (Path.cwd() / ".env")
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return

    try:
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ[key] = value


_load_dotenv()

import dataclasses
import logging
import signal
import subprocess
import sys
import threading
import time
from typing import Any

from wancontrol import __version__
from wancontrol.app import create_app
from wancontrol.config import AppConfig, Config, ConfigError
from wancontrol.controller import Controller
from wancontrol.database import Database
from wancontrol.logging_config import setup_logging
from wancontrol.network import _show_default_routes, check_prerequisites
from wancontrol.speedtest import SpeedtestRunner
from wancontrol.usage import UsageSampler
from wancontrol.watchdog import Watchdog


logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return int(value)


def _env_text(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _apply_env_overrides(cfg: AppConfig) -> AppConfig:
    server = cfg.server

    host = _env_text("WANCONTROL_HOST")
    port = _env_int("WANCONTROL_PORT")
    secret_key = _env_text("WANCONTROL_SECRET_KEY")
    db_path = _env_text("WANCONTROL_DB_PATH")
    log_dir = _env_text("WANCONTROL_LOG_DIR")
    lock_file = _env_text("WANCONTROL_LOCK_FILE")
    heartbeat_file = _env_text("WANCONTROL_HEARTBEAT_FILE")

    if host is not None or port is not None or secret_key is not None:
        server = dataclasses.replace(
            server,
            host=host if host is not None else server.host,
            port=port if port is not None else server.port,
            secret_key=secret_key if secret_key is not None else server.secret_key,
        )

    return dataclasses.replace(
        cfg,
        server=server,
        db_path=db_path if db_path is not None else cfg.db_path,
        log_dir=log_dir if log_dir is not None else cfg.log_dir,
        lock_file=lock_file if lock_file is not None else cfg.lock_file,
        heartbeat_file=heartbeat_file if heartbeat_file is not None else cfg.heartbeat_file,
    )


def _print_banner(config_path: Path, cfg: AppConfig) -> None:
    ifaces = ", ".join(cfg.interface_names)
    lines = [
        f"  WANControl v{__version__}",
        f"  Config : {config_path}",
        f"  DB     : {cfg.db_path}",
        f"  Listen : {cfg.server.host}:{cfg.server.port}",
        f"  Mode   : {cfg.wan_mode}",
        f"  Ifaces : {ifaces}",
    ]
    width = max(len(line) for line in lines)
    print("┌" + "─" * (width + 2) + "┐")
    for line in lines:
        print(f"│{line.ljust(width + 2)}│")
    print("└" + "─" * (width + 2) + "┘")


def _ping_gateway(gateway: str, *, timeout_sec: int = 2) -> bool:
    """Return True if ``gateway`` answers a single ICMP echo within timeout.

    Never raises — any failure (unreachable, missing ping, malformed address)
    is treated as "not yet reachable" so the boot-readiness loop keeps polling.
    """
    cmd = ["ping", "-c", "1", "-W", str(timeout_sec), "-w", str(timeout_sec), gateway]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec + 3)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug(
            "Ping to gateway %s failed to run: %s", gateway, exc, extra={"component": "wait-for-network"}
        )
        return False
    return res.returncode == 0


def _wait_for_network(config_path: Path, *, timeout_sec: int = 120) -> int:
    """Boot-readiness gate (item 4).

    Polls up to ``timeout_sec`` seconds until BOTH conditions hold:
      * a real IPv4 default route exists, AND
      * every configured interface gateway answers an ICMP echo.

    Returns 0 once the network is ready, non-zero on timeout (so systemd's
    ExecStartPre fails fast rather than starting the controller against a link
    that has no real default route yet — the empty-snapshot no-op trigger).
    """
    # Discover configured gateways. If the config cannot be loaded we still
    # gate on a default route existing, but cannot ping per-gateway.
    gateways: list[str] = []
    try:
        cfg = Config(config_path).load()
        gateways = [iface.gateway for iface in cfg.interfaces if iface.gateway]
        gateways += [iface.gateway6 for iface in cfg.interfaces if iface.gateway6]
    except (FileNotFoundError, ConfigError) as exc:
        logger.warning(
            "Could not load config for --wait-for-network gateway list: %s; "
            "gating on default-route presence only",
            exc,
            extra={"component": "wait-for-network"},
        )

    logger.info(
        "Waiting up to %ds for network readiness (default route + %d gateway(s))",
        timeout_sec,
        len(gateways),
        extra={"component": "wait-for-network"},
    )

    deadline = time.monotonic() + timeout_sec
    poll_interval_sec = 2.0
    while True:
        default_routes = _show_default_routes("4")
        have_default = bool(default_routes)  # None or [] both count as "not ready"

        unreachable = [gw for gw in gateways if not _ping_gateway(gw)]
        gateways_ok = not unreachable

        if have_default and gateways_ok:
            logger.info(
                "Network ready: default route present and all gateways reachable",
                extra={"component": "wait-for-network"},
            )
            return 0

        if time.monotonic() >= deadline:
            reasons: list[str] = []
            if not have_default:
                reasons.append("no IPv4 default route")
            if unreachable:
                reasons.append(f"unreachable gateways: {', '.join(unreachable)}")
            logger.critical(
                "Network not ready after %ds: %s",
                timeout_sec,
                "; ".join(reasons) or "unknown",
                extra={"component": "wait-for-network"},
            )
            print(
                f"WANControl --wait-for-network timed out after {timeout_sec}s: "
                f"{'; '.join(reasons) or 'unknown'}",
                file=sys.stderr,
            )
            return 1

        time.sleep(poll_interval_sec)


def main() -> int:
    if "--wait-for-network" in sys.argv:
        log_level = (_env_text("WANCONTROL_LOG_LEVEL") or "INFO").upper()
        wait_log_dir = _env_text("WANCONTROL_LOG_DIR") or "/var/lib/wancontrol/logs"
        json_logs = _env_flag("WANCONTROL_JSON_LOGS", default=False)
        setup_logging(log_level=log_level, log_dir=wait_log_dir, json_logs=json_logs)
        config_path = Path(_env_text("WANCONTROL_CONFIG") or "/etc/wancontrol/config.yaml")
        timeout = _env_int("WANCONTROL_WAIT_FOR_NETWORK_TIMEOUT_SEC") or 120
        return _wait_for_network(config_path, timeout_sec=timeout)

    config_path = Path(_env_text("WANCONTROL_CONFIG") or "/etc/wancontrol/config.yaml")
    log_level = (_env_text("WANCONTROL_LOG_LEVEL") or "INFO").upper()
    initial_log_dir = _env_text("WANCONTROL_LOG_DIR") or "/var/lib/wancontrol/logs"
    json_logs = _env_flag("WANCONTROL_JSON_LOGS", default=False)

    setup_logging(log_level=log_level, log_dir=initial_log_dir, json_logs=json_logs)

    cfg_loader = Config(config_path)
    try:
        cfg = cfg_loader.load()
    except FileNotFoundError:
        logger.critical(
            "Config file not found: %s",
            config_path,
            extra={"component": "main"},
        )
        print(f"WANControl could not start: config file not found: {config_path}", file=sys.stderr)
        return 1
    except ConfigError as exc:
        logger.critical(
            "Invalid configuration: %s",
            exc,
            extra={"component": "main"},
        )
        print(f"WANControl could not start due to invalid configuration: {exc}", file=sys.stderr)
        return 1

    cfg = _apply_env_overrides(cfg)
    if Path(initial_log_dir) != Path(cfg.log_dir):
        setup_logging(log_level=log_level, log_dir=cfg.log_dir, json_logs=json_logs)
        logger.info(
            "Logging reconfigured using effective log directory %s",
            cfg.log_dir,
            extra={"component": "main"},
        )

    db = Database(cfg.db_path)
    db.initialize()

    missing = check_prerequisites()
    if missing:
        logger.critical(
            "Cannot manage routes: missing prerequisite command(s): %s",
            ", ".join(missing),
            extra={"component": "main"},
        )
        print(
            "WANControl could not start: missing required command(s): "
            f"{', '.join(missing)}",
            file=sys.stderr,
        )
        return 1

    controller = Controller(cfg, db)
    watchdog = Watchdog(cfg, db, controller)
    usage_sampler = UsageSampler(cfg, db)
    speedtest_runner = SpeedtestRunner(cfg, db)

    # Holder for the waitress server; populated just before we serve. The
    # SIGTERM/SIGINT handler closes it so server.run() returns and the process
    # actually exits (items 26/27).
    server_holder: dict[str, Any] = {"server": None}

    # ── Signal Handlers ───────────────────────────────────────────────────
    # Signals must be registered in the main thread.

    def _shutdown_handler(signum: int, frame: object) -> None:
        sig_name = signal.Signals(signum).name
        logger.info(
            "Signal received (%s), shutting down", sig_name,
            extra={"component": "main"},
        )
        controller.shutdown()
        watchdog.stop()
        speedtest_runner.stop()
        usage_sampler.stop()
        # Close the waitress server so server.run() returns and main() exits
        # (item 27 — waitress does not self-terminate on SIGTERM).
        server = server_holder.get("server")
        if server is not None:
            try:
                server.close()
            except Exception as exc:  # noqa: BLE001 — shutdown must not raise out of a signal handler
                logger.warning(
                    "Error closing HTTP server during shutdown: %s",
                    exc,
                    extra={"component": "main"},
                )

    def _reload_handler(signum: int, frame: object) -> None:
        logger.info("SIGHUP received — reloading config", extra={"component": "main"})
        cfg_loader.reload()

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGHUP, _reload_handler)

    # ── Start Background Tasks ────────────────────────────────────────────

    watchdog.start()
    usage_sampler.start()
    speedtest_runner.start()

    if cfg.controller.auto_start:
        controller.start()
    else:
        db.set_state("controller_mode", "STOPPED")
        db.set_state("controller_status", "stopped")
        logger.info("Controller route management is stopped; use Start to apply routes", extra={"component": "main"})

    # ── Start Web Server ──────────────────────────────────────────────────

    app = create_app(
        cfg, cfg_loader, db, controller,
        usage_sampler=usage_sampler,
        speedtest_runner=speedtest_runner,
    )

    def _sync_app_config(new_cfg: AppConfig) -> None:
        effective_cfg = _apply_env_overrides(new_cfg)
        app.config["CFG"] = effective_cfg
        controller.update_config(effective_cfg)
        # Propagate the reload to the watchdog so its staleness/pruning loop
        # uses the new config too (item 19 wiring; safe via getattr in case the
        # watchdog landed without update_config).
        wd_update = getattr(watchdog, "update_config", None)
        if callable(wd_update):
            wd_update(effective_cfg)
        usage_sampler.update_config(effective_cfg)
        speedtest_runner.update_config(effective_cfg)

    cfg_loader.on_reload(_sync_app_config)

    _print_banner(config_path, cfg)

    from waitress import create_server

    logger.info(
        "Starting waitress HTTP server on %s:%s",
        cfg.server.host,
        cfg.server.port,
        extra={"component": "main"},
    )
    server = create_server(
        app,
        host=cfg.server.host,
        port=cfg.server.port,
        threads=8,
    )
    server_holder["server"] = server
    # Blocks until the server is closed (by the SIGTERM/SIGINT handler) so the
    # process exits cleanly on stop (items 26/27).
    server.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
