"""
tests/unit/test_network.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for wancontrol.network.

All subprocess calls are mocked via unittest.mock.patch.
WANCONTROL_DRY_RUN=0 is forced so real code paths run (subprocess is
mocked, not skipped).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

# Force dry-run OFF for all tests so real code paths execute.
os.environ["WANCONTROL_DRY_RUN"] = "0"

import wancontrol.network as net
from wancontrol.network import (
    _run,
    add_policy_route_table,
    add_policy_rule,
    check_prerequisites,
    enable_ip_forwarding,
    enable_rp_filter_loose,
    flush_policy_route_table,
    get_default_gateway,
    get_interface_ip,
    get_interface_ip6,
    get_interface_stats,
    probe_dns,
    probe_http,
    probe_icmp,
    remove_policy_rule,
    set_default_route,
    set_load_balance_route,
)


# ── Mock helpers ──────────────────────────────────────────────────────────────

def make_run_result(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Return a mock CompletedProcess for patching subprocess.run."""
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


def mock_run_success(stdout: str = ""):
    """Return a context manager that patches _run to return (True, stdout, '')."""
    return patch("wancontrol.network._run", return_value=(True, stdout, ""))


def mock_run_failure(stderr: str = "some error"):
    """Return a context manager that patches _run to return (False, '', stderr)."""
    return patch("wancontrol.network._run", return_value=(False, "", stderr))


# ── DRY RUN MODE ─────────────────────────────────────────────────────────────

class TestDryRunMode:
    """Tests for WANCONTROL_DRY_RUN=1 behaviour."""

    def test_dry_run_no_subprocess_called(self):
        """In dry-run mode, set_default_route() must not call subprocess.run."""
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                net.set_default_route("192.168.1.1", "eth0")
                mock_sub.assert_not_called()

    def test_dry_run_returns_true(self):
        """In dry-run mode, set_default_route() returns True without running commands."""
        with patch.object(net, "DRY_RUN", True):
            result = net.set_default_route("192.168.1.1", "eth0")
        assert result is True

    def test_dry_run_logs_message(self, caplog):
        """In dry-run mode, the function logs a 'DRY RUN — would run:' message."""
        with patch.object(net, "DRY_RUN", True):
            with caplog.at_level(logging.INFO, logger="wancontrol.network"):
                net.set_default_route("192.168.1.1", "eth0")
        assert any("DRY RUN" in r.message for r in caplog.records)


# ── _run() HELPER ─────────────────────────────────────────────────────────────

