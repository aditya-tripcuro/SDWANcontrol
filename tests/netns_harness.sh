#!/usr/bin/env bash
# tests/netns_harness.sh
# ----------------------------------------------------------------------------
# Dry-run Layer 2 (netns harness) for WANControl route snapshot/restore.
#
# Creates an ISOLATED `ip netns` with a couple of dummy gateway interfaces, then
# exercises the REAL route-mutation code paths in wancontrol.network
# (snapshot_default_routes / restore_default_routes and the
# `python -m wancontrol.network --restore-routes` CLI) entirely inside that
# namespace. The host routing table is never touched.
#
# Scenarios exercised:
#   1. single default route  -> snapshot, simulate failover, restore, verify.
#   2. multiple defaults (ECMP-ish, distinct metrics) -> snapshot, clobber,
#      restore ALL of them in metric order, verify.
#   3. empty snapshot        -> restore must REFUSE to delete the live default
#      (safety: never strip the current default off an empty/invalid snapshot).
#
# Requirements: root (CAP_NET_ADMIN) and a working `ip netns`. The companion
# pytest (test_route_restore_netns.py) skips automatically when these are
# missing; this script exits 2 ("skip") in the same situations so callers can
# distinguish skip from a genuine FAIL.
#
# Idempotent: setup tears down any leftover namespace first; teardown always
# runs via an EXIT trap. Safe to re-run.
#
# Usage:
#   sudo tests/netns_harness.sh                # run all scenarios
#   sudo tests/netns_harness.sh --keep         # leave the netns up for debugging
#
# Exit codes:  0 = PASS   1 = FAIL   2 = SKIP (not root / no netns support)
# ----------------------------------------------------------------------------
set -u -o pipefail

# ── Constants ───────────────────────────────────────────────────────────────
NS="wanctl_test_$$"                       # unique per invocation
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR=""
KEEP=0
FAILS=0

# Dummy gateway topology (all inside the netns). Each "WAN" is a dummy device
# carrying the host-side /30 address; the gateway is the .1 of that /30.
IF_A="wlan_a"; ADDR_A="10.10.0.2/30"; GW_A="10.10.0.1"; TABLE_A=100
IF_B="wlan_b"; ADDR_B="10.10.1.2/30"; GW_B="10.10.1.1"; TABLE_B=101
IF_C="wlan_c"; ADDR_C="10.10.2.2/30"; GW_C="10.10.2.1"; TABLE_C=102

# ── Logging helpers ─────────────────────────────────────────────────────────
log()  { printf '[netns-harness] %s\n' "$*" >&2; }
pass() { printf '  PASS: %s\n' "$*" >&2; }
fail() { printf '  FAIL: %s\n' "$*" >&2; FAILS=$((FAILS + 1)); }

# Run a command inside the test namespace.
nsx() { ip netns exec "$NS" "$@"; }

# Python invocation pinned to the repo (prefer the project venv).
py() {
    local python="$REPO_ROOT/.venv/bin/python"
    [ -x "$python" ] || python="$(command -v python3 || command -v python)"
    # Scrub dry-run/shadow so the harness exercises REAL route mutations. When
    # invoked from pytest, conftest sets WANCONTROL_DRY_RUN=1 globally, which
    # would turn every `ip` call into a no-op and defeat the whole point of the
    # netns harness (Layer 2: real mutations, isolated from the host).
    nsx env --unset=WANCONTROL_DRY_RUN --unset=WANCONTROL_SHADOW \
        PYTHONPATH="$REPO_ROOT" \
        WANCONTROL_CONFIG="$CONFIG_PATH" \
        "$python" "$@"
}

# ── Preconditions ───────────────────────────────────────────────────────────
require_root_and_netns() {
    if [ "$(id -u)" -ne 0 ]; then
        log "SKIP: must run as root (CAP_NET_ADMIN) to create network namespaces."
        exit 2
    fi
    if ! command -v ip >/dev/null 2>&1; then
        log "SKIP: 'ip' (iproute2) not found."
        exit 2
    fi
    # Probe that we can actually create+enter a namespace in this sandbox.
    local probe="wanctl_probe_$$"
    if ! ip netns add "$probe" >/dev/null 2>&1; then
        log "SKIP: cannot create network namespaces here (no CAP_NET_ADMIN / no netns)."
        exit 2
    fi
    if ! ip netns exec "$probe" ip link set lo up >/dev/null 2>&1; then
        ip netns del "$probe" >/dev/null 2>&1 || true
        log "SKIP: cannot exec inside a network namespace here."
        exit 2
    fi
    ip netns del "$probe" >/dev/null 2>&1 || true
}

