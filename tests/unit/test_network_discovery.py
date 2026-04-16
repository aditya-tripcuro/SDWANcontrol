"""
tests/unit/test_network_discovery.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for wancontrol.network_discovery module.

All tests use unittest.mock.patch to mock subprocess calls.
No real network access. No real filesystem access except /sys reads which are also mocked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from wancontrol.network_discovery import (
    DiscoveredInterface,
    check_prerequisites,
    discover_interfaces,
    generate_config_fragment,
    generate_config_fragment_dict,
)


# ── Mock helpers ──────────────────────────────────────────────────────────────

MOCK_IP_LINK = [
    {"ifname": "lo", "link_type": "loopback", "address": "00:00:00:00:00:00", "operstate": "UNKNOWN"},
    {"ifname": "eth0", "link_type": "ether", "address": "aa:bb:cc:dd:ee:01", "operstate": "UP"},
    {"ifname": "eth1", "link_type": "ether", "address": "aa:bb:cc:dd:ee:02", "operstate": "UP"},
    {"ifname": "docker0", "link_type": "ether", "address": "02:42:xx:xx:xx:xx", "operstate": "DOWN"},
]

MOCK_IP_ADDR = [
    {"ifname": "lo", "addr_info": [{"local": "127.0.0.1", "prefixlen": 8}]},
    {"ifname": "eth0", "addr_info": [{"local": "192.168.1.5", "prefixlen": 24}]},
    {"ifname": "eth1", "addr_info": [{"local": "10.0.0.5", "prefixlen": 24}]},
]

MOCK_IP_ROUTE = [
    {"dst": "default", "dev": "eth0", "gateway": "192.168.1.1"},
    {"dst": "default", "dev": "eth1", "gateway": "10.0.0.1"},
    {"dst": "192.168.1.0/24", "dev": "eth0"},
]


def _mock_subprocess_run_link(*args, **kwargs):
    """Mock subprocess.run for ip -j link show."""
    cmd = args[0] if args else kwargs.get("args", [])
    if isinstance(cmd, list) and "link" in cmd:
        return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_LINK), "")
    return subprocess.CompletedProcess(cmd, 0, "", "")


def _mock_subprocess_run_addr(*args, **kwargs):
    """Mock subprocess.run for ip -j -4 addr show."""
    cmd = args[0] if args else kwargs.get("args", [])
    if isinstance(cmd, list) and "addr" in cmd:
        return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ADDR), "")
    return subprocess.CompletedProcess(cmd, 0, "", "")


def _mock_subprocess_run_route(*args, **kwargs):
    """Mock subprocess.run for ip -j route show."""
    cmd = args[0] if args else kwargs.get("args", [])
    if isinstance(cmd, list) and "route" in cmd:
        return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ROUTE), "")
    return subprocess.CompletedProcess(cmd, 0, "", "")


def _mock_subprocess_run_ping_success(*args, **kwargs):
    """Mock subprocess.run for ping - success."""
    cmd = args[0] if args else kwargs.get("args", [])
    if isinstance(cmd, list) and "ping" in cmd:
        return subprocess.CompletedProcess(cmd, 0, "", "")
    # Handle other commands
    if isinstance(cmd, list) and "link" in cmd:
        return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_LINK), "")
    if isinstance(cmd, list) and "addr" in cmd:
        return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ADDR), "")
    if isinstance(cmd, list) and "route" in cmd:
        return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ROUTE), "")
    return subprocess.CompletedProcess(cmd, 0, "", "")


def _mock_subprocess_run_ping_failure(*args, **kwargs):
    """Mock subprocess.run for ping - failure."""
    cmd = args[0] if args else kwargs.get("args", [])
    if isinstance(cmd, list) and "ping" in cmd:
        return subprocess.CompletedProcess(cmd, 1, "", "")
    # Handle other commands
    if isinstance(cmd, list) and "link" in cmd:
        return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_LINK), "")
    if isinstance(cmd, list) and "addr" in cmd:
        return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ADDR), "")
    if isinstance(cmd, list) and "route" in cmd:
        return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ROUTE), "")
    return subprocess.CompletedProcess(cmd, 0, "", "")


# ── PREREQUISITES TESTS ───────────────────────────────────────────────────────

class TestPrerequisites:
    """Tests for check_prerequisites()."""

    def test_check_prerequisites_all_found(self):
        """check_prerequisites() returns [] when ip and ping are found."""
        with patch("wancontrol.network_discovery.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/fake"
            result = check_prerequisites()
            assert result == []

    def test_check_prerequisites_ip_missing(self):
        """check_prerequisites() returns ["ip"] when ip is missing."""
        with patch("wancontrol.network_discovery.shutil.which") as mock_which:
            mock_which.side_effect = lambda x: None if x == "ip" else "/usr/bin/ping"
            result = check_prerequisites()
            assert result == ["ip"]

    def test_check_prerequisites_ping_missing(self):
        """check_prerequisites() returns ["ping"] when ping is missing."""
        with patch("wancontrol.network_discovery.shutil.which") as mock_which:
            mock_which.side_effect = lambda x: "/usr/bin/ip" if x == "ip" else None
            result = check_prerequisites()
            assert result == ["ping"]

    def test_check_prerequisites_both_missing(self):
        """check_prerequisites() returns both when both missing."""
        with patch("wancontrol.network_discovery.shutil.which") as mock_which:
            mock_which.return_value = None
            result = check_prerequisites()
            assert set(result) == {"ip", "ping"}


# ── INTERFACE ENUMERATION TESTS ───────────────────────────────────────────────

class TestInterfaceEnumeration:
    """Tests for interface enumeration from ip link."""

    @patch("subprocess.run")
    def test_loopback_excluded(self, mock_run):
        """loopback (lo) is excluded from results."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        names = [i.name for i in interfaces]
        assert "lo" not in names

    @patch("subprocess.run")
    def test_docker_excluded(self, mock_run):
        """docker0 is excluded (virtual prefix match)."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        docker_ifaces = [i for i in interfaces if i.name == "docker0"]
        assert len(docker_ifaces) == 1
        assert docker_ifaces[0].skip_reason == "virtual"

    @patch("subprocess.run")
    def test_eth_included(self, mock_run):
        """eth0 and eth1 are included."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        names = [i.name for i in interfaces]
        assert "eth0" in names
        assert "eth1" in names

    @patch("subprocess.run")
    def test_operstate_down_sets_is_up_false(self, mock_run):
        """operstate DOWN sets is_up=False."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        docker_iface = next((i for i in interfaces if i.name == "docker0"), None)
        assert docker_iface is not None
        assert docker_iface.is_up is False

    @patch("subprocess.run")
    def test_mac_address_captured(self, mock_run):
        """MAC address is captured correctly."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.mac == "aa:bb:cc:dd:ee:01"


