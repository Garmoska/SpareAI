You are working as a senior software architect and engineer helping me build a small technical Proof of Concept (PoC) for an opportunistic distributed LLM inference pool called SpareAI.

# Timeline
Presentation in 2 days. Earlier "two-week PoC" language is obsolete. Every proposed deliverable must be completable in ~2–4 hours of focused work. Prefer the smallest implementation that satisfies the requirement. Cut scope rather than extend time. Tag every deliverable you propose as **must / should / nice**.

# Goal
Demonstrate that otherwise underutilized enterprise compute can serve LLM inference without interfering with the hosts' primary workloads.

The system must show:
1. A client submits an LLM request through a single API.
2. A Central Dispatcher selects an appropriate worker node.
3. Each worker is managed by a lightweight local Agent.
4. The Agent communicates with Ollama running locally on the same host.
5. The Dispatcher distinguishes HOT, COLD, and UNKNOWN model states.
6. The system fails over to another worker when one worker becomes unavailable.
7. The system measures and exposes inference latency and related metrics.
8. The architecture can later evolve toward more sophisticated routing and possibly peer-to-peer orchestration.

This is a technical PoC, not a production platform.

# High-level architecture

```
                    ┌──────────────────┐
                    │   Chat Client    │
                    │  (HTML served    │
                    │   by Dispatcher) │
                    └────────┬─────────┘
                             │  HTTPS / SSE
                             │  Bearer CLIENT_TOKEN
                             ▼
                    ┌──────────────────┐
                    │ Central          │
                    │ Dispatcher       │
                    │  Routing         │
                    │  Health          │
                    │  Model State     │
                    └────────┬─────────┘
                             │  HTTPS / SSE
                             │  Bearer AGENT_TOKEN
                    ┌────────┴────────┐
                    │                 │
                    ▼                 ▼
             ┌─────────────┐   ┌─────────────┐
             │   Agent A   │   │   Agent B   │
             │             │   │             │
             │   Ollama    │   │   Ollama    │
             │   qwen2.5   │   │   qwen2.5   │
             │   :3b-q4    │   │   :3b-q4    │
             └─────────────┘   └─────────────┘
```

## Component responsibilities

**Chat Client**
- Minimal single-page HTML served by the Dispatcher at `GET /`.
- Sends requests only to the Dispatcher.
- Never communicates with Agents or Ollama directly.
- Receives SSE and renders tokens incrementally.

**Central Dispatcher**
- Receives inference requests from the Chat Client.
- Serves the Chat Client HTML at `/` with `CLIENT_TOKEN` injected server-side.
- Maintains an in-memory registry of configured Agents and their most recent status.
- Selects the most appropriate Agent (HOT preference, fewer in-flight, lower host load).
- Performs health polling and failover.
- Proxies the SSE stream from the selected Agent to the browser.

**Agent**
- Runs on each worker host.
- Exposes a small HTTP API behind Bearer-token auth.
- Communicates with the local Ollama instance only (localhost).
- Reports health, utilization, installed models, model state, in-flight count, and READY/OVERLOAD state.
- Executes inference requests delegated by the Dispatcher.
- Refuses new work when the host CPU load exceeds the overload threshold.

**Ollama**
- Runs locally on each worker.
- Bound to `127.0.0.1` — never exposed to the public network.
- The Agent is the only component that talks to the local Ollama API.

# Terminology
Do not call the Agent a "Dispatcher". There is one Central Dispatcher in this PoC. Use consistent terms: **Chat Client**, **Central Dispatcher**, **Agent**, **Ollama**, **Qwen**.
The Agent manages one host; the Central Dispatcher decides which host executes a request. The Agent API must remain orchestration-mechanism-agnostic so a future P2P coordinator could replace the Dispatcher.

# Target environment

**Stage 1 — Local debugging (Windows laptop at `C:\Leonov\SpareAI`):**
- Full stack in-process on one machine: Chat Client (served by Dispatcher) + Central Dispatcher + Agent A + Ollama. Optionally a second Agent process on the same host (different port) to exercise routing logic locally.
- Purpose: debug end-to-end request path with Claude before touching cloud.

**Stage 2 — AWS target (demo environment):**
- 2× AWS EC2 **`c7i.xlarge`** (4 vCPU, 8 GB RAM, Intel Sapphire Rapids), Ubuntu 22.04 LTS, in **`eu-central-1`** (Frankfurt).
- Provisioned by Terraform in `infra/` — see `infra/README.md`.
- Instance A: Dispatcher + Agent A + Ollama. Instance B: Agent B + Ollama.
- Networking: SSH (22) and Dispatcher (8080) ingress only from the user's laptop IP; Agent (8081) ingress only between the two instances via security-group self-reference. Ollama remains bound to `127.0.0.1` on each host.
- Dispatcher reaches Agents using **private** IPs; the Chat Client reaches the Dispatcher using the public IP.

On-prem HPE DL380 is no longer the target. Any residual on-prem language in later prompts is obsolete.

