"""
tests/conftest.py
~~~~~~~~~~~~~~~~~
Shared fixtures for unit and integration tests.
All tests use WANCONTROL_DRY_RUN=1 and in-memory or tmp_path databases.
"""
from __future__ import annotations
import os
import time
import yaml
import pytest
import wancontrol.auth
from wancontrol.config import Config
from wancontrol.database import Database
from wancontrol.auth import Auth
from wancontrol.config import ServerConfig

os.environ["WANCONTROL_DRY_RUN"] = "1"


# ── bcrypt speed ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _fast_bcrypt(monkeypatch):
    """Patch BCRYPT_ROUNDS=4 for every test — real bcrypt, just fast."""
    monkeypatch.setattr(wancontrol.auth, "BCRYPT_ROUNDS", 4)


# ── Config helpers ─────────────────────────────────────────────────────────────

def make_cfg_dict(tmp_path, wan_mode="load_balance", **overrides):
    d = {
        "interfaces": [
            {"name": "wan0", "label": "Fiber Primary",
             "expected_speed_mbps": 100, "gateway": "192.168.1.1",
             "routing_table_id": 100},
            {"name": "wan1", "label": "LTE Backup",
             "expected_speed_mbps": 30, "gateway": "10.0.0.1",
             "routing_table_id": 101},
        ],
        "wan_mode": wan_mode,
        "probes": {
            "interval_sec": 1, "dns_targets": ["8.8.8.8"],
            "icmp_targets": ["8.8.8.8"], "http_targets": ["http://x.com"],
            "icmp_count": 3, "icmp_timeout_sec": 2,
            "dns_timeout_sec": 2, "http_timeout_sec": 3,
        },
        "scoring": {
            "latency_penalty_per_ms": 0.3, "loss_penalty_per_percent": 2.0,
            "dns_fail_penalty": 15, "http_fail_penalty": 20,
            "hard_fail_threshold": 20, "hysteresis_switch_to_backup": 25,
            "hysteresis_return_to_primary": 10, "recovery_margin": 10,
        },
        "controller": {
            "loop_interval_sec": 1, "benchmark_interval_sec": 300,
            "metric_collection_timeout_sec": 8,
            "heartbeat_interval_sec": 5, "heartbeat_stale_sec": 15,
        },
        "retention": {"metrics_hours": 72, "events_days": 30, "prune_interval_min": 60},
        "alerting": {"enabled": False, "webhooks": []},
        "server": {
            "host": "0.0.0.0", "port": 5000,
            "secret_key": "a" * 32,
            "jwt_expiry_hours": 1,
            "session_timeout_minutes": 60,
        },
        "lock_file": str(tmp_path / "test.lock"),
        "heartbeat_file": str(tmp_path / "test.heartbeat"),
        "db_path": ":memory:",
        "log_dir": str(tmp_path),
    }
    d.update(overrides)
    return d


@pytest.fixture
def app_cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(make_cfg_dict(tmp_path)))
    return Config(str(p)).load()


@pytest.fixture
def cfg_loader(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(make_cfg_dict(tmp_path)))
    loader = Config(str(p))
    loader.load()
    return loader


# ── Database ───────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_db():
    db = Database(":memory:")
    db.initialize()
    return db


# ── Controller stub ────────────────────────────────────────────────────────────

class ControllerStub:
    """Minimal controller stub — returns static status dict. No routing."""
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
            "timestamp": 1700000000.0,
        }


# ── Flask app + test client ────────────────────────────────────────────────────

@pytest.fixture
def flask_app(app_cfg, cfg_loader, mem_db):
    from wancontrol.app import create_app
    app = create_app(
        cfg=app_cfg,
        cfg_loader=cfg_loader,
        db=mem_db,
        controller=ControllerStub(),
    )
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


# ── Seeded client with known users ────────────────────────────────────────────

ADMIN_PASSWORD    = "adminpassword123"
OPERATOR_PASSWORD = "operatorpassword123"
VIEWER_PASSWORD   = "viewerpassword123"


@pytest.fixture
def seeded_client(flask_app, mem_db, app_cfg):
    """Flask test client with admin/operator/viewer pre-created at known passwords."""
    auth = Auth(db=mem_db, server_cfg=app_cfg.server)
    auth.create_user("admin",     ADMIN_PASSWORD,    "admin")
    auth.create_user("operator1", OPERATOR_PASSWORD, "operator")
    auth.create_user("viewer1",   VIEWER_PASSWORD,   "viewer")
    return flask_app.test_client()


# ── Login helpers ─────────────────────────────────────────────────────────────

def login(client, username: str, password: str) -> str:
    """Log in and return the raw access token string."""
    resp = client.post("/api/auth/login",
                       json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.data}"
    return resp.get_json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
