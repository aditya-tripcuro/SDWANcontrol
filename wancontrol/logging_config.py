from __future__ import annotations

import json
import logging
import logging.config
from logging.handlers import RotatingFileHandler
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
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "DEBUG",
                "formatter": formatter_name,
                "filters": ["inject_component"],
                "filename": str(log_file),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
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
            handlers["file"]["formatter"] = "json" if json_logs else "human"
            handlers["file"]["filename"] = str(log_file)

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
    """Configure stdout + rotating-file logging for WANControl."""
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
        logging.config.dictConfig(config)
    else:
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

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(inject_component)

        root.addHandler(stdout_handler)
        root.addHandler(file_handler)
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

