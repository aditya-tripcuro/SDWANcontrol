"""
wancontrol/app.py
~~~~~~~~~~~~~~~~~
Flask REST API layer for WANControl v2.

All endpoints are under /api and return application/json.
No authentication — designed for trusted local network use.
Unix timestamps are returned as floats.
"""

from __future__ import annotations

import dataclasses
import functools
import ipaddress
import logging
import secrets
import threading
import time
import traceback
from typing import TYPE_CHECKING, Any
import json as _json
from pathlib import Path
import yaml

from flask import (
    Blueprint,
    Flask,
    Response,
    abort,
    current_app,
    jsonify,
    request,
    stream_with_context,
    send_from_directory,
)

from wancontrol import __version__
from wancontrol.auth import Auth, AuthError, UserPrincipal
from wancontrol.config import AppConfig, Config, ConfigError, VALID_WAN_MODES, _parse_interfaces
from wancontrol.database import Database, MetricRow, SpeedtestRow, UsageRow, UserRow
from wancontrol.network_discovery import DiscoveredInterface, discover_interfaces, generate_config_fragment_dict

if TYPE_CHECKING:
    from wancontrol.controller import Controller
    from wancontrol.speedtest import SpeedtestRunner
    from wancontrol.usage import UsageSampler

logger = logging.getLogger(__name__)

REDACTED = "***REDACTED***"

# Header names (lower-cased) that carry secrets on outbound webhook calls and
# must be scrubbed from any config exposed over the API (item 2).
_SENSITIVE_HEADER_NAMES = frozenset({
    "authorization",
    "x-api-token",
    "x-api-key",
    "api-key",
    "proxy-authorization",
    "x-auth-token",
    "x-webhook-secret",
})

# ── Blueprint ──────────────────────────────────────────────────────────────────

api_bp = Blueprint("api", __name__, url_prefix="/api")

PUBLIC_ENDPOINTS = {
    "api.health",
    "api.auth_config",
    "api.login",
}


class _StreamTicketStore:
    """Short-lived, single-use tickets for SSE authentication.

    A browser's EventSource API cannot send Authorization/X-API-Token headers,
    and the ?token= query path was removed (item 31) so long-lived credentials
    never appear in URLs/logs. Instead a client POSTs to /api/stream/ticket with
    normal header auth, receives a single-use ticket that expires in TTL_SEC, and
    opens EventSource("/api/stream?ticket=<ticket>"). The ticket is consumed on
    connect, is short-lived, and carries no reusable secret.
    """

    TTL_SEC = 30.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tickets: dict[str, tuple[UserPrincipal, float]] = {}

    def _prune(self, now: float) -> None:
        for tok in [t for t, (_, exp) in self._tickets.items() if now > exp]:
            self._tickets.pop(tok, None)

    def issue(self, principal: UserPrincipal, now: float) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune(now)
            self._tickets[token] = (principal, now + self.TTL_SEC)
        return token

    def consume(self, token: str, now: float) -> UserPrincipal | None:
        with self._lock:
            self._prune(now)
            entry = self._tickets.pop(token, None)
        if entry is None:
            return None
        principal, expiry = entry
        return principal if now <= expiry else None

ROLE_REQUIREMENTS: dict[tuple[str, str], str] = {
    ("GET", "/api/users"): "admin",
    ("GET", "/api/config/raw"): "admin",
    ("GET", "/api/db/stats"): "admin",
    ("POST", "/api/db/flush"): "admin",
    ("POST", "/api/db/prune"): "admin",
    ("POST", "/api/alerts"): "operator",
    ("POST", "/api/config/reload"): "operator",
    ("PUT", "/api/config/interfaces"): "operator",
    ("PUT", "/api/config/wan-mode"): "operator",
    ("POST", "/api/control/start"): "operator",
    ("POST", "/api/control/pause"): "operator",
    ("POST", "/api/control/resume"): "operator",
    ("POST", "/api/control/stop"): "operator",
    ("POST", "/api/control/kill"): "operator",
    ("POST", "/api/speedtest/run"): "operator",
    ("PATCH", "/api/speedtest/enabled"): "operator",
}


def _auth_enabled() -> bool:
    cfg: AppConfig = current_app.config["CFG"]
    return bool(getattr(cfg.server, "auth_enabled", True))


def _shadow_mode_enabled() -> bool:
    """Return True when shadow (dry-run Layer 1) mode is active.

    Delegates to network._shadow_enabled() so the API banner agrees exactly
    with what the route layer is doing; falls back to reading the env var
    directly if network lands without that helper.
    """
    try:
        from wancontrol import network

        checker = getattr(network, "_shadow_enabled", None)
        if callable(checker):
            return bool(checker())
    except ImportError:
        pass
    import os

    return os.environ.get("WANCONTROL_SHADOW", "").strip().lower() in {"1", "true", "yes", "on"}


