"""
tests/test_route_restore_netns.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Dry-run Layer 2 (netns harness) tests for WANControl route snapshot/restore.

These tests exercise the REAL route-mutation code in ``wancontrol.network``
(``snapshot_default_routes`` / ``restore_default_routes`` and the
``python -m wancontrol.network --restore-routes`` CLI) inside an isolated
``ip netns``, so nothing touches the host routing table.

They SKIP automatically when:
  * the process is not root (no CAP_NET_ADMIN), or
  * network namespaces cannot be created/entered in this sandbox, or
  * ``ip`` (iproute2) is unavailable.

Two layers of coverage:
  1. ``test_netns_harness_script`` runs the shell harness end-to-end and asserts
     it reports PASS (exit 0). It covers single-default, multi-default, and
     empty-snapshot scenarios.
  2. ``test_*_netns`` drive the same real functions directly from Python (inside
     a fresh namespace per test) and assert specific resulting route state, so a
     regression names the exact failing scenario rather than an opaque script
     exit.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS = Path(__file__).resolve().parent / "netns_harness.sh"

# Dummy topology mirrored from netns_harness.sh.
IF_A, ADDR_A, GW_A, TABLE_A = "wlan_a", "10.10.0.2/30", "10.10.0.1", 100
IF_B, ADDR_B, GW_B, TABLE_B = "wlan_b", "10.10.1.2/30", "10.10.1.1", 101
IF_C, ADDR_C, GW_C, TABLE_C = "wlan_c", "10.10.2.2/30", "10.10.2.1", 102


# ── Skip gating ──────────────────────────────────────────────────────────────

def _netns_available() -> bool:
    """Return True only if we can actually create AND enter a network namespace."""
    if os.geteuid() != 0:
        return False
    if shutil.which("ip") is None:
        return False
    probe = f"wanctl_probe_{os.getpid()}"
    try:
        if subprocess.run(["ip", "netns", "add", probe],
                          capture_output=True).returncode != 0:
            return False
        try:
            ok = subprocess.run(
                ["ip", "netns", "exec", probe, "ip", "link", "set", "lo", "up"],
                capture_output=True,
            ).returncode == 0
        finally:
            subprocess.run(["ip", "netns", "del", probe], capture_output=True)
        return ok
    except OSError:
        return False


_SKIP = pytest.mark.skipif(
    not _netns_available(),
    reason="requires root and a usable `ip netns` (skipped otherwise)",
)


# ── Per-test isolated namespace fixture ──────────────────────────────────────

class _Netns:
    """A throwaway network namespace with the dummy WAN topology + a config/DB.

    All routing operations run INSIDE the namespace, so the host is untouched.
    """

    def __init__(self, name: str, workdir: Path) -> None:
        self.name = name
        self.workdir = workdir
        self.config_path = workdir / "config.yaml"
        self.db_path = workdir / "wan.db"

    # -- low-level exec helpers ------------------------------------------------
    def exec(self, *argv: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a command inside the namespace."""
        return subprocess.run(
            ["ip", "netns", "exec", self.name, *argv],
            capture_output=True, text=True, check=check,
        )

    def _python(self) -> str:
        venv = REPO_ROOT / ".venv" / "bin" / "python"
        return str(venv) if venv.exists() else sys.executable

    def py(self, snippet: str) -> subprocess.CompletedProcess:
        """Run a python snippet inside the namespace against the isolated DB."""
        env = {
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT),
            "WANCONTROL_CONFIG": str(self.config_path),
        }
        # Run WITHOUT dry-run so real `ip route` mutations happen in the netns.
        env.pop("WANCONTROL_DRY_RUN", None)
        env.pop("WANCONTROL_SHADOW", None)
        return subprocess.run(
            ["ip", "netns", "exec", self.name, self._python(), "-c", snippet],
            capture_output=True, text=True, env=env, check=True,
        )

    # -- route inspection ------------------------------------------------------
    def defaults(self) -> list[dict]:
        """Return the current IPv4 default routes (parsed JSON) in the namespace."""
        res = self.exec("ip", "-4", "-json", "route", "show", "default")
        return json.loads(res.stdout or "[]")

    def default_gateways(self) -> set[str]:
        gws: set[str] = set()
        for r in self.defaults():
            gw = r.get("gateway") or r.get("via")
            if gw:
                gws.add(str(gw))
            for nh in r.get("nexthops") or []:
                nh_gw = nh.get("gateway") or nh.get("via")
                if nh_gw:
                    gws.add(str(nh_gw))
        return gws

    # -- snapshot / restore drivers (REAL wancontrol.network code) -------------
    def snapshot(self) -> None:
        self.py(
            "import os\n"
            "from wancontrol.config import Config\n"
            "from wancontrol.database import Database\n"
            "from wancontrol import network\n"
            "cfg = Config(os.environ['WANCONTROL_CONFIG']).load()\n"
            "db = Database(cfg.db_path); db.initialize()\n"
            "network.snapshot_default_routes(db, force=True)\n"
        )

    def restore_cli(self) -> None:
        env = {
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT),
            "WANCONTROL_CONFIG": str(self.config_path),
        }
        env.pop("WANCONTROL_DRY_RUN", None)
        env.pop("WANCONTROL_SHADOW", None)
        subprocess.run(
            ["ip", "netns", "exec", self.name, self._python(),
             "-m", "wancontrol.network", "--restore-routes"],
            capture_output=True, text=True, env=env, check=True,
        )


