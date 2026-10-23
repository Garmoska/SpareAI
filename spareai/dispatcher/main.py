"""Dispatcher FastAPI app."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..common.auth import bearer_dependency
from ..common.schemas import ChatRequest
from ..common.sse import sse_end, sse_event
from .config import DispatcherConfig
from .health import HealthPoller
from .registry import AgentEntry, AgentRegistry
from .router import eligible, order

log = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class DispatcherState:
    def __init__(self, config: DispatcherConfig):
        self.config = config
        self.registry = AgentRegistry(list(config.agents))
        self.http = httpx.AsyncClient()
        self.poller = HealthPoller(config, self.registry, self.http)
        jenv = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html"]),
        )
        self.index_tpl = jenv.get_template("index.html")


def create_app(config: DispatcherConfig | None = None) -> FastAPI:
    config = config or DispatcherConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = DispatcherState(config)
        await state.poller.start()
        app.state.dispatcher = state
        try:
            yield
        finally:
            await state.poller.stop()
            await state.http.aclose()

    app = FastAPI(title="SpareAI Dispatcher", version="0.1.0", lifespan=lifespan)
    client_auth = Depends(bearer_dependency(config.client_token))

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        st: DispatcherState = request.app.state.dispatcher
        html = st.index_tpl.render(
            client_token=config.client_token,
            default_model=config.default_model,
        )
        return HTMLResponse(html)

    @app.get("/agents", dependencies=[client_auth])
    async def agents_endpoint(request: Request):
        st: DispatcherState = request.app.state.dispatcher
        out = []
        for e in st.registry.all():
            s = e.last_status
            out.append({
                "node_id": e.node_id,
                "url": e.url,
                "reachable": e.reachable(config.health_staleness_s),
                "state": s.state if s else None,
                "in_flight_requests": s.in_flight_requests if s else None,
                "load_avg_1m": s.load_avg_1m if s else None,
                "load_per_core": round(s.load_avg_1m / max(1, s.cpu_cores), 3) if s else None,
                "cpu_cores": s.cpu_cores if s else None,
                "models": {k: v.model_dump() for k, v in (s.models.items() if s else [])},
                "last_status_at_mono": e.last_status_at_mono,
                "consecutive_failures": e.consecutive_failures,
                "last_error": e.last_error,
            })
        return {"agents": out}

    @app.post("/chat", dependencies=[client_auth])
    async def chat(req: ChatRequest, request: Request):
        st: DispatcherState = request.app.state.dispatcher
        model = req.model or config.default_model
        request_id = str(uuid.uuid4())

        candidates = eligible(st.registry.all(), model, config.health_staleness_s)
        candidates = order(candidates, model)
        if not candidates:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": "no_eligible_agent", "model": model},
            )

        max_attempts = min(config.failover_max_attempts, len(candidates))
        start_mono = time.monotonic_ns()

        async def stream():
            tried: list[str] = []
            opts = req.options.model_dump(exclude_none=True) if req.options else None
            payload = {
                "request_id": request_id,
                "model": model,
                "prompt": req.prompt,
            }
            if opts:
                payload["options"] = opts

            headers = {
                "Authorization": f"Bearer {config.agent_token}",
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            }

            selected: AgentEntry | None = None
            for attempt in range(1, max_attempts + 1):
                e = candidates[attempt - 1]
                model_state = e.last_status.models[model].state if e.last_status else "UNKNOWN"

                try:
                    timeout = httpx.Timeout(
                        connect=config.generate_connect_timeout_s,
                        read=config.generate_read_timeout_s,
                        write=config.generate_connect_timeout_s,
                        pool=config.generate_connect_timeout_s,
                    )
                    async with st.http.stream(
                        "POST",
                        f"{e.url}/generate",
                        headers=headers,
                        json=payload,
                        timeout=timeout,
                    ) as resp:
                        if resp.status_code == 503:
                            # Agent overloaded — try next candidate.
                            tried.append(e.node_id)
                            continue
                        if resp.status_code >= 400:
                            tried.append(e.node_id)
                            # 404 model_not_installed is terminal only for this agent.
                            continue

                        selected = e
                        # Emit routing event first.
                        yield sse_event("routing", {
                            "request_id": request_id,
                            "node_id": e.node_id,
                            "model": model,
                            "model_state_at_routing": model_state,
                            "attempt": attempt,
                        })

                        dispatcher_ttft_ms: int | None = None
                        first_token_seen = False
                        got_done = False

                        async for raw in resp.aiter_lines():
                            # Pass through Agent SSE lines unchanged, but inspect for
                            # TTFT measurement and done detection.
                            if raw == "":
                                yield b"\n"
                                continue
                            if raw.startswith("event: token") and not first_token_seen:
                                first_token_seen = True
                                dispatcher_ttft_ms = (time.monotonic_ns() - start_mono) // 1_000_000
                            if raw.startswith("event: done"):
                                got_done = True
                            if raw.startswith("event: error"):
                                # If error arrives before any token: treat as pre-stream failure
                                # (continue to next candidate). After tokens: pass through, no retry.
                                if not first_token_seen:
                                    tried.append(e.node_id)
                                    # Consume rest of this stream before breaking out.
                                    break
                            yield (raw + "\n").encode("utf-8")

                        if first_token_seen or got_done:
                            # Final dispatcher metrics event.
                            e2e_ms = (time.monotonic_ns() - start_mono) // 1_000_000
                            yield sse_event("metrics", {
                                "request_id": request_id,
                                "dispatcher_ttft_ms": dispatcher_ttft_ms,
                                "e2e_latency_ms": e2e_ms,
                                "selected_node": e.node_id,
                                "failover_attempts": tried,
                            })
                            yield sse_end()
                            return
                        # else: pre-stream error on this agent, loop to next.
                except (httpx.HTTPError, Exception) as exc:
                    tried.append(e.node_id)
                    log.warning("agent %s failed pre-stream: %s", e.node_id, exc)
                    continue

            # All candidates exhausted without producing tokens.
            yield sse_event("error", {
                "request_id": request_id,
                "where": "pre_stream",
                "code": "all_agents_failed",
                "detail": json.dumps({"attempted": tried}),
            })
            yield sse_end()

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


try:
    app = create_app()
except RuntimeError:
    app = None


def main() -> None:
    import uvicorn
    cfg = DispatcherConfig.from_env()
    uvicorn.run(create_app(cfg), host=cfg.bind_host, port=cfg.bind_port, log_level="info")


if __name__ == "__main__":
    main()