def _remote_addr_allowed() -> bool:
    """Item 1: enforce server.allowed_cidrs against the request's remote_addr.

    Returns True when no allow-list is configured (empty/missing) or when the
    peer address falls inside at least one configured CIDR. An unparseable
    allow-list entry is ignored (does not widen access); an unparseable
    remote_addr is rejected when an allow-list is present.
    """
    cfg: AppConfig = current_app.config["CFG"]
    allowed = getattr(cfg.server, "allowed_cidrs", None) or []
    if not allowed:
        return True

    remote = request.remote_addr
    if not remote:
        return False
    try:
        peer = ipaddress.ip_address(remote)
    except ValueError:
        return False

    for entry in allowed:
        try:
            network = ipaddress.ip_network(str(entry), strict=False)
        except ValueError:
            logger.warning(
                "Ignoring invalid allowed_cidrs entry %r", entry,
                extra={"component": "api"},
            )
            continue
        if peer.version == network.version and peer in network:
            return True
    return False


def _local_principal() -> UserPrincipal:
    return UserPrincipal(
        user_id=0,
        username="local",
        role="admin",
        source="disabled",
        requires_password_change=False,
    )


def _auth() -> Auth:
    return current_app.config["AUTH"]


def _json_auth_error(exc: AuthError, status: int) -> tuple[Response, int]:
    return jsonify({"error": exc.code, "message": exc.message}), status


def _principal_from_request() -> UserPrincipal:
    if not _auth_enabled():
        return _local_principal()

    api_token = request.headers.get("X-API-Token")
    if api_token:
        return _auth().verify_api_token(api_token)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return _auth().verify_token(auth_header.split(" ", 1)[1].strip())

    # Item 31: tokens are accepted via headers only; the ?token= query-string
    # branch was removed so credentials never land in URLs / access logs.
    raise AuthError("Authentication required.", "authentication_required")


def current_principal() -> UserPrincipal:
    principal = getattr(request, "principal", None)
    if principal is None:
        principal = _principal_from_request()
        setattr(request, "principal", principal)
    return principal