def _write_config(ns: _Netns) -> None:
    ns.config_path.write_text(
        f"""\
interfaces:
  - {{name: {IF_A}, label: "WAN A", expected_speed_mbps: 100, gateway: {GW_A}, routing_table_id: {TABLE_A}}}
  - {{name: {IF_B}, label: "WAN B", expected_speed_mbps: 50, gateway: {GW_B}, routing_table_id: {TABLE_B}}}
  - {{name: {IF_C}, label: "WAN C", expected_speed_mbps: 30, gateway: {GW_C}, routing_table_id: {TABLE_C}}}
wan_mode: failover
probes:
  interval_sec: 5
  dns_targets: ["8.8.8.8"]
  icmp_targets: ["8.8.8.8"]
  http_targets: ["http://example.com"]
  icmp_count: 3
  icmp_timeout_sec: 2
  dns_timeout_sec: 2
  http_timeout_sec: 3
scoring:
  latency_penalty_per_ms: 0.3
  loss_penalty_per_percent: 2.0
  dns_fail_penalty: 15
  http_fail_penalty: 20
  hard_fail_threshold: 20
  hysteresis_switch_to_backup: 25
  hysteresis_return_to_primary: 10
  recovery_margin: 10
controller:
  loop_interval_sec: 5
  benchmark_interval_sec: 300
  metric_collection_timeout_sec: 8
  heartbeat_interval_sec: 5
  heartbeat_stale_sec: 15
retention:
  metrics_hours: 72
  events_days: 30
  prune_interval_min: 60
alerting:
  enabled: false
  webhooks: []
server:
  host: 0.0.0.0
  port: 5000
  secret_key: "netnsharnesssecretkeythatislongenough32"
  jwt_expiry_hours: 1
  session_timeout_minutes: 60
lock_file: {ns.workdir / 'controller.lock'}
heartbeat_file: {ns.workdir / 'controller.heartbeat'}
db_path: {ns.db_path}
log_dir: {ns.workdir}
"""
    )


@pytest.fixture
def netns(tmp_path):
    """Yield an isolated namespace with the dummy WAN topology; always torn down."""
    name = f"wanctl_pt_{uuid.uuid4().hex[:8]}"
    # Idempotent: clear any stale namespace of the same name.
    subprocess.run(["ip", "netns", "del", name], capture_output=True)
    subprocess.run(["ip", "netns", "add", name], capture_output=True, check=True)
    ns = _Netns(name, tmp_path)
    try:
        ns.exec("ip", "link", "set", "lo", "up")
        for ifname, addr in ((IF_A, ADDR_A), (IF_B, ADDR_B), (IF_C, ADDR_C)):
            ns.exec("ip", "link", "add", ifname, "type", "dummy")
            ns.exec("ip", "addr", "add", addr, "dev", ifname)
            ns.exec("ip", "link", "set", ifname, "up")
        _write_config(ns)
        yield ns
    finally:
        subprocess.run(["ip", "netns", "del", name], capture_output=True)


# ── Tests ────────────────────────────────────────────────────────────────────

