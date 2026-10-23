"""Host-load overload state machine with hysteresis."""
from __future__ import annotations

import asyncio
import os
import platform
from dataclasses import dataclass
from typing import Literal

import psutil

AgentState = Literal["READY", "OVERLOAD"]


@dataclass
class HostSample:
    load_avg_1m: float
    cpu_usage_pct: float
    memory_usage_pct: float
    cpu_cores: int


class OverloadMonitor:
    """Samples host load periodically; transitions READY <-> OVERLOAD with hysteresis.

    - On Linux: uses `psutil.getloadavg()[0]` (true 1-min load average).
    - On other OSes (Windows dev): approximates `load_avg_1m` as
      `cpu_percent / 100 * cpu_cores` using smoothed CPU percent.
    """

    def __init__(self, high_pct: float, low_pct: float, sample_interval_s: float):
        self._high = high_pct
        self._low = low_pct
        self._interval = sample_interval_s
        self._state: AgentState = "READY"
        self._cores = max(1, psutil.cpu_count(logical=True) or os.cpu_count() or 1)
        self._last: HostSample = HostSample(0.0, 0.0, 0.0, self._cores)
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def last(self) -> HostSample:
        return self._last

    def retry_after_s(self) -> int:
        return max(1, int(self._interval * 2))

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
        # Prime cpu_percent so the first real sample is meaningful.
        psutil.cpu_percent(interval=None)
        while not self._stop.is_set():
            await self._sample_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue

    async def _sample_once(self) -> None:
        cpu_pct = psutil.cpu_percent(interval=None)
        mem_pct = psutil.virtual_memory().percent
        if platform.system() == "Linux":
            try:
                load_1m = psutil.getloadavg()[0]
            except (AttributeError, OSError):
                load_1m = (cpu_pct / 100.0) * self._cores
        else:
            load_1m = (cpu_pct / 100.0) * self._cores

        self._last = HostSample(
            load_avg_1m=load_1m,
            cpu_usage_pct=cpu_pct,
            memory_usage_pct=mem_pct,
            cpu_cores=self._cores,
        )
        self._apply_hysteresis(load_1m)

    def _apply_hysteresis(self, load_1m: float) -> None:
        norm = load_1m / self._cores if self._cores else 0.0
        if self._state == "READY" and norm > self._high:
            self._state = "OVERLOAD"
        elif self._state == "OVERLOAD" and norm < self._low:
            self._state = "READY"

    # ---- Pure helper for tests ----
    def inject_sample(self, load_1m: float) -> None:
        """Test hook: inject a load value and run the hysteresis step."""
        self._last = HostSample(load_1m, (load_1m / self._cores) * 100.0, 0.0, self._cores)
        self._apply_hysteresis(load_1m)
