# SpareAI

Opportunistic distributed LLM inference pool — technical PoC.

Shows that otherwise underutilized enterprise compute can serve LLM inference
without interfering with the host's primary workloads. One Central Dispatcher
routes requests across lightweight Agents that each manage a local Ollama.

```
Chat Client ──(Bearer CLIENT_TOKEN)──▶ Dispatcher ──(Bearer AGENT_TOKEN)──▶ Agent ──localhost──▶ Ollama
```

## Components

| Component   | Where                       | Port |
|-------------|-----------------------------|------|
| Chat Client | served by Dispatcher at `/` | 8080 |
| Dispatcher  | one per deployment          | 8080 |
| Agent       | one per worker host         | 8081 |
| Ollama      | one per worker, `127.0.0.1` | 11434 |

Pinned model: **`qwen2.5:3b-instruct-q4_K_M`** on every worker.

## Prerequisites

- Python 3.11+
- Ollama with the model pulled:
  ```bash
  ollama pull qwen2.5:3b-instruct-q4_K_M
  ```

## Install

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/mac
source .venv/bin/activate

pip install -e ".[dev]"
```

## Configure

```bash
cp .env.example .env
cp agents.yaml.example agents.yaml
# edit tokens in .env; edit agent node_id/url entries in agents.yaml
```

Required env vars:

- `CLIENT_TOKEN` — Chat Client → Dispatcher auth
- `AGENT_TOKEN`  — Dispatcher → Agent auth
- `MODEL`        — default `qwen2.5:3b-instruct-q4_K_M`

See `.env.example` for the full list (overload thresholds, poll intervals, timeouts).

## Run — Stage 1 (laptop, single host)

Three shells, same `.env`:

```bash
# Shell 1 — Ollama (if not already running)
ollama serve

# Shell 2 — Agent (port 8081)
python -m spareai.agent.main

# Shell 3 — Dispatcher + Chat Client (port 8080)
python -m spareai.dispatcher.main
```

Open http://localhost:8080/ — the Chat Client is served by the Dispatcher with
`CLIENT_TOKEN` injected server-side; no token entry UI needed.

### Second Agent on the same laptop (routing/failover demo)

```bash
AGENT_NODE_ID=worker-02 AGENT_BIND_PORT=8082 python -m spareai.agent.main
```

Add it to `agents.yaml`:

```yaml
agents:
  - node_id: worker-01
    url: http://127.0.0.1:8081
  - node_id: worker-02
    url: http://127.0.0.1:8082
```

## Run — Stage 2 (AWS, 2× c7i.xlarge)

See `infra/README.md`. Instance A runs Dispatcher + Agent A + Ollama;
Instance B runs Agent B + Ollama. Dispatcher reaches Agents on **private** IPs;
Chat Client reaches the Dispatcher on the public IP.

## Benchmark + 10-prompt quality run

```bash
python -m bench.run_bench \
  --dispatcher   http://localhost:8080 \
  --client-token "$CLIENT_TOKEN" \
  --agent        http://localhost:8081 \
  --agent-token  "$AGENT_TOKEN" \
  --ollama       http://127.0.0.1:11434 \
  --model        qwen2.5:3b-instruct-q4_K_M
```

Writes `bench/results-<ts>.jsonl` (raw per-event log) and
`bench/results-<ts>-summary.md` (medians, p95, per-prompt table).
Rate the 10 quality rows manually in `docs/quality-notes.md`.

## Tests

```bash
pytest -q
```

Covers router ordering, overload hysteresis, model-state cache (HOT/COLD/UNKNOWN + TTL),
SSE framing, bearer auth, YAML agents loader, and failover eligibility.

## HOT / COLD / UNKNOWN

- **HOT**  — model loaded in Ollama RAM (via `GET /api/ps`).
- **COLD** — model present on disk but not loaded.
- **UNKNOWN** — `/api/ps` is unreachable or timed out. Never silently promoted
  to HOT or COLD. Routing orders HOT > COLD > UNKNOWN; UNKNOWN is used only
  when it's the sole remaining option.

Force a cold run for benchmarks:

```bash
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen2.5:3b-instruct-q4_K_M","keep_alive":0,"prompt":"","stream":false}'
# verify absent:
curl -s http://localhost:11434/api/ps | jq '.models'
```

## Overload policy

The Agent samples 1-minute load average every ~2s and uses hysteresis:

- Enter **OVERLOAD** when `load_avg_1m / cpu_cores > OVERLOAD_HIGH_PCT` (default 0.70).
- Exit **OVERLOAD** when `load_avg_1m / cpu_cores < OVERLOAD_LOW_PCT` (default 0.50).

In OVERLOAD the Agent returns `503 {"error":"agent_overloaded"}`, and
`/status.state` publishes `"OVERLOAD"` so the Dispatcher skips it without a round trip.

## Failover

- **Pre-stream** failure (connect error, 503 overload, 5xx before first token):
  try the next eligible Agent, up to `FAILOVER_MAX_ATTEMPTS`.
- **Mid-stream** failure (connection drops after tokens have flowed): no retry
  — the Chat Client receives an `error` SSE event with `where="mid_stream"`.
  Duplicate execution across Agents is deliberately avoided.
- An Agent becomes eligible again after one successful `/status` poll.

## Security — PoC-grade, not production

- Two static shared bearer tokens, loaded from env, never logged.
- `/health` on both services is unauthenticated and returns only `{"ok": true}`.
- Ollama binds to `127.0.0.1` on each worker; never exposed on the network.
- No TLS; no account system; no rotation. **Do not deploy this as-is.**

## Repository layout

```
spareai/
  common/     # shared Pydantic schemas, SSE helpers, bearer dep
  agent/      # Agent FastAPI app, Ollama client, model-state cache, overload FSM
  dispatcher/ # Dispatcher app, registry, poller, router, SSE proxy, Chat Client template
bench/        # bench driver + 10 quality prompts
tests/        # pytest suite
infra/        # Terraform for the 2× EC2 target
docs/         # quality-notes.md, presentation-source.md (later)
prompts/      # prompt pack + clarifications
```
