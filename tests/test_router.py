"""Router determinism + ordering rules."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from spareai.common.schemas import AgentStatus, ModelInfo
from spareai.dispatcher.config import AgentRef
from spareai.dispatcher.registry import AgentEntry, AgentRegistry
from spareai.dispatcher.router import eligible, order

MODEL = "qwen2.5:3b-instruct-q4_K_M"


def _status(node_id, state="READY", model_state="HOT", in_flight=0,
            load=0.5, cores=4, has_model=True):
    models = {MODEL: ModelInfo(state=model_state)} if has_model else {}
    return AgentStatus(
        node_id=node_id, state=state, available=True,
        cpu_cores=cores, load_avg_1m=load, cpu_usage_pct=10.0,
        memory_usage_pct=10.0, models=models, in_flight_requests=in_flight,
        last_heartbeat=datetime.now(timezone.utc),
    )


def _entry(node_id, status, fresh=True):
    e = AgentEntry(ref=AgentRef(node_id=node_id, url=f"http://x/{node_id}"))
    e.last_status = status
    e.last_status_at_mono = time.monotonic() if fresh else time.monotonic() - 1000
    return e


def test_eligibility_filters_unreachable():
    e1 = _entry("a", _status("a"), fresh=False)
    e2 = _entry("b", _status("b"), fresh=True)
    out = eligible([e1, e2], MODEL, staleness_s=5)
    assert [e.node_id for e in out] == ["b"]


def test_eligibility_filters_overload_and_missing_model():
    e1 = _entry("a", _status("a", state="OVERLOAD"))
    e2 = _entry("b", _status("b", has_model=False))
    e3 = _entry("c", _status("c"))
    out = eligible([e1, e2, e3], MODEL, staleness_s=5)
    assert [e.node_id for e in out] == ["c"]


def test_order_prefers_hot_over_cold_over_unknown():
    entries = [
        _entry("a", _status("a", model_state="UNKNOWN")),
        _entry("b", _status("b", model_state="COLD")),
        _entry("c", _status("c", model_state="HOT")),
    ]
    out = order(entries, MODEL)
    assert [e.node_id for e in out] == ["c", "b", "a"]


def test_order_tiebreak_in_flight_then_load_then_node_id():
    # All HOT; tie break on in_flight then load then node_id (lexicographic).
    entries = [
        _entry("b", _status("b", in_flight=0, load=1.0)),
        _entry("a", _status("a", in_flight=0, load=1.0)),  # same, lex wins → "a" first
        _entry("c", _status("c", in_flight=0, load=0.5)),  # lower load → "c" first of all
        _entry("d", _status("d", in_flight=1, load=0.1)),  # higher in_flight → after the 0's
    ]
    out = order(entries, MODEL)
    assert [e.node_id for e in out] == ["c", "a", "b", "d"]


def test_registry_reachability_window():
    reg = AgentRegistry([AgentRef("a", "http://x")])
    e = reg.get("a")
    assert not e.reachable(5)
    reg.record_success("a", _status("a"))
    assert reg.get("a").reachable(5)
