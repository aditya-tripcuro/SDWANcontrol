"""
wancontrol/app.py
~~~~~~~~~~~~~~~~~
Flask REST API layer for WANControl v2 (Phase 6).

All endpoints are under /api and return application/json.
Authentication via ``Authorization: Bearer <jwt>`` or ``X-API-Token: <raw>``.
Unix timestamps are returned as floats.
"""

from __future__ import annotations

import dataclasses
import logging
import time
import traceback
from functools import wraps
from typing import TYPE_CHECKING, Any
import json as _json
from pathlib import Path
import yaml

from flask import (
    Blueprint,
    Flask,
    Response,
    current_app,
    g,
    jsonify,
    request,
    stream_with_context,
    send_from_directory,
)

from wancontrol import __version__
from wancontrol.auth import Auth, AuthError, UserPrincipal
from wancontrol.config import AppConfig, Config, ConfigError, _parse_interfaces
from wancontrol.database import ApiTokenRow, Database, MetricRow, UserRow

if TYPE_CHECKING:
    from wancontrol.controller import Controller

logger = logging.getLogger(__name__)

# ── Blueprint ──────────────────────────────────────────────────────────────────

api_bp = Blueprint("api", __name__, url_prefix="/api")

# ── Serialisation helpers ──────────────────────────────────────────────────────

def _user_to_dict(user: UserRow) -> dict[str, Any]:
    """Serialise a UserRow, explicitly omitting password_hash."""
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "created_at": user.created_at,
        "last_login": user.last_login,
        "is_active": user.is_active,
    }


def _token_to_dict(token: ApiTokenRow) -> dict[str, Any]:
    """Serialise an ApiTokenRow, omitting token_hash."""
    return {
        "id": token.id,
        "user_id": token.user_id,
        "label": token.label,
        "created_at": token.created_at,
        "last_used": token.last_used,
        "expires_at": token.expires_at,
        "is_revoked": token.is_revoked,
    }


def _metric_to_dict(m: MetricRow) -> dict[str, Any]:
    """Serialise a MetricRow with explicit bool coercion for dns_ok/http_ok."""
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


# ── Auth helpers ───────────────────────────────────────────────────────────────

_AUTH_ERROR_STATUS: dict[str, int] = {
    "token_expired": 401,
    "token_invalid": 401,
    "token_revoked": 401,
    "user_inactive": 403,
    "insufficient_role": 403,
    "invalid_credentials": 401,
}


def _auth_error_status(code: str) -> int:
    """Map an AuthError code to an HTTP status code."""
    return _AUTH_ERROR_STATUS.get(code, 401)


def _resolve_principal() -> tuple[UserPrincipal | None, tuple | None]:
    """
    Resolve the caller's identity from request headers.

    Token resolution order:
      1. ``Authorization: Bearer <jwt>``  → auth.verify_token()
      2. ``X-API-Token: <raw>``           → auth.verify_api_token()

    Returns ``(UserPrincipal, None)`` on success.
    Returns ``(None, (response, status))`` on any auth failure.
    Error responses carry ``Cache-Control: no-store``.
    """
    auth: Auth = current_app.config["AUTH"]
    auth_header = request.headers.get("Authorization", "")
    api_token_header = request.headers.get("X-API-Token", "")

    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            return auth.verify_token(token), None
        except AuthError as err:
            status = _auth_error_status(err.code)
            resp = jsonify({"error": err.code, "message": err.message})
            resp.headers["Cache-Control"] = "no-store"
            return None, (resp, status)

    if api_token_header:
        try:
            return auth.verify_api_token(api_token_header), None
        except AuthError as err:
            status = _auth_error_status(err.code)
            resp = jsonify({"error": err.code, "message": err.message})
            resp.headers["Cache-Control"] = "no-store"
            return None, (resp, status)

    resp = jsonify({"error": "unauthorized", "message": "Authentication required."})
    resp.headers["Cache-Control"] = "no-store"
    return None, (resp, 401)


# ── Auth decorators ────────────────────────────────────────────────────────────

def require_auth(f: Any) -> Any:
    """
    Decorator — resolves caller identity and injects ``g.principal``.

    Token resolution order:
      1. ``Authorization: Bearer <jwt>``  → auth.verify_token()
      2. ``X-API-Token: <raw>``           → auth.verify_api_token()

    Returns 401 JSON on any AuthError.
    Sets ``Cache-Control: no-store`` on error responses.
    """
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        principal, err = _resolve_principal()
        if err is not None:
            logger.warning(
                "Auth failure on %s %s", request.method, request.path,
                extra={"component": "api"},
            )
            return err
        g.principal = principal
        return f(*args, **kwargs)
    return decorated