# ── IP ADDRESS PARSING TESTS ──────────────────────────────────────────────────

class TestIPAddressParsing:
    """Tests for IP address parsing from ip addr."""

    @patch("subprocess.run")
    def test_eth0_correct_ip_prefix(self, mock_run):
        """eth0 gets correct ip and prefix_len."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.ip == "192.168.1.5"
        assert eth0.prefix_len == 24

    @patch("subprocess.run")
    def test_no_addr_info_empty_ip(self, mock_run):
        """interface with no addr_info entry gets ip="" and prefix_len=0."""
        # Modify mock to exclude eth1 from addr_info
        mock_addr = [
            {"ifname": "lo", "addr_info": [{"local": "127.0.0.1", "prefixlen": 8}]},
            {"ifname": "eth0", "addr_info": [{"local": "192.168.1.5", "prefixlen": 24}]},
        ]

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "addr" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(mock_addr), "")
            if isinstance(cmd, list) and "link" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_LINK), "")
            if isinstance(cmd, list) and "route" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ROUTE), "")
            if isinstance(cmd, list) and "ping" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        interfaces = discover_interfaces()
        eth1 = next((i for i in interfaces if i.name == "eth1"), None)
        assert eth1 is not None
        assert eth1.ip == ""
        assert eth1.prefix_len == 0

    @patch("subprocess.run")
    def test_only_first_ipv4_used(self, mock_run):
        """only first IPv4 address is used when multiple exist."""
        mock_addr = [
            {"ifname": "eth0", "addr_info": [
                {"local": "192.168.1.5", "prefixlen": 24},
                {"local": "192.168.2.5", "prefixlen": 24},
            ]},
        ]
        mock_link = [
            {"ifname": "eth0", "link_type": "ether", "address": "aa:bb:cc:dd:ee:01", "operstate": "UP"},
        ]
        mock_route = [
            {"dst": "default", "dev": "eth0", "gateway": "192.168.1.1"},
        ]

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "addr" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(mock_addr), "")
            if isinstance(cmd, list) and "link" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(mock_link), "")
            if isinstance(cmd, list) and "route" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(mock_route), "")
            if isinstance(cmd, list) and "ping" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.ip == "192.168.1.5"


# ── GATEWAY PARSING TESTS ─────────────────────────────────────────────────────

class TestGatewayParsing:
    """Tests for gateway parsing from ip route."""

    @patch("subprocess.run")
    def test_eth0_correct_gateway(self, mock_run):
        """eth0 gets correct gateway from route table."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.gateway == "192.168.1.1"

    @patch("subprocess.run")
    def test_no_default_route_empty_gateway(self, mock_run):
        """interface with no default route gets gateway=\"\"."""
        mock_route = [
            {"dst": "192.168.1.0/24", "dev": "eth0"},
        ]

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "route" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(mock_route), "")
            if isinstance(cmd, list) and "link" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_LINK), "")
            if isinstance(cmd, list) and "addr" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ADDR), "")
            if isinstance(cmd, list) and "ping" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.gateway == ""

    @patch("subprocess.run")
    def test_non_default_routes_ignored(self, mock_run):
        """non-default routes are ignored."""
        mock_route = [
            {"dst": "192.168.1.0/24", "dev": "eth0", "gateway": "192.168.1.254"},
        ]

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "route" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(mock_route), "")
            if isinstance(cmd, list) and "link" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_LINK), "")
            if isinstance(cmd, list) and "addr" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ADDR), "")
            if isinstance(cmd, list) and "ping" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.gateway == ""


