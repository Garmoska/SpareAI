"""SSE event formatting helpers."""
from __future__ import annotations

import json
from typing import Any


def sse_event(event: str, data: Any) -> bytes:
    """Format one SSE event. `data` is JSON-serialized."""
    payload = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def sse_end() -> bytes:
    return b"event: end\ndata: {}\n\n"
