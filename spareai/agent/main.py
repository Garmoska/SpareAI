"""Agent FastAPI app: /health, /status, /models, /generate (SSE)."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from ..common.auth import bearer_dependency
from ..common.schemas import (
    AgentStatus,
    GenerateRequest,
    ModelEntry,
    ModelInfo,
    ModelsResponse,
)
from ..common.sse import sse_end, sse_event
from .config import AgentConfig
from .model_state import ModelStateCache
from .ollama import OllamaClient
from .overload import OverloadMonitor


class AgentState:
    """Mutable per-process state."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.ollama = OllamaClient(
            config.ollama_url,
            config.ollama_connect_timeout_s,
            config.ollama_read_timeout_s,
        )
        self.model_state = ModelStateCache(self.ollama, config.model_state_ttl_s)
        self.overload = OverloadMonitor(
            config.overload_high_pct,
            config.overload_low_pct,
            config.overload_sample_interval_s,
        )
        self.in_flight: int = 0
        self._in_flight_lock = asyncio.Lock()
        self.started_at = datetime.now(timezone.utc)

    async def inc_in_flight(self) -> None:
        async with self._in_flight_lock:
            self.in_flight += 1

    async def dec_in_flight(self) -> None:
        async with self._in_flight_lock:
            self.in_flight = max(0, self.in_flight - 1)


def create_app(config: AgentConfig | None = None) -> FastAPI:
    config = config or AgentConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = AgentState(config)
        await state.overload.start()
        app.state.agent = state
        try:
            yield
        finally:
            await state.overload.stop()
            await state.ollama.aclose()

    app = FastAPI(title="SpareAI Agent", version="0.1.0", lifespan=lifespan)
    auth = Depends(bearer_dependency(config.agent_token))

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/status", dependencies=[auth])
    async def status_endpoint(request: Request) -> AgentStatus:
        st: AgentState = request.app.state.agent
        model_state = await st.model_state.get(config.default_model)
        host = st.overload.last
        return AgentStatus(
            node_id=config.node_id,
            state=st.overload.state,
            available=True,
            cpu_cores=host.cpu_cores,
            load_avg_1m=round(host.load_avg_1m, 3),
            cpu_usage_pct=round(host.cpu_usage_pct, 1),
            memory_usage_pct=round(host.memory_usage_pct, 1),
            models={config.default_model: ModelInfo(state=model_state)},
            in_flight_requests=st.in_flight,
            last_heartbeat=datetime.now(timezone.utc),
        )

    @app.get("/models", dependencies=[auth], response_model=ModelsResponse)
    async def models_endpoint(request: Request) -> ModelsResponse:
        st: AgentState = request.app.state.agent
        try:
            installed = await st.ollama.list_installed()
        except (httpx.HTTPError, Exception) as e:
            raise HTTPException(status_code=502, detail={"error": "ollama_unreachable", "detail": str(e)})
        states = await st.model_state.snapshot()
        out: list[ModelEntry] = []
        for m in installed:
            name = m.get("name") or m.get("model")
            if not name:
                continue
            s = states.get(name, "COLD")
            out.append(ModelEntry(
                name=name,
                size_bytes=m.get("size"),
                state=s,
                modified_at=m.get("modified_at"),
            ))
        return ModelsResponse(models=out)

    @app.post("/generate", dependencies=[auth])
    async def generate_endpoint(req: GenerateRequest, request: Request):
        st: AgentState = request.app.state.agent

        # Overload gate (fast path, no round trip to Ollama).
        if st.overload.state == "OVERLOAD":
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": "agent_overloaded", "retry_after": st.overload.retry_after_s()},
            )

        # Verify model is installed; if not, return 404 before streaming.
        try:
            installed = await st.ollama.list_installed()
        except Exception as e:
            return JSONResponse(status_code=502,
                                content={"error": "ollama_unreachable", "detail": str(e)})
        names = {m.get("name") or m.get("model") for m in installed}
        if req.model not in names:
            return JSONResponse(status_code=404,
                                content={"error": "model_not_installed", "model": req.model})

        await st.inc_in_flight()

        async def stream():
            agent_ttft_ms: int | None = None
            start_mono = time.monotonic_ns()
            final_done: dict | None = None
            opts = req.options.model_dump(exclude_none=True) if req.options else None
            try:
                async for chunk in st.ollama.generate_stream(
                    model=req.model,
                    prompt=req.prompt,
                    options=opts,
                    keep_alive=req.keep_alive,
                ):
                    piece = chunk.get("response", "")
                    if piece:
                        if agent_ttft_ms is None:
                            agent_ttft_ms = (time.monotonic_ns() - start_mono) // 1_000_000
                        yield sse_event("token", {
                            "request_id": req.request_id,
                            "chunk": piece,
                            "ts_mono_ms": (time.monotonic_ns() - start_mono) // 1_000_000,
                        })
                    if chunk.get("done"):
                        final_done = chunk
                        break

                if final_done is not None:
                    # Invalidate the model-state cache; after a generate the state
                    # may have flipped COLD→HOT (or vice versa on keep_alive=0).
                    st.model_state.invalidate()
                    yield sse_event("done", {
                        "request_id": req.request_id,
                        "total_duration": final_done.get("total_duration"),
                        "load_duration": final_done.get("load_duration"),
                        "prompt_eval_count": final_done.get("prompt_eval_count"),
                        "prompt_eval_duration": final_done.get("prompt_eval_duration"),
                        "eval_count": final_done.get("eval_count"),
                        "eval_duration": final_done.get("eval_duration"),
                        "agent_ttft_ms": agent_ttft_ms,
                    })
                yield sse_end()
            except (httpx.HTTPError, Exception) as e:
                yield sse_event("error", {
                    "request_id": req.request_id,
                    "where": "mid_stream" if agent_ttft_ms is not None else "pre_stream",
                    "code": "ollama_stream_broken",
                    "detail": str(e),
                })
                yield sse_end()
            finally:
                await st.dec_in_flight()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return app


# Factory for `uvicorn spareai.agent.main:app` — only built if env is set.
try:
    app = create_app()
except RuntimeError:
    app = None  # tests / tooling can import this module without env


def main() -> None:
    import uvicorn
    cfg = AgentConfig.from_env()
    uvicorn.run(create_app(cfg), host=cfg.bind_host, port=cfg.bind_port, log_level="info")


if __name__ == "__main__":
    main()
