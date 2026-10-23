# Prompt #2 — Implement the Worker Agent

You are implementing **SpareAI**, a 2-day PoC for routing LLM inference across underutilized compute. Presentation is in 2 days — timebox this task to 2–4 hours and cut scope before extending time.

## Context
The architecture (approved in Prompt #1) has a Chat Client (HTML served by the Dispatcher), one Central Dispatcher, one lightweight Agent per worker host, and a local Ollama on each worker. Model pinned to `qwen2.5:3b-instruct-q4_K_M`. Agents are the only components that talk to Ollama; Ollama binds to `127.0.0.1`.

## Goal
Implement the Worker Agent. Do not implement the Dispatcher or Chat Client in this task, except for any shared contract file both components will consume.

## Technology (pinned)
- Python 3.11+, FastAPI, Pydantic v2, `httpx.AsyncClient`, `psutil`, `pytest` + `pytest-asyncio`.
- Serve SSE via `sse-starlette` or `StreamingResponse`.
- No database, message broker, auth framework, or ORM.

## Endpoints
1. `GET /health` — unauthenticated. Returns `{"ok": true}` only. For liveness probes.
2. `GET /status` — Bearer `AGENT_TOKEN`. Returns the full status payload (see Prompt #1 for shape, including `state`, `in_flight_requests`, `models[name].state`, `load_avg_1m`, `cpu_cores`, `cpu_usage_pct`, `memory_usage_pct`, `last_heartbeat`, `node_id`).
3. `GET /models` — Bearer `AGENT_TOKEN`. Returns installed models from Ollama `/api/tags` combined with per-model HOT/COLD/UNKNOWN state from `/api/ps`.
4. `POST /generate` — Bearer `AGENT_TOKEN`. Pydantic-validated body (`model`, `prompt`, `options` optional, `keep_alive` optional). SSE streaming response.

## HOT / COLD / UNKNOWN detection
- Poll Ollama's `GET /api/ps`. If the requested model name appears → `HOT`. If absent → `COLD`. If the call fails or times out → `UNKNOWN`. Never silently coerce UNKNOWN to HOT or COLD.
- Cache the result for `STATUS_CACHE_TTL_S` (default 2 s) to avoid hammering Ollama on bursts of `/status` requests.
- `GET /status` and `GET /models` must reflect the current cached state at response time.

## Streaming
- Agent calls Ollama `POST /api/generate` with `stream: true`.
- Agent re-emits events to its caller as SSE (`text/event-stream`). One event per Ollama chunk:
  - `event: token`
  - `data: {"request_id": "...", "content": "<chunk>", "ts_ms": <int>}`
- Final event:
  - `event: done`
  - `data: {"request_id": "...", "ollama": { "total_duration": ..., "load_duration": ..., "prompt_eval_duration": ..., "prompt_eval_count": ..., "eval_duration": ..., "eval_count": ... }, "agent_ttft_ms": <first_chunk_ts - request_start_ts>}`
- On mid-stream error:
  - `event: error`
  - `data: {"request_id": "...", "code": "<string>", "message": "<safe>"}`
  Then close the stream. Do not raise HTTP 500 after streaming has started.

## In-flight tracking + overload
- Increment an in-memory counter when `/generate` begins; decrement on completion or error.
- `/status` publishes `in_flight_requests` (not `queue_length`). No bounded queue; Ollama serializes internally.
- Overload policy:
  - Sample `psutil.getloadavg()[0]` on Linux; smoothed `psutil.cpu_percent(interval=1.0)` on Windows for dev.
  - Enter `OVERLOAD` when `load_avg_1m > OVERLOAD_HIGH_PCT * cpu_cores` (default `0.70`).
  - Exit `OVERLOAD` when `load_avg_1m < OVERLOAD_LOW_PCT * cpu_cores` (default `0.50`).
  - While in OVERLOAD, `/generate` returns `503 {"error": "agent_overloaded", "retry_after": <seconds>}`.
  - `/status.state` is `"READY"` or `"OVERLOAD"` and reflects the hysteresis state machine.

## Authentication
- All endpoints except `GET /health` require `Authorization: Bearer <AGENT_TOKEN>`.
- `AGENT_TOKEN` loaded from env; required at startup; refuse to start if missing or set to a placeholder like `changeme`.
- Return 401 with `{"error": "unauthorized"}` on missing or wrong token. Do not reveal which case it was.
- Never log the token.

## Configuration (env vars)
- `AGENT_TOKEN` — required.
- `NODE_ID` — required (e.g., `worker-01`).
- `OLLAMA_BASE_URL` — default `http://127.0.0.1:11434`.
- `MODEL` — default `qwen2.5:3b-instruct-q4_K_M`.
- `LISTEN_HOST` — default `0.0.0.0`.
- `LISTEN_PORT` — default `8081`.
- `REQUEST_TIMEOUT_S` — default `180`.
- `STATUS_CACHE_TTL_S` — default `2`.
- `OVERLOAD_HIGH_PCT` — default `0.70`.
- `OVERLOAD_LOW_PCT` — default `0.50`.

## Error handling
- Ollama unreachable → `502 {"error": "ollama_unreachable"}` for `/generate`; UNKNOWN state in `/status`.
- Model not installed → `404 {"error": "model_not_found"}`.
- Timeout → `504 {"error": "ollama_timeout"}`, or a mid-stream `error` event if streaming had already begun.
- Validation errors → `400` with Pydantic's error list (field names only; do not echo prompt text).
- Never log prompt text or generated text by default. Use `request_id` for correlation.

## Tests
- `pytest` tests for:
  - Pydantic validation on `/generate`.
  - HOT / COLD / UNKNOWN classification given mocked `/api/ps` responses (success, empty, 500, timeout).
  - Overload hysteresis state machine (unit test the transitions directly).
  - 401 on missing/invalid token on `/status`, `/models`, `/generate`.
  - `/status` payload shape and in-flight counter movement.
- Mock Ollama with `httpx.MockTransport`. Keep tests fast.

## Deliverables
- Agent implementation under `agent/`.
- `requirements.txt` (or project's dependency file).
- `.env.example` with placeholder values only.
- Tests + the exact `pytest` command.
- README snippet: how to run locally, example `curl` calls, how to swap models.

## Workflow
1. Confirm the repository structure and shared contracts from Prompt #1.
2. Implement Agent + tests.
3. Run tests and report actual results — do not claim passing without running.
4. Smoke-test against a real local Ollama with the pinned model.
5. Summarize files changed and any open questions.

Avoid unrelated refactoring. Avoid adding dependencies not listed above without justification.
