"""Unit tests for UsageSampler rate derivation."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from wancontrol.usage import UsageSampler


@pytest.fixture
def sampler(app_cfg, mem_db):
    return UsageSampler(app_cfg, mem_db)


def _patch_counters(values):
    """Patch read_interface_counters to return the given dict per call.

    values is a list of dicts (iface -> (rx, tx, rxp, txp)) or None to simulate
    a missing interface. Each call to read_interface_counters(iface) returns
    the entry for that iface in the current dict; advance() moves to the next.
    """
    state = {"i": 0}

    def fake(iface):
        d = values[state["i"]]
        return d.get(iface)

    return fake, state


def test_first_sample_is_baseline_only(sampler, mem_db, app_cfg):
    """The first read can't produce a rate — nothing should be written."""
    values = [{"wan0": (1000, 500, 1, 1), "wan1": (2000, 1000, 1, 1)}]
    fake, _ = _patch_counters(values)
    with patch("wancontrol.usage.read_interface_counters", side_effect=fake):
        sampler._tick(app_cfg)
    assert mem_db.get_usage(limit=100) == []


def test_second_sample_produces_rate(sampler, mem_db, app_cfg, monkeypatch):
    """A second sample with a higher counter yields a non-zero rate."""
    seq = [
        {"wan0": (0, 0, 0, 0), "wan1": (0, 0, 0, 0)},
        {"wan0": (1_000_000, 500_000, 100, 50), "wan1": (0, 0, 0, 0)},
    ]
    state = {"i": 0}

    def fake(iface):
        return seq[state["i"]].get(iface)

    # Freeze monotonic so dt is a known 1s; advance index between ticks.
    mono = {"t": 100.0}
    monkeypatch.setattr("wancontrol.usage.time.monotonic", lambda: mono["t"])

    with patch("wancontrol.usage.read_interface_counters", side_effect=fake):
        sampler._tick(app_cfg)            # baseline
        state["i"] = 1
        mono["t"] = 101.0
        sampler._tick(app_cfg)            # produces rates

    rows = mem_db.get_usage(interface="wan0", limit=10)
    assert len(rows) == 1
    row = rows[0]
    # 1_000_000 bytes / 1s * 8 / 1_000_000 = 8 Mbps
    assert row.rx_mbps == pytest.approx(8.0, rel=1e-3)
    assert row.tx_mbps == pytest.approx(4.0, rel=1e-3)
    assert row.rx_bytes_total == 1_000_000


def test_counter_reset_is_treated_as_new_baseline(sampler, mem_db, app_cfg, monkeypatch):
    """If counters appear to decrease (interface bounce), no negative row written."""
    seq = [
        {"wan0": (1_000_000, 500_000, 100, 50), "wan1": (0, 0, 0, 0)},
        {"wan0": (10, 5, 1, 1), "wan1": (0, 0, 0, 0)},  # bounce: smaller
        {"wan0": (1_000_010, 510, 2, 2), "wan1": (0, 0, 0, 0)},  # normal growth
    ]
    state = {"i": 0}
    mono = {"t": 100.0}
    monkeypatch.setattr("wancontrol.usage.time.monotonic", lambda: mono["t"])

    def fake(iface):
        return seq[state["i"]].get(iface)

    with patch("wancontrol.usage.read_interface_counters", side_effect=fake):
        sampler._tick(app_cfg)
        state["i"] = 1
        mono["t"] = 101.0
        sampler._tick(app_cfg)            # counter went down -> skip insert
        state["i"] = 2
        mono["t"] = 102.0
        sampler._tick(app_cfg)            # picks up from the (10, 5) baseline

    rows = mem_db.get_usage(interface="wan0", limit=10)
    # Only the third tick should have inserted a row (positive delta vs baseline).
    assert len(rows) == 1
    assert rows[0].rx_bytes_total == 1_000_010


def test_missing_interface_drops_baseline(sampler, mem_db, app_cfg, monkeypatch):
    """If an interface disappears between ticks, no spike when it reappears."""
    seq = [
        {"wan0": (1000, 500, 1, 1)},                  # wan1 absent
        {"wan0": (2000, 1000, 2, 2)},                 # wan1 still absent
        {"wan0": (3000, 1500, 3, 3), "wan1": (999_999_999, 999_999_999, 1, 1)},
    ]
    state = {"i": 0}
    mono = {"t": 100.0}
    monkeypatch.setattr("wancontrol.usage.time.monotonic", lambda: mono["t"])

    def fake(iface):
        return seq[state["i"]].get(iface)

    with patch("wancontrol.usage.read_interface_counters", side_effect=fake):
        sampler._tick(app_cfg)
        state["i"] = 1
        mono["t"] = 101.0
        sampler._tick(app_cfg)
        state["i"] = 2
        mono["t"] = 102.0
        sampler._tick(app_cfg)

    rows = mem_db.get_usage(interface="wan1", limit=10)
    # wan1 had no prior baseline when it reappeared, so no row yet.
    assert rows == []