# Model
Pinned: `qwen2.5:3b-instruct-q4_K_M` on every worker.
- ~2 GB RAM footprint; fits an 8 GB `c7i.xlarge` comfortably alongside Ollama + the Agent + OS.
- Identical model across workers so HOT/COLD comparisons are meaningful.
- CPU-only; expect roughly 8–15 tok/s on `c7i.xlarge`, lower on the laptop.
Do not change the model mid-run without agreement.

# HOT / COLD / UNKNOWN

- **HOT**: the model is loaded in RAM and ready for inference.
- **COLD**: the model is not loaded; the next inference pays the load cost.
- **UNKNOWN**: the state cannot be determined right now. Do not fall back to HOT or COLD.

**Detection**: the Agent polls Ollama's `GET /api/ps`. If the configured model name is in the response → HOT. If absent → COLD. If `/api/ps` is unreachable or times out → UNKNOWN. Cache the result for 1–2 seconds so `/status` calls don't hammer Ollama.

**Forcing COLD** (for benchmarks and the demo): send `POST /api/generate` with `"keep_alive": 0` to unload. Verify absence via `/api/ps` before interpreting the next run as COLD. Do not restart Ollama to force COLD — that conflates with the Agent-down failover scenario.

The Dispatcher prefers HOT. UNKNOWN is treated conservatively (not treated as HOT).

# Streaming (in scope end-to-end)

- Agent → Ollama: `POST /api/generate` with `stream: true`.
- Agent → Dispatcher: Server-Sent Events (`text/event-stream`), one event per token chunk, final event carries Ollama's timing fields (`total_duration`, `load_duration`, `prompt_eval_duration`, `prompt_eval_count`, `eval_duration`, `eval_count`) plus the Agent's measured TTFT.
- Dispatcher → Chat Client: SSE passthrough; no buffering of the stream.
- Chat Client: renders tokens from an SSE source as they arrive.

Streaming enables honest TTFT measurement. Record both **Agent-side TTFT** (first chunk out of Ollama) and **Dispatcher-side TTFT** (first chunk observed by the Dispatcher) so network overhead is visible.

# Minimal Agent API

- `GET  /health`     — unauthenticated; returns `{"ok": true}`. For liveness probes only.
- `GET  /status`     — Bearer `AGENT_TOKEN`. Full status payload (shape below).
- `GET  /models`     — Bearer `AGENT_TOKEN`. Installed models (from Ollama `/api/tags`) + per-model HOT/COLD/UNKNOWN state.
- `POST /generate`   — Bearer `AGENT_TOKEN`. Validated input. SSE streaming output.