class TestRunHelper:
    """Unit tests for the private _run() helper."""

    def test_success_returns_true_stdout_stderr(self):
        """returncode=0 → (True, stdout, stderr)."""
        with patch(
            "subprocess.run",
            return_value=make_run_result(stdout="hello", stderr="warn", returncode=0),
        ):
            ok, out, err = _run(["echo", "hello"])
        assert ok is True
        assert out == "hello"
        assert err == "warn"

    def test_failure_returns_false_stdout_stderr(self):
        """returncode!=0 → (False, stdout, stderr)."""
        with patch(
            "subprocess.run",
            return_value=make_run_result(stdout="", stderr="oops", returncode=1),
        ):
            ok, out, err = _run(["false"])
        assert ok is False
        assert err == "oops"

    def test_timeout_returns_false_with_timeout_stderr(self):
        """TimeoutExpired → (False, '', 'timeout')."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["sleep"], timeout=1),
        ):
            ok, out, err = _run(["sleep", "100"])
        assert ok is False
        assert out == ""
        assert err == "timeout"

    def test_sudo_failure_logs_error(self, caplog):
        """check_sudo=True + 'password is required' in stderr → ERROR logged."""
        with patch(
            "subprocess.run",
            return_value=make_run_result(
                stdout="",
                stderr="sudo: password is required",
                returncode=1,
            ),
        ):
            with caplog.at_level(logging.ERROR, logger="wancontrol.network"):
                ok, _, _ = _run(
                    ["sudo", "ip", "route", "del", "default"],
                    check_sudo=True,
                )
        assert ok is False
        assert any(
            "password" in r.message.lower() or "sudo" in r.message.lower()
            for r in caplog.records
            if r.levelno >= logging.ERROR
        )


# ── INTERFACE INFORMATION ─────────────────────────────────────────────────────

class TestGetInterfaceIp:
    _ADDR_OUTPUT = (
        "2: eth0    inet 192.168.1.100/24 brd 192.168.1.255 "
        "scope global eth0\\       valid_lft forever preferred_lft forever\n"
    )

    def test_parses_ip_addr_output_correctly(self):
        """get_interface_ip() strips the prefix and returns the address."""
        with mock_run_success(stdout=self._ADDR_OUTPUT):
            ip = get_interface_ip("eth0")
        assert ip == "192.168.1.100"

    def test_returns_none_when_interface_not_found(self):
        """Empty stdout → None."""
        with mock_run_success(stdout=""):
            ip = get_interface_ip("nonexistent0")
        assert ip is None

    def test_returns_none_on_command_failure(self):
        """Command failure → None."""
        with mock_run_failure():
            ip = get_interface_ip("eth0")
        assert ip is None


class TestGetDefaultGateway:
    def test_parses_json_route_output(self):
        """Parses ip -j route JSON and returns (gateway, interface)."""
        routes = [{"dst": "default", "gateway": "192.168.1.1", "dev": "eth0"}]
        with mock_run_success(stdout=json.dumps(routes)):
            result = get_default_gateway()
        assert result == ("192.168.1.1", "eth0")

    def test_returns_none_when_no_default_route(self):
        """No entry with dst=='default' → None."""
        routes = [{"dst": "192.168.1.0/24", "dev": "eth0", "prefsrc": "192.168.1.100"}]
        with mock_run_success(stdout=json.dumps(routes)):
            result = get_default_gateway()
        assert result is None

    def test_returns_none_on_command_failure(self):
        """Command failure → None."""
        with mock_run_failure():
            result = get_default_gateway()
        assert result is None


class TestGetInterfaceStats:
    _PROC_CONTENT = (
        "Inter-|   Receive                                                "
        "|  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast"
        "|bytes    packets errs drop fifo colls carrier compressed\n"
        "    lo:       0       0    0    0    0     0          0         0"
        "        0       0    0    0    0     0       0          0\n"
        "  eth0:   12345     678    0    0    0     0          0         0"
        "    98765     432    0    0    0     0       0          0\n"
    )

    def test_parses_proc_net_dev_correctly(self):
        """Reads rx_bytes, rx_packets, tx_bytes, tx_packets from /proc/net/dev."""
        with patch("wancontrol.network.Path") as MockPath:
            MockPath.return_value.read_text.return_value = self._PROC_CONTENT
            stats = get_interface_stats("eth0")
        assert stats["rx_bytes"] == 12345
        assert stats["rx_packets"] == 678
        assert stats["tx_bytes"] == 98765
        assert stats["tx_packets"] == 432

    def test_returns_zeros_for_unknown_interface(self):
        """Interface not in /proc/net/dev → all-zero dict."""
        with patch("wancontrol.network.Path") as MockPath:
            MockPath.return_value.read_text.return_value = self._PROC_CONTENT
            stats = get_interface_stats("eth99")
        assert stats == {
            "rx_bytes": 0,
            "tx_bytes": 0,
            "rx_packets": 0,
            "tx_packets": 0,
        }


# ── ROUTE MANAGEMENT ──────────────────────────────────────────────────────────

class TestSetDefaultRoute:
    def test_calls_del_then_add_in_order(self):
        """set_default_route() calls 'del default' before 'add default'."""
        call_order: list[list[str]] = []

        def capture(args, timeout=10, check_sudo=False):
            call_order.append(list(args))
            return (True, "", "")

        with patch("wancontrol.network._run", side_effect=capture):
            set_default_route("192.168.1.1", "eth0")

        assert len(call_order) == 2
        assert "del" in call_order[0]
        assert "default" in call_order[0]
        assert "add" in call_order[1]
        assert "default" in call_order[1]

    def test_returns_true_when_add_succeeds(self):
        """Returns True when the add command succeeds."""
        side_effects = [(True, "", ""), (True, "", "")]
        with patch("wancontrol.network._run", side_effect=side_effects):
            assert set_default_route("192.168.1.1", "eth0") is True

    def test_returns_false_when_add_fails(self):
        """Returns False when the add command fails."""
        side_effects = [(True, "", ""), (False, "", "RTNETLINK: file exists")]
        with patch("wancontrol.network._run", side_effect=side_effects):
            assert set_default_route("192.168.1.1", "eth0") is False


class TestSetLoadBalanceRoute:
    def test_builds_correct_nexthop_command(self):
        """Builds a command with nexthop via/dev/weight tokens."""
        captured: list[list[str]] = []

        def capture(args, timeout=10, check_sudo=False):
            captured.append(list(args))
            return (True, "", "")

        with patch("wancontrol.network._run", side_effect=capture):
            set_load_balance_route([("192.168.1.1", "eth0", 10)])

        add_cmd = next(a for a in captured if "add" in a)
        assert "nexthop" in add_cmd
        assert "192.168.1.1" in add_cmd
        assert "eth0" in add_cmd
        assert "10" in add_cmd

    def test_raises_value_error_on_empty_nexthops(self):
        """Raises ValueError when nexthops list is empty."""
        with pytest.raises(ValueError):
            set_load_balance_route([])

    def test_three_nexthops_builds_correct_command(self):
        """Three nexthops → three 'nexthop' tokens in the add command."""
        captured: list[list[str]] = []

        def capture(args, timeout=10, check_sudo=False):
            captured.append(list(args))
            return (True, "", "")

        nexthops = [
            ("192.168.1.1", "eth0", 10),
            ("10.0.0.1", "eth1", 3),
            ("172.16.0.1", "eth2", 5),
        ]
        with patch("wancontrol.network._run", side_effect=capture):
            set_load_balance_route(nexthops)

        add_cmd = next(a for a in captured if "add" in a)
        assert add_cmd.count("nexthop") == 3


class TestAddPolicyRouteTable:
    def test_calls_both_route_add_commands(self):
        """Issues exactly two ip route add commands."""
        call_count = [0]

        def count_calls(args, timeout=10, check_sudo=False):
            call_count[0] += 1
            return (True, "", "")

        with patch("wancontrol.network._run", side_effect=count_calls):
            add_policy_route_table(
                100, "eth0", "192.168.1.1", "192.168.1.2", "192.168.1.0/24"
            )

        assert call_count[0] == 2

    def test_returns_false_if_first_command_fails(self):
        """Returns False immediately if the first add command fails."""
        side_effects = [(False, "", "error")]
        with patch("wancontrol.network._run", side_effect=side_effects):
            assert (
                add_policy_route_table(
                    100, "eth0", "192.168.1.1", "192.168.1.2", "192.168.1.0/24"
                )
                is False
            )

    def test_returns_false_if_second_command_fails(self):
        """Returns False if the second add command fails."""
        side_effects = [(True, "", ""), (False, "", "error")]
        with patch("wancontrol.network._run", side_effect=side_effects):
            assert (
                add_policy_route_table(
                    100, "eth0", "192.168.1.1", "192.168.1.2", "192.168.1.0/24"
                )
                is False
            )


class TestFlushPolicyRouteTable:
    def test_calls_correct_command(self):
        """Calls 'ip route flush table <id>'."""
        captured: list[list[str]] = []

        def capture(args, timeout=10, check_sudo=False):
            captured.append(list(args))
            return (True, "", "")

        with patch("wancontrol.network._run", side_effect=capture):
            flush_policy_route_table(100)

        assert len(captured) == 1
        assert "flush" in captured[0]
        assert "100" in captured[0]


class TestAddPolicyRule:
    def test_returns_true_on_success(self):
        """Returns True when the ip rule add command succeeds."""
        with mock_run_success():
            assert add_policy_rule(100, "192.168.1.2") is True

    def test_returns_false_and_logs_info_if_already_exists(self, caplog):
        """Returns False and logs INFO when rule already exists."""
        with patch(
            "wancontrol.network._run",
            return_value=(False, "", "already exists"),
        ):
            with caplog.at_level(logging.INFO, logger="wancontrol.network"):
                result = add_policy_rule(100, "192.168.1.2")

        assert result is False
        assert any(
            "already exists" in r.message.lower() or "skipping" in r.message.lower()
            for r in caplog.records
            if r.levelno == logging.INFO
        )


class TestRemovePolicyRule:
    def test_returns_true_even_if_rule_did_not_exist(self):
        """Returns True even when the ip rule del command reports no such rule."""
        with patch(
            "wancontrol.network._run",
            return_value=(False, "", "No such file or directory"),
        ):
            assert remove_policy_rule(100) is True


# ── SYSTEM CONFIGURATION ──────────────────────────────────────────────────────

class TestSystemConfiguration:
    def test_enable_ip_forwarding_calls_sysctl(self):
        """Calls sysctl -w net.ipv4.ip_forward=1."""
        captured: list[list[str]] = []

        def capture(args, timeout=10, check_sudo=False):
            captured.append(list(args))
            return (True, "", "")

        with patch("wancontrol.network._run", side_effect=capture):
            enable_ip_forwarding()

        assert len(captured) == 1
        assert "sysctl" in captured[0]
        assert "net.ipv4.ip_forward=1" in captured[0]

    def test_enable_rp_filter_loose_substitutes_interface_name(self):
        """Uses the interface name in the sysctl key."""
        captured: list[list[str]] = []

        def capture(args, timeout=10, check_sudo=False):
            captured.append(list(args))
            return (True, "", "")

        with patch("wancontrol.network._run", side_effect=capture):
            enable_rp_filter_loose("eth0")

        assert len(captured) == 1
        assert any("net.ipv4.conf.eth0.rp_filter=2" in arg for arg in captured[0])

    def test_check_prerequisites_returns_empty_when_all_found(self):
        """Returns [] when all required commands are found by shutil.which."""
        with patch("shutil.which", return_value="/usr/bin/ip"):
            result = check_prerequisites()
        assert result == []

    def test_check_prerequisites_returns_missing_command_names(self):
        """Returns only the names of commands not found."""
        def which_side_effect(cmd: str):
            return None if cmd == "dig" else f"/usr/bin/{cmd}"

        with patch("shutil.which", side_effect=which_side_effect):
            result = check_prerequisites()

        assert "dig" in result
        assert "ip" not in result
        assert "ping" not in result

    def test_check_prerequisites_uses_shutil_which_not_subprocess(self):
        """check_prerequisites() must never call subprocess.run."""
        with patch("shutil.which", return_value="/usr/bin/cmd") as mock_which:
            with patch("subprocess.run") as mock_sub:
                check_prerequisites()
        mock_sub.assert_not_called()
        assert mock_which.called


# ── PROBE HELPERS ─────────────────────────────────────────────────────────────

_PING_SUCCESS = (
    "PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n"
    "64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=5.23 ms\n"
    "64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=5.12 ms\n"
    "\n"
    "--- 8.8.8.8 ping statistics ---\n"
    "2 packets transmitted, 2 received, 0% packet loss, time 1001ms\n"
    "rtt min/avg/max/mdev = 5.120/5.175/5.230/0.055 ms\n"
)


class TestProbeIcmp:
    def test_parses_rtt_line_correctly(self):
        """Extracts avg latency and mdev (jitter) from the rtt line."""
        with mock_run_success(stdout=_PING_SUCCESS):
            avg, jitter, loss = probe_icmp("eth0", "8.8.8.8", 2, 3)
        assert abs(avg - 5.175) < 0.001
        assert abs(jitter - 0.055) < 0.001

    def test_parses_packet_loss_correctly(self):
        """Extracts 0% loss from the statistics line."""
        with mock_run_success(stdout=_PING_SUCCESS):
            _, _, loss = probe_icmp("eth0", "8.8.8.8", 2, 3)
        assert loss == 0.0

    def test_returns_failure_on_ping_command_failure(self):
        """Command failure → (0.0, 0.0, 100.0)."""
        with mock_run_failure():
            result = probe_icmp("eth0", "8.8.8.8", 2, 3)
        assert result == (0.0, 0.0, 100.0)

    def test_returns_failure_on_timeout(self):
        """Timeout → (0.0, 0.0, 100.0)."""
        with patch(
            "wancontrol.network._run", return_value=(False, "", "timeout")
        ):
            result = probe_icmp("eth0", "8.8.8.8", 2, 3)
        assert result == (0.0, 0.0, 100.0)


class TestProbeDns:
    def test_returns_true_when_dig_returns_output(self):
        """Returns True when dig succeeds and stdout is non-empty."""
        with mock_run_success(stdout="142.250.80.46\n"):
            assert probe_dns("eth0", "8.8.8.8", 3, "192.168.1.2") is True

    def test_returns_false_when_dig_stdout_empty(self):
        """Returns False when dig succeeds but stdout is empty."""
        with mock_run_success(stdout=""):
            assert probe_dns("eth0", "8.8.8.8", 3, "192.168.1.2") is False

    def test_returns_false_on_command_failure(self):
        """Command failure → False."""
        with mock_run_failure():
            assert probe_dns("eth0", "8.8.8.8", 3, "192.168.1.2") is False


class TestProbeHttp:
    def test_returns_true_on_200_response(self):
        """HTTP 200 → (True, >0.0)."""
        with mock_run_success(stdout="200 0.123"):
            ok, ms = probe_http("eth0", "http://example.com", 5)
        assert ok is True
        assert ms > 0.0

    def test_returns_true_on_204_response(self):
        """HTTP 204 → (True, >0.0)."""
        with mock_run_success(stdout="204 0.050"):
            ok, ms = probe_http("eth0", "http://example.com", 5)
        assert ok is True
        assert ms > 0.0

    def test_returns_false_on_404_response(self):
        """HTTP 404 → (False, 0.0)."""
        with mock_run_success(stdout="404 0.100"):
            ok, ms = probe_http("eth0", "http://example.com", 5)
        assert ok is False
        assert ms == 0.0

    def test_returns_false_on_curl_failure(self):
        """curl command failure → (False, 0.0)."""
        with mock_run_failure():
            ok, ms = probe_http("eth0", "http://example.com", 5)
        assert ok is False
        assert ms == 0.0

    def test_returns_false_on_empty_stdout(self):
        """curl succeeds but empty stdout → (False, 0.0)."""
        with mock_run_success(stdout=""):
            ok, ms = probe_http("eth0", "http://example.com", 5)
        assert ok is False
        assert ms == 0.0

    def test_returns_false_on_non_parseable_stdout(self):
        """curl stdout with non-numeric values → (False, 0.0)."""
        with mock_run_success(stdout="bad output"):
            ok, ms = probe_http("eth0", "http://example.com", 5)
        assert ok is False
        assert ms == 0.0


# ── ADDITIONAL COVERAGE: DRY_RUN branches and error paths ────────────────────

class TestRunHelperErrorPaths:
    """Cover SubprocessError and OSError branches in _run()."""

    def test_subprocess_error_returns_false(self):
        """SubprocessError (non-timeout) → (False, '', error_message)."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.SubprocessError("pipe broken"),
        ):
            ok, out, err = _run(["ip", "link"])
        assert ok is False
        assert out == ""
        assert "pipe broken" in err

    def test_os_error_returns_false(self):
        """OSError (e.g. command not found) → (False, '', error_message)."""
        with patch(
            "subprocess.run",
            side_effect=OSError("No such file or directory"),
        ):
            ok, out, err = _run(["nonexistent_cmd"])
        assert ok is False
        assert out == ""
        assert "No such file" in err