def require_role(minimum_role: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            principal = current_principal()
            try:
                _auth().require_role(principal, minimum_role)
            except AuthError as exc:
                return _json_auth_error(exc, 403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# ── Serialisation helpers ──────────────────────────────────────────────────────

def _user_to_dict(user: UserRow) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "created_at": user.created_at,
        "last_login": user.last_login,
        "is_active": user.is_active,
    }


def _metric_to_dict(m: MetricRow) -> dict[str, Any]:
    return {
        "id": m.id,
        "interface": m.interface,
        "timestamp": m.timestamp,
        "latency_ms": m.latency_ms,
        "jitter_ms": m.jitter_ms,
        "loss_pct": m.loss_pct,
        "dns_ok": bool(m.dns_ok),
        "http_ok": bool(m.http_ok),
        "score": m.score,
    }


def _speedtest_to_dict(s: SpeedtestRow) -> dict[str, Any]:
    return {
        "id": s.id,
        "interface": s.interface,
        "timestamp": s.timestamp,
        "download_mbps": s.download_mbps,
        "upload_mbps": s.upload_mbps,
        "ping_ms": s.ping_ms,
        "jitter_ms": s.jitter_ms,
        "packet_loss_pct": s.packet_loss_pct,
        "server_name": s.server_name,
        "isp": s.isp,
        "error": s.error,
    }


def _usage_to_dict(u: UsageRow) -> dict[str, Any]:
    return {
        "id": u.id,
        "interface": u.interface,
        "timestamp": u.timestamp,
        "rx_mbps": u.rx_mbps,
        "tx_mbps": u.tx_mbps,
        "rx_bytes_total": u.rx_bytes_total,
        "tx_bytes_total": u.tx_bytes_total,
    }


def _alert_to_dict(a) -> dict[str, Any]:
    return {
        "id": a.id,
        "timestamp": a.timestamp,
        "level": a.level,
        "title": a.title,
        "body": a.body,
        "resolved_at": a.resolved_at,
        "notified": bool(a.notified),
    }


def _discovered_interface_to_dict(iface: DiscoveredInterface) -> dict[str, Any]:
    return {
        "name": iface.name,
        "label": iface.label,
        "mac": iface.mac,
        "ip": iface.ip,
        "prefix_len": iface.prefix_len,
        "gateway": iface.gateway,
        "speed_mbps": iface.speed_mbps,
        "is_up": iface.is_up,
        "is_reachable": iface.is_reachable,
        "is_wan_candidate": iface.is_wan_candidate,
        "skip_reason": iface.skip_reason,
        "suggested_routing_table_id": iface.suggested_routing_table_id,
    }


def _redact_raw_config(data: Any) -> Any:
    """Return a copy of parsed config.yaml with secrets scrubbed (item 2).

    Redacts ``server.secret_key`` and any auth-bearing headers configured on
    alerting webhooks. The input is never mutated.
    """
    if not isinstance(data, dict):
        return data

    redacted: dict[str, Any] = dict(data)

    server = redacted.get("server")
    if isinstance(server, dict) and "secret_key" in server:
        server = dict(server)
        server["secret_key"] = REDACTED
        redacted["server"] = server

    alerting = redacted.get("alerting")
    if isinstance(alerting, dict):
        webhooks = alerting.get("webhooks")
        if isinstance(webhooks, list):
            new_webhooks = []
            for wh in webhooks:
                if isinstance(wh, dict) and isinstance(wh.get("headers"), dict):
                    wh = dict(wh)
                    wh["headers"] = {
                        k: (REDACTED if str(k).lower() in _SENSITIVE_HEADER_NAMES else v)
                        for k, v in wh["headers"].items()
                    }
                new_webhooks.append(wh)
            alerting = dict(alerting)
            alerting["webhooks"] = new_webhooks
            redacted["alerting"] = alerting

    return redacted


def _sync_reloaded_config(new_cfg: AppConfig) -> None:
    """Propagate a reloaded config into the running app (items 21/29).

    This ONLY swaps the cached AppConfig + rebuilds Auth and delegates route
    reconciliation to ``Controller.update_config`` (which performs the
    diff-based, lock-guarded teardown/setup). It MUST NOT call
    ``setup_all_interfaces`` itself — doing so would double-apply routes on top
    of the controller's own diff. Env overrides are already re-applied inside
    ``Config.reload()`` (the parse path reads WANCONTROL_* every time).
    """
    current_app.config["CFG"] = new_cfg
    current_app.config["AUTH"] = Auth(db=current_app.config["DB"], server_cfg=new_cfg.server)
    controller: Controller = current_app.config["CONTROLLER"]
    update = getattr(controller, "update_config", None)
    if callable(update):
        update(new_cfg)


# ── Health ─────────────────────────────────────────────────────────────────────

@api_bp.route("/health", methods=["GET"])
def health() -> tuple[Response, int]:
    return jsonify({
        "status": "ok",
        "version": __version__,
        "timestamp": time.time(),
    }), 200


@api_bp.route("/auth/config", methods=["GET"])
def auth_config() -> tuple[Response, int]:
    return jsonify({"auth_enabled": _auth_enabled()}), 200


@api_bp.route("/auth/login", methods=["POST"])
def login() -> tuple[Response, int]:
    if not _auth_enabled():
        return jsonify({
            "access_token": "",
            "token_type": "disabled",
            "expires_in": 0,
            "requires_password_change": False,
        }), 200

    body = request.get_json(force=True, silent=True) or {}
    username = body.get("username")
    password = body.get("password")
    if not username or not password:
        return jsonify({"error": "bad_request", "message": "username and password are required."}), 400
    try:
        pair = _auth().authenticate(str(username), str(password))
    except AuthError as exc:
        return _json_auth_error(exc, 401)
    return jsonify(dataclasses.asdict(pair)), 200


@api_bp.route("/auth/logout", methods=["POST"])
def logout() -> tuple[Response, int]:
    return jsonify({"logged_out": True}), 200


@api_bp.route("/auth/change-password", methods=["POST"])
def change_password() -> tuple[Response, int]:
    principal = current_principal()
    if principal.user_id == 0:
        return jsonify({"changed": True}), 200
    body = request.get_json(force=True, silent=True) or {}
    old_password = body.get("old_password")
    new_password = body.get("new_password")
    if not old_password or not new_password:
        return jsonify({"error": "bad_request", "message": "old_password and new_password are required."}), 400
    try:
        _auth().change_password(principal.user_id, str(old_password), str(new_password))
    except AuthError as exc:
        return _json_auth_error(exc, 400)
    return jsonify({"changed": True}), 200


# ── Status ─────────────────────────────────────────────────────────────────────

@api_bp.route("/status", methods=["GET"])
def get_status() -> tuple[Response, int]:
    controller: Controller = current_app.config["CONTROLLER"]
    status = dict(controller.get_status())
    status["shadow_mode"] = _shadow_mode_enabled()
    return jsonify(status), 200


@api_bp.route("/status/interfaces", methods=["GET"])
def get_interfaces_status() -> tuple[Response, int]:
    cfg: AppConfig = current_app.config["CFG"]
    controller: Controller = current_app.config["CONTROLLER"]
    status = controller.get_status()
    iface_states = status.get("interfaces", {})

    result = []
    for iface_cfg in cfg.interfaces:
        live = iface_states.get(iface_cfg.name, {})
        result.append({
            "name": iface_cfg.name,
            "label": iface_cfg.label,
            "expected_speed_mbps": iface_cfg.expected_speed_mbps,
            "gateway": iface_cfg.gateway,
            "routing_table_id": iface_cfg.routing_table_id,
            "wan_state": live.get("wan_state"),
            "score": live.get("score"),
            "in_pool": live.get("in_pool"),
        })
    return jsonify(result), 200


@api_bp.route("/control/start", methods=["POST"])
def control_start() -> tuple[Response, int]:
    controller: Controller = current_app.config["CONTROLLER"]
    controller.start()
    return jsonify(controller.get_status()), 200


@api_bp.route("/control/pause", methods=["POST"])
def control_pause() -> tuple[Response, int]:
    controller: Controller = current_app.config["CONTROLLER"]
    controller.pause()
    return jsonify(controller.get_status()), 200


@api_bp.route("/control/resume", methods=["POST"])
def control_resume() -> tuple[Response, int]:
    controller: Controller = current_app.config["CONTROLLER"]
    controller.resume()
    return jsonify(controller.get_status()), 200


@api_bp.route("/control/stop", methods=["POST"])
def control_stop() -> tuple[Response, int]:
    controller: Controller = current_app.config["CONTROLLER"]
    controller.stop()
    return jsonify(controller.get_status()), 200


@api_bp.route("/control/kill", methods=["POST"])
def control_kill() -> tuple[Response, int]:
    controller: Controller = current_app.config["CONTROLLER"]
    controller.kill()
    return jsonify(controller.get_status()), 200


# ── Metrics ────────────────────────────────────────────────────────────────────

@api_bp.route("/metrics", methods=["GET"])
def get_metrics() -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    interface = request.args.get("interface") or None

    try:
        limit = int(request.args.get("limit", 200))
    except ValueError:
        return jsonify({"error": "bad_request", "message": "limit must be an integer."}), 400

    since: float | None = None
    since_str = request.args.get("since")
    if since_str:
        try:
            since = float(since_str)
        except ValueError:
            return jsonify({"error": "bad_request", "message": "since must be a float."}), 400

    rows = db.get_metrics(interface=interface, limit=limit, since=since)
    return jsonify([_metric_to_dict(m) for m in rows]), 200


@api_bp.route("/metrics/latest", methods=["GET"])
def get_latest_metrics() -> tuple[Response, int]:
    cfg: AppConfig = current_app.config["CFG"]
    db: Database = current_app.config["DB"]
    result: dict[str, Any] = {}
    for iface_cfg in cfg.interfaces:
        row = db.get_latest_metric(iface_cfg.name)
        result[iface_cfg.name] = _metric_to_dict(row) if row else None
    return jsonify(result), 200


# ── Speedtest ─────────────────────────────────────────────────────────────────

def _parse_query_window(default_limit: int) -> tuple[int, float | None, Response | None]:
    """Parse the shared ?interface/?limit/?since query for history endpoints.

    Returns (limit, since, error_response). When error_response is not None
    the caller should return it immediately. The interface filter is read by
    the caller directly via ``request.args.get("interface")``.
    """
    try:
        limit = int(request.args.get("limit", default_limit))
    except ValueError:
        return 0, None, jsonify({"error": "bad_request", "message": "limit must be an integer."})
    since: float | None = None
    since_str = request.args.get("since")
    if since_str:
        try:
            since = float(since_str)
        except ValueError:
            return 0, None, jsonify({"error": "bad_request", "message": "since must be a float."})
    return limit, since, None


@api_bp.route("/speedtest", methods=["GET"])
def get_speedtests() -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    interface = request.args.get("interface") or None
    limit, since, err = _parse_query_window(default_limit=100)
    if err is not None:
        return err, 400
    rows = db.get_speedtests(interface=interface, limit=limit, since=since)
    return jsonify([_speedtest_to_dict(r) for r in rows]), 200


@api_bp.route("/speedtest/latest", methods=["GET"])
def get_latest_speedtests() -> tuple[Response, int]:
    cfg: AppConfig = current_app.config["CFG"]
    db: Database = current_app.config["DB"]
    result: dict[str, Any] = {}
    for iface_cfg in cfg.interfaces:
        row = db.get_latest_speedtest(iface_cfg.name)
        result[iface_cfg.name] = _speedtest_to_dict(row) if row else None
    return jsonify(result), 200


@api_bp.route("/speedtest/enabled", methods=["GET"])
def get_speedtest_enabled() -> tuple[Response, int]:
    """Per-interface opt-in flags for the dashboard toggle."""
    cfg: AppConfig = current_app.config["CFG"]
    runner: "SpeedtestRunner | None" = current_app.config.get("SPEEDTEST_RUNNER")
    if runner is None:
        # No live runner (e.g. tests with stub controller only) — report whatever
        # the YAML says so the UI can still render the panel.
        enabled = set(cfg.speedtest.enabled_interfaces)
    else:
        enabled = runner.get_enabled()
    return jsonify({iface.name: iface.name in enabled for iface in cfg.interfaces}), 200


@api_bp.route("/speedtest/enabled", methods=["PATCH"])
def patch_speedtest_enabled() -> tuple[Response, int]:
    body = request.get_json(force=True, silent=True) or {}
    interface = body.get("interface")
    enabled = body.get("enabled")
    if not isinstance(interface, str) or not interface:
        return jsonify({
            "error": "bad_request",
            "message": "interface is required.",
        }), 400
    if not isinstance(enabled, bool):
        return jsonify({
            "error": "bad_request",
            "message": "enabled must be a boolean.",
        }), 400
    cfg: AppConfig = current_app.config["CFG"]
    if cfg.get_interface(interface) is None:
        return jsonify({
            "error": "not_found",
            "message": f"unknown interface {interface!r}",
        }), 404
    runner: "SpeedtestRunner | None" = current_app.config.get("SPEEDTEST_RUNNER")
    if runner is None:
        return jsonify({
            "error": "unavailable",
            "message": "speedtest runner not configured",
        }), 503
    new_set = runner.set_enabled(interface, enabled)
    return jsonify({
        "interface": interface,
        "enabled": enabled,
        "enabled_set": sorted(new_set),
    }), 200


@api_bp.route("/speedtest/run", methods=["POST"])
def post_speedtest_run() -> tuple[Response, int]:
    body = request.get_json(force=True, silent=True) or {}
    interface = body.get("interface")
    if not isinstance(interface, str) or not interface:
        return jsonify({
            "error": "bad_request",
            "message": "interface is required.",
        }), 400
    cfg: AppConfig = current_app.config["CFG"]
    if cfg.get_interface(interface) is None:
        return jsonify({
            "error": "not_found",
            "message": f"unknown interface {interface!r}",
        }), 404
    runner: "SpeedtestRunner | None" = current_app.config.get("SPEEDTEST_RUNNER")
    if runner is None:
        return jsonify({
            "error": "unavailable",
            "message": "speedtest runner not configured",
        }), 503
    runner.run_once(interface)
    return jsonify({"queued": True, "interface": interface}), 202


# ── Network usage (rx/tx throughput) ──────────────────────────────────────────

@api_bp.route("/usage", methods=["GET"])
def get_usage() -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    interface = request.args.get("interface") or None
    limit, since, err = _parse_query_window(default_limit=720)
    if err is not None:
        return err, 400
    rows = db.get_usage(interface=interface, limit=limit, since=since)
    return jsonify([_usage_to_dict(r) for r in rows]), 200


# ── Interface discovery ───────────────────────────────────────────────────────

@api_bp.route("/interfaces/discover", methods=["GET"])
def discover_network_interfaces() -> tuple[Response, int]:
    interfaces = discover_interfaces()
    return jsonify({
        "interfaces": [_discovered_interface_to_dict(i) for i in interfaces],
        "suggested_config": generate_config_fragment_dict(interfaces),
    }), 200


# ── Events ─────────────────────────────────────────────────────────────────────

@api_bp.route("/events/switches", methods=["GET"])
def get_switch_events() -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        return jsonify({"error": "bad_request", "message": "limit must be an integer."}), 400
    rows = db.get_switch_events(limit=limit)
    return jsonify([dataclasses.asdict(r) for r in rows]), 200


@api_bp.route("/events/controller", methods=["GET"])
def get_controller_events() -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        return jsonify({"error": "bad_request", "message": "limit must be an integer."}), 400
    level = request.args.get("level") or None
    rows = db.get_events(limit=limit, level=level)
    return jsonify([dataclasses.asdict(r) for r in rows]), 200


# ── Alerts ─────────────────────────────────────────────────────────────────────

@api_bp.route("/alerts", methods=["GET"])
def get_alerts() -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    try:
        limit = int(request.args.get("limit", 20))
    except ValueError:
        return jsonify({"error": "bad_request", "message": "limit must be an integer."}), 400
    rows = db.get_recent_alerts(limit=limit)
    return jsonify([dataclasses.asdict(r) for r in rows]), 200


@api_bp.route("/alerts/<int:alert_id>/resolve", methods=["POST"])
def resolve_alert(alert_id: int) -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    existing = db.get_recent_alerts(limit=100_000)
    if not any(a.id == alert_id for a in existing):
        return jsonify({"error": "not_found", "message": "Alert not found."}), 404
    db.resolve_alert(alert_id)
    return jsonify({"resolved": True, "alert_id": alert_id}), 200


# ── Users ──────────────────────────────────────────────────────────────────────

@api_bp.route("/users", methods=["GET"])
def list_users() -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    return jsonify([_user_to_dict(u) for u in db.list_users()]), 200


@api_bp.route("/users", methods=["POST"])
def create_user() -> tuple[Response, int]:
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "bad_request", "message": "valid JSON body required."}), 400
    try:
        user_id = _auth().create_user(
            str(body.get("username") or ""),
            str(body.get("password") or ""),
            str(body.get("role") or "viewer"),
            created_by_user_id=current_principal().user_id,
        )
    except (AuthError, ValueError) as exc:
        return jsonify({"error": getattr(exc, "code", "bad_request"), "message": str(exc)}), 400
    user = current_app.config["DB"].get_user_by_id(user_id)
    return jsonify(_user_to_dict(user)), 201


