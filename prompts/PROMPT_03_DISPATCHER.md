# Prompt #3 — Implement the Central Dispatcher

You are implementing the Central Dispatcher for **SpareAI**. Presentation in 2 days — timebox this task to 2–4 hours.

## Context
The approved architecture (Prompt #1) has one Dispatcher, one Agent per worker, and a Chat Client HTML page served by the Dispatcher at `GET /`. Model pinned to `qwen2.5:3b-instruct-q4_K_M`. SSE streaming end-to-end. Shared bearer tokens: `CLIENT_TOKEN` inbound from browser, `AGENT_TOKEN` outbound to Agents.

## Technology (pinned)
- Python 3.11+, FastAPI, Pydantic v2.
- `httpx.AsyncClient` with streaming for Agent calls.
- `sse-starlette` or `StreamingResponse` for SSE.
- Jinja2 (or FastAPI's built-in templating) for the single Chat Client HTML page.

## Endpoints
1. `GET /` — unauthenticated. Serves the Chat Client HTML with `CLIENT_TOKEN` injected server-side (e.g., `window.SPAREAI_TOKEN = "…"` in a `<script>` block). No separate token-entry UI in the browser.
2. `GET /health` — unauthenticated. `{"ok": true}`.
3. `GET /status` — Bearer `CLIENT_TOKEN`. Snapshot of registered Agents and their most recent cached status (useful for the demo and troubleshooting).
4. `POST /generate` — Bearer `CLIENT_TOKEN`. Request body `{"model": "...", "prompt": "...", "options": {...}}`. Returns an SSE stream proxied from the selected Agent, prefixed with a `routing` event.

## Routing (deterministic)
Build the eligible set from the cached registry:
1. Agent reachable (last successful status within `STATUS_FRESHNESS_S`).
2. `state == "READY"` (not OVERLOAD).
3. Requested model present in the Agent's `/models` output.

If empty → `503 {"error": "no_eligible_agents"}`.

Order the eligible set by:
1. Model state: `HOT` > `COLD`. `UNKNOWN` only chosen when no non-UNKNOWN Agent is eligible.
2. Lower `in_flight_requests`.
3. Lower `load_avg_1m / cpu_cores`.
4. Lexicographic `node_id` as the deterministic final tie-break (so tests can assert selection).

Emit a `routing` SSE event before any token events:
```
event: routing
data: {"request_id": "<uuid>", "selected_node": "worker-01", "model_state_at_route": "HOT", "reason": "hot_and_least_in_flight"}
```

Then proxy chunk events from the Agent verbatim, and finally the Agent's `done` event (augmented with `dispatcher_ttft_ms = first_token_observed - request_accepted`).

## Health monitoring
- Background task polls `GET /status` on each configured Agent every `HEALTH_POLL_INTERVAL_S` (default `3`).
- Cache the latest status per `node_id`. Mark Agent unavailable when the last successful poll is older than `STATUS_FRESHNESS_S` (default `10`).
- A single failed poll does not immediately mark the Agent down — wait for staleness.
- On an in-flight `503 agent_overloaded` response from a `/generate` call, optimistically mark the Agent OVERLOAD in the local cache; the next status poll corrects it.

## Failover
- If connecting to the selected Agent fails (connect error, immediate 5xx, timeout before streaming starts), try the next eligible Agent.
- If the stream has started and then fails mid-stream, surface a mid-stream `error` SSE event to the client and close the stream. Do **not** retry on another Agent — duplicate generation risk.
- Bounded attempts: at most `MAX_ROUTING_ATTEMPTS` (default `2`). Log each attempt.
- If all attempts fail before streaming began, return `503 {"error": "no_eligible_agents"}`.

## Authentication
- `/generate` and `/status` require `Authorization: Bearer <CLIENT_TOKEN>`.
- All outbound calls to Agents include `Authorization: Bearer <AGENT_TOKEN>`.
- Never log tokens.

## Configuration (env vars)
- `CLIENT_TOKEN` — required.
- `AGENT_TOKEN` — required.
- `AGENTS` — comma-separated list of Agent base URLs, e.g. `AGENTS=http://127.0.0.1:8081,http://cloud-vm:8081`.
- `LISTEN_HOST` — default `0.0.0.0`.
- `LISTEN_PORT` — default `8080`.
- `HEALTH_POLL_INTERVAL_S` — default `3`.
- `STATUS_FRESHNESS_S` — default `10`.
- `MAX_ROUTING_ATTEMPTS` — default `2`.
- `REQUEST_TIMEOUT_S` — default `180`.
- `STREAM_INACTIVITY_TIMEOUT_S` — default `60` (inactivity on the token stream, not total duration).

## Tests
- Routing selection unit tests: HOT vs COLD, UNKNOWN handling, in-flight tie-break, load tie-break, lex tie-break.
- Stale status handling.
- No eligible agents.
- Connection failure → failover to next eligible Agent.
- Mid-stream failure not retried.
- 401 on missing/invalid `CLIENT_TOKEN`.
- Routing event emitted before token events.

## Deliverables
- Dispatcher implementation under `dispatcher/`.
- Chat Client HTML template (basic — Prompt #4 polishes it).
- `.env.example` with placeholders.
- Tests + the exact `pytest` command.
- README snippet: run order, config, example `curl` and browser flows.

## Workflow
1. Confirm shared contracts with Prompt #2 output. If the Agent SSE schema differs, reconcile before implementing.
2. Implement + test.
3. Smoke-test against two local Agents on different ports.
4. Summarize files changed and open questions.

Do not call Ollama from the Dispatcher directly — always go through an Agent.