# ── SPEED READING TESTS ───────────────────────────────────────────────────────

class TestSpeedReading:
    """Tests for reading link speed from /sys/class/net."""

    @patch("pathlib.Path.read_text")
    @patch("subprocess.run")
    def test_speed_read_integer(self, mock_run, mock_read):
        """reads integer from /sys/class/net/<iface>/speed correctly."""
        mock_read.return_value = "1000\n"
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.speed_mbps == 1000

    @patch("pathlib.Path.read_text")
    @patch("subprocess.run")
    def test_speed_file_not_exist(self, mock_run, mock_read):
        """returns -1 when file does not exist."""
        mock_read.side_effect = FileNotFoundError()
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.speed_mbps == -1

    @patch("pathlib.Path.read_text")
    @patch("subprocess.run")
    def test_speed_returns_minus_one(self, mock_run, mock_read):
        """returns -1 when file contains -1."""
        mock_read.return_value = "-1\n"
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.speed_mbps == -1

    @patch("pathlib.Path.read_text")
    @patch("subprocess.run")
    def test_speed_non_integer(self, mock_run, mock_read):
        """returns -1 when file contains non-integer."""
        mock_read.return_value = "unknown\n"
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.speed_mbps == -1


# ── REACHABILITY TESTS ────────────────────────────────────────────────────────

