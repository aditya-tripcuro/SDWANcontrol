"""
wancontrol/network_discovery.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Network interface discovery for WANControl v2.

Discovers network interfaces, determines WAN candidates, and generates
configuration fragments for config.yaml.

Usage:
    from wancontrol.network_discovery import discover_interfaces, generate_config_fragment
    
    interfaces = discover_interfaces()
    yaml_fragment = generate_config_fragment(interfaces)
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Virtual interface prefixes to skip ────────────────────────────────────────

VIRTUAL_PREFIXES = (
    "docker",
    "br-",
    "veth",
    "virbr",
    "tun",
    "tap",
    "vlan",
    "bond",
    "dummy",
    "sit",
    "ip6tnl",
    "ip6gre",
    "gre",
)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class DiscoveredInterface:
    """Represents a discovered network interface with all relevant attributes."""

    name: str                    # e.g. "eth0"
    label: str                   # auto-generated e.g. "WAN-1 (edit me)"
    mac: str                     # e.g. "aa:bb:cc:dd:ee:ff", "" if unknown
    ip: str                      # first IPv4 address, "" if none
    prefix_len: int              # e.g. 24, 0 if none
    gateway: str                 # default gateway for this interface, "" if none
    speed_mbps: int              # from /sys/class/net/<iface>/speed, -1 if unknown
    is_up: bool                  # interface is UP
    is_reachable: bool           # can ping 8.8.8.8 via this interface
    is_wan_candidate: bool       # True if has gateway AND is reachable
    skip_reason: str             # why it was skipped, "" if not skipped
    suggested_routing_table_id: int  # auto-assigned 100, 101, 102...


# ── Prerequisites check ───────────────────────────────────────────────────────

def check_prerequisites() -> list[str]:
    """
    Check that required commands are available: ip, ping.

    Returns:
        List of missing command names. Empty list means all good.
    """
    missing: list[str] = []

    for cmd in ("ip", "ping"):
        if shutil.which(cmd) is None:
            missing.append(cmd)

    return missing


# ── Discovery helpers ─────────────────────────────────────────────────────────

def _run_command(args: list[str]) -> tuple[int, str, str]:
    """
    Run a subprocess command with standard safety settings.

    Args:
        args: Command arguments as a list (shell=False).

    Returns:
        Tuple of (returncode, stdout, stderr).
    """
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.warning(
            "Command timed out: %s", args,
            extra={"component": "discovery"},
        )
        return -1, "", "timeout"
    except FileNotFoundError:
        logger.error(
            "Command not found: %s", args[0],
            extra={"component": "discovery"},
        )
        return -1, "", "command not found"
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Command failed: %s — %s", args, exc,
            extra={"component": "discovery"},
        )
        return -1, "", str(exc)


def _parse_ip_link() -> list[dict[str, Any]] | None:
    """
    Parse output of `ip -j link show`.

    Returns:
        List of interface dicts, or None on failure.
    """
    retcode, stdout, _ = _run_command(["ip", "-j", "link", "show"])

    if retcode != 0:
        logger.error(
            "ip link command failed with return code %d", retcode,
            extra={"component": "discovery"},
        )
        return None

    try:
        data = json.loads(stdout)
        if not isinstance(data, list):
            logger.error(
                "ip link returned non-list JSON",
                extra={"component": "discovery"},
            )
            return None
        return data
    except json.JSONDecodeError as exc:
        logger.error(
            "Failed to parse ip link JSON: %s", exc,
            extra={"component": "discovery"},
        )
        return None


def _parse_ip_addr() -> dict[str, dict[str, Any]]:
    """
    Parse output of `ip -j -4 addr show`.

    Returns:
        Dict mapping ifname -> addr_info dict with 'local' and 'prefixlen'.
    """
    retcode, stdout, _ = _run_command(["ip", "-j", "-4", "addr", "show"])

    result: dict[str, dict[str, Any]] = {}

    if retcode != 0:
        logger.warning(
            "ip addr command failed with return code %d", retcode,
            extra={"component": "discovery"},
        )
        return result

    try:
        data = json.loads(stdout)
        if not isinstance(data, list):
            return result

        for entry in data:
            ifname = entry.get("ifname")
            if not ifname:
                continue

            addr_info_list = entry.get("addr_info", [])
            if not addr_info_list or not isinstance(addr_info_list, list):
                continue

            # Take first valid local address
            for addr_info in addr_info_list:
                local = addr_info.get("local")
                prefixlen = addr_info.get("prefixlen", 0)
                if local:
                    result[ifname] = {"local": local, "prefixlen": prefixlen}
                    break
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse ip addr JSON",
            extra={"component": "discovery"},
        )

    return result


def _parse_ip_route() -> dict[str, str]:
    """
    Parse output of `ip -j route show` to find default gateways.

    Returns:
        Dict mapping ifname -> gateway IP for default routes only.
    """
    retcode, stdout, _ = _run_command(["ip", "-j", "route", "show"])

    result: dict[str, str] = {}

    if retcode != 0:
        logger.warning(
            "ip route command failed with return code %d", retcode,
            extra={"component": "discovery"},
        )
        return result

    try:
        data = json.loads(stdout)
        if not isinstance(data, list):
            return result

        for entry in data:
            dst = entry.get("dst")
            dev = entry.get("dev")
            gateway = entry.get("gateway")

            if dst == "default" and dev and gateway:
                result[dev] = gateway
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse ip route JSON",
            extra={"component": "discovery"},
        )

    return result


def _is_virtual_interface(name: str) -> bool:
    """
    Check if an interface name matches virtual interface prefixes.

    Args:
        name: Interface name to check.

    Returns:
        True if the interface should be skipped as virtual.
    """
    name_lower = name.lower()

    # Exact match for "lo"
    if name_lower == "lo":
        return True

    # Prefix matches
    for prefix in VIRTUAL_PREFIXES:
        if name_lower.startswith(prefix):
            return True

    return False


def _read_speed(iface_name: str) -> int:
    """
    Read link speed from /sys/class/net/<iface>/speed.

    Args:
        iface_name: Name of the network interface.

    Returns:
        Speed in Mbps, or -1 if unknown/unreadable.
    """
    speed_path = Path(f"/sys/class/net/{iface_name}/speed")

    try:
        content = speed_path.read_text().strip()
        speed = int(content)
        if speed < 0:
            return -1
        return speed
    except (OSError, ValueError):
        return -1


def _test_reachability(iface_name: str, ip_addr: str) -> bool:
    """
    Test if an interface can reach 8.8.8.8 via ping.

    Args:
        iface_name: Interface name to bind ping to.
        ip_addr: Source IP address (not used directly, ping uses -I).

    Returns:
        True if ping succeeds, False otherwise.
    """
    if not ip_addr:
        return False

    retcode, _, _ = _run_command([
        "ping",
        "-I", iface_name,
        "-c", "1",
        "-W", "2",
        "8.8.8.8",
    ])

    return retcode == 0


# ── Main discovery pipeline ───────────────────────────────────────────────────

def discover_interfaces() -> list[DiscoveredInterface]:
    """
    Run full discovery pipeline. Returns all interfaces including skipped ones.

    Caller filters by is_wan_candidate for config generation.
    Never raises — returns empty list on catastrophic failure.

    Returns:
        List of DiscoveredInterface objects.
    """
    # Step 1: Enumerate interfaces
    link_data = _parse_ip_link()
    if link_data is None:
        return []

    # Step 2: Get IP addresses
    addr_data = _parse_ip_addr()

    # Step 3: Get default gateways
    route_data = _parse_ip_route()

    interfaces: list[DiscoveredInterface] = []
    wan_candidate_count = 0

    for entry in link_data:
        ifname = entry.get("ifname", "")
        if not ifname:
            continue

        link_type = entry.get("link_type", "")
        operstate = entry.get("operstate", "")
        mac = entry.get("address", "")

        # Skip loopback
        if link_type == "loopback" or ifname.lower() == "lo":
            continue

        # Skip virtual interfaces
        if _is_virtual_interface(ifname):
            interfaces.append(DiscoveredInterface(
                name=ifname,
                label=f"{ifname} (virtual)",
                mac=mac,
                ip="",
                prefix_len=0,
                gateway="",
                speed_mbps=-1,
                is_up=(operstate == "UP"),
                is_reachable=False,
                is_wan_candidate=False,
                skip_reason="virtual",
                suggested_routing_table_id=0,
            ))
            continue

        # Get IP info
        ip_info = addr_data.get(ifname, {})
        ip_addr = ip_info.get("local", "")
        prefix_len = ip_info.get("prefixlen", 0)

        # Get gateway
        gateway = route_data.get(ifname, "")

        # Get speed
        speed_mbps = _read_speed(ifname)

        # Determine if up
        is_up = operstate == "UP"

        # Test reachability
        is_reachable = _test_reachability(ifname, ip_addr) if ip_addr else False

        # Classify
        skip_reason = ""
        is_wan_candidate = False

        if not ip_addr:
            skip_reason = "no_ip"
        elif not gateway:
            skip_reason = "no_gateway"
        elif not is_up:
            skip_reason = "not_up"
        else:
            # It's a candidate because it has an IP, Gateway, and is UP.
            # Reachability is recorded but doesn't disqualify it, as multi-WAN
            # pings often fail before policy routing is established.
            is_wan_candidate = True
            wan_candidate_count += 1
            if not is_reachable:
                skip_reason = "not_reachable (but has gateway)"

        # Generate label
        label = f"WAN-{wan_candidate_count} (edit me)" if is_wan_candidate else f"{ifname}"

        # Assign routing table ID
        suggested_routing_table_id = 100 + (wan_candidate_count - 1) if is_wan_candidate else 0

        interfaces.append(DiscoveredInterface(
            name=ifname,
            label=label,
            mac=mac,
            ip=ip_addr,
            prefix_len=prefix_len,
            gateway=gateway,
            speed_mbps=speed_mbps,
            is_up=is_up,
            is_reachable=is_reachable,
            is_wan_candidate=is_wan_candidate,
            skip_reason=skip_reason,
            suggested_routing_table_id=suggested_routing_table_id,
        ))

    return interfaces


# ── Config generation ─────────────────────────────────────────────────────────

def generate_config_fragment_dict(interfaces: list[DiscoveredInterface]) -> list[dict]:
    """
    Return the interfaces: block as a list of dicts (for JSON/API output).

    Only includes interfaces where is_wan_candidate == True.

    Args:
        interfaces: List of discovered interfaces.

    Returns:
        List of dicts suitable for YAML/JSON serialization.
    """
    candidates = [i for i in interfaces if i.is_wan_candidate]
    result: list[dict] = []

    for iface in candidates:
        speed = iface.speed_mbps if iface.speed_mbps > 0 else 100
        entry: dict[str, Any] = {
            "name": iface.name,
            "label": iface.label,
            "expected_speed_mbps": speed,
            "gateway": iface.gateway,
            "routing_table_id": iface.suggested_routing_table_id,
        }
        if iface.speed_mbps < 0:
            entry["_comment"] = "speed unknown — update this"
        result.append(entry)

    return result


def generate_config_fragment(interfaces: list[DiscoveredInterface]) -> str:
    """
    Return a YAML string for the interfaces: block.

    Uses only is_wan_candidate == True entries.
    Ready to paste into config.yaml.
    Returns empty string if no candidates found.

    Args:
        interfaces: List of discovered interfaces.

    Returns:
        YAML fragment string.
    """
    candidates = [i for i in interfaces if i.is_wan_candidate]

    if not candidates:
        return ""

    lines = ["interfaces:"]

    for iface in candidates:
        speed = iface.speed_mbps if iface.speed_mbps > 0 else 100
        speed_comment = "  # speed unknown — update this" if iface.speed_mbps < 0 else ""

        lines.append(f"  - name: \"{iface.name}\"")
        lines.append(f"    label: \"{iface.label}\"")
        lines.append(f"    expected_speed_mbps: {speed}{speed_comment}")
        lines.append(f"    gateway: \"{iface.gateway}\"")
        lines.append(f"    routing_table_id: {iface.suggested_routing_table_id}")
        lines.append("")

    return "\n".join(lines)
