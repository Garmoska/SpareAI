"""Overload hysteresis state machine."""
from __future__ import annotations

from spareai.agent.overload import OverloadMonitor


def _mk():
    m = OverloadMonitor(high_pct=0.70, low_pct=0.50, sample_interval_s=1.0)
    # Pretend 4 cores regardless of host.
    m._cores = 4  # noqa: SLF001
    return m


def test_enters_overload_above_high():
    m = _mk()
    assert m.state == "READY"
    m.inject_sample(3.0)  # 3/4 = 0.75 > 0.70
    assert m.state == "OVERLOAD"


def test_hysteresis_band_does_not_flap():
    m = _mk()
    m.inject_sample(3.0)
    assert m.state == "OVERLOAD"
    m.inject_sample(2.4)  # 0.60 — inside band, stays OVERLOAD
    assert m.state == "OVERLOAD"
    m.inject_sample(1.9)  # 0.475 — below low, exits
    assert m.state == "READY"


def test_ready_stays_ready_in_band():
    m = _mk()
    m.inject_sample(2.4)  # 0.60 — inside band, no transition from READY
    assert m.state == "READY"
    m.inject_sample(2.9)  # 0.725 — above high
    assert m.state == "OVERLOAD"


def test_retry_after_is_positive():
    m = _mk()
    assert m.retry_after_s() >= 1