# ── Setup / teardown ────────────────────────────────────────────────────────
setup() {
    # Idempotent: clear any stale namespace of the same name first.
    ip netns del "$NS" >/dev/null 2>&1 || true
    ip netns add "$NS"
    nsx ip link set lo up

    # Bring up three dummy "WAN" interfaces with their /30 host addresses.
    local pairs=(
        "$IF_A $ADDR_A" "$IF_B $ADDR_B" "$IF_C $ADDR_C"
    )
    local pair name addr
    for pair in "${pairs[@]}"; do
        name="${pair%% *}"; addr="${pair##* }"
        nsx ip link add "$name" type dummy
        nsx ip addr add "$addr" dev "$name"
        nsx ip link set "$name" up
        # A connected route to the gateway's /30 so `ip route add ... via <gw>`
        # is accepted by the kernel (gateway must be on-link).
    done

    WORKDIR="$(mktemp -d /tmp/wanctl_netns.XXXXXX)"
    CONFIG_PATH="$WORKDIR/config.yaml"
    DB_PATH="$WORKDIR/wan.db"
    write_config

    log "namespace=$NS  workdir=$WORKDIR  db=$DB_PATH"
}

teardown() {
    if [ "$KEEP" -eq 1 ]; then
        log "--keep set: leaving namespace $NS and $WORKDIR in place."
        return
    fi
    ip netns del "$NS" >/dev/null 2>&1 || true
    [ -n "$WORKDIR" ] && rm -rf "$WORKDIR" 2>/dev/null || true
}

# A minimal-but-valid config.yaml so the CLI (`--restore-routes`) and our python
# snapshot helper both resolve the SAME isolated db_path. db_path lives in the
# tempdir; interfaces mirror the dummy topology so teardown_all_interfaces has
# real devices/subnets to operate on inside the namespace.
write_config() {
    cat > "$CONFIG_PATH" <<EOF
interfaces:
  - name: $IF_A
    label: "WAN A"
    expected_speed_mbps: 100
    gateway: $GW_A
    routing_table_id: $TABLE_A
  - name: $IF_B
    label: "WAN B"
    expected_speed_mbps: 50
    gateway: $GW_B
    routing_table_id: $TABLE_B
  - name: $IF_C
    label: "WAN C"
    expected_speed_mbps: 30
    gateway: $GW_C
    routing_table_id: $TABLE_C
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
lock_file: $WORKDIR/controller.lock
heartbeat_file: $WORKDIR/controller.heartbeat
db_path: $DB_PATH
log_dir: $WORKDIR
EOF
}

# Reset the DB state between scenarios so a stale snapshot never leaks across.
reset_db() {
    rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm" 2>/dev/null || true
}

# ── Snapshot / restore drivers (REAL wancontrol.network code) ───────────────
# Take a snapshot of the namespace's current default routes into the DB.
do_snapshot() {
    py - <<'PY'
import os
from wancontrol.config import Config
from wancontrol.database import Database
from wancontrol import network

cfg = Config(os.environ["WANCONTROL_CONFIG"]).load()
db = Database(cfg.db_path)
db.initialize()
network.snapshot_default_routes(db, force=True)
PY
}

# Restore via the real CLI entrypoint (exercises __main__ wiring + teardown).
do_restore_cli() {
    local python="$REPO_ROOT/.venv/bin/python"
    [ -x "$python" ] || python="$(command -v python3 || command -v python)"
    nsx env --unset=WANCONTROL_DRY_RUN --unset=WANCONTROL_SHADOW \
        PYTHONPATH="$REPO_ROOT" \
        WANCONTROL_CONFIG="$CONFIG_PATH" \
        "$python" -m wancontrol.network --restore-routes
}

# Echo the current IPv4 default route(s) as a normalized, sorted string so we
# can compare snapshot-vs-restored deterministically.
current_defaults() {
    nsx ip -4 route show default | sed 's/[[:space:]]\+/ /g; s/ $//' | sort
}

# ── Scenarios ───────────────────────────────────────────────────────────────

