"""
wancontrol/config.py
~~~~~~~~~~~~~~~~~~~~
Loads, validates, and provides hot-reload for config.yaml.

Usage:
    from wancontrol.config import Config
    cfg = Config("/etc/wancontrol/config.yaml")
    cfg.load()                     # initial load — raises ConfigError on bad config
    cfg.reload()                   # called on SIGHUP
    ifaces = cfg.interfaces        # returns validated InterfaceConfig list
"""

from __future__ import annotations

import logging
import os
import signal
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

# ── Exceptions ────────────────────────────────────────────────────────────────

class ConfigError(Exception):
    """Raised when config.yaml is missing required keys or has invalid values."""


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InterfaceConfig:
    name: str
    label: str
    expected_speed_mbps: int
    gateway: str
    routing_table_id: int


@dataclass(frozen=True)
class ProbeConfig:
    interval_sec: int
    dns_targets: list[str]
    icmp_targets: list[str]
    http_targets: list[str]
    icmp_count: int
    icmp_timeout_sec: int
    dns_timeout_sec: int
    http_timeout_sec: int


@dataclass(frozen=True)
class ScoringConfig:
    latency_penalty_per_ms: float
    loss_penalty_per_percent: float
    dns_fail_penalty: float
    http_fail_penalty: float
    hard_fail_threshold: float
    hysteresis_switch_to_backup: float
    hysteresis_return_to_primary: float
    recovery_margin: float


@dataclass(frozen=True)
class ControllerConfig:
    loop_interval_sec: int
    benchmark_interval_sec: int
    metric_collection_timeout_sec: int
    heartbeat_interval_sec: int
    heartbeat_stale_sec: int


@dataclass(frozen=True)
class RetentionConfig:
    metrics_hours: int
    events_days: int
    prune_interval_min: int


@dataclass(frozen=True)
class WebhookConfig:
    url: str
    method: str
    headers: dict[str, str]
    on_events: list[str]


@dataclass(frozen=True)
class AlertingConfig:
    enabled: bool
    webhooks: list[WebhookConfig]


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    secret_key: str
    jwt_expiry_hours: int
    session_timeout_minutes: int


@dataclass(frozen=True)
class AppConfig:
    interfaces: list[InterfaceConfig]
    wan_mode: str
    probes: ProbeConfig
    scoring: ScoringConfig
    controller: ControllerConfig
    retention: RetentionConfig
    alerting: AlertingConfig
    server: ServerConfig
    lock_file: str
    heartbeat_file: str
    db_path: str
    log_dir: str

    # Derived helpers
    @property
    def interface_names(self) -> list[str]:
        return [i.name for i in self.interfaces]

    def get_interface(self, name: str) -> InterfaceConfig | None:
        return next((i for i in self.interfaces if i.name == name), None)


# ── Validator helpers ─────────────────────────────────────────────────────────

def _require(d: dict, key: str, section: str = "root") -> Any:
    if key not in d:
        raise ConfigError(f"Missing required key '{key}' in [{section}]")
    return d[key]


def _require_non_empty_list(d: dict, key: str, section: str) -> list:
    val = _require(d, key, section)
    if not isinstance(val, list) or len(val) == 0:
        raise ConfigError(f"[{section}].{key} must be a non-empty list")
    return val


def _require_positive(d: dict, key: str, section: str) -> float:
    val = _require(d, key, section)
    if not isinstance(val, (int, float)) or val <= 0:
        raise ConfigError(f"[{section}].{key} must be a positive number, got {val!r}")
    return val


def _require_non_negative(d: dict, key: str, section: str) -> float:
    val = _require(d, key, section)
    if not isinstance(val, (int, float)) or val < 0:
        raise ConfigError(f"[{section}].{key} must be >= 0, got {val!r}")
    return val


def _require_number(d: dict, key: str, section: str) -> float:
    """Require the key exists and its value is a numeric type (int or float)."""
    val = _require(d, key, section)
    if not isinstance(val, (int, float)):
        raise ConfigError(f"[{section}].{key} must be a number, got {val!r}")
    return val