@_SKIP
def test_netns_harness_script():
    """The end-to-end shell harness must report PASS for all scenarios."""
    assert HARNESS.exists(), f"harness script missing: {HARNESS}"
    res = subprocess.run(
        ["bash", str(HARNESS)],
        capture_output=True, text=True,
    )
    # 0 = PASS, 1 = FAIL, 2 = SKIP. We've already gated on root+netns, so a SKIP
    # here would indicate an environment mismatch worth surfacing as skip.
    if res.returncode == 2:
        pytest.skip(f"harness self-skipped:\n{res.stderr}")
    assert res.returncode == 0, (
        f"netns harness FAILED (exit {res.returncode}):\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


@_SKIP
def test_single_default_snapshot_restore_netns(netns):
    """Single default: snapshot, simulate failover, restore the original."""
    netns.exec("ip", "route", "replace", "default", "via", GW_A, "dev", IF_A)
    netns.snapshot()
    assert netns.default_gateways() == {GW_A}

    # Simulate a controller failover off the snapshotted state.
    netns.exec("ip", "route", "replace", "default", "via", GW_B, "dev", IF_B)
    assert netns.default_gateways() == {GW_B}

    netns.restore_cli()

    gws = netns.default_gateways()
    assert GW_A in gws, f"original default via {GW_A} not restored: {netns.defaults()}"
    assert GW_B not in gws, f"failover default via {GW_B} survived restore: {netns.defaults()}"


@_SKIP
def test_multiple_defaults_snapshot_restore_netns(netns):
    """Multiple defaults (distinct metrics): ALL must be restored in metric order."""
    netns.exec("ip", "route", "add", "default", "via", GW_A, "dev", IF_A, "metric", "100")
    netns.exec("ip", "route", "add", "default", "via", GW_B, "dev", IF_B, "metric", "200")
    assert len(netns.defaults()) == 2

    netns.snapshot()
    assert netns.default_gateways() == {GW_A, GW_B}

    # Clobber with a single different default (simulate controller takeover).
    netns.exec("ip", "route", "del", "default", "via", GW_A, "dev", IF_A, "metric", "100", check=False)
    netns.exec("ip", "route", "del", "default", "via", GW_B, "dev", IF_B, "metric", "200", check=False)
    netns.exec("ip", "route", "replace", "default", "via", GW_C, "dev", IF_C, "metric", "50")
    assert netns.default_gateways() == {GW_C}

    netns.restore_cli()

    routes = netns.defaults()
    gws = netns.default_gateways()
    assert gws == {GW_A, GW_B}, f"both defaults must return, clobber gone: {routes}"
    assert len(routes) == 2, f"expected exactly 2 restored defaults: {routes}"

    # Metric must be preserved (item 7): lowest-metric default is the preferred one.
    metric_by_gw = {
        (r.get("gateway") or r.get("via")): r.get("metric")
        for r in routes
    }
    assert metric_by_gw.get(GW_A) == 100, f"metric not preserved for {GW_A}: {routes}"
    assert metric_by_gw.get(GW_B) == 200, f"metric not preserved for {GW_B}: {routes}"


@_SKIP
def test_empty_snapshot_does_not_delete_live_default_netns(netns):
    """Empty snapshot: restore must NOT strip a default that appeared afterwards."""
    # Snapshot with NO default routes present -> snapshot is empty.
    netns.exec("ip", "route", "flush", "default", check=False)
    assert netns.defaults() == []
    netns.snapshot()

    # A default appears afterwards (e.g. DHCP came up post-boot).
    netns.exec("ip", "route", "replace", "default", "via", GW_A, "dev", IF_A)
    live = netns.default_gateways()
    assert live == {GW_A}

    netns.restore_cli()

    # Safety: the live default must be left exactly as-is (item 4).
    assert netns.default_gateways() == {GW_A}, (
        f"empty-snapshot restore must not delete the live default: {netns.defaults()}"
    )


@_SKIP
def test_snapshot_cleared_after_restore_netns(netns):
    """After a successful restore the snapshot is cleared (item 8)."""
    netns.exec("ip", "route", "replace", "default", "via", GW_A, "dev", IF_A)
    netns.snapshot()
    netns.restore_cli()

    # Read the persisted snapshot state directly; it must be empty/cleared.
    res = netns.py(
        "import os, json\n"
        "from wancontrol.config import Config\n"
        "from wancontrol.database import Database\n"
        "from wancontrol import network\n"
        "cfg = Config(os.environ['WANCONTROL_CONFIG']).load()\n"
        "db = Database(cfg.db_path); db.initialize()\n"
        "snap = db.get_state(network.STATE_PRE_START_DEFAULT_ROUTES)\n"
        "active = db.get_state(network.STATE_ROUTE_MANAGEMENT_ACTIVE)\n"
        "print(json.dumps({'snap': snap, 'active': active}))\n"
    )
    state = json.loads(res.stdout.strip().splitlines()[-1])
    assert not state["snap"], f"snapshot not cleared after restore: {state['snap']!r}"
    assert state["active"] in (None, "", "0"), (
        f"route management flag not cleared: {state['active']!r}"
    )
