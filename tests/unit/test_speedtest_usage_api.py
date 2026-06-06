"""API endpoint tests for speedtest + usage routes."""
from __future__ import annotations

import time

import pytest

from tests.conftest import (
    OPERATOR_PASSWORD,
    VIEWER_PASSWORD,
    auth_headers,
    login,
)


class _SpeedtestRunnerStub:
    """In-process stub replacing the live runner for API tests."""
    def __init__(self):
        self.enabled = set()
        self.queued = []

    def get_enabled(self):
        return set(self.enabled)

    def set_enabled(self, interface, enabled):
        if enabled:
            self.enabled.add(interface)
        else:
            self.enabled.discard(interface)
        return set(self.enabled)

    def run_once(self, interface):
        self.queued.append(interface)


@pytest.fixture
def runner_stub():
    return _SpeedtestRunnerStub()


@pytest.fixture
def app_with_runner(flask_app, runner_stub):
    flask_app.config["SPEEDTEST_RUNNER"] = runner_stub
    return flask_app


@pytest.fixture
def seeded_runner_client(app_with_runner, mem_db, app_cfg):
    """Seeded client variant that also has the runner stub wired in."""
    from wancontrol.auth import Auth
    auth = Auth(db=mem_db, server_cfg=app_cfg.server)
    auth.create_user("operator1", OPERATOR_PASSWORD, "operator")
    auth.create_user("viewer1", VIEWER_PASSWORD, "viewer")
    return app_with_runner.test_client()


@pytest.fixture
def viewer_token_local(seeded_runner_client):
    return login(seeded_runner_client, "viewer1", VIEWER_PASSWORD)


@pytest.fixture
def operator_token_local(seeded_runner_client):
    return login(seeded_runner_client, "operator1", OPERATOR_PASSWORD)


# ── /api/speedtest history ───────────────────────────────────────────────────

def test_get_speedtest_empty_history(seeded_runner_client, viewer_token_local):
    r = seeded_runner_client.get("/api/speedtest", headers=auth_headers(viewer_token_local))
    assert r.status_code == 200
    assert r.get_json() == []


def test_get_speedtest_returns_seeded_rows(seeded_runner_client, viewer_token_local, mem_db):
    mem_db.insert_speedtest("wan0", 100.0, 50.0, 5.0, 1.0, 0.0, "srv", "isp", None, timestamp=time.time())
    mem_db.insert_speedtest("wan1", None, None, None, None, None, None, None, "boom", timestamp=time.time())
    r = seeded_runner_client.get("/api/speedtest", headers=auth_headers(viewer_token_local))
    assert r.status_code == 200
    body = r.get_json()
    assert len(body) == 2
    by_iface = {row["interface"]: row for row in body}
    assert by_iface["wan0"]["download_mbps"] == 100.0
    assert by_iface["wan1"]["error"] == "boom"


def test_get_speedtest_latest_per_interface(seeded_runner_client, viewer_token_local, mem_db):
    mem_db.insert_speedtest("wan0", 90.0, 40.0, 5.0, 1.0, 0.0, "srv", "isp", None, timestamp=1.0)
    mem_db.insert_speedtest("wan0", 100.0, 45.0, 6.0, 1.0, 0.0, "srv", "isp", None, timestamp=2.0)
    r = seeded_runner_client.get("/api/speedtest/latest", headers=auth_headers(viewer_token_local))
    body = r.get_json()
    assert body["wan0"]["download_mbps"] == 100.0
    assert body["wan1"] is None


# ── /api/speedtest/enabled toggle ────────────────────────────────────────────

def test_speedtest_enabled_get_returns_per_iface_map(seeded_runner_client, viewer_token_local):
    r = seeded_runner_client.get("/api/speedtest/enabled", headers=auth_headers(viewer_token_local))
    assert r.status_code == 200
    body = r.get_json()
    assert "wan0" in body and "wan1" in body
    assert body["wan0"] is False and body["wan1"] is False


def test_speedtest_enabled_patch_requires_operator(seeded_runner_client, viewer_token_local):
    r = seeded_runner_client.patch(
        "/api/speedtest/enabled",
        headers=auth_headers(viewer_token_local),
        json={"interface": "wan0", "enabled": True},
    )
    assert r.status_code == 403


def test_speedtest_enabled_patch_updates_runner(seeded_runner_client, operator_token_local, runner_stub):
    r = seeded_runner_client.patch(
        "/api/speedtest/enabled",
        headers=auth_headers(operator_token_local),
        json={"interface": "wan0", "enabled": True},
    )
    assert r.status_code == 200
    assert "wan0" in runner_stub.enabled
    assert r.get_json()["enabled_set"] == ["wan0"]


def test_speedtest_enabled_unknown_interface_404(seeded_runner_client, operator_token_local):
    r = seeded_runner_client.patch(
        "/api/speedtest/enabled",
        headers=auth_headers(operator_token_local),
        json={"interface": "ghost0", "enabled": True},
    )
    assert r.status_code == 404


def test_speedtest_enabled_bad_payload_400(seeded_runner_client, operator_token_local):
    r = seeded_runner_client.patch(
        "/api/speedtest/enabled",
        headers=auth_headers(operator_token_local),
        json={"interface": "wan0", "enabled": "yes"},  # not a bool
    )
    assert r.status_code == 400


# ── /api/speedtest/run ───────────────────────────────────────────────────────

def test_speedtest_run_queues_request(seeded_runner_client, operator_token_local, runner_stub):
    r = seeded_runner_client.post(
        "/api/speedtest/run",
        headers=auth_headers(operator_token_local),
        json={"interface": "wan0"},
    )
    assert r.status_code == 202
    assert runner_stub.queued == ["wan0"]


def test_speedtest_run_requires_operator(seeded_runner_client, viewer_token_local):
    r = seeded_runner_client.post(
        "/api/speedtest/run",
        headers=auth_headers(viewer_token_local),
        json={"interface": "wan0"},
    )
    assert r.status_code == 403


def test_speedtest_run_unknown_interface_404(seeded_runner_client, operator_token_local):
    r = seeded_runner_client.post(
        "/api/speedtest/run",
        headers=auth_headers(operator_token_local),
        json={"interface": "ghost0"},
    )
    assert r.status_code == 404


# ── /api/usage ────────────────────────────────────────────────────────────────

def test_get_usage_empty(seeded_runner_client, viewer_token_local):
    r = seeded_runner_client.get("/api/usage", headers=auth_headers(viewer_token_local))
    assert r.status_code == 200
    assert r.get_json() == []


def test_get_usage_filtered_by_interface(seeded_runner_client, viewer_token_local, mem_db):
    mem_db.insert_usage("wan0", 1.5, 0.8, 1000, 500, timestamp=time.time())
    mem_db.insert_usage("wan1", 5.0, 2.0, 2000, 1000, timestamp=time.time())
    r = seeded_runner_client.get(
        "/api/usage?interface=wan0",
        headers=auth_headers(viewer_token_local),
    )
    rows = r.get_json()
    assert len(rows) == 1
    assert rows[0]["interface"] == "wan0"
    assert rows[0]["rx_mbps"] == 1.5