@api_bp.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id: int) -> tuple[Response, int]:
    user = current_app.config["DB"].get_user_by_id(user_id)
    if user is None:
        return jsonify({"error": "not_found", "message": "User not found."}), 404
    return jsonify(_user_to_dict(user)), 200


@api_bp.route("/users/<int:user_id>/deactivate", methods=["POST"])
def deactivate_user(user_id: int) -> tuple[Response, int]:
    try:
        _auth().deactivate_user(user_id, current_principal().user_id)
    except AuthError as exc:
        return _json_auth_error(exc, 404)
    return jsonify({"deactivated": True, "id": user_id}), 200


@api_bp.route("/users/<int:user_id>/role", methods=["POST"])
def update_user_role(user_id: int) -> tuple[Response, int]:
    body = request.get_json(force=True, silent=True) or {}
    try:
        _auth().update_role(user_id, str(body.get("role") or ""), current_principal().user_id)
    except (AuthError, ValueError) as exc:
        return jsonify({"error": getattr(exc, "code", "bad_request"), "message": str(exc)}), 400
    return jsonify({"updated": True, "id": user_id}), 200


@api_bp.route("/tokens", methods=["GET"])
def list_tokens() -> tuple[Response, int]:
    principal = current_principal()
    rows = _auth().list_api_tokens(user_id=None if principal.role == "admin" else principal.user_id)
    return jsonify([dataclasses.asdict(r) for r in rows]), 200


