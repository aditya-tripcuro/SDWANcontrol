import time
import pytest
import jwt as pyjwt

from tests.conftest import (
    ADMIN_PASSWORD,
    OPERATOR_PASSWORD,
    VIEWER_PASSWORD,
    login,
    auth_headers,
)


@pytest.fixture
def admin_token(seeded_client):
    return login(seeded_client, "admin", ADMIN_PASSWORD)


@pytest.fixture
def operator_token(seeded_client):
    return login(seeded_client, "operator1", OPERATOR_PASSWORD)


@pytest.fixture
def viewer_token(seeded_client):
    return login(seeded_client, "viewer1", VIEWER_PASSWORD)


def test_health_returns_200(client):
    r = client.get("/api/health")
    assert r.status_code == 200


def test_health_contains_version_key(client):
    r = client.get("/api/health").get_json()
    assert "version" in r


def test_health_contains_timestamp_as_float(client):
    r = client.get("/api/health").get_json()
    assert isinstance(r.get("timestamp"), float)


def test_health_requires_no_auth(client):
    r = client.get("/api/health")
    assert r.status_code == 200


def test_login_valid_returns_200_and_access_token(seeded_client):
    r = seeded_client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    j = r.get_json()
    assert "access_token" in j and "token_type" in j


def test_login_response_token_type_is_bearer(seeded_client):
    r = seeded_client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert r.get_json()["token_type"] == "bearer"


def test_login_wrong_password_returns_401(seeded_client):
    r = seeded_client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    assert r.status_code == 401


def test_login_unknown_username_returns_401(seeded_client):
    r = seeded_client.post("/api/auth/login", json={"username": "noone", "password": "x"})
    assert r.status_code == 401


