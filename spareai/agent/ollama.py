"""Thin async client for the local Ollama HTTP API."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx


class OllamaClient:
    def __init__(self, base_url: str, connect_timeout_s: float, read_timeout_s: float):
        self._base = base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            connect=connect_timeout_s,
            read=read_timeout_s,
            write=connect_timeout_s,
            pool=connect_timeout_s,
        )
        self._client = httpx.AsyncClient(timeout=self._timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_running(self) -> list[dict[str, Any]]:
        r = await self._client.get(f"{self._base}/api/ps",
                                   timeout=httpx.Timeout(connect=1.0, read=1.0, write=1.0, pool=1.0))
        r.raise_for_status()
        return r.json().get("models", [])

    async def list_installed(self) -> list[dict[str, Any]]:
        r = await self._client.get(f"{self._base}/api/tags")
        r.raise_for_status()
        return r.json().get("models", [])

    async def unload(self, model: str) -> None:
        """Force COLD by sending a zero-work generate with keep_alive=0."""
        payload = {"model": model, "keep_alive": 0, "prompt": "", "stream": False}
        await self._client.post(f"{self._base}/api/generate", json=payload)

    async def generate_stream(
        self,
        model: str,
        prompt: str,
        options: Optional[dict[str, Any]] = None,
        keep_alive: Optional[int | str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream chunks from Ollama's /api/generate. Yields parsed JSON dicts."""
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": True}
        if options:
            payload["options"] = options
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive

        async with self._client.stream("POST", f"{self._base}/api/generate", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
