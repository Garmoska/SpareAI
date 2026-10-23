"""Deterministic routing: eligibility filter + ordering."""
from __future__ import annotations

from typing import Iterable

from .registry import AgentEntry

_STATE_RANK = {"HOT": 0, "COLD": 1, "UNKNOWN": 2}


def eligible(entries: Iterable[AgentEntry], model: str, staleness_s: float) -> list[AgentEntry]:
    out: list[AgentEntry] = []
    for e in entries:
        if not e.reachable(staleness_s):
            continue
        s = e.last_status
        if s is None or s.state != "READY":
            continue
        if model not in s.models:
            continue
        out.append(e)
    return out


def rank(entry: AgentEntry, model: str) -> tuple:
    """Lower tuple = preferred. Deterministic across runs."""
    s = entry.last_status
    assert s is not None, "eligible() guarantees last_status is set"
    state = s.models[model].state
    cores = max(1, s.cpu_cores)
    load_norm = s.load_avg_1m / cores
    return (
        _STATE_RANK.get(state, 99),
        s.in_flight_requests,
        load_norm,
        s.node_id,
    )


def order(entries: list[AgentEntry], model: str) -> list[AgentEntry]:
    """Return eligible entries ordered best-first. UNKNOWN is kept as last resort."""
    return sorted(entries, key=lambda e: rank(e, model))