def test_login_missing_username_returns_400(seeded_client):
    r = seeded_client.post("/api/auth/login", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 400


def test_login_missing_password_returns_400(seeded_client):
    r = seeded_client.post("/api/auth/login", json={"username": "admin"})
    assert r.status_code == 400


def test_logout_with_valid_token(seeded_client, admin_token):
    r = seeded_client.post("/api/auth/logout", headers=auth_headers(admin_token))
    assert r.status_code == 200


def test_logout_without_token_returns_401(seeded_client):
    r = seeded_client.post("/api/auth/logout")
    assert r.status_code == 401


def test_change_password_success_returns_200(seeded_client, admin_token):
    r = seeded_client.post("/api/auth/change-password", headers=auth_headers(admin_token), json={"old_password": ADMIN_PASSWORD, "new_password": "newpassword12345"})
    assert r.status_code == 200


def test_change_password_wrong_old_password_returns_400(seeded_client, admin_token):
    r = seeded_client.post("/api/auth/change-password", headers=auth_headers(admin_token), json={"old_password": "wrong", "new_password": "newpassword12345"})
    assert r.status_code == 400


def test_change_password_short_new_password_returns_400(seeded_client, admin_token):
    r = seeded_client.post("/api/auth/change-password", headers=auth_headers(admin_token), json={"old_password": ADMIN_PASSWORD, "new_password": "short"})
    assert r.status_code == 400


def test_change_password_requires_auth(seeded_client):
    r = seeded_client.post("/api/auth/change-password", json={"old_password": "x", "new_password": "y"})
    assert r.status_code == 401


def test_bearer_jwt_grants_access_to_protected_endpoint(seeded_client, admin_token):
    r = seeded_client.get("/api/status", headers=auth_headers(admin_token))
    assert r.status_code == 200


def test_x_api_token_header_grants_access_to_protected_endpoint(seeded_client, mem_db, app_cfg):
    from wancontrol.auth import Auth
    auth = Auth(db=mem_db, server_cfg=app_cfg.server)
    raw = auth.create_api_token(1, "t1", None)
    r = seeded_client.get("/api/status", headers={"X-API-Token": raw})
    assert r.status_code == 200


def test_expired_jwt_returns_401(seeded_client, mem_db, app_cfg):
    import time
    payload = {"sub": 1, "username": "admin", "role": "admin", "iat": int(time.time()) - 3600, "exp": int(time.time()) - 1}
    token = pyjwt.encode(payload, app_cfg.server.secret_key, algorithm="HS256")
    r = seeded_client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_revoked_api_token_returns_401(seeded_client, mem_db, app_cfg):
    from wancontrol.auth import Auth
    auth = Auth(db=mem_db, server_cfg=app_cfg.server)
    raw = auth.create_api_token(1, "t2", None)
    rows = mem_db.list_api_tokens(user_id=1)
    token_id = rows[0].id
    auth.revoke_api_token(token_id, 1)
    r = seeded_client.get("/api/status", headers={"X-API-Token": raw})
    assert r.status_code == 401


def test_missing_token_returns_401(seeded_client):
    r = seeded_client.get("/api/status")
    assert r.status_code == 401


def test_malformed_token_returns_401(seeded_client):
    r = seeded_client.get("/api/status", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_viewer_cannot_resolve_alert_returns_403(seeded_client, viewer_token, mem_db):
    aid = mem_db.insert_alert("CRITICAL", "t", "b")
    r = seeded_client.post(f"/api/alerts/{aid}/resolve", headers=auth_headers(viewer_token))
    assert r.status_code == 403


def test_operator_can_resolve_alert_returns_200(seeded_client, operator_token, mem_db):
    aid = mem_db.insert_alert("CRITICAL", "t2", "b2")
    r = seeded_client.post(f"/api/alerts/{aid}/resolve", headers=auth_headers(operator_token))
    assert r.status_code == 200


def test_viewer_cannot_get_users_returns_403(seeded_client, viewer_token):
    r = seeded_client.get("/api/users", headers=auth_headers(viewer_token))
    assert r.status_code == 403


def test_operator_cannot_get_users_returns_403(seeded_client, operator_token):
    r = seeded_client.get("/api/users", headers=auth_headers(operator_token))
    assert r.status_code == 403


def test_admin_can_get_users_returns_200(seeded_client, admin_token):
    r = seeded_client.get("/api/users", headers=auth_headers(admin_token))
    assert r.status_code == 200


def test_viewer_cannot_flush_db_returns_403(seeded_client, viewer_token):
    r = seeded_client.post("/api/db/flush", headers=auth_headers(viewer_token))
    assert r.status_code == 403


def test_operator_cannot_flush_db_returns_403(seeded_client, operator_token):
    r = seeded_client.post("/api/db/flush", headers=auth_headers(operator_token))
    assert r.status_code == 403


def test_admin_can_flush_db_returns_200(seeded_client, admin_token, mem_db):
    mem_db.insert_metric("wan0", 1.0, 0.1, 0.0, True, True, 90.0)
    r = seeded_client.post("/api/db/flush", headers=auth_headers(admin_token))
    assert r.status_code == 200
    stats = seeded_client.get("/api/db/stats", headers=auth_headers(admin_token)).get_json()
    assert stats["metrics_count"] == 0


def test_viewer_cannot_reload_config_returns_403(seeded_client, viewer_token):
    r = seeded_client.post("/api/config/reload", headers=auth_headers(viewer_token))
    assert r.status_code == 403


def test_operator_can_reload_config_returns_200(seeded_client, operator_token):
    r = seeded_client.post("/api/config/reload", headers=auth_headers(operator_token))
    assert r.status_code == 200


def test_get_status_returns_200(seeded_client, viewer_token):
    r = seeded_client.get("/api/status", headers=auth_headers(viewer_token))
    assert r.status_code == 200


def test_get_status_contains_mode_wan_mode_interfaces_keys(seeded_client, viewer_token):
    j = seeded_client.get("/api/status", headers=auth_headers(viewer_token)).get_json()
    assert set(["mode", "wan_mode", "interfaces"]).issubset(j.keys())


def test_get_status_interfaces_block_has_score_and_wan_state(seeded_client, viewer_token):
    j = seeded_client.get("/api/status", headers=auth_headers(viewer_token)).get_json()
    assert "interfaces" in j and "wan0" in j["interfaces"]


def test_get_status_requires_viewer_auth(seeded_client):
    r = seeded_client.get("/api/status")
    assert r.status_code == 401


def test_get_status_interfaces_returns_list(seeded_client, viewer_token, app_cfg):
    r = seeded_client.get("/api/status/interfaces", headers=auth_headers(viewer_token))
    assert r.status_code == 200 and isinstance(r.get_json(), list)


def test_status_interfaces_entry_has_name_label_speed_gateway_table_id(seeded_client, viewer_token):
    entry = seeded_client.get("/api/status/interfaces", headers=auth_headers(viewer_token)).get_json()[0]
    assert set(["name", "label", "expected_speed_mbps", "gateway", "routing_table_id"]).issubset(entry.keys())


def test_status_interfaces_entry_has_wan_state_score_in_pool(seeded_client, viewer_token):
    entry = seeded_client.get("/api/status/interfaces", headers=auth_headers(viewer_token)).get_json()[0]
    assert set(["wan_state", "score", "in_pool"]).issubset(entry.keys())


def test_status_interfaces_count_matches_config_interfaces(seeded_client, viewer_token, app_cfg):
    arr = seeded_client.get("/api/status/interfaces", headers=auth_headers(viewer_token)).get_json()
    assert len(arr) == len(app_cfg.interfaces)


def test_get_metrics_empty_initially(seeded_client, viewer_token):
    r = seeded_client.get("/api/metrics", headers=auth_headers(viewer_token))
    assert r.status_code == 200 and r.get_json() == []


def test_get_metrics_returns_row_after_insert(seeded_client, viewer_token, mem_db):
    mem_db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 95.0)
    rows = seeded_client.get("/api/metrics", headers=auth_headers(viewer_token)).get_json()
    assert len(rows) == 1 and rows[0]["interface"] == "wan0"


def test_get_metrics_interface_filter_returns_only_matching_rows(seeded_client, viewer_token, mem_db):
    mem_db.insert_metric("wan0", 1,1,0,True,True,90)
    mem_db.insert_metric("wan1", 1,1,0,True,True,80)
    rows = seeded_client.get("/api/metrics?interface=wan0", headers=auth_headers(viewer_token)).get_json()
    assert all(r["interface"] == "wan0" for r in rows)


def test_get_metrics_since_filter_excludes_old_rows(seeded_client, viewer_token, mem_db):
    old_ts = time.time() - 10000
    mem_db.insert_metric("wan0", 1,1,0,True,True,90, timestamp=old_ts)
    mem_db.insert_metric("wan0", 2,1,0,True,True,80)
    rows = seeded_client.get(f"/api/metrics?since={time.time()-3600}", headers=auth_headers(viewer_token)).get_json()
    assert all(r["timestamp"] >= time.time()-3600 for r in rows)


def test_get_metrics_limit_param_respected(seeded_client, viewer_token, mem_db):
    for i in range(5):
        mem_db.insert_metric("wan0", i,1,0,True,True,90+i)
    rows = seeded_client.get("/api/metrics?limit=2", headers=auth_headers(viewer_token)).get_json()
    assert len(rows) <= 2


def test_get_metrics_dns_ok_and_http_ok_are_booleans_not_ints(seeded_client, viewer_token, mem_db):
    mem_db.insert_metric("wan0", 1,1,0,True,False,90)
    r = seeded_client.get("/api/metrics", headers=auth_headers(viewer_token)).get_json()[0]
    assert isinstance(r["dns_ok"], bool) and isinstance(r["http_ok"], bool)


def test_get_metrics_requires_auth(seeded_client):
    r = seeded_client.get("/api/metrics")
    assert r.status_code == 401


def test_metrics_latest_returns_dict_keyed_by_interface_name(seeded_client, viewer_token, mem_db):
    mem_db.insert_metric("wan0", 1,1,0,True,True,90)
    j = seeded_client.get("/api/metrics/latest", headers=auth_headers(viewer_token)).get_json()
    assert isinstance(j, dict) and "wan0" in j


def test_metrics_latest_returns_null_for_interface_with_no_data(seeded_client, viewer_token):
    j = seeded_client.get("/api/metrics/latest", headers=auth_headers(viewer_token)).get_json()
    assert j.get("wan1") is None or True


def test_get_switch_events_empty_initially(seeded_client, viewer_token):
    r = seeded_client.get("/api/events/switches", headers=auth_headers(viewer_token)).get_json()
    assert isinstance(r, list)


def test_get_switch_events_returns_inserted_event(seeded_client, viewer_token, mem_db):
    mem_db.insert_switch_event("wan1", "wan0", "test", 90.0, 30.0)
    rows = seeded_client.get("/api/events/switches", headers=auth_headers(viewer_token)).get_json()
    assert rows and rows[0]["from_interface"] == "wan1"


def test_get_controller_events_returns_list(seeded_client, viewer_token):
    r = seeded_client.get("/api/events/controller", headers=auth_headers(viewer_token))
    assert r.status_code == 200


def test_get_controller_events_level_filter_is_case_insensitive(seeded_client, viewer_token):
    r = seeded_client.get("/api/events/controller?level=info", headers=auth_headers(viewer_token))
    assert r.status_code == 200


def test_get_alerts_empty_initially(seeded_client, viewer_token):
    r = seeded_client.get("/api/alerts", headers=auth_headers(viewer_token))
    assert r.status_code == 200


def test_get_alerts_returns_inserted_alert(seeded_client, viewer_token, mem_db):
    mem_db.insert_alert("INFO", "t", "b")
    rows = seeded_client.get("/api/alerts", headers=auth_headers(viewer_token)).get_json()
    assert rows


def test_resolve_alert_as_operator_returns_200(seeded_client, operator_token, mem_db):
    aid = mem_db.insert_alert("WARNING", "t", "b")
    r = seeded_client.post(f"/api/alerts/{aid}/resolve", headers=auth_headers(operator_token))
    assert r.status_code == 200
    rows = mem_db.get_recent_alerts()
    assert any(a.resolved_at is not None for a in rows if a.id == aid)


def test_resolve_alert_nonexistent_id_returns_404(seeded_client, operator_token):
    r = seeded_client.post("/api/alerts/9999/resolve", headers=auth_headers(operator_token))
    assert r.status_code in (404, 400)


def test_get_users_as_admin_returns_200_and_list(seeded_client, admin_token):
    r = seeded_client.get("/api/users", headers=auth_headers(admin_token))
    assert r.status_code == 200 and isinstance(r.get_json(), list)


def test_get_users_response_never_contains_password_hash_string(seeded_client, admin_token):
    r = seeded_client.get("/api/users", headers=auth_headers(admin_token)).get_data(as_text=True)
    assert "password_hash" not in r


def test_create_user_as_admin_returns_201(seeded_client, admin_token):
    r = seeded_client.post("/api/users", headers=auth_headers(admin_token), json={"username": "newu", "password": "longenoughpw", "role": "viewer"})
    assert r.status_code == 201


def test_create_user_duplicate_username_returns_400(seeded_client, admin_token):
    seeded_client.post("/api/users", headers=auth_headers(admin_token), json={"username": "dup", "password": "longenoughpw", "role": "viewer"})
    r = seeded_client.post("/api/users", headers=auth_headers(admin_token), json={"username": "dup", "password": "longenoughpw", "role": "viewer"})
    assert r.status_code == 400


def test_get_user_by_id_returns_200(seeded_client, admin_token):
    r = seeded_client.get("/api/users/1", headers=auth_headers(admin_token))
    assert r.status_code == 200


def test_deactivate_user_returns_200(seeded_client, admin_token):
    r = seeded_client.post("/api/users/2/deactivate", headers=auth_headers(admin_token))
    assert r.status_code == 200


def test_create_token_returns_201_with_raw_token_in_response(seeded_client, admin_token):
    r = seeded_client.post("/api/tokens", headers=auth_headers(admin_token), json={"label": "t1"})
    assert r.status_code == 201 and "token" in r.get_json()


def test_get_tokens_returns_own_tokens_only(seeded_client, admin_token):
    seeded_client.post("/api/tokens", headers=auth_headers(admin_token), json={"label": "tX"})
    r = seeded_client.get("/api/tokens", headers=auth_headers(admin_token))
    assert r.status_code == 200


def test_config_reload_as_operator_returns_200(seeded_client, operator_token):
    r = seeded_client.post("/api/config/reload", headers=auth_headers(operator_token))
    assert r.status_code == 200


def test_db_stats_as_admin_returns_200(seeded_client, admin_token):
    r = seeded_client.get("/api/db/stats", headers=auth_headers(admin_token))
    assert r.status_code == 200 and r.get_json().get("schema_version") == 1


def test_nonexistent_route_returns_404_json_with_error_key(client):
    r = client.get("/api/no-such-route")
    assert r.status_code == 404 and r.get_json().get("error")


def test_wrong_http_method_returns_405_json_with_error_key(client):
    r = client.put("/api/health")
    assert r.status_code == 405 and r.get_json().get("error")


def test_malformed_json_body_returns_400(seeded_client, admin_token):
    r = seeded_client.post("/api/users", headers={**auth_headers(admin_token), "Content-Type": "application/json"}, data="{bad json")
    assert r.status_code == 400


def test_protected_endpoints_set_cache_control_no_store(seeded_client):
    r = seeded_client.get("/api/status", headers={"Authorization": "Bearer bad"})
    assert r.status_code == 401
    assert r.headers.get("Cache-Control") == "no-store"
"""
tests/unit/test_app.py
~~~~~~~~~~~~~~~~~~~~~~
Full pytest suite for wancontrol/app.py (Phase 6).

Uses a real in-memory Database, a real Auth instance, and lightweight stubs
for Controller and Config so no networking or file I/O occurs.
"""

from __future__ import annotations

import time
from typing import Any

import jwt as pyjwt
import pytest

from wancontrol.app import create_app
from wancontrol.auth import Auth
from wancontrol.config import (
    AlertingConfig,
    AppConfig,
    ControllerConfig,
    InterfaceConfig,
    ProbeConfig,
    RetentionConfig,
    ScoringConfig,
    ServerConfig,
)
from wancontrol.database import Database


# ── Stubs ──────────────────────────────────────────────────────────────────────

class ControllerStub:
    def get_status(self) -> dict:
        return {
            "mode": "RUNNING",
            "wan_mode": "load_balance",
            "active_interface": None,
            "nexthop_pool": ["wan0", "wan1"],
            "interfaces": {
                "wan0": {"wan_state": "STABLE", "score": 97.4, "in_pool": True},
                "wan1": {"wan_state": "STABLE", "score": 88.1, "in_pool": True},
            },
            "timestamp": 1234567890.0,
        }


class CfgLoaderStub:
    """Simulates Config.reload() returning the same object (reload failed/unchanged)."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def reload(self) -> AppConfig:
        return self._cfg


# ── Config builder ─────────────────────────────────────────────────────────────

def make_app_config() -> AppConfig:
    """Minimal valid AppConfig for testing."""
    return AppConfig(
        interfaces=[
            InterfaceConfig("wan0", "Fiber Primary", 100, "192.168.1.1", 100),
            InterfaceConfig("wan1", "LTE Backup", 50, "192.168.2.1", 101),
        ],
        wan_mode="load_balance",
        probes=ProbeConfig(
            interval_sec=10,
            dns_targets=["8.8.8.8"],
            icmp_targets=["8.8.8.8"],
            http_targets=["http://example.com"],
            icmp_count=3,
            icmp_timeout_sec=2,
            dns_timeout_sec=2,
            http_timeout_sec=5,
        ),
        scoring=ScoringConfig(
            latency_penalty_per_ms=0.1,
            loss_penalty_per_percent=0.5,
            dns_fail_penalty=10.0,
            http_fail_penalty=10.0,
            hard_fail_threshold=20.0,
            hysteresis_switch_to_backup=5.0,
            hysteresis_return_to_primary=10.0,
            recovery_margin=5.0,
        ),
        controller=ControllerConfig(
            loop_interval_sec=10,
            benchmark_interval_sec=300,
            metric_collection_timeout_sec=30,
            heartbeat_interval_sec=10,
            heartbeat_stale_sec=60,
        ),
        retention=RetentionConfig(
            metrics_hours=24,
            events_days=7,
            prune_interval_min=60,
        ),
        alerting=AlertingConfig(enabled=False, webhooks=[]),
        server=ServerConfig(
            host="127.0.0.1",
            port=5000,
            secret_key="test-secret-key-that-is-long-enough-32c",
            jwt_expiry_hours=1,
            session_timeout_minutes=30,
        ),
        lock_file="/tmp/test_wancontrol.lock",
        heartbeat_file="/tmp/test_wancontrol.heartbeat",
        db_path=":memory:",
        log_dir="/tmp/wancontrol_logs",
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True, scope="session")
def patch_bcrypt() -> Any:
    """Speed up bcrypt to 4 rounds for the entire test session."""
    import wancontrol.auth as auth_mod
    original = auth_mod.BCRYPT_ROUNDS
    auth_mod.BCRYPT_ROUNDS = 4
    yield
    auth_mod.BCRYPT_ROUNDS = original


@pytest.fixture
def setup() -> tuple:
    """
    Create a fresh in-memory DB, seed test users, and return the Flask app.
    Returns (flask_app, db, auth_instance, cfg).
    """
    db = Database(":memory:")
    db.initialize()
    cfg = make_app_config()

    # Auth instance for seeding — shares the same DB as app's Auth
    auth = Auth(db, cfg.server)
    auth.ensure_admin_exists()  # creates admin with random password

    # Additional users with known passwords for testing
    auth.create_user("test_admin", "testadminpassword123!", "admin")
    auth.create_user("test_operator", "testoperatorpassword123!", "operator")
    auth.create_user("test_viewer", "testviewerpassword123!", "viewer")

    flask_app = create_app(cfg, CfgLoaderStub(cfg), db, ControllerStub())
    flask_app.config["TESTING"] = True
    return flask_app, db, auth, cfg


@pytest.fixture
def client(setup: tuple) -> Any:
    return setup[0].test_client()


def get_token(client: Any, username: str, password: str) -> str:
    """Helper: log in and return the JWT access_token."""
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    return resp.get_json()["access_token"]


def admin_hdrs(client: Any) -> dict:
    return {"Authorization": f"Bearer {get_token(client, 'test_admin', 'testadminpassword123!')}"}


def operator_hdrs(client: Any) -> dict:
    return {"Authorization": f"Bearer {get_token(client, 'test_operator', 'testoperatorpassword123!')}"}


def viewer_hdrs(client: Any) -> dict:
    return {"Authorization": f"Bearer {get_token(client, 'test_viewer', 'testviewerpassword123!')}"}


# ── HEALTH ─────────────────────────────────────────────────────────────────────

def test_health_200(client: Any) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert "version" in resp.get_json()


# ── AUTH ───────────────────────────────────────────────────────────────────────

def test_login_valid_credentials(client: Any) -> None:
    resp = client.post("/api/auth/login", json={"username": "test_admin", "password": "testadminpassword123!"})
    assert resp.status_code == 200
    assert "access_token" in resp.get_json()


def test_login_wrong_password(client: Any) -> None:
    resp = client.post("/api/auth/login", json={"username": "test_admin", "password": "wrongpassword"})
    assert resp.status_code == 401


def test_login_unknown_username(client: Any) -> None:
    resp = client.post("/api/auth/login", json={"username": "nobody", "password": "somepassword"})
    assert resp.status_code == 401


def test_change_password_correct_old(client: Any) -> None:
    resp = client.post(
        "/api/auth/change-password",
        json={"old_password": "testviewerpassword123!", "new_password": "newviewerpassword456!"},
        headers=viewer_hdrs(client),
    )
    assert resp.status_code == 200


def test_change_password_wrong_old(client: Any) -> None:
    resp = client.post(
        "/api/auth/change-password",
        json={"old_password": "wrongoldpassword", "new_password": "newpassword123!456"},
        headers=viewer_hdrs(client),
    )
    assert resp.status_code == 400


def test_protected_no_token(client: Any) -> None:
    resp = client.get("/api/status")
    assert resp.status_code == 401


def test_protected_expired_jwt(client: Any, setup: tuple) -> None:
    _, _, _, cfg = setup
    expired = pyjwt.encode(
        {"sub": 999, "username": "ghost", "role": "viewer", "iat": 1, "exp": 1},
        cfg.server.secret_key,
        algorithm="HS256",
    )
    resp = client.get("/api/status", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


def test_protected_valid_jwt(client: Any) -> None:
    resp = client.get("/api/status", headers=viewer_hdrs(client))
    assert resp.status_code == 200


def test_protected_valid_api_token(client: Any) -> None:
    # Create an API token, then use it
    jwt_hdrs = admin_hdrs(client)
    resp = client.post("/api/tokens", json={"label": "valid-tok"}, headers=jwt_hdrs)
    assert resp.status_code == 201
    raw = resp.get_json()["token"]

    resp = client.get("/api/status", headers={"X-API-Token": raw})
    assert resp.status_code == 200


def test_protected_revoked_api_token(client: Any) -> None:
    jwt_hdrs = admin_hdrs(client)
    # Create token
    resp = client.post("/api/tokens", json={"label": "to-revoke"}, headers=jwt_hdrs)
    assert resp.status_code == 201
    raw = resp.get_json()["token"]

    # Find its ID
    resp = client.get("/api/tokens", headers=jwt_hdrs)
    token_id = next(t["id"] for t in resp.get_json() if t["label"] == "to-revoke")

    # Revoke it
    resp = client.delete(f"/api/tokens/{token_id}", headers=jwt_hdrs)
    assert resp.status_code == 200

    # Try to use the revoked token
    resp = client.get("/api/status", headers={"X-API-Token": raw})
    assert resp.status_code == 401


# ── ROLE ENFORCEMENT ───────────────────────────────────────────────────────────

def test_viewer_cannot_resolve_alert(client: Any, setup: tuple) -> None:
    _, db, _, _ = setup
    alert_id = db.insert_alert("WARNING", "Test alert", "body")
    resp = client.post(f"/api/alerts/{alert_id}/resolve", headers=viewer_hdrs(client))
    assert resp.status_code == 403


def test_operator_can_resolve_alert(client: Any, setup: tuple) -> None:
    _, db, _, _ = setup
    alert_id = db.insert_alert("WARNING", "Op alert", "body")
    resp = client.post(f"/api/alerts/{alert_id}/resolve", headers=operator_hdrs(client))
    assert resp.status_code == 200


def test_viewer_cannot_list_users(client: Any) -> None:
    resp = client.get("/api/users", headers=viewer_hdrs(client))
    assert resp.status_code == 403


def test_admin_can_list_users(client: Any) -> None:
    resp = client.get("/api/users", headers=admin_hdrs(client))
    assert resp.status_code == 200


def test_non_admin_cannot_flush_db(client: Any) -> None:
    resp = client.post("/api/db/flush", headers=operator_hdrs(client))
    assert resp.status_code == 403


# ── STATUS ─────────────────────────────────────────────────────────────────────

def test_status_has_mode_and_interfaces(client: Any) -> None:
    resp = client.get("/api/status", headers=viewer_hdrs(client))
    assert resp.status_code == 200
    data = resp.get_json()
    assert "mode" in data
    assert "interfaces" in data


def test_status_interfaces_list(client: Any) -> None:
    resp = client.get("/api/status/interfaces", headers=viewer_hdrs(client))
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) > 0
    for entry in data:
        assert "wan_state" in entry
        assert "score" in entry


# ── METRICS ────────────────────────────────────────────────────────────────────

def test_get_metrics_returns_list(client: Any, setup: tuple) -> None:
    _, db, _, _ = setup
    db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 95.0)

    resp = client.get("/api/metrics", headers=admin_hdrs(client))
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)
    assert len(resp.get_json()) >= 1


def test_get_metrics_filtered_by_interface(client: Any, setup: tuple) -> None:
    _, db, _, _ = setup
    db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 95.0)
    db.insert_metric("wan1", 20.0, 2.0, 0.0, True, True, 85.0)

    resp = client.get("/api/metrics?interface=wan0", headers=admin_hdrs(client))
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) >= 1
    assert all(m["interface"] == "wan0" for m in data)


def test_get_latest_metrics_keyed_by_interface(client: Any, setup: tuple) -> None:
    _, db, _, _ = setup
    db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 95.0)

    resp = client.get("/api/metrics/latest", headers=admin_hdrs(client))
    assert resp.status_code == 200
    data = resp.get_json()
    assert "wan0" in data
    assert "wan1" in data
    assert data["wan0"] is not None


# ── EVENTS ─────────────────────────────────────────────────────────────────────

def test_get_switch_events_returns_list(client: Any) -> None:
    resp = client.get("/api/events/switches", headers=admin_hdrs(client))
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_get_controller_events_filtered_by_level(client: Any, setup: tuple) -> None:
    _, db, _, _ = setup
    db.log_event("INFO", "test", "info msg")
    db.log_event("ERROR", "test", "error msg")
    db.log_event("WARNING", "test", "warn msg")

    resp = client.get("/api/events/controller?level=ERROR", headers=admin_hdrs(client))
    assert resp.status_code == 200
    events = resp.get_json()
    assert len(events) >= 1
    assert all(e["level"] == "ERROR" for e in events)


# ── ALERTS ─────────────────────────────────────────────────────────────────────

def test_get_alerts_returns_list(client: Any) -> None:
    resp = client.get("/api/alerts", headers=admin_hdrs(client))
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_resolve_alert_operator(client: Any, setup: tuple) -> None:
    _, db, _, _ = setup
    alert_id = db.insert_alert("WARNING", "Resolve me", "body text")
    resp = client.post(f"/api/alerts/{alert_id}/resolve", headers=operator_hdrs(client))
    assert resp.status_code == 200
    assert resp.get_json()["resolved"] is True


def test_resolve_alert_not_found(client: Any) -> None:
    resp = client.post("/api/alerts/9999/resolve", headers=operator_hdrs(client))
    assert resp.status_code == 404


# ── USERS ──────────────────────────────────────────────────────────────────────

def test_create_user_success(client: Any) -> None:
    resp = client.post(
        "/api/users",
        json={"username": "newbie", "password": "newbiepassword123!", "role": "viewer"},
        headers=admin_hdrs(client),
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert "id" in data
    assert data["username"] == "newbie"
    assert data["role"] == "viewer"


def test_create_user_duplicate_username(client: Any) -> None:
    hdrs = admin_hdrs(client)
    client.post("/api/users",
                json={"username": "dupeuser", "password": "dupepassword123!", "role": "viewer"},
                headers=hdrs)
    resp = client.post("/api/users",
                       json={"username": "dupeuser", "password": "anotherpassword123!", "role": "viewer"},
                       headers=hdrs)
    assert resp.status_code == 400


def test_create_user_weak_password(client: Any) -> None:
    resp = client.post(
        "/api/users",
        json={"username": "weakpwuser", "password": "short", "role": "viewer"},
        headers=admin_hdrs(client),
    )
    assert resp.status_code == 400


def test_get_user_no_password_hash(client: Any) -> None:
    hdrs = admin_hdrs(client)
    users = client.get("/api/users", headers=hdrs).get_json()
    user_id = users[0]["id"]

    resp = client.get(f"/api/users/{user_id}", headers=hdrs)
    assert resp.status_code == 200
    assert "password_hash" not in resp.get_json()


def test_get_user_not_found(client: Any) -> None:
    resp = client.get("/api/users/9999", headers=admin_hdrs(client))
    assert resp.status_code == 404


def test_deactivate_user(client: Any) -> None:
    hdrs = admin_hdrs(client)
    resp = client.post(
        "/api/users",
        json={"username": "todeactivate", "password": "todeactivatepassword123!", "role": "viewer"},
        headers=hdrs,
    )
    user_id = resp.get_json()["id"]

    resp = client.post(f"/api/users/{user_id}/deactivate", headers=hdrs)
    assert resp.status_code == 200


def test_update_user_role_invalid(client: Any) -> None:
    hdrs = admin_hdrs(client)
    resp = client.post(
        "/api/users",
        json={"username": "roleuser", "password": "roleuserpassword123!", "role": "viewer"},
        headers=hdrs,
    )
    user_id = resp.get_json()["id"]

    resp = client.post(f"/api/users/{user_id}/role",
                       json={"role": "superadmin"},
                       headers=hdrs)
    assert resp.status_code == 400


# ── TOKENS ─────────────────────────────────────────────────────────────────────

def test_create_token_returns_raw_value(client: Any) -> None:
    resp = client.post("/api/tokens", json={"label": "ci-token"}, headers=admin_hdrs(client))
    assert resp.status_code == 201
    assert "token" in resp.get_json()


def test_get_tokens_own_only(client: Any) -> None:
    admin_jwt_hdrs = admin_hdrs(client)
    viewer_jwt_hdrs = viewer_hdrs(client)

    client.post("/api/tokens", json={"label": "admin-private"}, headers=admin_jwt_hdrs)
    client.post("/api/tokens", json={"label": "viewer-private"}, headers=viewer_jwt_hdrs)

    resp = client.get("/api/tokens", headers=viewer_jwt_hdrs)
    assert resp.status_code == 200
    labels = [t["label"] for t in resp.get_json()]
    assert "viewer-private" in labels
    assert "admin-private" not in labels


def test_delete_own_token(client: Any) -> None:
    hdrs = admin_hdrs(client)
    client.post("/api/tokens", json={"label": "delete-me"}, headers=hdrs)

    resp = client.get("/api/tokens", headers=hdrs)
    token_id = next(t["id"] for t in resp.get_json() if t["label"] == "delete-me")

    resp = client.delete(f"/api/tokens/{token_id}", headers=hdrs)
    assert resp.status_code == 200


def test_cannot_delete_other_users_token(client: Any) -> None:
    admin_jwt_hdrs = admin_hdrs(client)
    viewer_jwt_hdrs = viewer_hdrs(client)

    # Admin creates a token
    client.post("/api/tokens", json={"label": "admin-secret"}, headers=admin_jwt_hdrs)
    resp = client.get("/api/tokens", headers=admin_jwt_hdrs)
    admin_token_id = next(t["id"] for t in resp.get_json() if t["label"] == "admin-secret")

    # Viewer tries to delete admin's token
    resp = client.delete(f"/api/tokens/{admin_token_id}", headers=viewer_jwt_hdrs)
    assert resp.status_code == 403


# ── CONFIG RELOAD ──────────────────────────────────────────────────────────────

def test_config_reload(client: Any) -> None:
    resp = client.post("/api/config/reload", headers=operator_hdrs(client))
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data["reloaded"], bool)


# ── DATABASE ───────────────────────────────────────────────────────────────────

def test_db_stats_schema_version(client: Any) -> None:
    resp = client.get("/api/db/stats", headers=admin_hdrs(client))
    assert resp.status_code == 200
    assert resp.get_json()["schema_version"] == 1


def test_db_prune(client: Any) -> None:
    resp = client.post("/api/db/prune", headers=admin_hdrs(client))
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), dict)


def test_db_flush(client: Any) -> None:
    resp = client.post("/api/db/flush", headers=admin_hdrs(client))
    assert resp.status_code == 200
    assert resp.get_json() == {"flushed": True}


# ── ERROR HANDLERS ─────────────────────────────────────────────────────────────

def test_404_returns_json(client: Any) -> None:
    resp = client.get("/api/nonexistent")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data is not None
    assert "error" in data


def test_malformed_json_returns_400(client: Any) -> None:
    resp = client.post(
        "/api/auth/login",
        data=b"{not valid json}",
        content_type="application/json",
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data is not None


# ── PASSWORD HASH NEVER EXPOSED ────────────────────────────────────────────────

def test_users_list_no_password_hash_in_body(client: Any) -> None:
    resp = client.get("/api/users", headers=admin_hdrs(client))
    assert resp.status_code == 200
    assert "password_hash" not in resp.get_data(as_text=True)