class TestGetInterfaceIp6:
    """Tests for get_interface_ip6() — IPv6 counterpart of get_interface_ip."""

    _ADDR6_OUTPUT = (
        "2: eth0    inet6 2001:db8::1/64 scope global eth0\\"
        "       valid_lft forever preferred_lft forever\n"
    )

    def test_parses_ip6_addr_output_correctly(self):
        """Strips the prefix and returns the IPv6 address."""
        with mock_run_success(stdout=self._ADDR6_OUTPUT):
            ip = get_interface_ip6("eth0")
        assert ip == "2001:db8::1"

    def test_returns_none_when_interface_not_found(self):
        """Empty stdout → None."""
        with mock_run_success(stdout=""):
            assert get_interface_ip6("eth99") is None

    def test_returns_none_on_command_failure(self):
        """Command failure → None."""
        with mock_run_failure():
            assert get_interface_ip6("eth0") is None

    def test_dry_run_returns_none(self):
        """DRY_RUN mode → None without calling subprocess."""
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.get_interface_ip6("eth0")
                mock_sub.assert_not_called()
        assert result is None


class TestGetInterfaceIpDryRun:
    def test_dry_run_returns_none(self):
        """DRY_RUN mode → None for get_interface_ip."""
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.get_interface_ip("eth0")
                mock_sub.assert_not_called()
        assert result is None