VALID_WAN_MODES = {"failover", "load_balance"}
VALID_ROLES = {"admin", "operator", "viewer"}
VALID_EVENTS = {
    "link_down", "link_up", "gateway_switch",
    "interface_added_to_pool", "interface_removed_from_pool",
    "controller_error",
}


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_interfaces(raw: list) -> list[InterfaceConfig]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise ConfigError("interfaces must be a list with at least 2 entries")

    seen_names: set[str] = set()
    seen_table_ids: set[int] = set()
    result = []

    for idx, item in enumerate(raw):
        s = f"interfaces[{idx}]"
        name = _require(item, "name", s)
        if not isinstance(name, str) or not name:
            raise ConfigError(f"{s}.name must be a non-empty string")
        if name in seen_names:
            raise ConfigError(f"Duplicate interface name: {name!r}")
        seen_names.add(name)

        table_id = _require(item, "routing_table_id", s)
        if not isinstance(table_id, int) or table_id < 1 or table_id > 252:
            raise ConfigError(f"{s}.routing_table_id must be an integer between 1 and 252 (inclusive), got {table_id!r}")
        if table_id in seen_table_ids:
            raise ConfigError(f"Duplicate routing_table_id: {table_id}")
        seen_table_ids.add(table_id)

        label = str(_require(item, "label", s))
        if not label:
            raise ConfigError(f"{s}.label must be a non-empty string")

        gateway = str(_require(item, "gateway", s))
        if not gateway:
            raise ConfigError(f"{s}.gateway must be a non-empty string")

        result.append(InterfaceConfig(
            name=name,
            label=label,
            expected_speed_mbps=int(_require_positive(item, "expected_speed_mbps", s)),
            gateway=gateway,
            routing_table_id=table_id,
        ))

    return result


def _parse_probes(raw: dict) -> ProbeConfig:
    s = "probes"
    return ProbeConfig(
        interval_sec=int(_require_positive(raw, "interval_sec", s)),
        dns_targets=_require_non_empty_list(raw, "dns_targets", s),
        icmp_targets=_require_non_empty_list(raw, "icmp_targets", s),
        http_targets=_require_non_empty_list(raw, "http_targets", s),
        icmp_count=int(_require_positive(raw, "icmp_count", s)),
        icmp_timeout_sec=int(_require_positive(raw, "icmp_timeout_sec", s)),
        dns_timeout_sec=int(_require_positive(raw, "dns_timeout_sec", s)),
        http_timeout_sec=int(_require_positive(raw, "http_timeout_sec", s)),
    )


def _parse_scoring(raw: dict) -> ScoringConfig:
    s = "scoring"
    return ScoringConfig(
        latency_penalty_per_ms=_require_non_negative(raw, "latency_penalty_per_ms", s),
        loss_penalty_per_percent=_require_non_negative(raw, "loss_penalty_per_percent", s),
        dns_fail_penalty=_require_non_negative(raw, "dns_fail_penalty", s),
        http_fail_penalty=_require_non_negative(raw, "http_fail_penalty", s),
        hard_fail_threshold=_require_number(raw, "hard_fail_threshold", s),
        hysteresis_switch_to_backup=_require_non_negative(raw, "hysteresis_switch_to_backup", s),
        hysteresis_return_to_primary=_require_non_negative(raw, "hysteresis_return_to_primary", s),
        recovery_margin=_require_non_negative(raw, "recovery_margin", s),
    )


def _parse_controller(raw: dict) -> ControllerConfig:
    s = "controller"
    return ControllerConfig(
        loop_interval_sec=int(_require_positive(raw, "loop_interval_sec", s)),
        benchmark_interval_sec=int(_require_positive(raw, "benchmark_interval_sec", s)),
        metric_collection_timeout_sec=int(_require_positive(raw, "metric_collection_timeout_sec", s)),
        heartbeat_interval_sec=int(_require_positive(raw, "heartbeat_interval_sec", s)),
        heartbeat_stale_sec=int(_require_positive(raw, "heartbeat_stale_sec", s)),
    )


def _parse_retention(raw: dict) -> RetentionConfig:
    s = "retention"
    return RetentionConfig(
        metrics_hours=int(_require_positive(raw, "metrics_hours", s)),
        events_days=int(_require_positive(raw, "events_days", s)),
        prune_interval_min=int(_require_positive(raw, "prune_interval_min", s)),
    )


def _parse_alerting(raw: dict) -> AlertingConfig:
    s = "alerting"
    enabled = bool(raw.get("enabled", True))
    webhooks = []
    for idx, wh in enumerate(raw.get("webhooks", [])):
        ws = f"alerting.webhooks[{idx}]"
        url = _require(wh, "url", ws)
        method = str(wh.get("method", "POST")).upper()
        if method not in {"GET", "POST", "PUT"}:
            raise ConfigError(f"{ws}.method must be GET/POST/PUT")
        headers = dict(wh.get("headers", {}))
        on_events = wh.get("on_events", list(VALID_EVENTS))
        invalid = set(on_events) - VALID_EVENTS
        if invalid:
            raise ConfigError(f"{ws}.on_events contains unknown events: {invalid}")
        webhooks.append(WebhookConfig(
            url=url, method=method, headers=headers, on_events=on_events
        ))
    return AlertingConfig(enabled=enabled, webhooks=webhooks)


