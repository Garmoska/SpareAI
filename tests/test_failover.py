"""Dispatcher failover: pre-stream retry; mid-stream no retry (manual trace)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from spareai.common.schemas import AgentStatus, ModelInfo
from spareai.dispatcher.config import AgentRef
from spareai.dispatcher.registry import AgentEntry
from spareai.dispatcher.router import eligible, order

MODEL = "qwen2.5:3b-instruct-q4_K_M"


def _ready_entry(node_id, model_state="HOT"):
    e = AgentEntry(ref=AgentRef(node_id=node_id, url=f"http://x/{node_id}"))
    e.last_status = AgentStatus(
        node_id=node_id, state="READY", available=True,
        cpu_cores=4, load_avg_1m=0.5, cpu_usage_pct=10.0,
        memory_usage_pct=10.0,
        models={MODEL: ModelInfo(state=model_state)},
        in_flight_requests=0,
        last_heartbeat=datetime.now(timezone.utc),
    )
    e.last_status_at_mono = time.monotonic()
    return e


def test_failover_candidate_list_order():
    """Dispatcher must try HOT first, then COLD, then UNKNOWN."""
    entries = [
        _ready_entry("c-unknown", "UNKNOWN"),
        _ready_entry("a-hot", "HOT"),
        _ready_entry("b-cold", "COLD"),
    ]
    cands = order(eligible(entries, MODEL, staleness_s=5), MODEL)
    assert [c.node_id for c in cands] == ["a-hot", "b-cold", "c-unknown"]


def test_only_unknown_available_is_still_eligible():
    """If only UNKNOWN is reachable, it must still be eligible (last resort)."""
    entries = [_ready_entry("only", "UNKNOWN")]
    cands = order(eligible(entries, MODEL, staleness_s=5), MODEL)
    assert [c.node_id for c in cands] == ["only"]


def test_no_candidates_when_all_overloaded():
    e = _ready_entry("a")
    e.last_status.state = "OVERLOAD"
    assert eligible([e], MODEL, staleness_s=5) == []
