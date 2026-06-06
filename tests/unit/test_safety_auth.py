from __future__ import annotations

import dataclasses
import json
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import ControllerStub
from wancontrol.app import create_app
from wancontrol.config import Config, ServerConfig
from wancontrol.controller import Controller, ControllerMode
from wancontrol.database import Database
from wancontrol.monitor import InterfaceMetric


def test_auth_enabled_false_parses_from_config(tmp_path):
    from tests.conftest import make_cfg_dict
    import yaml

    data = make_cfg_dict(tmp_path)
    data["server"]["host"] = "127.0.0.1"
    data["server"]["auth_enabled"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    cfg = Config(path).load()

    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.auth_enabled is False


@pytest.fixture
def no_auth_app(tmp_path):
    from tests.conftest import make_cfg_dict
    import yaml

    path = tmp_path / "config.yaml"
    data = make_cfg_dict(tmp_path)
    data["server"]["auth_enabled"] = False
    path.write_text(yaml.dump(data), encoding="utf-8")
    loader = Config(path)
    cfg = loader.load()
    db = Database(":memory:")
    db.initialize()
    app = create_app(cfg, loader, db, ControllerStub())
    app.config["TESTING"] = True
    return app


def test_api_access_without_jwt_when_auth_disabled(no_auth_app):
    client = no_auth_app.test_client()

    resp = client.get("/api/status")

    assert resp.status_code == 200


def test_sse_without_jwt_when_auth_disabled(no_auth_app):
    client = no_auth_app.test_client()

    resp = client.get("/api/stream", buffered=False)

    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    resp.close()


def test_start_saves_restore_state(tmp_path):
    from tests.conftest import make_cfg_dict
    import yaml

    path = tmp_path / "config.yaml"
    data = make_cfg_dict(tmp_path, wan_mode="failover")
    path.write_text(yaml.dump(data), encoding="utf-8")
    cfg = Config(path).load()
    db = Database(":memory:")
    db.initialize()
    ctrl = Controller(cfg, db)

    route_json = json.dumps([{"gateway": "192.0.2.1", "dev": "eth9", "metric": 50}])

    def stop_after_collect(*args, **kwargs):
        ctrl._mode = ControllerMode.STOPPED
        return [
            InterfaceMetric("wan0", 1.0, 1, 1, 0, True, True, 90, False),
            InterfaceMetric("wan1", 1.0, 1, 1, 0, True, True, 80, False),
        ]

    with patch("subprocess.run", return_value=MagicMock(stdout=route_json)), \
         patch("wancontrol.network.setup_all_interfaces"), \
         patch.object(ctrl._monitor, "collect", side_effect=stop_after_collect):
        ctrl._run_master()

    assert json.loads(db.get_state("pre_start_default_routes"))[0]["gateway"] == "192.0.2.1"
    assert db.get_state("route_management_active") == "1"


def test_stop_restores_route_state(app_cfg, mem_db):
    ctrl = Controller(app_cfg, mem_db)
    mem_db.set_state("pre_start_default_routes", '[{"gateway":"192.0.2.1","dev":"eth9"}]')

    with patch("wancontrol.network.emergency_cleanup") as cleanup:
        ctrl.shutdown()

    cleanup.assert_called_once_with(app_cfg.interfaces, mem_db)
    assert mem_db.get_state("controller_status") == "stopped"


def test_stale_managed_state_is_detected_on_startup(tmp_path):
    from tests.conftest import make_cfg_dict
    import yaml

    path = tmp_path / "config.yaml"
    data = make_cfg_dict(tmp_path, wan_mode="failover")
    path.write_text(yaml.dump(data), encoding="utf-8")
    cfg = Config(path).load()
    db = Database(":memory:")
    db.initialize()
    db.set_state("route_management_active", "1")
    db.set_state("pre_start_default_routes", '[{"gateway":"198.51.100.1","dev":"eth0"}]')
    ctrl = Controller(cfg, db)

    def stop_after_collect(*args, **kwargs):
        ctrl._mode = ControllerMode.STOPPED
        return []

    with patch("wancontrol.network.setup_all_interfaces"), \
         patch.object(ctrl._monitor, "collect", side_effect=stop_after_collect):
        ctrl._run_master()

    assert db.get_state("stale_managed_state_detected") == "1"
    assert json.loads(db.get_state("pre_start_default_routes"))[0]["gateway"] == "198.51.100.1"
