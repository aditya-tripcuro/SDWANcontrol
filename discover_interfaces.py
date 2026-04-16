#!/usr/bin/env python3
"""
discover_interfaces.py
~~~~~~~~~~~~~~~~~~~~~~
Standalone CLI for WANControl v2 network interface discovery.

Usage:
    python discover_interfaces.py              # human-readable table (default)
    python discover_interfaces.py --yaml       # YAML fragment for config.yaml
    python discover_interfaces.py --json       # JSON output
    python discover_interfaces.py --all        # include skipped interfaces in table
    python discover_interfaces.py --check      # only check prerequisites, exit 0/1
"""

from __future__ import annotations

import json
import shutil
import sys
from typing import Any

from wancontrol.network_discovery import (
    DiscoveredInterface,
    check_prerequisites,
    discover_interfaces,
    generate_config_fragment,
    generate_config_fragment_dict,
)


def _format_table(interfaces: list[DiscoveredInterface], show_all: bool = False) -> str:
    """
    Format discovered interfaces as a human-readable ASCII table.

    Args:
        interfaces: List of discovered interfaces.
        show_all: If True, include skipped interfaces with SKIP column.

    Returns:
        Formatted table string.
    """
    lines: list[str] = []

    # Filter if not showing all
    display_list = interfaces if show_all else [i for i in interfaces if i.is_wan_candidate]

    if not display_list:
        return "No interfaces to display."

    # Determine columns
    if show_all:
        headers = ["Name", "IP", "Gateway", "Speed", "Reachable", "WAN Cand.", "SKIP"]
        col_widths = [6, 18, 12, 10, 10, 10, 15]
    else:
        headers = ["Name", "IP", "Gateway", "Speed", "Reachable", "WAN Cand."]
        col_widths = [6, 18, 12, 10, 10, 10]

    # Build table
    def _top_sep() -> str:
        parts = ["─" * w for w in col_widths]
        return "┌" + "┬".join(parts) + "┐"

    def _mid_sep() -> str:
        parts = ["─" * w for w in col_widths]
        return "├" + "┼".join(parts) + "┤"

    def _bottom_sep() -> str:
        parts = ["─" * w for w in col_widths]
        return "└" + "┴".join(parts) + "┘"

    def _row(values: list[str]) -> str:
        padded = [v.center(w) for v, w in zip(values, col_widths)]
        return "│" + "│".join(padded) + "│"

    # Header separator
    lines.append(_top_sep())
    lines.append(_row(headers))
    lines.append(_mid_sep())

    for iface in display_list:
        ip_display = f"{iface.ip}/{iface.prefix_len}" if iface.ip else ""
        speed_display = f"{iface.speed_mbps}Mbps" if iface.speed_mbps > 0 else "unknown"
        reachable_display = "YES" if iface.is_reachable else "NO"
        wan_display = "YES ✓" if iface.is_wan_candidate else "NO"

        if show_all:
            skip_display = iface.skip_reason if iface.skip_reason else "-"
            row_values = [
                iface.name,
                ip_display,
                iface.gateway or "-",
                speed_display,
                reachable_display,
                wan_display,
                skip_display,
            ]
        else:
            row_values = [
                iface.name,
                ip_display,
                iface.gateway or "-",
                speed_display,
                reachable_display,
                wan_display,
            ]

        lines.append(_row(row_values))

    lines.append(_bottom_sep())

    return "\n".join(lines)


def cmd_check() -> int:
    """
    Run prerequisite check and print results.

    Returns:
        Exit code: 0 if all prerequisites met, 1 otherwise.
    """
    print("Checking prerequisites...")

    missing = check_prerequisites()
    all_ok = len(missing) == 0

    for cmd in ("ip", "ping"):
        path = shutil.which(cmd)
        status = f"FOUND ({path})" if path else "MISSING"
        print(f"  {cmd:5}: {status}")

    if all_ok:
        print("All prerequisites met.")
        return 0
    else:
        print("Prerequisites not met. Install iproute2: sudo apt install iproute2")
        return 1


def cmd_default(show_all: bool = False) -> None:
    """
    Run discovery and display human-readable table.

    Args:
        show_all: If True, include skipped interfaces.
    """
    print("WANControl v2 — Interface Discovery")
    print("=" * 40)
    print()

    # Check prerequisites
    print("Checking prerequisites...", end=" ")
    missing = check_prerequisites()
    if missing:
        print(f"FAILED - missing: {', '.join(missing)}")
        print("Install iproute2: sudo apt install iproute2")
        return
    print("OK")
    print()

    # Discover interfaces
    interfaces = discover_interfaces()

    print("Discovered interfaces:")
    print(_format_table(interfaces, show_all=show_all))
    print()

    # Summary
    candidates = [i for i in interfaces if i.is_wan_candidate]
    count = len(candidates)
    print(f"Found {count} WAN candidate(s).")
    print()

    if candidates:
        print("Paste this into config.yaml under the 'interfaces:' key:")
        print()
        yaml_fragment = generate_config_fragment(interfaces)
        print(yaml_fragment)


def cmd_yaml() -> None:
    """
    Run discovery and output YAML fragment only.
    """
    interfaces = discover_interfaces()
    yaml_fragment = generate_config_fragment(interfaces)
    if yaml_fragment:
        print(yaml_fragment)


def cmd_json() -> None:
    """
    Run discovery and output JSON.
    """
    interfaces = discover_interfaces()
    candidates = [i for i in interfaces if i.is_wan_candidate]
    missing = check_prerequisites()

    def _iface_to_dict(iface: DiscoveredInterface) -> dict[str, Any]:
        return {
            "name": iface.name,
            "label": iface.label,
            "mac": iface.mac,
            "ip": iface.ip,
            "prefix_len": iface.prefix_len,
            "gateway": iface.gateway,
            "speed_mbps": iface.speed_mbps,
            "is_up": iface.is_up,
            "is_reachable": iface.is_reachable,
            "is_wan_candidate": iface.is_wan_candidate,
            "skip_reason": iface.skip_reason,
            "suggested_routing_table_id": iface.suggested_routing_table_id,
        }

    output = {
        "candidates": [_iface_to_dict(i) for i in candidates],
        "all": [_iface_to_dict(i) for i in interfaces],
        "prerequisites_ok": len(missing) == 0,
    }

    print(json.dumps(output, indent=2))


def main() -> int:
    """
    Main entry point for the CLI.

    Returns:
        Exit code.
    """
    args = sys.argv[1:]

    if "--check" in args:
        return cmd_check()
    elif "--yaml" in args:
        cmd_yaml()
        return 0
    elif "--json" in args:
        cmd_json()
        return 0
    else:
        show_all = "--all" in args
        cmd_default(show_all=show_all)
        return 0


if __name__ == "__main__":
    sys.exit(main())