@api_bp.route("/tokens", methods=["POST"])
def create_token() -> tuple[Response, int]:
    principal = current_principal()
    body = request.get_json(force=True, silent=True) or {}
    label = str(body.get("label") or "").strip()
    if not label:
        return jsonify({"error": "bad_request", "message": "label is required."}), 400
    expires = body.get("expires_in_days")
    try:
        expires_days = int(expires) if expires is not None else None
    except (TypeError, ValueError):
        return jsonify({"error": "bad_request", "message": "expires_in_days must be an integer."}), 400
    try:
        token = _auth().create_api_token(principal.user_id, label, expires_days)
    except AuthError as exc:
        return _json_auth_error(exc, 400)
    rows = _auth().list_api_tokens(user_id=principal.user_id)
    token_id = rows[0].id if rows else None
    return jsonify({"id": token_id, "token": token, "label": label}), 201


@api_bp.route("/tokens/<int:token_id>", methods=["DELETE"])
def revoke_token(token_id: int) -> tuple[Response, int]:
    principal = current_principal()
    rows = _auth().list_api_tokens(user_id=None if principal.role == "admin" else principal.user_id)
    if not any(row.id == token_id for row in rows):
        return jsonify({"error": "insufficient_role", "message": "Cannot revoke another user's token."}), 403
    _auth().revoke_api_token(token_id, principal.user_id)
    return jsonify({"revoked": True, "id": token_id}), 200