# Scenario 1: single default route. Snapshot it, simulate a controller failover
# (rewrite the default to GW_B), restore, and assert the original GW_A default
# came back.
scenario_single_default() {
    log "Scenario 1: single default route snapshot/restore"
    reset_db
    nsx ip route flush default 2>/dev/null || true
    nsx ip route replace default via "$GW_A" dev "$IF_A"

    local before; before="$(current_defaults)"
    do_snapshot

    # Simulate a failover route mutation off the snapshotted state.
    nsx ip route replace default via "$GW_B" dev "$IF_B"
    local switched; switched="$(current_defaults)"
    if [ "$switched" = "$before" ]; then
        fail "failover mutation did not change the default route"
        return
    fi

    do_restore_cli >/dev/null 2>&1
    local after; after="$(current_defaults)"

    if echo "$after" | grep -q "via $GW_A" && echo "$after" | grep -q "dev $IF_A"; then
        pass "original default (via $GW_A dev $IF_A) restored"
    else
        fail "expected restored default via $GW_A dev $IF_A; got: [$after]"
    fi
    if echo "$after" | grep -q "via $GW_B"; then
        fail "failover default via $GW_B still present after restore"
    fi
}

# Scenario 2: MULTIPLE default routes (distinct metrics). All must be
# snapshotted, all live defaults deleted on restore, and ALL re-added in metric
# order (item 7).
scenario_multiple_defaults() {
    log "Scenario 2: multiple default routes snapshot/restore (metric order)"
    reset_db
    nsx ip route flush default 2>/dev/null || true
    nsx ip route add default via "$GW_A" dev "$IF_A" metric 100
    nsx ip route add default via "$GW_B" dev "$IF_B" metric 200

    local count_before; count_before="$(nsx ip -4 route show default | grep -c default || true)"
    if [ "$count_before" -lt 2 ]; then
        fail "expected 2 default routes before snapshot, got $count_before"
        return
    fi
    do_snapshot

    # Clobber with a single different default (simulate controller takeover).
    nsx ip route replace default via "$GW_C" dev "$IF_C" metric 50
    # Drop the higher-metric ones so only the clobber remains.
    nsx ip route del default via "$GW_A" dev "$IF_A" metric 100 2>/dev/null || true
    nsx ip route del default via "$GW_B" dev "$IF_B" metric 200 2>/dev/null || true

    do_restore_cli >/dev/null 2>&1

    local after; after="$(current_defaults)"
    local ok=1
    echo "$after" | grep -q "via $GW_A" || ok=0
    echo "$after" | grep -q "via $GW_B" || ok=0
    if echo "$after" | grep -q "via $GW_C"; then
        ok=0  # the clobber default must be gone
    fi
    local count_after; count_after="$(nsx ip -4 route show default | grep -c default || true)"
    if [ "$ok" -eq 1 ] && [ "$count_after" -eq 2 ]; then
        pass "both defaults (via $GW_A + via $GW_B) restored; clobber removed"
    else
        fail "multi-default restore wrong: count=$count_after defaults=[$after]"
    fi
}

# Scenario 3: EMPTY snapshot. If the host had NO default at snapshot time, a
# later restore must NOT strip whatever default is currently live (safety —
# never delete the current default off an empty/invalid snapshot, item 4).
scenario_empty_snapshot() {
    log "Scenario 3: empty snapshot must not delete the live default"
    reset_db
    nsx ip route flush default 2>/dev/null || true

    # Snapshot with NO default routes present -> snapshot is empty.
    do_snapshot

    # Now a default appears (e.g. DHCP came up after boot).
    nsx ip route replace default via "$GW_A" dev "$IF_A"
    local live; live="$(current_defaults)"

    do_restore_cli >/dev/null 2>&1
    local after; after="$(current_defaults)"

    if [ "$after" = "$live" ] && echo "$after" | grep -q "via $GW_A"; then
        pass "live default left untouched by empty-snapshot restore"
    else
        fail "empty-snapshot restore altered the live default: before=[$live] after=[$after]"
    fi
}

# ── Main ────────────────────────────────────────────────────────────────────
main() {
    for arg in "$@"; do
        case "$arg" in
            --keep) KEEP=1 ;;
            *) log "unknown arg: $arg" ;;
        esac
    done

    require_root_and_netns
    trap teardown EXIT
    setup

    scenario_single_default
    scenario_multiple_defaults
    scenario_empty_snapshot

    if [ "$FAILS" -eq 0 ]; then
        log "RESULT: PASS (all scenarios)"
        exit 0
    fi
    log "RESULT: FAIL ($FAILS scenario assertion(s) failed)"
    exit 1
}

main "$@"
