"""Unit tests for Ookla speedtest JSON parsing in network.run_speedtest."""
from __future__ import annotations

import json
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from wancontrol.network import SpeedtestResult, run_speedtest


OOKLA_SUCCESS_JSON = json.dumps({
    "type": "result",
    "timestamp": "2026-01-01T00:00:00Z",
    "ping": {"jitter": 1.234, "latency": 5.678, "low": 4.0, "high": 9.0},
    "download": {"bandwidth": 12_500_000, "bytes": 0, "elapsed": 0},   # 100 Mbps
    "upload":   {"bandwidth":  6_250_000, "bytes": 0, "elapsed": 0},   # 50 Mbps
    "packetLoss": 0,
    "isp": "Example ISP",
    "server": {"name": "Example Server", "id": 1, "host": "ex.com"},
})


@pytest.fixture(autouse=True)
def _disable_dry_run(monkeypatch):
    """run_speedtest's dry-run path short-circuits the subprocess; turn it off."""
    monkeypatch.delenv("WANCONTROL_DRY_RUN", raising=False)
    yield
    os.environ["WANCONTROL_DRY_RUN"] = "1"  # restore for subsequent tests


def _mock_completed(stdout="", stderr="", returncode=0):
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


def test_parses_ookla_json_success():
    with patch("wancontrol.network.shutil.which", return_value="/usr/bin/speedtest"), \
         patch("wancontrol.network.subprocess.run",
               return_value=_mock_completed(stdout=OOKLA_SUCCESS_JSON, returncode=0)):
        r = run_speedtest("eth0", binary_path="", timeout_sec=10)
    assert r.error is None
    assert r.download_mbps == pytest.approx(100.0, rel=1e-3)
    assert r.upload_mbps == pytest.approx(50.0, rel=1e-3)
    assert r.ping_ms == pytest.approx(5.678)
    assert r.jitter_ms == pytest.approx(1.234)
    assert r.packet_loss_pct == 0.0
    assert r.server_name == "Example Server"
    assert r.isp == "Example ISP"


def test_missing_binary_returns_error_result():
    with patch("wancontrol.network.shutil.which", return_value=None):
        r = run_speedtest("eth0", binary_path="", timeout_sec=10)
    assert isinstance(r, SpeedtestResult)
    assert r.error == "speedtest binary not found"
    assert r.download_mbps is None and r.upload_mbps is None


def test_explicit_binary_path_used_when_set():
    with patch("os.path.isfile", return_value=True), \
         patch("wancontrol.network.subprocess.run",
               return_value=_mock_completed(stdout=OOKLA_SUCCESS_JSON, returncode=0)) as run:
        r = run_speedtest("eth0", binary_path="/opt/bin/speedtest", timeout_sec=10)
    assert r.error is None
    cmd = run.call_args[0][0]
    assert cmd[0] == "/opt/bin/speedtest"
    assert "--interface" in cmd and "eth0" in cmd
    assert "--format=json" in cmd


def test_subprocess_timeout_records_error():
    with patch("wancontrol.network.shutil.which", return_value="/usr/bin/speedtest"), \
         patch("wancontrol.network.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="speedtest", timeout=5)):
        r = run_speedtest("eth0", binary_path="", timeout_sec=5)
    assert r.error is not None and "timed out" in r.error
    assert r.download_mbps is None


def test_non_zero_exit_records_error():
    with patch("wancontrol.network.shutil.which", return_value="/usr/bin/speedtest"), \
         patch("wancontrol.network.subprocess.run",
               return_value=_mock_completed(stdout="", stderr="No internet", returncode=2)):
        r = run_speedtest("eth0", binary_path="", timeout_sec=10)
    assert r.error is not None and "exit 2" in r.error


def test_invalid_json_records_parse_error():
    with patch("wancontrol.network.shutil.which", return_value="/usr/bin/speedtest"), \
         patch("wancontrol.network.subprocess.run",
               return_value=_mock_completed(stdout="not json", returncode=0)):
        r = run_speedtest("eth0", binary_path="", timeout_sec=10)
    assert r.error is not None and "parse error" in r.error