def require_role(minimum_role: str) -> Any:
    """
    Decorator factory — wraps require_auth and enforces a minimum role.

    Calls ``auth.require_role(g.principal, minimum_role)``.
    Returns 403 JSON if the caller's role rank is insufficient.
    """
    def decorator(f: Any) -> Any:
        @wraps(f)
        def decorated(*args: Any, **kwargs: Any) -> Any:
            principal, err = _resolve_principal()
            if err is not None:
                logger.warning(
                    "Auth failure on %s %s", request.method, request.path,
                    extra={"component": "api"},
                )
                return err
            g.principal = principal
            auth: Auth = current_app.config["AUTH"]
            try:
                auth.require_role(g.principal, minimum_role)
            except AuthError as role_err:
                logger.warning(
                    "Insufficient role on %s %s: %s",
                    request.method, request.path, role_err.code,
                    extra={"component": "api"},
                )
                return jsonify({"error": role_err.code, "message": role_err.message}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── Health ─────────────────────────────────────────────────────────────────────

@api_bp.route("/health", methods=["GET"])
def health() -> tuple[Response, int]:
    """Return service health. Never exposes internal errors."""
    try:
        return jsonify({
            "status": "ok",
            "version": __version__,
            "timestamp": time.time(),
        }), 200
    except Exception:
        return jsonify({"status": "ok"}), 200


# ── Auth endpoints ─────────────────────────────────────────────────────────────

@api_bp.route("/auth/login", methods=["POST"])
def login() -> tuple[Response, int]:
    """Authenticate with username/password and return a JWT token pair."""
    body = request.get_json(force=True, silent=True)
    if not body or "username" not in body or "password" not in body:
        return jsonify({"error": "bad_request", "message": "username and password required."}), 400

    auth: Auth = current_app.config["AUTH"]
    try:
        token_pair = auth.authenticate(body["username"], body["password"])
    except AuthError as err:
        logger.warning(
            "Login failure for %r: %s", body.get("username"), err.code,
            extra={"component": "api"},
        )
        return jsonify({"error": err.code, "message": err.message}), _auth_error_status(err.code)

    return jsonify(dataclasses.asdict(token_pair)), 200


@api_bp.route("/auth/logout", methods=["POST"])
@require_auth
def logout() -> tuple[Response, int]:
    """Acknowledge logout. JWTs are stateless; session invalidation is Phase 7."""
    return jsonify({"message": "logged out"}), 200


@api_bp.route("/auth/change-password", methods=["POST"])
@require_auth
def change_password() -> tuple[Response, int]:
    """Change the authenticated user's password."""
    body = request.get_json(force=True, silent=True)
    if not body or "old_password" not in body or "new_password" not in body:
        return jsonify({"error": "bad_request", "message": "old_password and new_password required."}), 400

    auth: Auth = current_app.config["AUTH"]
    try:
        auth.change_password(g.principal.user_id, body["old_password"], body["new_password"])
    except AuthError as err:
        return jsonify({"error": err.code, "message": err.message}), 400

    return jsonify({"message": "password changed"}), 200


# ── Status ─────────────────────────────────────────────────────────────────────

@api_bp.route("/status", methods=["GET"])
@require_role("viewer")
def get_status() -> tuple[Response, int]:
    """Return current controller status."""
    controller: Controller = current_app.config["CONTROLLER"]
    return jsonify(controller.get_status()), 200


@api_bp.route("/status/interfaces", methods=["GET"])
@require_role("viewer")
def get_interfaces_status() -> tuple[Response, int]:
    """Return per-interface config merged with live controller state."""
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


# ── Metrics ────────────────────────────────────────────────────────────────────

@api_bp.route("/metrics", methods=["GET"])
@require_role("viewer")
def get_metrics() -> tuple[Response, int]:
    """Fetch recent metrics, optionally filtered by interface and time window."""
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
@require_role("viewer")
def get_latest_metrics() -> tuple[Response, int]:
    """Return the most recent metric row for each configured interface."""
    cfg: AppConfig = current_app.config["CFG"]
    db: Database = current_app.config["DB"]
    result: dict[str, Any] = {}
    for iface_cfg in cfg.interfaces:
        row = db.get_latest_metric(iface_cfg.name)
        result[iface_cfg.name] = _metric_to_dict(row) if row else None
    return jsonify(result), 200


# ── Events ─────────────────────────────────────────────────────────────────────

@api_bp.route("/events/switches", methods=["GET"])
@require_role("viewer")
def get_switch_events() -> tuple[Response, int]:
    """Return recent WAN switch events."""
    db: Database = current_app.config["DB"]
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        return jsonify({"error": "bad_request", "message": "limit must be an integer."}), 400
    rows = db.get_switch_events(limit=limit)
    return jsonify([dataclasses.asdict(r) for r in rows]), 200


@api_bp.route("/events/controller", methods=["GET"])
@require_role("viewer")
def get_controller_events() -> tuple[Response, int]:
    """Return recent controller events, optionally filtered by level."""
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
@require_role("viewer")
def get_alerts() -> tuple[Response, int]:
    """Return recent alerts."""
    db: Database = current_app.config["DB"]
    try:
        limit = int(request.args.get("limit", 20))
    except ValueError:
        return jsonify({"error": "bad_request", "message": "limit must be an integer."}), 400
    rows = db.get_recent_alerts(limit=limit)
    return jsonify([dataclasses.asdict(r) for r in rows]), 200


@api_bp.route("/alerts/<int:alert_id>/resolve", methods=["POST"])
@require_role("operator")
def resolve_alert(alert_id: int) -> tuple[Response, int]:
    """Mark an alert as resolved. Returns 404 if the alert does not exist."""
    db: Database = current_app.config["DB"]
    existing = db.get_recent_alerts(limit=100_000)
    if not any(a.id == alert_id for a in existing):
        return jsonify({"error": "not_found", "message": "Alert not found."}), 404
    db.resolve_alert(alert_id)
    return jsonify({"resolved": True, "alert_id": alert_id}), 200


# ── Users ──────────────────────────────────────────────────────────────────────

@api_bp.route("/users", methods=["GET"])
@require_role("admin")
def list_users() -> tuple[Response, int]:
    """Return all users. password_hash is never included."""
    db: Database = current_app.config["DB"]
    return jsonify([_user_to_dict(u) for u in db.list_users()]), 200


@api_bp.route("/users", methods=["POST"])
@require_role("admin")
def create_user() -> tuple[Response, int]:
    """Create a new user. Returns 400 on weak password or duplicate username."""
    body = request.get_json(force=True, silent=True)
    if not body or "username" not in body or "password" not in body or "role" not in body:
        return jsonify({"error": "bad_request", "message": "username, password, role required."}), 400

    auth: Auth = current_app.config["AUTH"]
    try:
        user_id = auth.create_user(
            body["username"],
            body["password"],
            body["role"],
            created_by_user_id=g.principal.user_id,
        )
    except AuthError as err:
        return jsonify({"error": err.code, "message": err.message}), 400

    return jsonify({"id": user_id, "username": body["username"], "role": body["role"]}), 201


@api_bp.route("/users/<int:user_id>", methods=["GET"])
@require_role("admin")
def get_user(user_id: int) -> tuple[Response, int]:
    """Return a single user. password_hash excluded. 404 if not found."""
    db: Database = current_app.config["DB"]
    user = db.get_user_by_id(user_id)
    if user is None:
        return jsonify({"error": "not_found", "message": "User not found."}), 404
    return jsonify(_user_to_dict(user)), 200


@api_bp.route("/users/<int:user_id>/deactivate", methods=["POST"])
@require_role("admin")
def deactivate_user(user_id: int) -> tuple[Response, int]:
    """Deactivate a user account."""
    auth: Auth = current_app.config["AUTH"]
    try:
        auth.deactivate_user(user_id, g.principal.user_id)
    except AuthError as err:
        if err.code == "user_not_found":
            return jsonify({"error": "not_found", "message": err.message}), 404
        return jsonify({"error": err.code, "message": err.message}), 400
    return jsonify({"deactivated": True, "user_id": user_id}), 200


@api_bp.route("/users/<int:user_id>/role", methods=["POST"])
@require_role("admin")
def update_user_role(user_id: int) -> tuple[Response, int]:
    """Update a user's role. Returns 400 on invalid role value."""
    body = request.get_json(force=True, silent=True)
    if not body or "role" not in body:
        return jsonify({"error": "bad_request", "message": "role required."}), 400

    auth: Auth = current_app.config["AUTH"]
    try:
        auth.update_role(user_id, body["role"], g.principal.user_id)
    except ValueError as err:
        return jsonify({"error": "bad_request", "message": str(err)}), 400
    except AuthError as err:
        if err.code == "user_not_found":
            return jsonify({"error": "not_found", "message": err.message}), 404
        return jsonify({"error": err.code, "message": err.message}), 400
    return jsonify({"user_id": user_id, "role": body["role"]}), 200


# ── API Tokens ─────────────────────────────────────────────────────────────────

@api_bp.route("/tokens", methods=["GET"])
@require_auth
def list_tokens() -> tuple[Response, int]:
    """Return API tokens. Admins may pass ?all=true to see all users' tokens."""
    auth: Auth = current_app.config["AUTH"]
    show_all = request.args.get("all", "").lower() == "true"
    if show_all and g.principal.role == "admin":
        tokens = auth.list_api_tokens()
    else:
        tokens = auth.list_api_tokens(user_id=g.principal.user_id)
    return jsonify([_token_to_dict(t) for t in tokens]), 200


@api_bp.route("/tokens", methods=["POST"])
@require_auth
def create_token() -> tuple[Response, int]:
    """Create a new API token. The raw token value is shown exactly once."""
    body = request.get_json(force=True, silent=True)
    if not body or "label" not in body:
        return jsonify({"error": "bad_request", "message": "label required."}), 400

    expires_in_days: int | None = body.get("expires_in_days")
    if expires_in_days is not None:
        try:
            expires_in_days = int(expires_in_days)
        except (TypeError, ValueError):
            return jsonify({"error": "bad_request", "message": "expires_in_days must be an integer."}), 400

    auth: Auth = current_app.config["AUTH"]
    try:
        raw_token = auth.create_api_token(g.principal.user_id, body["label"], expires_in_days)
    except AuthError as err:
        return jsonify({"error": err.code, "message": err.message}), 400

    return jsonify({"token": raw_token, "label": body["label"]}), 201


@api_bp.route("/tokens/<int:token_id>", methods=["DELETE"])
@require_auth
def delete_token(token_id: int) -> tuple[Response, int]:
    """Revoke an API token. Users may revoke their own; admins may revoke any."""
    db: Database = current_app.config["DB"]
    auth: Auth = current_app.config["AUTH"]

    user_tokens = db.list_api_tokens(user_id=g.principal.user_id)
    is_own = any(t.id == token_id for t in user_tokens)

    if not is_own and g.principal.role != "admin":
        return jsonify({"error": "forbidden", "message": "Cannot revoke another user's token."}), 403

    auth.revoke_api_token(token_id, g.principal.user_id)
    return jsonify({"revoked": True, "token_id": token_id}), 200


# ── Config reload ──────────────────────────────────────────────────────────────

@api_bp.route("/config/reload", methods=["POST"])
@require_role("operator")
def reload_config() -> tuple[Response, int]:
    """Hot-reload config.yaml. db_path is not hot-reloadable."""
    cfg: AppConfig = current_app.config["CFG"]
    cfg_loader: Config = current_app.config["CFG_LOADER"]
    new_cfg = cfg_loader.reload()
    # reload() returns the same object on failure and a new object on success
    reloaded = new_cfg is not cfg
    return jsonify({
        "reloaded": reloaded,
        "wan_mode": new_cfg.wan_mode,
        "interfaces": len(new_cfg.interfaces),
    }), 200


# ── Database admin ─────────────────────────────────────────────────────────────

@api_bp.route("/db/stats", methods=["GET"])
@require_role("admin")
def db_stats() -> tuple[Response, int]:
    """Return database row counts and file size."""
    db: Database = current_app.config["DB"]
    return jsonify(dataclasses.asdict(db.get_db_stats())), 200


@api_bp.route("/db/prune", methods=["POST"])
@require_role("admin")
def db_prune() -> tuple[Response, int]:
    """Prune data older than configured retention thresholds."""
    db: Database = current_app.config["DB"]
    cfg: AppConfig = current_app.config["CFG"]
    result = db.prune_old_data(cfg.retention.metrics_hours, cfg.retention.events_days)
    return jsonify(result), 200


@api_bp.route("/db/flush", methods=["POST"])
@require_role("admin")
def db_flush() -> tuple[Response, int]:
    """Flush all metrics and events. Preserves users, state, and schema."""
    db: Database = current_app.config["DB"]
    db.flush_all_data()
    return jsonify({"flushed": True}), 200


# ── SSE stream / config edit endpoints (Phase 7) ---------------------------


@api_bp.route("/stream", methods=["GET"])
def sse_stream():
    # EventSource cannot set headers — accept token from query param
    token = request.args.get("token", "")
    auth: Auth = current_app.config["AUTH"]
    try:
        principal = auth.verify_token(token)
    except AuthError as e:
        return jsonify({"error": e.code, "message": e.message}), 401

    controller: Controller = current_app.config["CONTROLLER"]
    cfg: AppConfig = current_app.config["CFG"]
    db: Database = current_app.config["DB"]

    def event_stream():
        last_alert_id = 0
        while True:
            # Push status
            status = controller.get_status()
            yield f"event: status\ndata: {_json.dumps(status)}\n\n"

            # Push latest metrics
            latest = {
                iface.name: _metric_to_dict(db.get_latest_metric(iface.name))
                for iface in cfg.interfaces
            }
            yield f"event: metric\ndata: {_json.dumps(latest)}\n\n"

            # Push any new unnotified alerts
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


@api_bp.route("/config/raw", methods=["GET"])
@require_role("operator")
def get_config_raw():
    cfg_loader: Config = current_app.config["CFG_LOADER"]
    path: Path = cfg_loader._path
    try:
        with path.open("r", encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        return jsonify({"error": "not_found", "message": "config.yaml not found"}), 404
    return Response(content, mimetype="text/plain; charset=utf-8"), 200


@api_bp.route("/config/interfaces", methods=["PUT"])
@require_role("operator")
def put_config_interfaces():
    body = request.get_json(force=True, silent=True)
    if not body or "interfaces" not in body:
        return jsonify({"error": "bad_request", "message": "interfaces required"}), 400

    new_raw = body["interfaces"]
    try:
        # Validate via existing parser
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

    cfg_loader.reload()
    return jsonify({"updated": True, "interfaces": len(new_raw)}), 200


# ── Application factory ────────────────────────────────────────────────────────

def create_app(
    cfg: AppConfig,
    cfg_loader: Config,
    db: Database,
    controller: Controller,
) -> Flask:
    """
    Application factory. Called once at startup by the entrypoint.

    Stores shared objects on app.config:
        app.config["CFG"]        = cfg
        app.config["CFG_LOADER"] = cfg_loader
        app.config["DB"]         = db
        app.config["AUTH"]       = Auth(db, cfg.server)
        app.config["CONTROLLER"] = controller

    Registers all blueprints and error handlers.
    Sets Flask secret_key from cfg.server.secret_key.
    """
    app = Flask(__name__)
    app.secret_key = cfg.server.secret_key

    app.config["CFG"] = cfg
    app.config["CFG_LOADER"] = cfg_loader
    app.config["DB"] = db
    app.config["AUTH"] = Auth(db, cfg.server)
    app.config["CONTROLLER"] = controller

    app.register_blueprint(api_bp)

    # Serve frontend dist (SPA) if present
    FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

    @app.route("/assets/<path:filename>")
    def static_assets(filename: str):
        return send_from_directory(FRONTEND_DIST / "assets", filename)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def spa_catchall(path: str):
        return send_from_directory(FRONTEND_DIST, "index.html")

    # ── Error handlers ─────────────────────────────────────────────────────

    @app.errorhandler(400)
    def bad_request(e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "bad_request", "message": str(e)}), 400

    @app.errorhandler(401)
    def unauthorized(e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "unauthorized", "message": str(e)}), 401

    @app.errorhandler(403)
    def forbidden(e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "forbidden", "message": str(e)}), 403

    @app.errorhandler(404)
    def not_found(e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "not_found", "message": str(e)}), 404

    @app.errorhandler(405)
    def method_not_allowed(e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "method_not_allowed", "message": str(e)}), 405

    @app.errorhandler(500)
    def internal_error(e: Exception) -> tuple[Response, int]:
        logger.error(
            "Unhandled internal error: %s\n%s",
            e,
            traceback.format_exc(),
            extra={"component": "api"},
        )
        return jsonify({"error": "internal_server_error", "message": "Internal server error."}), 500

    # ── After-request logging ──────────────────────────────────────────────

    @app.after_request
    def log_request(response: Response) -> Response:
        logger.debug(
            "%s %s %d",
            request.method,
            request.path,
            response.status_code,
            extra={"component": "api"},
        )
        return response

    return app
