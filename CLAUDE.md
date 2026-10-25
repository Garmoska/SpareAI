# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SpareAI is a PoC distributed LLM inference pool. A browser Chat Client talks to one Central Dispatcher, which routes each prompt to one of several lightweight Agents, each of which owns a local Ollama instance:

```
Chat Client ──Bearer CLIENT_TOKEN──▶ Dispatcher :8080 ──Bearer AGENT_TOKEN──▶ Agent :8081 ──localhost──▶ Ollama :11434
```

Pinned model everywhere: `qwen2.5:3b-instruct-q4_K_M`. Python 3.11+, FastAPI, streaming SSE end-to-end (TTFT is measured, not inferred). The same repo/package contains both services; shared wire contracts live in `spareai/common`.

## Commands

```bash
# Install (editable, with dev deps)
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -e ".[dev]"

# Run the two services (separate shells; Ollama must be running)
python -m spareai.agent.main                       # :8081
python -m spareai.dispatcher.main                  # :8080, also serves the Chat Client at /
AGENT_NODE_ID=worker-02 AGENT_BIND_PORT=8082 python -m spareai.agent.main   # second local agent

# Tests (asyncio_mode=auto; no live services needed)
pytest -q
pytest tests/test_router.py::test_eligibility_filters_unreachable -q

# Benchmark + 10-prompt quality run (writes gitignored bench/results-*)
python -m bench.run_bench --dispatcher http://localhost:8080 --client-token "$CLIENT_TOKEN" \
  --agent http://localhost:8081 --agent-token "$AGENT_TOKEN" \
  --ollama http://127.0.0.1:11434 --model qwen2.5:3b-instruct-q4_K_M

# AWS target (Terraform; see infra/README.md)
cd infra && terraform init && terraform apply -var="my_ip=<public-ip>"
```

## Configuration gotchas

- Config is read directly from `os.environ` in `AgentConfig.from_env()` / `DispatcherConfig.from_env()`. `.env` is **not** auto-loaded (there is no dotenv dependency), so export the variables in the shell before starting a service.
- Both services refuse to start if `CLIENT_TOKEN`/`AGENT_TOKEN` are missing or still placeholder values (`changeme*`).
- Several aliases are accepted, in precedence order:
  - `NODE_ID` | `AGENT_NODE_ID`
  - `LISTEN_HOST` | `AGENT_BIND_HOST` / `DISPATCHER_BIND_HOST`
  - `LISTEN_PORT` | `AGENT_BIND_PORT` / `DISPATCHER_BIND_PORT`
  - `OLLAMA_BASE_URL` | `OLLAMA_URL`
  - `STATUS_CACHE_TTL_S` | `MODEL_STATE_TTL_S`
  - `STATUS_FRESHNESS_S` | `HEALTH_STALENESS_S`
  - `MAX_ROUTING_ATTEMPTS` | `FAILOVER_MAX_ATTEMPTS`
  - `REQUEST_TIMEOUT_S` overrides either service's read timeout.
- Dispatcher agent list comes from `AGENTS=url1,url2` if set, else `agents.yaml` at `AGENTS_FILE` (default `./agents.yaml`). YAML entries need unique `node_id` + `url`; URLs must be reachable from the Dispatcher (private IPs on AWS).
- Both `main.py` modules build a module-level `app` only when env is valid (they catch `RuntimeError` and set `app = None`) so tests can import without configuration.

## Architecture

### Request path

1. `Dispatcher /chat` (client bearer) builds a `request_id` and picks candidates from `AgentRegistry` via `router.eligible()` then `router.order()`.
   - Eligible: status snapshot fresh within `HEALTH_STALENESS_S`, agent `state == "READY"`, requested model present on that agent.
   - Ordered best-first by `(model_state rank, in_flight_requests, load_avg_1m/cpu_cores, node_id)`; rank is HOT < COLD < UNKNOWN. UNKNOWN is a last resort, never dropped while reachable.
2. `Dispatcher` opens an SSE stream to the chosen `Agent /generate` with `AGENT_TOKEN`, passing agent SSE lines through and injecting its own `routing` and `metrics` events.
3. `Agent /generate` checks its overload FSM (returns 503 `agent_overloaded`), verifies the model is installed (`/api/tags`, 404 `model_not_installed`), increments in-flight, then streams Ollama output as `token` events and a final `done` event with Ollama timings + agent TTFT; invalidates the model-state cache afterward.
4. SSE events are `routing`, `token`, `done`, `metrics`, `error`, `end`; helpers in `spareai/common/sse.py` (`sse_event`, `sse_end`). Docs-only payload models are in `spareai/common/schemas.py`.

### Failover semantics (deliberate, tested)

- Pre-stream failure only: connect error, 503, HTTP >= 400, or an SSE `error` before the first token → mark that node tried and advance to the next candidate, capped by `FAILOVER_MAX_ATTEMPTS` (min with candidate count).
- Mid-stream failure: stream is passed through; the client gets `error` with `where="mid_stream"`; **no retry** — duplicate execution is intentionally avoided.
- `tests/test_failover.py` and `test_router.py` encode candidate ordering/eligibility; the actual mid-stream trace is manual (`docs/failure-playbook.md`).

### Agent-side subsystems

- `model_state.py` — `ModelStateCache`: HOT/COLD/UNKNOWN from Ollama `/api/ps`, TTL-cached with single-flight refresh. A failed `/api/ps` yields UNKNOWN, never a silent HOT/COLD. `invalidate()` forces the next read to refetch.
- `overload.py` — `OverloadMonitor`: samples every ~2s and uses hysteresis on `load_avg_1m / cpu_cores` (enter OVERLOAD above `OVERLOAD_HIGH_PCT`, exit below `OVERLOAD_LOW_PCT`). On Linux uses `psutil.getloadavg()`; on Windows approximates load from `cpu_percent`. `inject_sample()` is the test hook.
- `ollama.py` — thin async httpx client for `/api/ps`, `/api/tags`, streaming `/api/generate`, and `unload()` (zero-work generate with `keep_alive=0`, used to force COLD).

### Dispatcher-side subsystems

- `health.py` — background `HealthPoller` fetches `/status` from every registered agent each interval (immediate first poll) and feeds `AgentRegistry`; failures increment `consecutive_failures` and staleness makes the node unreachable.
- `registry.py` — in-memory most-recent status per node; `reachable()` is purely staleness-based.
- `router.py` — pure functions (`eligible`, `order`, `rank`); keep routing deterministic and free of I/O so it stays unit-testable.
- `config.py` — also parses the agents YAML / `AGENTS` env.
- `templates/index.html` — Chat Client page, rendered with the `CLIENT_TOKEN` injected server-side; there is no token-entry UI.

## Conventions

- Tests are unit-level: construct configs/entries directly or fake the Ollama client (see `FakeOllama` in `tests/test_model_state.py`); `respx` is available for HTTP mocking. No test starts the apps.
- Keep routing, hysteresis, and model-state logic as pure/separable classes — that is what the test suite targets.
- Benchmark and quality artifacts belong in `bench/results-*` (gitignored) and manual ratings in `docs/quality-notes.md`.
- Remaining operational docs: `docs/demo-runbook.md` (live demo), `docs/failure-playbook.md` (injection procedures), `docs/engineering-review.md`, `infra/README.md` (AWS/Terraform).
- Security posture is intentionally PoC-grade: static bearer tokens, no TLS, no accounts/rotation, `/health` unauthenticated. Do not add production-auth scaffolding unless asked.