class TestReachability:
    """Tests for reachability testing via ping."""

    @patch("subprocess.run")
    def test_reachable_ping_success(self, mock_run):
        """is_reachable=True when ping returncode==0."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.is_reachable is True

    @patch("subprocess.run")
    def test_reachable_ping_failure(self, mock_run):
        """is_reachable=False when ping returncode!=0."""
        mock_run.side_effect = _mock_subprocess_run_ping_failure
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.is_reachable is False

    @patch("subprocess.run")
    def test_reachable_ping_timeout(self, mock_run):
        """is_reachable=False when ping times out (TimeoutExpired)."""
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "ping" in cmd:
                raise subprocess.TimeoutExpired(cmd, 5)
            if isinstance(cmd, list) and "link" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_LINK), "")
            if isinstance(cmd, list) and "addr" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ADDR), "")
            if isinstance(cmd, list) and "route" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ROUTE), "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.is_reachable is False

    @patch("subprocess.run")
    def test_reachable_no_ip_no_ping(self, mock_run):
        """is_reachable=False when interface has no IP (ping not called)."""
        mock_addr = [
            {"ifname": "lo", "addr_info": [{"local": "127.0.0.1", "prefixlen": 8}]},
        ]
        mock_link = [
            {"ifname": "lo", "link_type": "loopback", "address": "00:00:00:00:00:00", "operstate": "UNKNOWN"},
            {"ifname": "eth0", "link_type": "ether", "address": "aa:bb:cc:dd:ee:01", "operstate": "UP"},
        ]
        mock_route = [
            {"dst": "default", "dev": "eth0", "gateway": "192.168.1.1"},
        ]

        ping_called = []

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "ping" in cmd:
                ping_called.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if isinstance(cmd, list) and "link" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(mock_link), "")
            if isinstance(cmd, list) and "addr" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(mock_addr), "")
            if isinstance(cmd, list) and "route" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(mock_route), "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.is_reachable is False
        assert len(ping_called) == 0  # ping should not be called


# ── CLASSIFICATION TESTS ──────────────────────────────────────────────────────

class TestClassification:
    """Tests for interface classification as WAN candidates."""

    @patch("subprocess.run")
    def test_wan_candidate_all_conditions_met(self, mock_run):
        """is_wan_candidate=True when has gateway, is_up, is_reachable."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.is_wan_candidate is True

    @patch("subprocess.run")
    def test_not_wan_no_gateway(self, mock_run):
        """is_wan_candidate=False when no gateway."""
        mock_route = [
            {"dst": "192.168.1.0/24", "dev": "eth0"},
        ]

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "route" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(mock_route), "")
            if isinstance(cmd, list) and "link" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_LINK), "")
            if isinstance(cmd, list) and "addr" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ADDR), "")
            if isinstance(cmd, list) and "ping" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.is_wan_candidate is False

    @patch("subprocess.run")
    def test_not_wan_not_reachable(self, mock_run):
        """is_wan_candidate=False when not reachable."""
        mock_run.side_effect = _mock_subprocess_run_ping_failure
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.is_wan_candidate is False

    @patch("subprocess.run")
    def test_skip_reason_no_gateway(self, mock_run):
        """skip_reason="no_gateway" when has IP but no gateway."""
        mock_route = [
            {"dst": "192.168.1.0/24", "dev": "eth0"},
        ]

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "route" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(mock_route), "")
            if isinstance(cmd, list) and "link" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_LINK), "")
            if isinstance(cmd, list) and "addr" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ADDR), "")
            if isinstance(cmd, list) and "ping" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.skip_reason == "no_gateway"

    @patch("subprocess.run")
    def test_skip_reason_not_reachable(self, mock_run):
        """skip_reason="not_reachable" when ping fails."""
        mock_run.side_effect = _mock_subprocess_run_ping_failure
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.skip_reason == "not_reachable"

    @patch("subprocess.run")
    def test_skip_reason_virtual(self, mock_run):
        """skip_reason="virtual" for docker0."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        docker0 = next((i for i in interfaces if i.name == "docker0"), None)
        assert docker0 is not None
        assert docker0.skip_reason == "virtual"

    @patch("subprocess.run")
    def test_skip_reason_empty_for_candidates(self, mock_run):
        """skip_reason="" for WAN candidates."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.skip_reason == ""


# ── ROUTING TABLE ID ASSIGNMENT TESTS ─────────────────────────────────────────