def _parse_server(raw: dict) -> ServerConfig:
    s = "server"
    secret = str(_require(raw, "secret_key", s)).strip()
    _PLACEHOLDER_KEYS = {
        "CHANGE_THIS_TO_A_RANDOM_STRING",
        "CHANGE_THIS_TO_A_RANDOM_STRING_MIN_32_CHARS",
        "REPLACE_ME_run_python_secrets_token_hex_32",
    }
    if secret in _PLACEHOLDER_KEYS:
        env_secret = os.environ.get("WANCONTROL_SECRET_KEY", "").strip()
        if env_secret and env_secret not in _PLACEHOLDER_KEYS:
            secret = env_secret
        else:
            raise ConfigError(
                "[server].secret_key is still the default placeholder. "
                "Set WANCONTROL_SECRET_KEY (recommended) or replace server.secret_key in config.yaml. "
                "Generate a random string: python3 -c \"import secrets; print(secrets.token_hex(32))\""
            )
    if len(secret) < 32:
        raise ConfigError("[server].secret_key must be at least 32 characters")
    return ServerConfig(
        host=str(raw.get("host", "0.0.0.0")),
        port=int(_require_positive(raw, "port", s)),
        secret_key=secret,
        jwt_expiry_hours=int(_require_positive(raw, "jwt_expiry_hours", s)),
        session_timeout_minutes=int(_require_positive(raw, "session_timeout_minutes", s)),
    )


def _parse(raw: dict) -> AppConfig:
    """Parse and validate a raw YAML dict into AppConfig. Raises ConfigError on any issue."""
    interfaces = _parse_interfaces(_require(raw, "interfaces"))
    wan_mode = str(raw.get("wan_mode", "load_balance"))
    if wan_mode not in VALID_WAN_MODES:
        raise ConfigError(f"wan_mode must be one of {VALID_WAN_MODES}, got {wan_mode!r}")

    return AppConfig(
        interfaces=interfaces,
        wan_mode=wan_mode,
        probes=_parse_probes(_require(raw, "probes")),
        scoring=_parse_scoring(_require(raw, "scoring")),
        controller=_parse_controller(_require(raw, "controller")),
        retention=_parse_retention(_require(raw, "retention")),
        alerting=_parse_alerting(raw.get("alerting", {"enabled": False})),
        server=_parse_server(_require(raw, "server")),
        lock_file=str(raw.get("lock_file", "/run/wancontrol/controller.lock")),
        heartbeat_file=str(raw.get("heartbeat_file", "/run/wancontrol/controller.heartbeat")),
        db_path=str(raw.get("db_path", "/var/lib/wancontrol/wan.db")),
        log_dir=str(raw.get("log_dir", "/var/lib/wancontrol/logs")),
    )


# ── Config singleton ──────────────────────────────────────────────────────────

class Config:
    """
    Thread-safe config loader.

    After construction, call load() once.
    The current config is always available via .current.
    Call reload() on SIGHUP or from the API.

    Example::

        cfg = Config("/etc/wancontrol/config.yaml")
        cfg.load()
        cfg.register_sighup()   # auto-reload on SIGHUP
        ifaces = cfg.current.interfaces
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._current: AppConfig | None = None
        self._reload_callbacks: list[Callable[[AppConfig], None]] = []

    # ── Public interface ───────────────────────────────────────────────────

    def load(self) -> AppConfig:
        """Initial load. Raises ConfigError or FileNotFoundError on failure."""
        cfg = self._read_and_parse()
        with self._lock:
            self._current = cfg
        logger.info(
            "Config loaded",
            extra={"component": "config", "path": str(self._path)},
        )
        return cfg

    def reload(self) -> AppConfig:
        """
        Hot-reload config.yaml.
        On parse failure, keeps the existing config and logs an error.
        Returns the (possibly unchanged) current config.
        """
        try:
            new_cfg = self._read_and_parse()
        except (ConfigError, FileNotFoundError, yaml.YAMLError) as exc:
            logger.error(
                "Config reload failed — keeping existing config: %s", exc,
                extra={"component": "config"},
            )
            return self._current  # type: ignore[return-value]

        with self._lock:
            self._current = new_cfg

        logger.info(
            "Config reloaded successfully",
            extra={"component": "config", "path": str(self._path)},
        )
        for cb in self._reload_callbacks:
            try:
                cb(new_cfg)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Reload callback raised: %s", exc, extra={"component": "config"})

        return new_cfg

    def on_reload(self, callback: Callable[[AppConfig], None]) -> None:
        """Register a callback(new_config: AppConfig) called after successful reload."""
        self._reload_callbacks.append(callback)

    @property
    def current(self) -> AppConfig:
        with self._lock:
            if self._current is None:
                raise RuntimeError("Config.load() has not been called yet")
            return self._current

    # ── Internal ───────────────────────────────────────────────────────────

    def _read_and_parse(self) -> AppConfig:
        if not self._path.exists():
            raise FileNotFoundError(f"Config file not found: {self._path}")
        with self._path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            raise ConfigError("config.yaml must be a YAML mapping at the top level")
        return _parse(raw)