# ── Config reload ──────────────────────────────────────────────────────────────

@api_bp.route("/config/reload", methods=["POST"])
def reload_config() -> tuple[Response, int]:
    cfg: AppConfig = current_app.config["CFG"]
    cfg_loader: Config = current_app.config["CFG_LOADER"]
    new_cfg = cfg_loader.reload()
    _sync_reloaded_config(new_cfg)
    reloaded = new_cfg is not cfg
    return jsonify({
        "reloaded": reloaded,
        "wan_mode": new_cfg.wan_mode,
        "interfaces": len(new_cfg.interfaces),
    }), 200


# ── Database admin ─────────────────────────────────────────────────────────────

@api_bp.route("/db/stats", methods=["GET"])
def db_stats() -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    return jsonify(dataclasses.asdict(db.get_db_stats())), 200


@api_bp.route("/db/prune", methods=["POST"])
def db_prune() -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    cfg: AppConfig = current_app.config["CFG"]
    result = db.prune_old_data(cfg.retention.metrics_hours, cfg.retention.events_days)
    return jsonify(result), 200


@api_bp.route("/db/flush", methods=["POST"])
def db_flush() -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    db.flush_all_data()
    return jsonify({"flushed": True}), 200


# ── SSE stream ─────────────────────────────────────────────────────────────────

@api_bp.route("/stream/ticket", methods=["POST"])
def sse_ticket():
    """Mint a short-lived single-use ticket for EventSource (see _StreamTicketStore).

    Requires normal auth (enforced by before_request). The ticket inherits the
    caller's principal/role and is the only credential the browser puts in the
    /api/stream URL.
    """
    principal = current_principal()
    store: _StreamTicketStore = current_app.config["STREAM_TICKETS"]
    ticket = store.issue(principal, time.time())
    return jsonify({"ticket": ticket, "expires_in": int(_StreamTicketStore.TTL_SEC)}), 200


