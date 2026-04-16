"""
wancontrol/network.py
~~~~~~~~~~~~~~~~~~~~~
Network layer for WANControl v2.

All Linux subprocess and iproute2 calls live exclusively in this module.
No other module may call subprocess directly for network commands.

Execution modes (controlled by WANCONTROL_DRY_RUN env var):
  WANCONTROL_DRY_RUN=0 (default) — runs real commands
  WANCONTROL_DRY_RUN=1           — skips all subprocess calls, logs what
                                    would have run, returns safe defaults.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

# ── Dry-run mode ─────────────────────────────────────────────────────────────

DRY_RUN: bool = os.environ.get("WANCONTROL_DRY_RUN", "0") == "1"

logger = logging.getLogger(__name__)

_LOG_EXTRA: dict[str, str] = {"component": "network"}


# ── Internal helper ──────────────────────────────────────────────────────────

def _run(
    args: list[str],
    timeout: int = 10,
    check_sudo: bool = False,
) -> tuple[bool, str, str]:
    """
    Run a subprocess command.

    Returns (success, stdout, stderr).
    Logs stderr at DEBUG on failure.
    If check_sudo=True and sudo fails with 'password is required', logs an
    actionable ERROR message pointing the operator to visudo.
    Never raises.
    """
    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            timeout=timeout,
            text=True,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        success = result.returncode == 0

        if not success:
            if check_sudo and "password is required" in stderr:
                logger.error(
                    "sudo password required while running '%s' — grant passwordless "
                    "sudo for this command via 'sudo visudo', or run WANControl as root.",
                    args[0],
                    extra=_LOG_EXTRA,
                )
            else:
                logger.debug(
                    "Command failed (rc=%d): %s | stderr: %s",
                    result.returncode,
                    " ".join(args),
                    stderr,
                    extra=_LOG_EXTRA,
                )

        return success, stdout, stderr

    except subprocess.TimeoutExpired:
        logger.debug(
            "Command timed out: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return False, "", "timeout"

    except subprocess.SubprocessError as exc:
        logger.debug(
            "SubprocessError running %s: %s", " ".join(args), exc,
            extra=_LOG_EXTRA,
        )
        return False, "", str(exc)

    except OSError as exc:
        logger.debug(
            "OSError running %s: %s", " ".join(args), exc,
            extra=_LOG_EXTRA,
        )
        return False, "", str(exc)


# ── Interface information ─────────────────────────────────────────────────────

def get_interface_ip(interface: str) -> str | None:
    """
    Return the first IPv4 address of interface, or None if not found.

    Command: ip -4 -o addr show dev <interface>
    Parses field 3 of output and strips the prefix length (e.g. /24).
    """
    args = ["ip", "-4", "-o", "addr", "show", "dev", interface]
    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return None

    success, stdout, _ = _run(args)
    if not success or not stdout.strip():
        return None

    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            return parts[3].split("/")[0]

    return None


def get_interface_ip6(interface: str) -> str | None:
    """
    Return the first IPv6 address of interface, or None.

    Command: ip -6 -o addr show dev <interface>
    Parses field 3 of output and strips the prefix length.
    """
    args = ["ip", "-6", "-o", "addr", "show", "dev", interface]
    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return None

    success, stdout, _ = _run(args)
    if not success or not stdout.strip():
        return None

    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            return parts[3].split("/")[0]

    return None


def get_default_gateway() -> tuple[str, str] | None:
    """
    Return (gateway_ip, interface) of the current default route, or None.

    Command: ip -j route show default
    Parses JSON output; uses the first entry whose dst == "default".
    """
    args = ["ip", "-j", "route", "show", "default"]
    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return None

    success, stdout, _ = _run(args)
    if not success or not stdout.strip():
        return None

    try:
        routes = json.loads(stdout)
    except json.JSONDecodeError as exc:
        logger.debug(
            "Failed to parse JSON from 'ip -j route': %s", exc,
            extra=_LOG_EXTRA,
        )
        return None

    for route in routes:
        if route.get("dst") == "default":
            gateway = route.get("gateway")
            iface = route.get("dev")
            if gateway and iface:
                return gateway, iface

    return None


def get_interface_stats(interface: str) -> dict[str, int]:
    """
    Return rx/tx byte and packet counters for interface.

    Reads /proc/net/dev directly (no subprocess).
    Returns {"rx_bytes": N, "tx_bytes": N, "rx_packets": N, "tx_packets": N}.
    Returns all zeros if interface is not found.
    """
    zeros: dict[str, int] = {
        "rx_bytes": 0,
        "tx_bytes": 0,
        "rx_packets": 0,
        "tx_packets": 0,
    }

    try:
        text = Path("/proc/net/dev").read_text()
    except OSError as exc:
        logger.debug(
            "Cannot read /proc/net/dev: %s", exc, extra=_LOG_EXTRA
        )
        return zeros

    for line in text.splitlines():
        if ":" not in line:
            continue
        iface_part, data_part = line.split(":", 1)
        if iface_part.strip() == interface:
            fields = data_part.split()
            # /proc/net/dev columns (after the colon):
            # 0:rx_bytes 1:rx_packets 2:rx_errs 3:rx_drop 4:rx_fifo
            # 5:rx_frame 6:rx_compressed 7:rx_multicast
            # 8:tx_bytes 9:tx_packets ...
            if len(fields) >= 10:
                return {
                    "rx_bytes": int(fields[0]),
                    "rx_packets": int(fields[1]),
                    "tx_bytes": int(fields[8]),
                    "tx_packets": int(fields[9]),
                }

    return zeros


# ── Route management ──────────────────────────────────────────────────────────

def set_default_route(gateway: str, interface: str) -> bool:
    """
    Replace the default route.

    Commands (in order):
      sudo ip route del default          (ignore failure — may not exist)
      sudo ip route add default via <gateway> dev <interface>

    Returns True only if the add command succeeds.
    Requires sudo.
    """
    del_args = ["sudo", "ip", "route", "del", "default"]
    add_args = ["sudo", "ip", "route", "add", "default", "via", gateway, "dev", interface]

    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(del_args), extra=_LOG_EXTRA
        )
        logger.info(
            "DRY RUN — would run: %s", " ".join(add_args), extra=_LOG_EXTRA
        )
        return True

    _run(del_args, check_sudo=True)  # ignore failure — route may not exist
    success, _, _ = _run(add_args, check_sudo=True)
    return success


def set_load_balance_route(
    nexthops: list[tuple[str, str, int]],
) -> bool:
    """
    Set a multipath default route for load balancing.

    nexthops is a list of (gateway, interface, weight).

    Commands:
      sudo ip route del default
      sudo ip route add default \\
        nexthop via <gw1> dev <iface1> weight <w1> \\
        nexthop via <gw2> dev <iface2> weight <w2> ...

    Raises ValueError if nexthops is empty.
    Requires sudo.
    """
    if not nexthops:
        raise ValueError("nexthops must not be empty")

    del_args = ["sudo", "ip", "route", "del", "default"]
    add_args = ["sudo", "ip", "route", "add", "default"]
    for gw, iface, weight in nexthops:
        add_args.extend(["nexthop", "via", gw, "dev", iface, "weight", str(weight)])

    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(del_args), extra=_LOG_EXTRA
        )
        logger.info(
            "DRY RUN — would run: %s", " ".join(add_args), extra=_LOG_EXTRA
        )
        return True

    _run(del_args, check_sudo=True)  # ignore failure
    success, _, _ = _run(add_args, check_sudo=True)
    return success


def add_policy_route_table(
    table_id: int,
    interface: str,
    gateway: str,
    iface_ip: str,
    network_cidr: str,
) -> bool:
    """
    Configure a per-interface policy routing table.

    Commands:
      sudo ip route add <network_cidr> dev <interface> src <iface_ip> table <table_id>
      sudo ip route add default via <gateway> dev <interface> table <table_id>

    Both must succeed. Returns True only if both succeed.
    Requires sudo.
    """
    net_args = [
        "sudo", "ip", "route", "add",
        network_cidr, "dev", interface,
        "src", iface_ip, "table", str(table_id),
    ]
    gw_args = [
        "sudo", "ip", "route", "add", "default",
        "via", gateway, "dev", interface, "table", str(table_id),
    ]

    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(net_args), extra=_LOG_EXTRA
        )
        logger.info(
            "DRY RUN — would run: %s", " ".join(gw_args), extra=_LOG_EXTRA
        )
        return True

    success1, _, _ = _run(net_args, check_sudo=True)
    if not success1:
        return False

    success2, _, _ = _run(gw_args, check_sudo=True)
    return success2


def flush_policy_route_table(table_id: int) -> bool:
    """
    Remove all routes in a policy routing table.

    Command: sudo ip route flush table <table_id>
    Requires sudo.
    """
    args = ["sudo", "ip", "route", "flush", "table", str(table_id)]

    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return True

    success, _, _ = _run(args, check_sudo=True)
    return success


def add_policy_rule(table_id: int, iface_ip: str) -> bool:
    """
    Add an ip rule to route traffic from iface_ip via table_id.

    Command: sudo ip rule add from <iface_ip> table <table_id> priority <table_id>

    Returns False if the rule already exists (not an error; logs INFO).
    Requires sudo.
    """
    args = [
        "sudo", "ip", "rule", "add",
        "from", iface_ip,
        "table", str(table_id),
        "priority", str(table_id),
    ]

    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return True

    success, _, stderr = _run(args, check_sudo=True)

    if not success:
        if "already exists" in stderr or "File exists" in stderr:
            logger.info(
                "Policy rule for table %d (from %s) already exists — skipping.",
                table_id, iface_ip,
                extra=_LOG_EXTRA,
            )
        return False

    return True


def remove_policy_rule(table_id: int) -> bool:
    """
    Remove the ip rule for table_id.

    Command: sudo ip rule del priority <table_id>
    Returns True even if the rule did not exist.
    Requires sudo.
    """
    args = ["sudo", "ip", "rule", "del", "priority", str(table_id)]

    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return True

    _run(args, check_sudo=True)  # ignore failure — rule may not exist
    return True


# ── System configuration ──────────────────────────────────────────────────────

def enable_ip_forwarding() -> bool:
    """
    Enable IPv4 forwarding.

    Command: sudo sysctl -w net.ipv4.ip_forward=1
    Requires sudo.
    """
    args = ["sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"]

    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return True

    success, _, _ = _run(args, check_sudo=True)
    return success


def enable_rp_filter_loose(interface: str) -> bool:
    """
    Set reverse path filter to loose mode for interface.

    Command: sudo sysctl -w net.ipv4.conf.<interface>.rp_filter=2
    Requires sudo.
    """
    args = ["sudo", "sysctl", "-w", f"net.ipv4.conf.{interface}.rp_filter=2"]

    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return True

    success, _, _ = _run(args, check_sudo=True)
    return success


def check_prerequisites() -> list[str]:
    """
    Check that required commands exist: ip, ping, dig, curl, sysctl.

    Uses shutil.which() — no subprocess calls.
    Returns a list of missing command names. An empty list means all present.
    """
    required = ["ip", "ping", "dig", "curl", "sysctl"]
    return [cmd for cmd in required if shutil.which(cmd) is None]


# ── Connectivity probe helpers ────────────────────────────────────────────────

def probe_icmp(
    interface: str,
    target: str,
    count: int,
    timeout_sec: int,
) -> tuple[float, float, float]:
    """
    Run a ping probe bound to interface.

    Command: ping -I <interface> -c <count> -W <timeout_sec> <target>

    Returns (avg_latency_ms, jitter_ms, loss_pct).
    Returns (0.0, 0.0, 100.0) on any failure.

    Parses:
      "rtt min/avg/max/mdev = 1.234/5.678/9.012/1.234 ms"  → avg, jitter
      "N packets transmitted, M received, X% packet loss"   → loss_pct
    """
    failure = (0.0, 0.0, 100.0)
    args = [
        "ping", "-I", interface,
        "-c", str(count),
        "-W", str(timeout_sec),
        target,
    ]

    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return failure

    success, stdout, _ = _run(args, timeout=timeout_sec * count + 5)
    if not success:
        return failure

    avg_latency_ms = 0.0
    jitter_ms = 0.0
    loss_pct = 100.0

    for line in stdout.splitlines():
        # "rtt min/avg/max/mdev = 1.234/5.678/9.012/1.234 ms"
        if line.startswith("rtt ") and "=" in line:
            try:
                stats_str = line.split("=", 1)[1].strip().split("ms")[0].strip()
                fields = stats_str.split("/")
                if len(fields) >= 4:
                    avg_latency_ms = float(fields[1])
                    jitter_ms = float(fields[3])
            except (ValueError, IndexError):
                pass

        # "N packets transmitted, M received, X% packet loss"
        if "packet loss" in line:
            m = re.search(r"(\d+(?:\.\d+)?)%\s+packet loss", line)
            if m:
                loss_pct = float(m.group(1))

    return avg_latency_ms, jitter_ms, loss_pct


def probe_dns(
    interface: str,
    target: str,
    timeout_sec: int,
    iface_ip: str,
) -> bool:
    """
    Run a DNS probe bound to the interface IP.

    Command: dig +short +time=<timeout_sec> +tries=1 -b <iface_ip> @<target> google.com

    Returns True if the command succeeds and stdout is non-empty.
    """
    args = [
        "dig", "+short",
        f"+time={timeout_sec}", "+tries=1",
        "-b", iface_ip,
        f"@{target}", "google.com",
    ]

    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return True

    success, stdout, _ = _run(args, timeout=timeout_sec + 2)
    return success and bool(stdout.strip())


def probe_http(
    interface: str,
    target: str,
    timeout_sec: int,
) -> tuple[bool, float]:
    """
    Run an HTTP probe bound to interface.

    Command:
      curl --interface <interface> --max-time <timeout_sec>
           --silent --output /dev/null
           --write-out "%{http_code} %{time_total}"
           <target>

    Returns (success, response_time_ms).
    success is True if http_code is 200 or 204.
    response_time_ms = time_total * 1000.
    Returns (False, 0.0) on any failure.
    """
    failure = (False, 0.0)
    args = [
        "curl",
        "--interface", interface,
        "--max-time", str(timeout_sec),
        "--silent",
        "--output", "/dev/null",
        "--write-out", "%{http_code} %{time_total}",
        target,
    ]

    if DRY_RUN:
        logger.info(
            "DRY RUN — would run: %s", " ".join(args), extra=_LOG_EXTRA
        )
        return failure

    success, stdout, _ = _run(args, timeout=timeout_sec + 5)
    if not success:
        return failure

    parts = stdout.strip().split()
    if len(parts) < 2:
        return failure

    try:
        http_code = int(parts[0])
        time_total = float(parts[1])
    except (ValueError, IndexError):
        return failure

    if http_code in {200, 204}:
        return True, time_total * 1000.0

    return False, 0.0
