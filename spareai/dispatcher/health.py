"""Background health poller for the Dispatcher."""
from __future__ import annotations

import asyncio
import logging

import httpx

from ..common.schemas import AgentStatus
from .config import DispatcherConfig
from .registry import AgentRegistry

log = logging.getLogger(__name__)


class HealthPoller:
    def __init__(self, config: DispatcherConfig, registry: AgentRegistry, client: httpx.AsyncClient):
        self._config = config
        self._registry = registry
        self._client = client
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        # Initial poll immediately so routing can start fast.
        await self._poll_all()
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._config.health_poll_interval_s)
            except asyncio.TimeoutError:
                await self._poll_all()

    async def _poll_all(self) -> None:
        await asyncio.gather(
            *(self._poll_one(e.ref.node_id, e.ref.url) for e in self._registry.all()),
            return_exceptions=True,
        )

    async def _poll_one(self, node_id: str, url: str) -> None:
        headers = {"Authorization": f"Bearer {self._config.agent_token}"}
        try:
            r = await self._client.get(
                f"{url}/status",
                headers=headers,
                timeout=self._config.agent_status_timeout_s,
            )
            if r.status_code != 200:
                self._registry.record_failure(node_id, f"status_http_{r.status_code}")
                return
            status_obj = AgentStatus.model_validate(r.json())
            self._registry.record_success(node_id, status_obj)
        except (httpx.HTTPError, httpx.TimeoutException, Exception) as e:
            self._registry.record_failure(node_id, type(e).__name__)
