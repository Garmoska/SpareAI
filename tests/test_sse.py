"""SSE event framing + end-of-stream."""
from __future__ import annotations

from spareai.common.sse import sse_end, sse_event


def test_sse_event_shape():
    out = sse_event("token", {"request_id": "r", "chunk": "hi", "ts_mono_ms": 1})
    text = out.decode("utf-8")
    assert text.startswith("event: token\n")
    assert "\ndata: " in text
    assert text.endswith("\n\n")


def test_sse_event_json_is_compact():
    out = sse_event("done", {"a": 1, "b": 2}).decode("utf-8")
    assert '{"a":1,"b":2}' in out  # no spaces


def test_sse_end_terminator():
    assert sse_end() == b"event: end\ndata: {}\n\n"
