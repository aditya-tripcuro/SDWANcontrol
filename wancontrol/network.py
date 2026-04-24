"""
wancontrol/network.py
~~~~~~~~~~~~~~~~~~~~~
Network utilities: snapshot/restore default routes, per-interface routing
tables, and socket binding helpers.

All subprocess invocations use subprocess.run(..., check=True, capture_output=True, text=True)
and errors are handled and logged with component="network".
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
from typing import Any

from wancontrol.config import InterfaceConfig, Config
from wancontrol.database import Database

logger = logging.getLogger(__name__)


def snapshot_default_routes(db: Database) -> None:
    """Snapshot current default routes and persist the raw JSON to DB.

    Stores the JSON string at state key "pre_start_default_routes".
    """
    try:
        res = subprocess.run(
            ["ip", "-json", "route", "show", "default"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to snapshot default routes: %s", exc, extra={"component": "network"})
        return

    raw = res.stdout.strip() or "[]"
    try:
        parsed = json.loads(raw)
        count = len(parsed) if isinstance(parsed, list) else 0
    except json.JSONDecodeError:
        count = 0

    try:
        db.set_state("pre_start_default_routes", raw)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to persist default routes snapshot: %s", exc, extra={"component": "network"})

    logger.info("Snapshotted %d default route(s)", count, extra={"component": "network"})


def restore_default_routes(db: Database) -> None:
    """Restore default routes from the DB snapshot.

    If the snapshot is missing or invalid, attempts a best-effort fallback
    using the DB state key "active_interface" (interpreted as a gateway).
    This function is idempotent.
    """
    raw = db.get_state("pre_start_default_routes")
    routes: list[dict[str, Any]] | None = None

    if raw:
        try:
            routes_parsed = json.loads(raw)
            if isinstance(routes_parsed, list):
                routes = routes_parsed
        except json.JSONDecodeError:
            logger.critical("pre_start_default_routes is invalid JSON", extra={"component": "network"})

    if not routes:
        # Best-effort fallback
        gw = db.get_state("active_interface")
        if not gw:
            logger.critical("No snapshot and no active_interface state; cannot restore routes", extra={"component": "network"})
            return
        cmd = ["ip", "route", "replace", "default", "via", gw]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info("Restored default route via %s (fallback)", gw, extra={"component": "network"})
        except subprocess.CalledProcessError as exc:
            logger.critical("Fallback restore failed: %s", exc, extra={"component": "network"})
        return

    for r in routes:
        cmd = ["ip", "route", "replace", "default"]
        # include attributes only if present
        if "via" in r and r["via"]:
            cmd += ["via", str(r["via"])]
        if "dev" in r and r["dev"]:
            cmd += ["dev", str(r["dev"])]
        if "metric" in r and r["metric"] is not None:
            cmd += ["metric", str(r["metric"])]
        if "proto" in r and r["proto"]:
            cmd += ["proto", str(r["proto"])]
        if "table" in r and r["table"] is not None:
            cmd += ["table", str(r["table"])]
        if "onlink" in r and r["onlink"]:
            cmd += ["onlink"]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info("Restored default route: %s", " ".join(cmd[4:]), extra={"component": "network"})
        except subprocess.CalledProcessError as exc:
            logger.error("Failed to restore route %s: %s", cmd, exc, extra={"component": "network"})


def get_interface_subnet(iface: str) -> str:
    """Return the first IPv4 CIDR (e.g. "192.168.2.100/24") for the given interface.

    Raises ValueError if no IPv4 address is found.
    """
    try:
        res = subprocess.run(
            ["ip", "-json", "addr", "show", "dev", iface],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.error("ip addr show failed for %s: %s", iface, exc, extra={"component": "network"})
        raise ValueError(f"Could not get address for interface {iface}") from exc

    try:
        parsed = json.loads(res.stdout or "[]")
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse ip addr output for %s: %s", iface, exc, extra={"component": "network"})
        raise ValueError(f"Invalid ip addr output for {iface}") from exc

    if not parsed:
        raise ValueError(f"No address info for interface {iface}")

    # parsed is a list; look for addr_info entries with family == 'inet'
    for entry in parsed:
        addr_info = entry.get("addr_info") or []
        for a in addr_info:
            family = a.get("family")
            if family == "inet":
                # prefer explicit cidr if present
                if "local" in a and "prefixlen" in a:
                    return f"{a['local']}/{a['prefixlen']}"
                if "cidr" in a:
                    return a["cidr"]

    raise ValueError(f"No IPv4 address found for interface {iface}")


def setup_interface_routing(iface_cfg: InterfaceConfig) -> None:
    """Create a per-interface routing table and policy rule.

    Always logs each command at DEBUG before executing it.
    """
    # route replace default via <gateway> dev <name> table <routing_table_id>
    cmd_route = [
        "ip", "route", "replace", "default",
        "via", iface_cfg.gateway,
        "dev", iface_cfg.name,
        "table", str(iface_cfg.routing_table_id),
    ]
    logger.debug("Running: %s", " ".join(cmd_route), extra={"component": "network"})
    try:
        subprocess.run(cmd_route, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to set route for %s: %s", iface_cfg.name, exc, extra={"component": "network"})

    try:
        subnet = get_interface_subnet(iface_cfg.name)
    except ValueError as exc:
        logger.error("Cannot determine subnet for %s: %s", iface_cfg.name, exc, extra={"component": "network"})
        return

    # Check existing rules
    try:
        res = subprocess.run(
            ["ip", "rule", "list"], check=True, capture_output=True, text=True
        )
        rules_text = res.stdout or ""
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to list ip rules: %s", exc, extra={"component": "network"})
        rules_text = ""

    rule_sig = f"from {subnet} lookup {iface_cfg.routing_table_id}"
    if rule_sig in rules_text:
        logger.debug("Rule already exists for %s: %s", iface_cfg.name, rule_sig, extra={"component": "network"})
        return

    cmd_rule = [
        "ip", "rule", "add", "from", subnet, "lookup", str(iface_cfg.routing_table_id), "priority", str(iface_cfg.routing_table_id)
    ]
    logger.debug("Running: %s", " ".join(cmd_rule), extra={"component": "network"})
    try:
        subprocess.run(cmd_rule, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to add ip rule for %s: %s", iface_cfg.name, exc, extra={"component": "network"})


def teardown_interface_routing(iface_cfg: InterfaceConfig) -> None:
    """Remove ip rule and table route for the interface. Logs warnings on failures.

    This function never raises.
    """
    try:
        subnet = get_interface_subnet(iface_cfg.name)
    except ValueError:
        subnet = None

    if subnet:
        cmd_del_rule = ["ip", "rule", "del", "from", subnet, "lookup", str(iface_cfg.routing_table_id)]
        try:
            subprocess.run(cmd_del_rule, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            logger.warning("Failed to delete ip rule for %s: %s", iface_cfg.name, exc, extra={"component": "network"})

    cmd_del_route = ["ip", "route", "del", "default", "table", str(iface_cfg.routing_table_id)]
    try:
        subprocess.run(cmd_del_route, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("Failed to delete route table %s: %s", iface_cfg.routing_table_id, exc, extra={"component": "network"})


def setup_all_interfaces(interfaces: list[InterfaceConfig]) -> None:
    """Setup routing for all configured interfaces.

    Logs a summary at INFO when complete.
    """
    for iface in interfaces:
        setup_interface_routing(iface)
    logger.info("Setup routing for %d interface(s)", len(interfaces), extra={"component": "network"})


def teardown_all_interfaces(interfaces: list[InterfaceConfig]) -> None:
    """Teardown routing for all interfaces. Never raises; logs failures and continues."""
    for iface in interfaces:
        try:
            teardown_interface_routing(iface)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unexpected error tearing down %s: %s", iface.name, exc, extra={"component": "network"})


def bind_socket_to_interface(sock: socket.socket, iface_name: str) -> None:
    """Bind a socket to an interface using SO_BINDTODEVICE.

    Always call `bind_socket_to_interface` before sending — unbound probes on
    multi-WAN hosts will use the kernel default and give false positives.

    Raises PermissionError if the operation is not permitted (e.g. CAP_NET_RAW).
    """
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, iface_name.encode())
    except OSError as exc:
        raise PermissionError(
            "Binding socket to device failed. Ensure the process has CAP_NET_RAW/CAP_NET_ADMIN or is running as root."
        ) from exc


def find_available_port(start: int = 5000, max_attempts: int = 10) -> int:
    """Find an available TCP port starting at `start` trying `max_attempts` ports.

    Logs the selected port at INFO.
    """
    for port in range(start, start + max_attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            s.close()
            logger.info("Web server will bind on port %d", port, extra={"component": "network"})
            return port
        except OSError:
            try:
                s.close()
            except Exception:
                pass
            continue

    raise RuntimeError(f"No available port found in range {start}\u2013{start+max_attempts-1}")


if __name__ == "__main__":
    import sys

    if "--restore-routes" in sys.argv:
        cfg_path = os.environ.get("WANCONTROL_CONFIG", "/etc/wancontrol/config.yaml")
        cfg = Config(cfg_path)
        try:
            app_cfg = cfg.load()
        except Exception:
            # continue with default DB path fallback
            app_cfg = None

        db_path = app_cfg.db_path if app_cfg is not None else "/var/lib/wancontrol/wan.db"
        db = Database(db_path)
        try:
            db.initialize()
        except Exception:
            # initialization may fail if DB already exists; proceed anyway
            pass
        restore_default_routes(db)