@api_bp.route("/stream", methods=["GET"])
def sse_stream():
    controller: Controller = current_app.config["CONTROLLER"]
    cfg: AppConfig = current_app.config["CFG"]
    db: Database = current_app.config["DB"]

    def event_stream():
        last_alert_id = 0
        last_speedtest_ids: dict[str, int] = {}
        while True:
            status = controller.get_status()
            yield f"event: status\ndata: {_json.dumps(status)}\n\n"

            latest = {
                iface.name: (
                    _metric_to_dict(row) if (row := db.get_latest_metric(iface.name)) else None
                )
                for iface in cfg.interfaces
            }
            yield f"event: metric\ndata: {_json.dumps(latest)}\n\n"

            # Latest usage sample per interface (cheap; one row each).
            usage_latest: dict[str, Any] = {}
            for iface in cfg.interfaces:
                rows = db.get_usage(interface=iface.name, limit=1)
                usage_latest[iface.name] = _usage_to_dict(rows[0]) if rows else None
            yield f"event: usage\ndata: {_json.dumps(usage_latest)}\n\n"

            # Newest speedtest per interface — emit only when the ID changes so
            # we don't spam the chart with the same row every 5s.
            for iface in cfg.interfaces:
                row = db.get_latest_speedtest(iface.name)
                if row is None:
                    continue
                prev_id = last_speedtest_ids.get(iface.name)
                if prev_id != row.id:
                    last_speedtest_ids[iface.name] = row.id
                    yield f"event: speedtest\ndata: {_json.dumps(_speedtest_to_dict(row))}\n\n"

            for alert in db.get_unnotified_alerts():
                if alert.id > last_alert_id:
                    last_alert_id = alert.id
                    yield f"event: alert\ndata: {_json.dumps(_alert_to_dict(alert))}\n\n"

            time.sleep(5)

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Shadow mode (dry-run Layer 1) ───────────────────────────────────────────────

def _intended_route_to_dict(row: Any) -> dict[str, Any]:
    """Normalise an intended-route record (dataclass / dict / tuple) to JSON."""
    if dataclasses.is_dataclass(row) and not isinstance(row, type):
        return dataclasses.asdict(row)
    if isinstance(row, dict):
        return dict(row)
    # Fallback for sqlite Row / tuple shaped as (id, ts, command).
    try:
        return {"id": row[0], "ts": row[1], "command": row[2]}
    except (TypeError, IndexError, KeyError):
        return {"value": row}


@api_bp.route("/shadow/intended", methods=["GET"])
def get_shadow_intended() -> tuple[Response, int]:
    db: Database = current_app.config["DB"]
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        return jsonify({"error": "bad_request", "message": "limit must be an integer."}), 400

    lister = getattr(db, "list_intended_routes", None)
    if not callable(lister):
        # Shadow recorder/table not present (older DB) — report empty rather than 500.
        rows: list[Any] = []
    else:
        rows = lister(limit=limit)
    return jsonify({
        "shadow_mode": _shadow_mode_enabled(),
        "intended_routes": [_intended_route_to_dict(r) for r in rows],
    }), 200


# ── Config edit ────────────────────────────────────────────────────────────────

@api_bp.route("/config/raw", methods=["GET"])
@require_role("admin")
def get_config_raw():
    cfg_loader: Config = current_app.config["CFG_LOADER"]
    path: Path = cfg_loader._path
    try:
        with path.open("r", encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        return jsonify({"error": "not_found", "message": "config.yaml not found"}), 404

    # Item 2: never return secrets verbatim. Parse, redact, re-serialise.
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError:
        # Malformed YAML can't be safely redacted token-by-token, so refuse
        # rather than risk leaking the secret_key in raw text.
        logger.warning(
            "config.yaml is not valid YAML; refusing to return raw contents",
            extra={"component": "api"},
        )
        return jsonify({
            "error": "config_invalid",
            "message": "config.yaml is not valid YAML and cannot be safely returned.",
        }), 500

    redacted = _redact_raw_config(data)
    rendered = yaml.safe_dump(redacted, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return Response(rendered, mimetype="text/plain; charset=utf-8"), 200


@api_bp.route("/config/interfaces", methods=["PUT"])
def put_config_interfaces():
    body = request.get_json(force=True, silent=True)
    if not body or "interfaces" not in body:
        return jsonify({"error": "bad_request", "message": "interfaces required"}), 400

    new_raw = body["interfaces"]
    try:
        _parse_interfaces(new_raw)
    except ConfigError as err:
        return jsonify({"error": "ConfigError", "message": str(err)}), 400

    cfg_loader: Config = current_app.config["CFG_LOADER"]
    cfg_path: Path = cfg_loader._path
    try:
        with cfg_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return jsonify({"error": "not_found", "message": "config.yaml not found"}), 404

    data["interfaces"] = new_raw
    with cfg_path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, default_flow_style=False)

    new_cfg = cfg_loader.reload()
    _sync_reloaded_config(new_cfg)
    return jsonify({"updated": True, "interfaces": len(new_raw)}), 200


@api_bp.route("/config/wan-mode", methods=["PUT"])
def put_config_wan_mode():
    body = request.get_json(force=True, silent=True)
    mode = (body or {}).get("wan_mode")
    if mode not in VALID_WAN_MODES:
        return jsonify({
            "error": "bad_request",
            "message": f"wan_mode must be one of {sorted(VALID_WAN_MODES)}",
        }), 400

    cfg_loader: Config = current_app.config["CFG_LOADER"]
    cfg_path: Path = cfg_loader._path
    try:
        with cfg_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return jsonify({"error": "not_found", "message": "config.yaml not found"}), 404

    data["wan_mode"] = mode
    with cfg_path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, default_flow_style=False)

    new_cfg = cfg_loader.reload()
    _sync_reloaded_config(new_cfg)
    return jsonify({"updated": True, "wan_mode": new_cfg.wan_mode}), 200