`/status` payload shape (illustrative, improve if there's a strong reason):

```json
{
  "node_id": "worker-01",
  "state": "READY",
  "available": true,
  "cpu_cores": 12,
  "load_avg_1m": 3.4,
  "cpu_usage_pct": 23,
  "memory_usage_pct": 61,
  "models": { "qwen2.5:3b-instruct-q4_K_M": { "state": "HOT" } },
  "in_flight_requests": 0,
  "last_heartbeat": "2026-10-23T14:00:00Z"
}
```

Note: `in_flight_requests`, not `queue_length`. The PoC does not implement an Agent-side request queue — Ollama serializes requests to the same model internally. `in_flight_requests` = count of currently-executing `/generate` handlers (typically 0 or 1).

# Dispatcher routing (deterministic)
Build the eligible set:
1. Agent reachable (last successful status within freshness threshold).
2. `state == READY` (not OVERLOAD).
3. Requested model installed.

Order the eligible set by:
1. Model state: HOT > COLD. UNKNOWN only chosen if no non-UNKNOWN Agent is eligible.
2. Lower `in_flight_requests`.
3. Lower `load_avg_1m / cpu_cores`.
4. Lexicographic `node_id` as the deterministic final tie-break.

Do **not** implement: ML-based routing, request-complexity classification, automatic quality evaluation, Gemini escalation, predictive scheduling, workload forecasting. Future extensions.

The Dispatcher serves `GET /` with the Chat Client HTML and injects `CLIENT_TOKEN` server-side so the browser needs no token-entry UI.

# Measurements
Capture at minimum:
- `request_id`;
- request start/end timestamps (monotonic for math, wall-clock for logs);
- selected Agent, model, model state at routing time;
- model load duration (from Ollama when available);
- prompt eval duration + token count;
- generation duration + output token count;
- TTFT (Agent-side and Dispatcher-side);
- end-to-end latency;
- output tokens per second;
- routing decision and failover attempts.

Clearly distinguish SpareAI-measured values from Ollama-reported values. Never log prompt contents or generated text. Correlate everything by `request_id`.

The benchmark script must:
- Force COLD via `keep_alive: 0`, verify via `/api/ps`, then time the cold request.
- Pre-warm, verify HOT via `/api/ps`, then time repeated warm requests.
- Write raw JSONL plus summary (median, p95) when samples suffice.
- Also run the 10-prompt quality set with the same metric capture so quality and latency share request IDs.

# Answer quality (sanity check)
Run a fixed set of 10 representative prompts (listed in `prompts/clarifications.md` entry 8). Each is manually rated acceptable / marginal / unacceptable with a one-line reason. Captured in `docs/quality-notes.md`. Reported in the exec deck as **Measured**, with the caveat: "small sample, single rater — a sanity check, not a benchmark."

# Failure handling (full detail in Prompt #6)
- Agent stops responding → marked unavailable after staleness threshold.
- Connection failure before streaming starts → try another eligible Agent (bounded attempts).
- `503 agent_overloaded` → try another eligible Agent.
- All Agents ineligible → stable client error.
- Mid-stream failure after generation began → do **not** transparently retry on another Agent (duplicate execution risk). Surface a clear mid-stream `error` SSE event.
- Agent recovers → re-eligible after one successful status poll.

# Security
```
Chat Client ─ Bearer CLIENT_TOKEN ─▶ Dispatcher ─ Bearer AGENT_TOKEN ─▶ Agent ─ localhost ─▶ Ollama
```
- Two static shared bearer tokens: `CLIENT_TOKEN` and `AGENT_TOKEN`.
- Both loaded from env vars; `.env.example` holds placeholders only; never committed.
- `/health` on both Agent and Dispatcher is unauthenticated and returns only liveness.
- Ollama binds to `127.0.0.1` on each worker.
- Clearly labeled as **PoC-grade authentication, not production-safe** in the README. No rotation, no revocation, no accounts.

# Overload policy (host workload protection)
The headline claim of SpareAI is "don't disturb primary workloads." The Agent must enforce this, not just claim it.

- Measure 1-minute load average: `psutil.getloadavg()[0]` on Linux; smoothed `psutil.cpu_percent(interval=1.0)` on Windows for dev.
- **Enter OVERLOAD** when `load_avg_1m > OVERLOAD_HIGH_PCT * cpu_cores` (default `OVERLOAD_HIGH_PCT = 0.70`).
- **Exit OVERLOAD** when `load_avg_1m < OVERLOAD_LOW_PCT * cpu_cores` (default `OVERLOAD_LOW_PCT = 0.50`).
- Hysteresis prevents flapping.
- In OVERLOAD, `/generate` returns `503 {"error": "agent_overloaded", "retry_after": <s>}`.
- `/status.state` is `"READY"` or `"OVERLOAD"` and reflects the hysteresis state machine, so the Dispatcher can skip the Agent without a round-trip rejection.
- Thresholds configurable via env vars. Defaults are reasonable PoC values, not calibrated.

# Technology stack (pinned)
- **Backend**: Python 3.11+ with FastAPI (Agent and Dispatcher).
- **Async HTTP**: `httpx.AsyncClient` (Ollama calls, Dispatcher→Agent, bench script).
- **SSE**: `sse-starlette` or raw `StreamingResponse`.
- **Validation**: Pydantic v2.
- **Host metrics**: `psutil`.
- **Tests**: `pytest` + `pytest-asyncio`.
- **Chat Client**: single HTML file + vanilla JS. Native streaming via `fetch` + `ReadableStream` (so the `Authorization` header can be set). No React/Vue/Svelte, no build step.
- **No** database, message broker, Kubernetes, service mesh, or auth framework.

If you find a concrete technical blocker that forces a stack change, stop and raise it. Do not re-litigate the choice otherwise.

# Development principles
Optimize for: simplicity, reliability, demonstrability, measurable results, understandable code.
Do not optimize for: scale, multi-tenancy, perfect consistency, sophisticated scheduling, maximum throughput.
A small working system is far more valuable than a sophisticated unfinished one — especially with 2 days.

# Future architecture (out of scope now)
More worker nodes, multiple models, Dynatrace integration, availability calendars, historical workload analysis, user-workstation workers, complexity-based routing, Gemini escalation, quality-based routing, peer-to-peer orchestration. Keep interfaces compatible; do not implement.

# Your first task
Do **not** start by writing the entire application.

First:
1. Inspect the repository state (likely close to empty).
2. Propose the repository structure (directory layout + key files).
3. Define the full API contracts for Agent and Dispatcher (request/response schemas, SSE event schema, error shapes).
4. Define the config shape (env vars and defaults for Agent and Dispatcher).
5. Define the Dispatcher's in-memory data structures (agent registry, status cache).
6. Explain the HOT/COLD/UNKNOWN detection + cache behavior.
7. Explain the overload state machine.
8. Explain the end-to-end SSE event schema (Ollama → Agent → Dispatcher → Browser).
9. Explain the health-polling + failover flow, including the mid-stream failure case.
10. Call out any specification ambiguity or technical risk given the 2-day timeline.
11. Tag each proposed deliverable as **must / should / nice** for the 2-day window.

Do not implement substantial code yet. Produce a concise design that can be reviewed in 15 minutes. Wait for approval before implementation.
