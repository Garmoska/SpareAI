"""In-memory agent registry — most-recent status snapshots."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ..common.schemas import AgentStatus
from .config import AgentRef


@dataclass
class AgentEntry:
    ref: AgentRef
    last_status: Optional[AgentStatus] = None
    last_status_at_mono: Optional[float] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0

    @property
    def node_id(self) -> str:
        return self.ref.node_id

    @property
    def url(self) -> str:
        return self.ref.url

    def reachable(self, staleness_s: float, now_mono: Optional[float] = None) -> bool:
        if self.last_status_at_mono is None:
            return False
        now = now_mono if now_mono is not None else time.monotonic()
        return (now - self.last_status_at_mono) < staleness_s


class AgentRegistry:
    def __init__(self, agents: list[AgentRef]):
        self._by_id: dict[str, AgentEntry] = {a.node_id: AgentEntry(ref=a) for a in agents}

    def all(self) -> list[AgentEntry]:
        return list(self._by_id.values())

    def get(self, node_id: str) -> Optional[AgentEntry]:
        return self._by_id.get(node_id)

    def record_success(self, node_id: str, status_obj: AgentStatus) -> None:
        e = self._by_id.get(node_id)
        if e is None:
            return
        e.last_status = status_obj
        e.last_status_at_mono = time.monotonic()
        e.last_error = None
        e.consecutive_failures = 0

    def record_failure(self, node_id: str, err: str) -> None:
        e = self._by_id.get(node_id)
        if e is None:
            return
        e.last_error = err
        e.consecutive_failures += 1