# ── Application factory ────────────────────────────────────────────────────────

def create_app(
    cfg: AppConfig,
    cfg_loader: Config,
    db: Database,
    controller: Controller,
    *,
    usage_sampler: "UsageSampler | None" = None,
    speedtest_runner: "SpeedtestRunner | None" = None,
) -> Flask:
    app = Flask(__name__)

    app.config["CFG"] = cfg
    app.config["CFG_LOADER"] = cfg_loader
    app.config["DB"] = db
    app.config["CONTROLLER"] = controller
    app.config["AUTH"] = Auth(db=db, server_cfg=cfg.server)
    app.config["STREAM_TICKETS"] = _StreamTicketStore()
    app.config["USAGE_SAMPLER"] = usage_sampler
    app.config["SPEEDTEST_RUNNER"] = speedtest_runner

    app.register_blueprint(api_bp)

    @app.before_request
    def authenticate_request():
        if not request.path.startswith("/api/"):
            return None
        if request.url_rule is None or request.endpoint == "spa_catchall":
            return None
        # Item 1: network allow-list gate runs before authentication so peers
        # outside allowed_cidrs cannot reach even public endpoints (e.g. login).
        if not _remote_addr_allowed():
            logger.warning(
                "Rejected %s %s from disallowed remote_addr %s",
                request.method, request.path, request.remote_addr,
                extra={"component": "api"},
            )
            return jsonify({
                "error": "forbidden_network",
                "message": "Source address not permitted.",
            }), 401
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        # SSE ticket path: a browser EventSource cannot send auth headers, so
        # GET /api/stream accepts a short-lived single-use ?ticket= minted via
        # POST /api/stream/ticket. Header auth still works for non-browser clients.
        if request.endpoint == "api.sse_stream" and _auth_enabled():
            ticket = request.args.get("ticket")
            if ticket:
                store: _StreamTicketStore = current_app.config["STREAM_TICKETS"]
                principal = store.consume(ticket, time.time())
                if principal is None:
                    return _json_auth_error(
                        AuthError("Invalid or expired stream ticket.", "authentication_required"), 401
                    )
                setattr(request, "principal", principal)
                return None
        try:
            principal = _principal_from_request()
            setattr(request, "principal", principal)
            required_role = "viewer"
            if request.path.startswith("/api/alerts/") and request.path.endswith("/resolve") and request.method == "POST":
                required_role = "operator"
            elif request.path.startswith("/api/users"):
                required_role = "admin"
            elif request.path.startswith("/api/tokens"):
                required_role = "viewer"
            else:
                required_role = ROLE_REQUIREMENTS.get((request.method, request.path), "viewer")
            _auth().require_role(principal, required_role)
        except AuthError as exc:
            status = 403 if exc.code == "insufficient_role" else 401
            return _json_auth_error(exc, status)
        return None

    FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist_app"

    @app.route("/assets/<path:filename>")
    def static_assets(filename: str):
        return send_from_directory(FRONTEND_DIST / "assets", filename)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def spa_catchall(path: str):
        if path.startswith("api/"):
            abort(404)
        return send_from_directory(FRONTEND_DIST, "index.html")

    @app.errorhandler(400)
    def bad_request(e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "bad_request", "message": str(e)}), 400

    @app.errorhandler(404)
    def not_found(e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "not_found", "message": str(e)}), 404

    @app.errorhandler(405)
    def method_not_allowed(e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "method_not_allowed", "message": str(e)}), 405

    @app.errorhandler(500)
    def internal_error(e: Exception) -> tuple[Response, int]:
        logger.error(
            "Unhandled internal error: %s\n%s", e, traceback.format_exc(),
            extra={"component": "api"},
        )
        return jsonify({"error": "internal_server_error", "message": "Internal server error."}), 500

    @app.after_request
    def log_request(response: Response) -> Response:
        if request.path.startswith("/api/") and request.endpoint not in PUBLIC_ENDPOINTS:
            response.headers.setdefault("Cache-Control", "no-store")
        logger.debug(
            "%s %s %d", request.method, request.path, response.status_code,
            extra={"component": "api"},
        )
        return response

    return app