class TestGetDefaultGatewayEdgeCases:
    def test_dry_run_returns_none(self):
        """DRY_RUN mode → None for get_default_gateway."""
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.get_default_gateway()
                mock_sub.assert_not_called()
        assert result is None

    def test_returns_none_on_malformed_json(self):
        """Malformed JSON output → None (logs DEBUG)."""
        with mock_run_success(stdout="not-json{{{"):
            result = get_default_gateway()
        assert result is None


class TestGetInterfaceStatsEdgeCases:
    def test_returns_zeros_on_os_error(self):
        """OSError reading /proc/net/dev → all-zero dict."""
        with patch("wancontrol.network.Path") as MockPath:
            MockPath.return_value.read_text.side_effect = OSError("permission denied")
            stats = get_interface_stats("eth0")
        assert stats == {
            "rx_bytes": 0,
            "tx_bytes": 0,
            "rx_packets": 0,
            "tx_packets": 0,
        }


class TestDryRunAllFunctions:
    """Cover DRY_RUN branches in route-management and system-config functions."""

    def test_set_load_balance_route_dry_run(self):
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.set_load_balance_route([("192.168.1.1", "eth0", 10)])
                mock_sub.assert_not_called()
        assert result is True

    def test_add_policy_route_table_dry_run(self):
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.add_policy_route_table(
                    100, "eth0", "192.168.1.1", "192.168.1.2", "192.168.1.0/24"
                )
                mock_sub.assert_not_called()
        assert result is True

    def test_flush_policy_route_table_dry_run(self):
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.flush_policy_route_table(100)
                mock_sub.assert_not_called()
        assert result is True

    def test_add_policy_rule_dry_run(self):
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.add_policy_rule(100, "192.168.1.2")
                mock_sub.assert_not_called()
        assert result is True

    def test_remove_policy_rule_dry_run(self):
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.remove_policy_rule(100)
                mock_sub.assert_not_called()
        assert result is True

    def test_enable_ip_forwarding_dry_run(self):
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.enable_ip_forwarding()
                mock_sub.assert_not_called()
        assert result is True

    def test_enable_rp_filter_loose_dry_run(self):
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.enable_rp_filter_loose("eth0")
                mock_sub.assert_not_called()
        assert result is True

    def test_probe_icmp_dry_run(self):
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.probe_icmp("eth0", "8.8.8.8", 2, 3)
                mock_sub.assert_not_called()
        assert result == (0.0, 0.0, 100.0)

    def test_probe_dns_dry_run(self):
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.probe_dns("eth0", "8.8.8.8", 3, "192.168.1.2")
                mock_sub.assert_not_called()
        assert result is True

    def test_probe_http_dry_run(self):
        with patch.object(net, "DRY_RUN", True):
            with patch("subprocess.run") as mock_sub:
                result = net.probe_http("eth0", "http://example.com", 5)
                mock_sub.assert_not_called()
        assert result == (False, 0.0)
