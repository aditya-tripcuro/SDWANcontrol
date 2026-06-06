from __future__ import annotations

import json
import logging
import logging.config
from pathlib import Path
from typing import Any

import yaml


DEFAULT_FORMAT = "%(asctime)s [%(levelname)-5s] %(component)-12s: %(message)s"
DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


class ComponentFilter(logging.Filter):
    """Ensure all log records expose ``component`` for formatter safety."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "component", None):
            record.component = "unknown"
        return True


class JsonFormatter(logging.Formatter):
    """Render one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        if not getattr(record, "component", None):
            record.component = "unknown"
        payload = {
            "ts": record.created,
            "level": record.levelname,
            "component": record.component,
            "msg": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=True)


def _default_config(log_level: str, log_file: Path, json_logs: bool) -> dict[str, Any]:
    formatter_name = "json" if json_logs else "human"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "human": {
                "format": DEFAULT_FORMAT,
                "datefmt": DEFAULT_DATEFMT,
            },
            "json": {
                "()": "wancontrol.logging_config.JsonFormatter",
            },
        },
        "filters": {
            "inject_component": {
                "()": "wancontrol.logging_config.ComponentFilter",
            }
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "level": "INFO",
                "formatter": formatter_name,
                "filters": ["inject_component"],
                "stream": "ext://sys.stdout",
            },
            # Plain FileHandler — rotation is owned by logrotate (copytruncate),
            # so the process must NOT rotate the file itself (audit item 3).
            "file": {
                "class": "logging.FileHandler",
                "level": "DEBUG",
                "formatter": formatter_name,
                "filters": ["inject_component"],
                "filename": str(log_file),
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "werkzeug": {"level": "WARNING"},
            "urllib3": {"level": "WARNING"},
        },
        "root": {
            "level": log_level.upper(),
            "handlers": ["stdout", "file"],
        },
    }


def _load_yaml_config(log_level: str, log_file: Path, json_logs: bool) -> dict[str, Any] | None:
    candidate_paths = [
        Path("/etc/wancontrol/logging.yaml"),
        Path(__file__).resolve().parent.parent / "logging.yaml",
    ]
    for path in candidate_paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        if not isinstance(cfg, dict):
            raise ValueError(f"logging config must be a mapping: {path}")

        handlers = cfg.setdefault("handlers", {})
        if "stdout" in handlers:
            handlers["stdout"]["formatter"] = "json" if json_logs else "human"
        if "file" in handlers:
            file_handler = handlers["file"]
            file_handler["formatter"] = "json" if json_logs else "human"
            file_handler["filename"] = str(log_file)
            # Rotation is owned by logrotate (copytruncate); force a plain
            # FileHandler even if the YAML still declares a rotating one, and
            # strip rotation-only keys so dictConfig does not reject it (item 3).
            if file_handler.get("class") in (
                "logging.handlers.RotatingFileHandler",
                "logging.handlers.TimedRotatingFileHandler",
            ):
                file_handler["class"] = "logging.FileHandler"
                for rotation_key in ("maxBytes", "backupCount", "when", "interval", "utc"):
                    file_handler.pop(rotation_key, None)

        root = cfg.setdefault("root", {})
        root["level"] = log_level.upper()
        return cfg
    return None


def _reset_root_logger() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def setup_logging(
    log_level: str,
    log_dir: str | Path,
    json_logs: bool = False,
) -> None:
    """Configure stdout + plain file logging for WANControl.

    The file handler is a plain ``logging.FileHandler``; log rotation is owned
    externally by logrotate using ``copytruncate`` (audit item 3), so the
    process never rotates or reopens the log file itself.
    """
    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)
    log_file = log_dir_path / "wancontrol.log"

    _reset_root_logger()

    try:
        config = _load_yaml_config(log_level, log_file, json_logs)
    except Exception as exc:
        print(f"WANControl logging config warning: {exc}; falling back to built-in defaults.")
        config = None

    if config is not None:
        try:
            logging.config.dictConfig(config)
        except Exception as exc:
            print(f"CRITICAL: Failed to configure logging from dict: {exc}. Falling back to default stdout logging.")
            config = None  # Force fallback

    if config is None:
        root = logging.getLogger()
        root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        inject_component = ComponentFilter()
        formatter: logging.Formatter = JsonFormatter() if json_logs else logging.Formatter(
            DEFAULT_FORMAT,
            datefmt=DEFAULT_DATEFMT,
        )

        stdout_handler = logging.StreamHandler()
        stdout_handler.setLevel(logging.INFO)
        stdout_handler.setFormatter(formatter)
        stdout_handler.addFilter(inject_component)

        # Plain FileHandler — logrotate (copytruncate) owns rotation (item 3).
        file_handler = logging.FileHandler(
            log_file,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(inject_component)

        root.addHandler(stdout_handler)
        root.addHandler(file_handler)
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

