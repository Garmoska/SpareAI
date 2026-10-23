"""Model state cache: HOT / COLD / UNKNOWN + TTL."""
from __future__ import annotations

import asyncio

import pytest

from spareai.agent.model_state import ModelStateCache

MODEL = "qwen2.5:3b-instruct-q4_K_M"


class FakeOllama:
    def __init__(self):
        self.calls = 0
        self.behavior = "hot"  # "hot" | "cold" | "fail"

    async def list_running(self):
        self.calls += 1
        if self.behavior == "fail":
            raise RuntimeError("api/ps unreachable")
        if self.behavior == "hot":
            return [{"name": MODEL, "size": 2 * 1024 * 1024 * 1024}]
        return []  # cold


@pytest.mark.asyncio
async def test_hot_detection():
    o = FakeOllama()
    c = ModelStateCache(o, ttl_s=0.5)
    assert await c.get(MODEL) == "HOT"


@pytest.mark.asyncio
async def test_cold_when_absent():
    o = FakeOllama(); o.behavior = "cold"
    c = ModelStateCache(o, ttl_s=0.5)
    assert await c.get(MODEL) == "COLD"


@pytest.mark.asyncio
async def test_unknown_when_ps_fails():
    o = FakeOllama(); o.behavior = "fail"
    c = ModelStateCache(o, ttl_s=0.5)
    assert await c.get(MODEL) == "UNKNOWN"


@pytest.mark.asyncio
async def test_ttl_caches_result():
    o = FakeOllama()
    c = ModelStateCache(o, ttl_s=1.0)
    await c.get(MODEL)
    await c.get(MODEL)
    await c.get(MODEL)
    assert o.calls == 1  # second and third served from cache


@pytest.mark.asyncio
async def test_cache_expires_and_refetches():
    o = FakeOllama()
    c = ModelStateCache(o, ttl_s=0.05)
    await c.get(MODEL)
    await asyncio.sleep(0.08)
    await c.get(MODEL)
    assert o.calls == 2


@pytest.mark.asyncio
async def test_invalidate_forces_refresh():
    o = FakeOllama()
    c = ModelStateCache(o, ttl_s=10.0)
    await c.get(MODEL)
    c.invalidate()
    await c.get(MODEL)
    assert o.calls == 2
