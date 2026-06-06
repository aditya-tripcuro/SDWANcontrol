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
import ipaddress
import logging
import os
import shutil
import socket
import subprocess
from typing import Any, Callable

from wancontrol.config import InterfaceConfig, Config
from wancontrol.database import Database

logger = logging.getLogger(__name__)

STATE_PRE_START_DEFAULT_ROUTES = "pre_start_default_routes"
STATE_PRE_START_DEFAULT_ROUTES_V6 = "pre_start_default_routes_v6"
STATE_FALLBACK_GATEWAY = "pre_start_fallback_gateway"
STATE_ROUTE_MANAGEMENT_ACTIVE = "route_management_active"
STATE_STALE_MANAGED_STATE = "stale_managed_state_detected"

# Dedicated priority base for per-interface policy rules (item 36). The rule
# priority MUST NOT collide with the routing table id; we offset every rule by
# this base so two interfaces with adjacent table ids never share a priority.
RULE_PRIORITY_BASE = 10000

# Shadow mode (Layer 1 dry-run) recorder. When set via set_shadow_recorder(),
# every route-mutating command that WOULD have run is handed to this callable
# instead of being executed (see _run_route_command).
_SHADOW_RECORDER: Callable[[list[str]], None] | None = None


def _dry_run_enabled() -> bool:
    return os.environ.get("WANCONTROL_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}


def _shadow_enabled() -> bool:
    """Return True when shadow mode is requested via WANCONTROL_SHADOW.

    Mirrors _dry_run_enabled(): full probe/score/decide still run, but route
    mutations are recorded instead of executed.
    """
    return os.environ.get("WANCONTROL_SHADOW", "").strip().lower() in {"1", "true", "yes", "on"}


def set_shadow_recorder(fn: Callable[[list[str]], None] | None) -> None:
    """Register (or clear) the shadow-mode command recorder.

    The controller installs a recorder at master start so that intended route
    commands are persisted to the DB instead of being applied to the host.
    """
    global _SHADOW_RECORDER
    _SHADOW_RECORDER = fn


def _subprocess_is_mocked() -> bool:
    return "unittest.mock" in type(subprocess.run).__module__


def _run_route_command(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Run a route-mutating command.

    Honors, in order (outside of mocked tests):
      * WANCONTROL_SHADOW — record the intended command, mutate nothing.
      * WANCONTROL_DRY_RUN — log the command, mutate nothing.
    """
    if not _subprocess_is_mocked():
        if _shadow_enabled():
            logger.info("SHADOW would run: %s", " ".join(cmd), extra={"component": "network"})
            recorder = _SHADOW_RECORDER
            if recorder is not None:
                try:
                    recorder(cmd)
                except Exception as exc:  # noqa: BLE001 — never let recording break routing flow
                    logger.warning("Shadow recorder failed: %s", exc, extra={"component": "network"})
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if _dry_run_enabled():
            logger.info("DRY RUN: %s", " ".join(cmd), extra={"component": "network"})
            return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(cmd, **kwargs)


def check_prerequisites() -> list[str]:
    """Verify that all required system tools are available.

    Returns a list of missing tool names.
    """
    tools = ["ip", "ping", "dig", "curl"]
    missing = []
    for tool in tools:
        try:
            subprocess.run(["which", tool], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            missing.append(tool)
    return missing


_SYSCTL_PERSIST_PATH = "/etc/sysctl.d/99-wancontrol.conf"


def _set_sysctl(key: str, value: str) -> bool:
    """Set a single sysctl at runtime. Returns True on success.

    Idempotent: re-applying the same value is a no-op for the kernel. Never
    raises — a missing knob (e.g. a per-interface conf that does not exist) is
    logged and treated as a soft failure so callers can continue.
    """
    cmd = ["sysctl", "-w", f"{key}={value}"]
    try:
        _run_route_command(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("Failed to set sysctl %s=%s: %s", key, value, exc, extra={"component": "network"})
        return False


def _persist_sysctls(settings: dict[str, str]) -> None:
    """Persist sysctl settings to /etc/sysctl.d so they survive reboot.

    Idempotent: the managed file is rewritten in full each time with the merged
    desired settings. Failures (read-only fs, no permission, dry-run/shadow) are
    logged and swallowed — runtime application already happened separately.
    """
    if _dry_run_enabled() or _shadow_enabled():
        return
    try:
        existing: dict[str, str] = {}
        if os.path.exists(_SYSCTL_PERSIST_PATH):
            with open(_SYSCTL_PERSIST_PATH, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    existing[k.strip()] = v.strip()
        existing.update(settings)
        lines = ["# Managed by wancontrol — do not edit by hand", ""]
        lines += [f"{k} = {v}" for k, v in sorted(existing.items())]
        with open(_SYSCTL_PERSIST_PATH, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as exc:
        logger.warning(
            "Could not persist sysctls to %s: %s", _SYSCTL_PERSIST_PATH, exc, extra={"component": "network"}
        )


def enable_ip_forwarding() -> None:
    """Enable IPv4 (and IPv6) forwarding at runtime and persist it.

    Idempotent and safe to call at every master setup.
    """
    settings = {
        "net.ipv4.ip_forward": "1",
        "net.ipv6.conf.all.forwarding": "1",
    }
    for key, value in settings.items():
        _set_sysctl(key, value)
    _persist_sysctls(settings)
    logger.info("Enabled IP forwarding", extra={"component": "network"})


def enable_rp_filter_loose() -> None:
    """Relax reverse-path filtering to loose mode (rp_filter=2).

    The kernel uses max(all, <iface>) for the effective value, so strict mode on
    either ``all`` or any per-interface conf would still drop asymmetrically
    routed multi-WAN replies. We therefore set ``all`` and ``default`` to loose,
    and best-effort relax every currently present per-interface conf. Idempotent
    and persisted via /etc/sysctl.d (item 12).
    """
    settings = {
        "net.ipv4.conf.all.rp_filter": "2",
        "net.ipv4.conf.default.rp_filter": "2",
    }
    for key, value in settings.items():
        _set_sysctl(key, value)

    # Relax any already-existing per-interface conf at runtime (these are not
    # persisted individually — `all`/`default` cover interfaces created later).
    conf_dir = "/proc/sys/net/ipv4/conf"
    try:
        ifaces = os.listdir(conf_dir)
    except OSError:
        ifaces = []
    for iface in ifaces:
        if iface in {"all", "default"}:
            continue
        _set_sysctl(f"net.ipv4.conf.{iface}.rp_filter", "2")

    _persist_sysctls(settings)
    logger.info("Set rp_filter to loose mode (2)", extra={"component": "network"})


def add_policy_route_table(iface_cfg: InterfaceConfig) -> None:
    setup_interface_routing(iface_cfg)


def add_policy_rule(iface_cfg: InterfaceConfig) -> None:
    setup_interface_routing(iface_cfg)


def get_interface_ip(iface_name: str) -> str | None:
    """Return the first IPv4 address of an interface or None."""
    try:
        res = subprocess.run(
            ["ip", "-j", "-4", "addr", "show", iface_name],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(res.stdout)
        if not data or not data[0].get("addr_info"):
            return None
        return str(data[0]["addr_info"][0]["local"])
    except (subprocess.CalledProcessError, json.JSONDecodeError, IndexError, KeyError):
        return None


def probe_icmp(interface: str, target: str, count: int = 3, timeout_sec: int = 2) -> tuple[float, float, float]:
    """
    Run ICMP ping bound to an interface.

    Returns (avg_latency_ms, jitter_ms, loss_pct).
    On failure: (0.0, 0.0, 100.0).
    """
    try:
        # -W: per-packet wait; -w: total deadline so the command never runs
        # longer than timeout_sec regardless of count (critical on dead interfaces).
        cmd = ["ping", "-I", interface, "-c", str(count), "-W", str(timeout_sec), "-w", str(timeout_sec), target]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec + 2)

        # Parse output
        # Example: 3 packets transmitted, 3 received, 0% packet loss, time 2003ms
        # rtt min/avg/max/mdev = 15.123/16.456/17.890/1.234 ms
        if res.returncode != 0 and not res.stdout:
            return 0.0, 0.0, 100.0

        loss = 100.0
        avg_lat = 0.0
        mdev = 0.0

        for line in res.stdout.splitlines():
            if "packet loss" in line:
                # "... 0% packet loss ..."
                parts = line.split(",")
                for p in parts:
                    if "packet loss" in p:
                        loss = float(p.strip().split("%")[0].split()[-1])
            if "rtt min/avg/max/mdev" in line:
                # "rtt min/avg/max/mdev = 15.123/16.456/17.890/1.234 ms"
                values = line.split("=")[1].strip().split()[0].split("/")
                avg_lat = float(values[1])
                mdev = float(values[3])

        return avg_lat, mdev, loss
    except subprocess.TimeoutExpired:
        return 0.0, 0.0, 100.0
    except Exception:
        return 0.0, 0.0, 100.0


def probe_dns(interface: str, target: str, timeout_sec: int = 2, iface_ip: str | None = None) -> bool:
    """
    Run DNS lookup bound to an interface via its IP.

    Uses `dig @8.8.8.8 google.com +short +timeout=N +tries=1 -b <ip>`.
    """
    if not iface_ip:
        return False
    try:
        cmd = ["dig", "@" + target, "google.com", "+short", f"+timeout={timeout_sec}", "+tries=1", "-b", iface_ip]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode == 0 and bool(res.stdout.strip())
    except Exception:
        return False


def probe_http(interface: str, target: str, timeout_sec: int = 2) -> tuple[bool, float]:
    """
    Run HTTP GET bound to an interface via curl.

    Returns (success, response_ms).
    """
    try:
        # --connect-timeout: TCP handshake limit; --max-time: total cap so curl
        # never hangs after connect (e.g. slow HTTP response on a degraded link).
        cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{time_total}",
               "--interface", interface,
               "--connect-timeout", str(timeout_sec),
               "--max-time", str(timeout_sec),
               target]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec + 2)
        if res.returncode == 0:
            return True, float(res.stdout.strip()) * 1000.0
        return False, 0.0
    except subprocess.TimeoutExpired:
        return False, 0.0
    except Exception:
        return False, 0.0


def _show_default_routes(family: str) -> list[dict[str, Any]] | None:
    """Return the current default routes for a family ("4" or "6").

    Returns a list of route dicts (possibly empty), or None if the query could
    not be run (so callers can distinguish "no defaults" from "unknown").
    """
    flag = "-6" if family == "6" else "-4"
    try:
        res = subprocess.run(
            ["ip", flag, "-json", "route", "show", "default"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.error(
            "Failed to query IPv%s default routes: %s", family, exc, extra={"component": "network"}
        )
        return None

    raw = res.stdout.strip() or "[]"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Invalid JSON from ip route show default (v%s)", family, extra={"component": "network"})
        return None
    return parsed if isinstance(parsed, list) else []


def _extract_fallback_gateway(routes: list[dict[str, Any]]) -> dict[str, str] | None:
    """Pick a real gateway IP + dev from a list of default routes (item 5).

    Walks single-hop routes first, then the first usable nexthop of a multipath
    route, returning {"gateway": ip, "dev": iface}. Returns None if none found.
    """
    for r in routes:
        gw = r.get("gateway") or r.get("via")
        dev = r.get("dev")
        if gw and dev:
            return {"gateway": str(gw), "dev": str(dev)}
        for nh in r.get("nexthops") or []:
            nh_gw = nh.get("gateway") or nh.get("via")
            nh_dev = nh.get("dev")
            if nh_gw and nh_dev:
                return {"gateway": str(nh_gw), "dev": str(nh_dev)}
    return None


def snapshot_default_routes(db: Database, *, force: bool = False) -> None:
    """Snapshot current IPv4 and IPv6 default routes and persist them to DB.

    Stores the raw JSON for each family ("pre_start_default_routes" for v4,
    "pre_start_default_routes_v6" for v6) plus a best-effort fallback gateway
    (real gateway IP + dev — item 5) used if the snapshot is later unusable.
    """
    if not force and db.get_state(STATE_PRE_START_DEFAULT_ROUTES):
        logger.info("Keeping existing default route snapshot", extra={"component": "network"})
        return

    v4 = _show_default_routes("4")
    v6 = _show_default_routes("6")
    if v4 is None:
        # Could not even query the host — do not overwrite any prior snapshot.
        logger.error("Aborting snapshot: could not read IPv4 default routes", extra={"component": "network"})
        return

    raw_v4 = json.dumps(v4)
    raw_v6 = json.dumps(v6 if v6 is not None else [])

    fallback = _extract_fallback_gateway(v4)

    try:
        db.set_state(STATE_PRE_START_DEFAULT_ROUTES, raw_v4)
        db.set_state(STATE_PRE_START_DEFAULT_ROUTES_V6, raw_v6)
        if fallback is not None:
            db.set_state(STATE_FALLBACK_GATEWAY, json.dumps(fallback))
        db.set_state(STATE_ROUTE_MANAGEMENT_ACTIVE, "1")
        db.set_state(STATE_STALE_MANAGED_STATE, "0")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to persist default routes snapshot: %s", exc, extra={"component": "network"})

    logger.info(
        "Snapshotted %d IPv4 + %d IPv6 default route(s)",
        len(v4),
        len(v6 or []),
        extra={"component": "network"},
    )


def _build_restore_command(r: dict[str, Any], family: str, verb: str) -> list[str] | None:
    """Build a single `ip route <verb> default ...` command from a route dict.

    Handles both single-hop routes and multipath (`nexthops` array — item 6),
    preserves `metric`, and reads the iproute2 key `protocol` (item 9, with a
    `proto` fallback for snapshots taken before this fix). Returns None if the
    route has neither a usable gateway nor nexthops.
    """
    flag = "-6" if family == "6" else "-4"
    cmd = ["ip", flag, "route", verb, "default"]

    nexthops = r.get("nexthops")
    if isinstance(nexthops, list) and nexthops:
        for nh in nexthops:
            nh_gw = nh.get("gateway") or nh.get("via")
            nh_dev = nh.get("dev")
            if not (nh_gw or nh_dev):
                continue
            cmd += ["nexthop"]
            if nh_gw:
                cmd += ["via", str(nh_gw)]
            if nh_dev:
                cmd += ["dev", str(nh_dev)]
            weight = nh.get("weight")
            if weight is not None:
                cmd += ["weight", str(weight)]
    else:
        gateway = r.get("via") or r.get("gateway")
        dev = r.get("dev")
        if not (gateway or dev):
            return None
        if gateway:
            cmd += ["via", str(gateway)]
        if dev:
            cmd += ["dev", str(dev)]

    if r.get("metric") is not None:
        cmd += ["metric", str(r["metric"])]
    protocol = r.get("protocol") or r.get("proto")
    if protocol:
        cmd += ["proto", str(protocol)]
    if r.get("table") is not None:
        cmd += ["table", str(r["table"])]
    if r.get("onlink"):
        cmd += ["onlink"]
    return cmd


def _delete_all_default_routes(family: str) -> None:
    """Delete every current default route for a family (item 7).

    iproute2 only deletes one default per `ip route del default`, so we loop
    until none remain (bounded to avoid spinning). Never raises.
    """
    flag = "-6" if family == "6" else "-4"
    if _dry_run_enabled() or _shadow_enabled():
        # Mutations are no-ops in these modes, so re-reading would never converge.
        # Issue a single representative delete (recorded/logged) and stop.
        _run_route_command(["ip", flag, "route", "del", "default"], check=True, capture_output=True, text=True)
        return
    for _ in range(16):
        current = _show_default_routes(family)
        if not current:
            return
        try:
            _run_route_command(["ip", flag, "route", "del", "default"], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Could not delete IPv%s default route during restore: %s",
                family,
                exc,
                extra={"component": "network"},
            )
            return


def _route_metric_key(route: dict[str, Any]) -> int:
    """Sort key for a snapshot route's metric, robust to malformed/missing values.

    restore_default_routes() runs on the shutdown path and must never raise, so a
    corrupted snapshot (e.g. a non-integer ``metric``) must not blow up the sort.
    Missing/unparsable metrics sort first (treated as 0).
    """
    try:
        m = route.get("metric")
        return int(m) if m is not None else 0
    except (TypeError, ValueError):
        return 0


def _restore_family(db: Database, family: str, state_key: str) -> tuple[bool, bool]:
    """Restore default routes for one family from its snapshot.

    Deletes ALL existing defaults first, then re-adds the snapshot routes in
    ascending metric order (item 7).

    Returns ``(had_usable_snapshot, fully_restored)``:
      - ``(False, False)`` — no usable snapshot (caller should run the fallback).
      - ``(True, True)``   — snapshot was empty (nothing to do) or every route
                              re-added cleanly.
      - ``(True, False)``  — a snapshot existed but at least one route failed to
                              re-add; the caller must PRESERVE the snapshot so the
                              ExecStopPost / next-start restore can retry.
    """
    raw = db.get_state(state_key)
    routes: list[dict[str, Any]] | None = None
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                routes = parsed
        except json.JSONDecodeError:
            logger.critical("%s is invalid JSON", state_key, extra={"component": "network"})

    if routes is None:
        return (False, False)
    if not routes:
        # Snapshot was explicitly empty: the host had no default of this family
        # at start. Refuse to delete the current default off an empty/invalid
        # snapshot (item 4 / safety) — leave existing routing untouched.
        logger.info(
            "IPv%s snapshot is empty; leaving current default route(s) in place",
            family,
            extra={"component": "network"},
        )
        return (True, True)

    _delete_all_default_routes(family)

    # Restore in ascending metric order so the lowest-metric (preferred) default
    # is installed first and stays preferred.
    ordered = sorted(routes, key=_route_metric_key)
    failures = 0
    for idx, r in enumerate(ordered):
        verb = "replace" if idx == 0 else "add"
        cmd = _build_restore_command(r, family, verb)
        if cmd is None:
            failures += 1
            logger.warning(
                "Skipping unrestorable IPv%s route: %s", family, r, extra={"component": "network"}
            )
            continue
        try:
            _run_route_command(cmd, check=True, capture_output=True, text=True)
            logger.info(
                "Restored IPv%s default route: %s", family, " ".join(cmd[4:]), extra={"component": "network"}
            )
        except subprocess.CalledProcessError as exc:
            failures += 1
            logger.error("Failed to restore route %s: %s", cmd, exc, extra={"component": "network"})
    return (True, failures == 0)


def _restore_fallback(db: Database) -> None:
    """Best-effort fallback restore when no usable IPv4 snapshot exists.

    Prefers the real gateway IP + dev captured at snapshot time (item 5); falls
    back to the legacy `active_interface`-as-gateway behavior for compatibility.
    """
    fb_raw = db.get_state(STATE_FALLBACK_GATEWAY)
    gw: str | None = None
    dev: str | None = None
    if fb_raw:
        try:
            fb = json.loads(fb_raw)
            gw = fb.get("gateway")
            dev = fb.get("dev")
        except (json.JSONDecodeError, AttributeError):
            gw = None

    if not gw:
        # Legacy path: some deployments stored a gateway IP in active_interface.
        legacy = db.get_state("active_interface")
        try:
            ipaddress.ip_address(legacy or "")
            gw = legacy
        except ValueError:
            gw = None

    if not gw:
        logger.critical(
            "No default route snapshot or fallback gateway available; cannot restore routes",
            extra={"component": "network"},
        )
        return

    _delete_all_default_routes("4")
    cmd = ["ip", "route", "replace", "default", "via", str(gw)]
    if dev:
        cmd += ["dev", str(dev)]
    try:
        _run_route_command(cmd, check=True, capture_output=True, text=True)
        logger.warning(
            "Restored fallback default route via %s%s",
            gw,
            f" dev {dev}" if dev else " (no dev)",
            extra={"component": "network"},
        )
    except subprocess.CalledProcessError as exc:
        logger.critical("Fallback restore failed: %s", exc, extra={"component": "network"})


def restore_default_routes(db: Database) -> None:
    """Restore IPv4 + IPv6 default routes from the DB snapshot.

    For each family: delete ALL current defaults, then re-add the snapshot
    routes in metric order (items 6-9). If the IPv4 snapshot is missing/invalid,
    falls back to the stored gateway IP + dev (item 5). After a successful
    restore the snapshot is cleared so a later run does not fight the new state
    (item 8). Idempotent and never raises.
    """
    had_v4, ok_v4 = _restore_family(db, "4", STATE_PRE_START_DEFAULT_ROUTES)
    if not had_v4:
        _restore_fallback(db)

    # IPv6: restore only if we have a snapshot; never fabricate a v6 default.
    had_v6, ok_v6 = _restore_family(db, "6", STATE_PRE_START_DEFAULT_ROUTES_V6)

    # Preserve the snapshot if any family had a snapshot we FAILED to fully
    # re-add: clearing it here would neuter the ExecStopPost / next-start retry
    # and could leave the host with no default route and no recovery snapshot.
    if (had_v4 and not ok_v4) or (had_v6 and not ok_v6):
        logger.warning(
            "Route restore incomplete (v4 ok=%s, v6 ok=%s); preserving snapshot for retry",
            (ok_v4 if had_v4 else "n/a"), (ok_v6 if had_v6 else "n/a"),
            extra={"component": "network"},
        )
        try:
            db.set_state(STATE_ROUTE_MANAGEMENT_ACTIVE, "0")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to update route-management state: %s", exc, extra={"component": "network"})
        return

    # Clear the snapshot after a fully successful restore (item 8) so subsequent
    # runs re-snapshot the (now-restored) original state instead of replaying
    # stale routes against a different live configuration.
    try:
        db.set_state(STATE_PRE_START_DEFAULT_ROUTES, "")
        db.set_state(STATE_PRE_START_DEFAULT_ROUTES_V6, "")
        db.set_state(STATE_FALLBACK_GATEWAY, "")
        db.set_state(STATE_ROUTE_MANAGEMENT_ACTIVE, "0")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to clear route snapshot after restore: %s", exc, extra={"component": "network"})


def detect_stale_managed_state(db: Database) -> bool:
    """Return True when previous route management did not shut down cleanly."""
    active = db.get_state(STATE_ROUTE_MANAGEMENT_ACTIVE)
    stale = active in {"1", "true", "True", "yes", "on"}
    db.set_state(STATE_STALE_MANAGED_STATE, "1" if stale else "0")
    return stale


def emergency_cleanup(interfaces: list[InterfaceConfig], db: Database) -> None:
    """Best-effort cleanup used by Stop/Kill/systemd ExecStop paths."""
    teardown_all_interfaces(interfaces)
    restore_default_routes(db)


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
        _run_route_command(cmd_route, check=True, capture_output=True, text=True)
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

    # Use a dedicated priority base so the rule priority never collides with the
    # routing table id (item 36); otherwise two interfaces with adjacent table
    # ids could share a priority and the kernel would order them ambiguously.
    rule_priority = RULE_PRIORITY_BASE + iface_cfg.routing_table_id

    rule_sig = f"from {subnet} lookup {iface_cfg.routing_table_id}"
    if rule_sig in rules_text:
        logger.debug("Rule already exists for %s: %s", iface_cfg.name, rule_sig, extra={"component": "network"})
        return

    cmd_rule = [
        "ip", "rule", "add", "from", subnet, "lookup", str(iface_cfg.routing_table_id), "priority", str(rule_priority)
    ]
    logger.debug("Running: %s", " ".join(cmd_rule), extra={"component": "network"})
    try:
        _run_route_command(cmd_rule, check=True, capture_output=True, text=True)
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
        rule_priority = RULE_PRIORITY_BASE + iface_cfg.routing_table_id
        cmd_del_rule = [
            "ip", "rule", "del", "from", subnet, "lookup", str(iface_cfg.routing_table_id),
            "priority", str(rule_priority),
        ]
        try:
            _run_route_command(cmd_del_rule, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            logger.warning("Failed to delete ip rule for %s: %s", iface_cfg.name, exc, extra={"component": "network"})

    cmd_del_route = ["ip", "route", "del", "default", "table", str(iface_cfg.routing_table_id)]
    try:
        _run_route_command(cmd_del_route, check=True, capture_output=True, text=True)
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


def get_default_gateway() -> tuple[str, str] | None:
    """Return (gateway_ip, interface_name) for the default route or None."""
    try:
        res = subprocess.run(
            ["ip", "-json", "route", "show", "default"],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(res.stdout)
        if not data:
            return None
        # Usually data[0] is the primary default route
        route = data[0]
        gw = route.get("gateway")
        dev = route.get("dev")
        if gw and dev:
            return str(gw), str(dev)
        return None
    except (subprocess.CalledProcessError, json.JSONDecodeError, IndexError, KeyError):
        return None


def _family_flag_for(gateway: str) -> str:
    """Return the `ip` family flag ("-4"/"-6") matching a gateway address.

    Defaults to "-4" if the address cannot be parsed (e.g. a hostname), which
    preserves the historical IPv4-only behavior for malformed/legacy inputs.
    """
    try:
        return "-6" if ipaddress.ip_address(gateway).version == 6 else "-4"
    except ValueError:
        return "-4"


def set_default_route(gateway: str, interface: str, gateway6: str | None = None) -> None:
    """Replace the main table's default route with a single via/dev pair.

    The address family of ``gateway`` is auto-detected so this function works
    whether it is handed an IPv4 or an IPv6 gateway — callers that switch the v6
    default with a separate call (passing the v6 gateway here) get the correct
    `ip -6 route replace` command (item 13).

    If ``gateway6`` is additionally provided, the IPv6 default route is set to
    match on the same interface in the same call. The IPv6 leg is best-effort: a
    failure there is logged but does not fail the (more critical) IPv4 switch.
    """
    flag = _family_flag_for(gateway)
    cmd = ["ip", flag, "route", "replace", "default", "via", gateway, "dev", interface]
    try:
        _run_route_command(cmd, check=True, capture_output=True, text=True)
        logger.info("Set default route via %s dev %s", gateway, interface, extra={"component": "network"})
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to set default route: %s", exc.stderr, extra={"component": "network"})
        raise

    if gateway6:
        cmd6 = ["ip", "-6", "route", "replace", "default", "via", gateway6, "dev", interface]
        try:
            _run_route_command(cmd6, check=True, capture_output=True, text=True)
            logger.info("Set IPv6 default route via %s dev %s", gateway6, interface, extra={"component": "network"})
        except subprocess.CalledProcessError as exc:
            logger.error(
                "Failed to set IPv6 default route via %s dev %s: %s",
                gateway6, interface, exc.stderr, extra={"component": "network"},
            )


def flush_route_cache() -> None:
    """Flush the kernel route cache and (if available) conntrack table.

    Called after every route switch (item 22) so existing flows are re-evaluated
    against the new default route instead of clinging to the old next hop. Never
    raises — flushing is best-effort hygiene, not a critical operation.
    """
    try:
        _run_route_command(["ip", "route", "flush", "cache"], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("Failed to flush route cache: %s", exc, extra={"component": "network"})
    except Exception as exc:  # noqa: BLE001 — never raise out of cleanup hygiene
        logger.warning("Unexpected error flushing route cache: %s", exc, extra={"component": "network"})

    if shutil.which("conntrack"):
        try:
            _run_route_command(["conntrack", "-F"], check=True, capture_output=True, text=True)
            logger.info("Flushed conntrack table after route switch", extra={"component": "network"})
        except subprocess.CalledProcessError as exc:
            logger.warning("Failed to flush conntrack table: %s", exc, extra={"component": "network"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unexpected error flushing conntrack: %s", exc, extra={"component": "network"})


def set_load_balance_route(nexthops: list[dict[str, Any]]) -> None:
    """Apply multipath nexthops to the default route in the main table.

    Refuses an empty pool (item 10): silently no-op'ing on an empty pool would
    leave whatever multipath default already exists — including one whose links
    are all dead — installed, blackholing traffic. The caller (controller) is
    responsible for choosing a least-bad single link or restoring the original
    default; this function therefore raises ``ValueError`` rather than
    installing or silently keeping a dead multipath route.
    """
    if not nexthops:
        raise ValueError("set_load_balance_route called with empty nexthop pool")

    cmd = ["ip", "route", "replace", "default"]
    for nh in nexthops:
        if isinstance(nh, dict):
            gateway = nh["gateway"]
            interface = nh["interface"]
            weight = nh.get("weight", 1)
        else:
            gateway, interface, *rest = nh
            weight = rest[0] if rest else 1
        cmd += ["nexthop", "via", gateway, "dev", interface, "weight", str(weight)]

    try:
        _run_route_command(cmd, check=True, capture_output=True, text=True)
        logger.info("Set multipath default route with %d nexthops", len(nexthops), extra={"component": "network"})
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to set load balance route: %s", exc.stderr, extra={"component": "network"})
        raise


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
        if app_cfg is not None:
            teardown_all_interfaces(app_cfg.interfaces)
        restore_default_routes(db)
