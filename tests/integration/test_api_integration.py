import threading
import time
import yaml
import pytest

from tests.conftest import (
    ADMIN_PASSWORD,
    OPERATOR_PASSWORD,
    login,
)


class ControllerStub:
    def get_status(self):
        return {
            "mode": "RUNNING",
            "wan_mode": "load_balance",
            "active_interface": None,
            "nexthop_pool": ["wan0", "wan1"],
            "interfaces": {
                "wan0": {"wan_state": "STABLE", "score": 97.4, "in_pool": True},
                "wan1": {"wan_state": "DEGRADED", "score": 42.0, "in_pool": True},
            },
            "timestamp": 1700000000.0,
        }


@pytest.fixture
def file_db(tmp_path):
    from wancontrol.database import Database
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    return db


@pytest.fixture
def file_app(tmp_path, file_db):
    from wancontrol.app import create_app
    from wancontrol.config import Config
    p = tmp_path / "config.yaml"
    from tests.conftest import make_cfg_dict
    p.write_text(yaml.dump(make_cfg_dict(tmp_path, db_path=str(tmp_path / "test.db"))))
    loader = Config(str(p))
    cfg = loader.load()
    from wancontrol.auth import Auth
    auth = Auth(db=file_db, server_cfg=cfg.server)
    auth.create_user("admin", ADMIN_PASSWORD, "admin")
    auth.create_user("operator1", OPERATOR_PASSWORD, "operator")
    app = create_app(cfg=cfg, cfg_loader=loader, db=file_db, controller=ControllerStub())
    app.config["TESTING"] = True
    return app, file_db, loader, tmp_path


def test_full_login_use_token_on_protected_endpoint_then_logout(file_app):
    app, db, loader, tmp_path = file_app
    client = app.test_client()
    resp = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert resp.status_code == 200
    token = resp.get_json()["access_token"]
    r = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    l = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert l.status_code == 200
    # stateless JWT remains valid
    r2 = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200


def test_api_token_full_lifecycle(file_app):
    app, db, loader, tmp_path = file_app
    client = app.test_client()
    resp = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    token = resp.get_json()["access_token"]
    # create token
    create = client.post("/api/tokens", headers={"Authorization": f"Bearer {token}"}, json={"label": "X"})
    assert create.status_code == 201
    raw = create.get_json()["token"]
    # use token
    r = client.get("/api/status", headers={"X-API-Token": raw})
    assert r.status_code == 200
    # revoke
    tokens = db.list_api_tokens(user_id=1)
    tid = tokens[0].id
    client.delete(f"/api/tokens/{tid}", headers={"Authorization": f"Bearer {token}"})
    r2 = client.get("/api/status", headers={"X-API-Token": raw})
    assert r2.status_code == 401


def test_password_change_new_password_works_old_still_valid_stateless(file_app):
    app, db, loader, tmp_path = file_app
    client = app.test_client()
    resp = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    token = resp.get_json()["access_token"]
    # change password
    client.post("/api/auth/change-password", headers={"Authorization": f"Bearer {token}"}, json={"old_password": ADMIN_PASSWORD, "new_password": "brandnewpassword123"})
    # old token still works
    r = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    # login with new password
    r2 = client.post("/api/auth/login", json={"username": "admin", "password": "brandnewpassword123"})
    assert r2.status_code == 200


def test_metric_inserted_via_db_visible_in_get_metrics(file_app):
    app, db, loader, tmp_path = file_app
    client = app.test_client()
    resp = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    token = resp.get_json()["access_token"]
    db.insert_metric("wan0", 10.0, 1.0, 0.0, True, True, 95.0)
    rows = client.get("/api/metrics", headers={"Authorization": f"Bearer {token}"}).get_json()
    assert any(r["interface"] == "wan0" and r["score"] == 95.0 for r in rows)


def test_switch_event_inserted_via_db_visible_in_get_switch_events(file_app):
    app, db, loader, tmp_path = file_app
    client = app.test_client()
    resp = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    token = resp.get_json()["access_token"]
    db.insert_switch_event("wan1", "wan0", "test", 90.0, 30.0)
    rows = client.get("/api/events/switches", headers={"Authorization": f"Bearer {token}"}).get_json()
    assert rows and rows[0]["from_interface"] == "wan1"


def test_alert_insert_then_resolve_via_api(file_app):
    app, db, loader, tmp_path = file_app
    client = app.test_client()
    resp = client.post("/api/auth/login", json={"username": "operator1", "password": OPERATOR_PASSWORD})
    otoken = resp.get_json()["access_token"]
    # insert
    aid = db.insert_alert("CRITICAL", "Test Alert", "body")
    rows = client.get("/api/alerts", headers={"Authorization": f"Bearer {otoken}"}).get_json()
    assert any(a["id"] == aid for a in rows)
    client.post(f"/api/alerts/{aid}/resolve", headers={"Authorization": f"Bearer {otoken}"})
    rows2 = client.get("/api/alerts", headers={"Authorization": f"Bearer {otoken}"}).get_json()
    assert any(a["id"] == aid and a["resolved_at"] is not None for a in rows2)


def test_config_reload_valid_and_invalid_yaml_returns_expected(file_app, tmp_path):
    app, db, loader, tmp_path = file_app
    client = app.test_client()
    resp = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    token = resp.get_json()["access_token"]
    # valid reload
    r = client.post("/api/config/reload", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and isinstance(r.get_json().get("reloaded"), bool)
    # corrupt file
    loader._path.write_text("!!invalid: [")
    r2 = client.post("/api/config/reload", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200


def test_concurrent_metric_inserts_visible_via_api(file_app):
    app, db, loader, tmp_path = file_app
    client = app.test_client()
    resp = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    token = resp.get_json()["access_token"]
    def worker(i):
        db.insert_metric("wan0", i, 0.1, 0.0, True, True, 90+i)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads: t.start()
    for t in threads: t.join()
    rows = client.get("/api/metrics?limit=200", headers={"Authorization": f"Bearer {token}"}).get_json()
    assert len(rows) >= 20