class TestRoutingTableIdAssignment:
    """Tests for routing table ID assignment."""

    @patch("subprocess.run")
    def test_first_candidate_id_100(self, mock_run):
        """first WAN candidate gets routing_table_id=100."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.suggested_routing_table_id == 100

    @patch("subprocess.run")
    def test_second_candidate_id_101(self, mock_run):
        """second WAN candidate gets routing_table_id=101."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        eth1 = next((i for i in interfaces if i.name == "eth1"), None)
        assert eth1 is not None
        assert eth1.suggested_routing_table_id == 101

    @patch("subprocess.run")
    def test_non_candidate_id_0(self, mock_run):
        """non-candidates get routing_table_id=0."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        docker0 = next((i for i in interfaces if i.name == "docker0"), None)
        assert docker0 is not None
        assert docker0.suggested_routing_table_id == 0


# ── CONFIG GENERATION TESTS ───────────────────────────────────────────────────

class TestConfigGeneration:
    """Tests for config fragment generation."""

    @patch("subprocess.run")
    def test_generate_config_fragment_valid_yaml(self, mock_run):
        """generate_config_fragment() returns valid YAML string."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        yaml_str = generate_config_fragment(interfaces)
        assert "interfaces:" in yaml_str
        assert "- name:" in yaml_str
        assert "eth0" in yaml_str

    @patch("subprocess.run")
    def test_generate_config_fragment_only_candidates(self, mock_run):
        """YAML contains only WAN candidates."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        yaml_str = generate_config_fragment(interfaces)
        assert "docker0" not in yaml_str

    @patch("subprocess.run")
    @patch("pathlib.Path.read_text")
    def test_generate_config_fragment_unknown_speed_comment(self, mock_read, mock_run):
        """speed -1 results in expected_speed_mbps: 100 with comment."""
        mock_read.return_value = "-1\n"
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        yaml_str = generate_config_fragment(interfaces)
        assert "expected_speed_mbps: 100" in yaml_str
        assert "# speed unknown" in yaml_str

    @patch("subprocess.run")
    def test_generate_config_fragment_no_candidates(self, mock_run):
        """generate_config_fragment() returns "" when no candidates."""
        # Make all interfaces fail reachability
        mock_run.side_effect = _mock_subprocess_run_ping_failure
        interfaces = discover_interfaces()
        yaml_str = generate_config_fragment(interfaces)
        assert yaml_str == ""

    @patch("subprocess.run")
    def test_generate_config_fragment_dict_correct(self, mock_run):
        """generate_config_fragment_dict() returns correct list of dicts."""
        mock_run.side_effect = _mock_subprocess_run_ping_success
        interfaces = discover_interfaces()
        result = generate_config_fragment_dict(interfaces)
        assert isinstance(result, list)
        assert len(result) == 2  # eth0 and eth1
        assert result[0]["name"] == "eth0"
        assert result[0]["routing_table_id"] == 100
        assert result[1]["name"] == "eth1"
        assert result[1]["routing_table_id"] == 101


# ── ERROR RESILIENCE TESTS ────────────────────────────────────────────────────

class TestErrorResilience:
    """Tests for error handling and resilience."""

    @patch("subprocess.run")
    def test_ip_link_failure_returns_empty_list(self, mock_run):
        """ip link command failure returns empty list, does not raise."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "ip")
        interfaces = discover_interfaces()
        assert interfaces == []

    @patch("subprocess.run")
    def test_ip_route_failure_sets_empty_gateways(self, mock_run):
        """ip route command failure sets all gateways to "", does not raise."""
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "route" in cmd:
                raise subprocess.CalledProcessError(1, "ip")
            if isinstance(cmd, list) and "link" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_LINK), "")
            if isinstance(cmd, list) and "addr" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ADDR), "")
            if isinstance(cmd, list) and "ping" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        interfaces = discover_interfaces()
        # Should still have interfaces, but with empty gateways
        eth0 = next((i for i in interfaces if i.name == "eth0"), None)
        assert eth0 is not None
        assert eth0.gateway == ""

    @patch("subprocess.run")
    def test_single_ping_failure_does_not_abort_others(self, mock_run):
        """single interface ping failure does not abort other interfaces."""
        call_count = [0]

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "ping" in cmd:
                call_count[0] += 1
                # Fail first ping, succeed on second
                if call_count[0] == 1:
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if isinstance(cmd, list) and "link" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_LINK), "")
            if isinstance(cmd, list) and "addr" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ADDR), "")
            if isinstance(cmd, list) and "route" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(MOCK_IP_ROUTE), "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        interfaces = discover_interfaces()
        # Both eth0 and eth1 should be discovered
        names = [i.name for i in interfaces]
        assert "eth0" in names
        assert "eth1" in names

    @patch("subprocess.run")
    def test_malformed_json_handled_gracefully(self, mock_run):
        """malformed JSON from ip command is handled gracefully."""
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "link" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "not valid json{", "")
            if isinstance(cmd, list) and "addr" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "not valid json{", "")
            if isinstance(cmd, list) and "route" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "not valid json{", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = side_effect
        interfaces = discover_interfaces()
        # Should return empty list on link JSON failure
        assert interfaces == []
