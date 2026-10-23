"""HOT/COLD/UNKNOWN detection with a short TTL cache."""
from __future__ import annotations

import asyncio
import time
from typing import Literal

import httpx

from .ollama import OllamaClient

ModelState = Literal["HOT", "COLD", "UNKNOWN"]


class ModelStateCache:
    """Caches the HOT/COLD/UNKNOWN state per model name for `ttl_s` seconds.

    Refresh fetches `/api/ps` from Ollama; failure of that call → UNKNOWN
    (never silently promoted to HOT or COLD).
    """

    def __init__(self, ollama: OllamaClient, ttl_s: float):
        self._ollama = ollama
        self._ttl = ttl_s
        self._lock = asyncio.Lock()
        self._states: dict[str, ModelState] = {}
        self._fetched_at: float = 0.0  # monotonic

    async def get(self, model: str) -> ModelState:
        now = time.monotonic()
        if now - self._fetched_at < self._ttl and self._states:
            return self._states.get(model, "COLD")

        async with self._lock:
            # Re-check under lock to avoid a stampede after waiting.
            now = time.monotonic()
            if now - self._fetched_at < self._ttl and self._states:
                return self._states.get(model, "COLD")
            try:
                running = await self._ollama.list_running()
                loaded = {m.get("name") for m in running if m.get("name")}
                # Reset: anything previously known as HOT but not now → COLD.
                new_states: dict[str, ModelState] = {}
                for name in loaded:
                    new_states[name] = "HOT"
                # Preserve a COLD entry for the queried model so callers see it.
                if model not in new_states:
                    new_states[model] = "COLD"
                self._states = new_states
                self._fetched_at = time.monotonic()
                return self._states[model]
            except (httpx.HTTPError, httpx.TimeoutException, Exception):
                self._states = {model: "UNKNOWN"}
                self._fetched_at = time.monotonic()
                return "UNKNOWN"

    async def snapshot(self) -> dict[str, ModelState]:
        """Return the current cache contents, refreshing if stale."""
        now = time.monotonic()
        if now - self._fetched_at >= self._ttl or not self._states:
            # Trigger a refresh via get() for any key; use empty-string sentinel.
            await self.get("__refresh__")
            self._states.pop("__refresh__", None)
        return dict(self._states)

    def invalidate(self) -> None:
        self._fetched_at = 0.0
        self._states = {}
