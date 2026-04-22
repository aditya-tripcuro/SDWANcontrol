from __future__ import annotations

import dataclasses
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from gunicorn.app.base import BaseApplication

from wancontrol import __version__
from wancontrol.app import create_app
from wancontrol.auth import Auth
from wancontrol.config import AppConfig, Config, ConfigError
from wancontrol.controller import Controller
from wancontrol.database import Database
from wancontrol.logging_config import setup_logging
from wancontrol.network import check_prerequisites
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


class _GunicornApplication(BaseApplication):
    def __init__(self, app: Any, options: dict[str, Any]) -> None:
        self._app = app
        self._options = options
        super().__init__()

    def load_config(self) -> None:
        for key, value in self._options.items():
            if key in self.cfg.settings and value is not None:
                self.cfg.set(key.lower(), value)

    def load(self) -> Any:
        return self._app


def _start_debug_server(app: Any, host: str, port: int) -> threading.Thread:
    def _run() -> None:
        logger.info(
            "Starting Flask development server",
            extra={"component": "main"},
        )
        app.run(host=host, port=port, debug=True, use_reloader=False, threaded=True)

    thread = threading.Thread(target=_run, name="wancontrol-flask", daemon=True)
    thread.start()
    return thread


def _start_gunicorn(app: Any, host: str, port: int) -> threading.Thread:
    options = {
        "bind": f"{host}:{port}",
        "workers": 1,
        "threads": 4,
        "worker_class": "gthread",
        "timeout": 30,
        "keepalive": 5,
        "accesslog": "-",
        "errorlog": "-",
        "loglevel": "warning",
    }

    def _run() -> None:
        logger.info(
            "Starting gunicorn HTTP server",
            extra={"component": "main"},
        )
        _GunicornApplication(app, options).run()

    thread = threading.Thread(target=_run, name="wancontrol-gunicorn", daemon=True)
    thread.start()
    return thread


def main() -> int:
    config_path = Path(_env_text("WANCONTROL_CONFIG") or "/etc/wancontrol/config.yaml")
    log_level = (_env_text("WANCONTROL_LOG_LEVEL") or "INFO").upper()
    initial_log_dir = _env_text("WANCONTROL_LOG_DIR") or "/var/lib/wancontrol/logs"
    json_logs = _env_flag("WANCONTROL_JSON_LOGS", default=False)
    debug_mode = _env_flag("WANCONTROL_DEBUG", default=False)

    setup_logging(log_level=log_level, log_dir=initial_log_dir, json_logs=json_logs)

    cfg_loader = Config(config_path)
    try:
        cfg = cfg_loader.load()
    except FileNotFoundError as exc:
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

    auth = Auth(db, cfg.server)
    auth.ensure_admin_exists()

    missing = check_prerequisites()
    for tool in missing:
        logger.warning(
            "Missing prerequisite command: %s",
            tool,
            extra={"component": "main"},
        )

    controller = Controller(cfg, db)
    watchdog = Watchdog(cfg, db, controller)

    cfg_loader.register_sighup()
    watchdog.start()

    app = create_app(cfg, cfg_loader, db, controller)

    def _sync_app_config(new_cfg: AppConfig) -> None:
        effective_cfg = _apply_env_overrides(new_cfg)
        app.config["CFG"] = effective_cfg
        app.config["AUTH"] = Auth(db, effective_cfg.server)
        app.secret_key = effective_cfg.server.secret_key

    cfg_loader.on_reload(_sync_app_config)

    _print_banner(config_path, cfg)

    server_thread = _start_debug_server(app, cfg.server.host, cfg.server.port) if debug_mode else _start_gunicorn(
        app,
        cfg.server.host,
        cfg.server.port,
    )

    time.sleep(0.25)
    if not server_thread.is_alive():
        logger.critical(
            "HTTP server failed to start",
            extra={"component": "main"},
        )
        return 1

    try:
        controller.start()
    except KeyboardInterrupt:
        logger.info(
            "Keyboard interrupt received",
            extra={"component": "main"},
        )
        watchdog._handle_signal(signal.SIGINT, None)  # type: ignore[arg-type]
    except Exception:
        logger.exception(
            "Fatal error in controller loop",
            extra={"component": "main"},
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
