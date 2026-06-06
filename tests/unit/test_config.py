"""
tests/unit/test_config.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for wancontrol.config.

All file I/O uses the tmp_path pytest fixture.
No writes to /etc or /var.
"""

from __future__ import annotations

import signal
import threading
from pathlib import Path

import pytest
import yaml

from wancontrol.config import (
    AppConfig,
    Config,
    ConfigError,
    InterfaceConfig,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _minimal_dict(*, secret_key: str = "a" * 32) -> dict:
    """Return the smallest valid config dict. All required keys present."""
    return {
        "interfaces": [
            {
                "name": "wan0",
                "label": "Fiber Primary",
                "expected_speed_mbps": 100,
                "gateway": "192.168.1.1",
                "routing_table_id": 100,
            },
            {
                "name": "wan1",
                "label": "BSNL Backup",
                "expected_speed_mbps": 30,
                "gateway": "10.0.0.1",
                "routing_table_id": 101,
            },
        ],
        "wan_mode": "load_balance",
        "probes": {
            "interval_sec": 1,
            "dns_targets": ["8.8.8.8"],
            "icmp_targets": ["8.8.8.8"],
            "http_targets": ["http://connectivitycheck.gstatic.com/generate_204"],
            "icmp_count": 3,
            "icmp_timeout_sec": 2,
            "dns_timeout_sec": 2,
            "http_timeout_sec": 3,
        },
        "scoring": {
            "latency_penalty_per_ms": 0.3,
            "loss_penalty_per_percent": 2.0,
            "dns_fail_penalty": 15,
            "http_fail_penalty": 20,
            "hard_fail_threshold": 20,
            "hysteresis_switch_to_backup": 25,
            "hysteresis_return_to_primary": 10,
            "recovery_margin": 10,
        },
        "controller": {
            "loop_interval_sec": 1,
            "benchmark_interval_sec": 300,
            "metric_collection_timeout_sec": 8,
            "heartbeat_interval_sec": 5,
            "heartbeat_stale_sec": 15,
        },
        "retention": {
            "metrics_hours": 72,
            "events_days": 30,
            "prune_interval_min": 60,
        },
        "alerting": {
            "enabled": False,
            "webhooks": [],
        },
        "server": {
            "host": "0.0.0.0",
            "port": 5000,
            "secret_key": secret_key,
            "jwt_expiry_hours": 24,
            "session_timeout_minutes": 60,
        },
    }


def _write(tmp_path: Path, data: dict, name: str = "config.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_path(tmp_path: Path) -> Path:
    return _write(tmp_path, _minimal_dict())


@pytest.fixture
def loaded_cfg(minimal_path: Path) -> Config:
    c = Config(minimal_path)
    c.load()
    return c


# ── VALID CONFIG ──────────────────────────────────────────────────────────────

class TestValidConfig:
    def test_loads_minimal_config(self, minimal_path: Path) -> None:
        result = Config(minimal_path).load()
        assert isinstance(result, AppConfig)

    def test_loads_full_config_yaml(self, tmp_path: Path) -> None:
        """Load the repo-root config.yaml, patching the placeholder secret_key."""
        repo_cfg = Path(__file__).parents[2] / "config.yaml"
        if not repo_cfg.exists():
            pytest.skip("config.yaml not found at repo root")
        data = yaml.safe_load(repo_cfg.read_text(encoding="utf-8"))
        data["server"]["secret_key"] = "x" * 32
        p = _write(tmp_path, data)
        result = Config(p).load()
        assert result.wan_mode in {"failover", "load_balance"}
        assert len(result.interfaces) >= 2

    def test_interface_names_property(self, loaded_cfg: Config) -> None:
        assert loaded_cfg.current.interface_names == ["wan0", "wan1"]

    def test_get_interface_returns_correct(self, loaded_cfg: Config) -> None:
        iface = loaded_cfg.current.get_interface("wan0")
        assert isinstance(iface, InterfaceConfig)
        assert iface.name == "wan0"
        assert iface.gateway == "192.168.1.1"
        assert iface.routing_table_id == 100

    def test_get_interface_returns_none_for_unknown(self, loaded_cfg: Config) -> None:
        assert loaded_cfg.current.get_interface("wan99") is None


# ── VALIDATION ERRORS ─────────────────────────────────────────────────────────

class TestValidationErrors:

    # Interfaces ------------------------------------------------------------------

    def test_missing_interfaces_key(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        del data["interfaces"]
        with pytest.raises(ConfigError, match="interfaces"):
            Config(_write(tmp_path, data)).load()

    def test_interfaces_only_one_entry(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["interfaces"] = data["interfaces"][:1]
        with pytest.raises(ConfigError, match="interfaces"):
            Config(_write(tmp_path, data)).load()

    def test_duplicate_interface_name(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["interfaces"][1]["name"] = "wan0"          # duplicate name
        data["interfaces"][1]["routing_table_id"] = 102  # keep table_id unique
        with pytest.raises(ConfigError, match="Duplicate interface name"):
            Config(_write(tmp_path, data)).load()

    def test_duplicate_routing_table_id(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["interfaces"][1]["routing_table_id"] = 100  # collides with wan0
        with pytest.raises(ConfigError, match="routing_table_id"):
            Config(_write(tmp_path, data)).load()

    def test_routing_table_id_out_of_range_zero(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["interfaces"][0]["routing_table_id"] = 0
        with pytest.raises(ConfigError, match="routing_table_id"):
            Config(_write(tmp_path, data)).load()

    def test_routing_table_id_out_of_range_253(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["interfaces"][0]["routing_table_id"] = 253
        with pytest.raises(ConfigError, match="routing_table_id"):
            Config(_write(tmp_path, data)).load()

    def test_routing_table_id_is_string(self, tmp_path: Path) -> None:
        # Write raw YAML so the value is a quoted string, not an int
        raw = yaml.dump(_minimal_dict()).replace(
            "routing_table_id: 100", "routing_table_id: '100'", 1
        )
        p = tmp_path / "config.yaml"
        p.write_text(raw, encoding="utf-8")
        with pytest.raises(ConfigError, match="routing_table_id"):
            Config(p).load()

    def test_missing_gateway(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        del data["interfaces"][0]["gateway"]
        with pytest.raises(ConfigError, match="gateway"):
            Config(_write(tmp_path, data)).load()

    # wan_mode --------------------------------------------------------------------

    def test_unsupported_wan_mode(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["wan_mode"] = "round_robin"
        with pytest.raises(ConfigError, match="wan_mode"):
            Config(_write(tmp_path, data)).load()

    # Probes ----------------------------------------------------------------------

    def test_interval_sec_zero(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["probes"]["interval_sec"] = 0
        with pytest.raises(ConfigError, match="interval_sec"):
            Config(_write(tmp_path, data)).load()

    def test_interval_sec_negative(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["probes"]["interval_sec"] = -1
        with pytest.raises(ConfigError, match="interval_sec"):
            Config(_write(tmp_path, data)).load()

    def test_probes_dns_targets_empty(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["probes"]["dns_targets"] = []
        with pytest.raises(ConfigError, match="dns_targets"):
            Config(_write(tmp_path, data)).load()

    # Server / secret_key ---------------------------------------------------------

    def test_secret_key_is_placeholder_string_without_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Placeholders are rejected unless WANCONTROL_SECRET_KEY is provided."""
        monkeypatch.delenv("WANCONTROL_SECRET_KEY", raising=False)
        for placeholder in (
            "REPLACE_ME_run_python_secrets_token_hex_32",
            "CHANGE_THIS_TO_A_RANDOM_STRING_MIN_32_CHARS",
        ):
            data = _minimal_dict()
            data["server"]["secret_key"] = placeholder
            with pytest.raises(ConfigError, match="secret_key"):
                Config(_write(tmp_path, data)).load()

    def test_secret_key_placeholder_is_allowed_with_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WANCONTROL_SECRET_KEY", "e" * 32)
        data = _minimal_dict()
        data["server"]["secret_key"] = "REPLACE_ME_run_python_secrets_token_hex_32"
        result = Config(_write(tmp_path, data)).load()
        assert result.server.secret_key == "e" * 32

    def test_secret_key_shorter_than_32(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["server"]["secret_key"] = "tooshort"
        with pytest.raises(ConfigError, match="secret_key"):
            Config(_write(tmp_path, data)).load()

    def test_secret_key_missing(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        del data["server"]["secret_key"]
        with pytest.raises(ConfigError, match="secret_key"):
            Config(_write(tmp_path, data)).load()

    # Alerting --------------------------------------------------------------------

    def test_webhook_method_delete(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["alerting"] = {
            "enabled": True,
            "webhooks": [
                {
                    "url": "http://example.com/hook",
                    "method": "DELETE",
                    "on_events": ["link_down"],
                }
            ],
        }
        with pytest.raises(ConfigError, match="method"):
            Config(_write(tmp_path, data)).load()

    def test_unknown_on_event_value(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["alerting"] = {
            "enabled": True,
            "webhooks": [
                {
                    "url": "http://example.com/hook",
                    "on_events": ["totally_unknown_event"],
                }
            ],
        }
        with pytest.raises(ConfigError, match="on_events"):
            Config(_write(tmp_path, data)).load()


# ── SECRET KEY ────────────────────────────────────────────────────────────────

class TestSecretKey:
    def test_valid_32_char_key_passes(self, tmp_path: Path) -> None:
        key = "k" * 32
        result = Config(_write(tmp_path, _minimal_dict(secret_key=key))).load()
        assert result.server.secret_key == key

    def test_valid_64_char_key_passes(self, tmp_path: Path) -> None:
        key = "z" * 64
        result = Config(_write(tmp_path, _minimal_dict(secret_key=key))).load()
        assert result.server.secret_key == key


# ── HOT RELOAD ────────────────────────────────────────────────────────────────

class TestHotReload:
    def test_reload_with_valid_config_updates_current(self, tmp_path: Path) -> None:
        p = _write(tmp_path, _minimal_dict())
        c = Config(p)
        c.load()
        assert c.current.wan_mode == "load_balance"

        updated = _minimal_dict()
        updated["wan_mode"] = "failover"
        p.write_text(yaml.dump(updated), encoding="utf-8")
        new = c.reload()

        assert new.wan_mode == "failover"
        assert c.current.wan_mode == "failover"

    def test_reload_with_invalid_yaml_keeps_old(self, tmp_path: Path) -> None:
        p = _write(tmp_path, _minimal_dict())
        c = Config(p)
        old = c.load()

        p.write_text("key: [unclosed", encoding="utf-8")
        returned = c.reload()

        assert returned is old
        assert c.current is old

    def test_reload_with_missing_file_keeps_old(self, tmp_path: Path) -> None:
        p = _write(tmp_path, _minimal_dict())
        c = Config(p)
        old = c.load()

        p.unlink()
        returned = c.reload()

        assert returned is old

    def test_reload_with_bad_config_keeps_old(self, tmp_path: Path) -> None:
        """Valid YAML but failing validation should keep old config."""
        p = _write(tmp_path, _minimal_dict())
        c = Config(p)
        old = c.load()

        p.write_text("{}", encoding="utf-8")  # missing all required keys
        returned = c.reload()

        assert returned is old

    def test_on_reload_callback_called_after_success(self, tmp_path: Path) -> None:
        p = _write(tmp_path, _minimal_dict())
        c = Config(p)
        c.load()

        received: list[AppConfig] = []
        c.on_reload(received.append)

        updated = _minimal_dict()
        updated["wan_mode"] = "failover"
        p.write_text(yaml.dump(updated), encoding="utf-8")
        c.reload()

        assert len(received) == 1
        assert received[0].wan_mode == "failover"

    def test_on_reload_callback_not_called_after_failure(self, tmp_path: Path) -> None:
        p = _write(tmp_path, _minimal_dict())
        c = Config(p)
        c.load()

        called: list[AppConfig] = []
        c.on_reload(called.append)

        p.write_text("{}", encoding="utf-8")  # invalid → ConfigError
        c.reload()

        assert called == []


# ── SIGHUP ────────────────────────────────────────────────────────────────────

class TestSighup:
    @pytest.mark.skipif(
        not hasattr(signal, "SIGHUP"),
        reason="SIGHUP not available on this platform (Windows)",
    )
    def test_register_sighup_installs_handler(self, loaded_cfg: Config) -> None:
        loaded_cfg.register_sighup()
        handler = signal.getsignal(signal.SIGHUP)  # type: ignore[attr-defined]
        assert callable(handler)
        assert handler is not signal.SIG_DFL
        assert handler is not signal.SIG_IGN


# ── THREAD SAFETY ─────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_current_raises_runtime_error_before_load(self, tmp_path: Path) -> None:
        c = Config(_write(tmp_path, _minimal_dict()))
        with pytest.raises(RuntimeError, match="load"):
            _ = c.current

    def test_concurrent_reads_return_same_object(self, loaded_cfg: Config) -> None:
        results: list[AppConfig] = []
        errors: list[Exception] = []

        def _read() -> None:
            try:
                results.append(loaded_cfg.current)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_read) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Threads raised: {errors}"
        assert len(results) == 10
        first = results[0]
        for r in results[1:]:
            assert r is first, "Threads got different AppConfig objects"


# ── Speedtest + Usage blocks ──────────────────────────────────────────────────

class TestSpeedtestUsageBlocks:
    def test_speedtest_block_absent_yields_disabled_defaults(self, tmp_path: Path) -> None:
        # _minimal_dict has no speedtest/usage keys at all.
        cfg = Config(_write(tmp_path, _minimal_dict())).load()
        assert cfg.speedtest.enabled is False
        assert cfg.speedtest.interval_sec == 3600
        assert cfg.speedtest.enabled_interfaces == ()
        assert cfg.usage.enabled is True
        assert cfg.usage.sample_interval_sec == 5

    def test_speedtest_block_parsed_from_yaml(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["speedtest"] = {
            "enabled": True,
            "interval_sec": 1800,
            "binary_path": "/opt/bin/speedtest",
            "enabled_interfaces": ["wan0"],
            "run_timeout_sec": 90,
        }
        data["usage"] = {"enabled": False, "sample_interval_sec": 10}
        cfg = Config(_write(tmp_path, data)).load()
        assert cfg.speedtest.enabled is True
        assert cfg.speedtest.interval_sec == 1800
        assert cfg.speedtest.binary_path == "/opt/bin/speedtest"
        assert cfg.speedtest.enabled_interfaces == ("wan0",)
        assert cfg.speedtest.run_timeout_sec == 90
        assert cfg.usage.enabled is False
        assert cfg.usage.sample_interval_sec == 10

    def test_speedtest_enabled_interfaces_must_be_list(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        data["speedtest"] = {"enabled_interfaces": "wan0"}  # wrong type
        with pytest.raises(ConfigError, match="enabled_interfaces"):
            Config(_write(tmp_path, data)).load()

    def test_retention_speedtest_usage_optional(self, tmp_path: Path) -> None:
        data = _minimal_dict()
        # retention block has no usage_hours/speedtest_days — should default.
        cfg = Config(_write(tmp_path, data)).load()
        assert cfg.retention.usage_hours == 336
        assert cfg.retention.speedtest_days == 90
