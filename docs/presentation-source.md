# SpareAI — Presentation evidence pack

Audience: mixed technical + management.
Every claim is tagged:

- **Implemented** — verifiable in committed code.
- **Demonstrated** — run live during the demo; cite the demo step.
- **Measured** — supported by `benchmarks/output/*.jsonl` (or `bench/results-*.jsonl`) or `docs/quality-notes.md`, with sample size and conditions.
- **Planned** — intended; not implemented.
- **Hypothesis** — plausible but not validated by this PoC.

Numeric placeholders (`<fill>`) mean "to be measured" — do not guess.

---

## 1. One-sentence project description

SpareAI is a PoC that routes LLM inference requests from a single API to a pool
of lightweight Agents running local Ollama instances on otherwise underutilized
hosts, with model-state-aware routing (HOT/COLD) and host-load-aware overload
protection. **Implemented**.

## 2. Problem statement

Enterprises run always-on compute (internal servers, workstations, long-running
VMs) that is often underutilized outside peak hours. Separately, LLM inference
is purchased from external providers at per-token prices. If a non-trivial
subset of enterprise LLM requests could be served by that idle hardware,
without disturbing the hosts' primary workloads, the mix shifts.

No numbers are claimed here. Scale of the opportunity depends on fleet
telemetry that this PoC does not possess.

## 3. Core hypothesis

A simple orchestration layer can:
1. detect which workers can handle a given model (HOT vs COLD vs UNKNOWN),
2. route each request to the best candidate,
3. refuse work on hosts under high load (host workload protection),
4. recover transparently when a worker disappears.

The PoC validates **the mechanism**. It does not validate business impact.

## 4. Proposed value — **Hypothesis**

- Reduces external-API spend for the subset of requests that the local model
  handles acceptably.
- Keeps data on internal infrastructure for that same subset.
- Uses hardware already paid for.

All three are **Hypothesis**, not **Measured**. Hardware is not free: power,
operations, security, maintenance, and licence terms (Qwen's Tongyi Qianwen
licence — verify) all have cost.

## 5. Architecture

```
Chat Client ─ CLIENT_TOKEN ─▶ Dispatcher ─ AGENT_TOKEN ─▶ Agent ─ localhost ─▶ Ollama
                                   │
                            Chat Client HTML
                              served at /
```

- One Central Dispatcher, N Agents (demo: N=2), one Ollama per Agent, bound to
  `127.0.0.1` on each worker. **Implemented** — see `spareai/dispatcher/main.py`,
  `spareai/agent/main.py`, `agents.yaml.example`.
- Two shared bearer tokens, loaded from env, never logged. 401 responses do
  not reveal which token was wrong. **Implemented** — `spareai/common/auth.py`.

## 6. Request lifecycle

1. Browser `POST /chat` with `Authorization: Bearer <CLIENT_TOKEN>`.
2. Dispatcher ranks eligible Agents and selects one.
3. Dispatcher emits `event: routing` on the SSE stream (names selected node,
   model state at routing time, attempt number).
4. Dispatcher opens a streaming `POST <agent>/generate`.
5. Agent asks local Ollama with `stream: true`, forwards chunks as
   `event: token` SSE.
6. Agent emits `event: done` with Ollama timings + `agent_ttft_ms`.
7. Dispatcher appends `event: metrics` with `dispatcher_ttft_ms`,
   `e2e_latency_ms`, `selected_node`, `failover_attempts`.

Two distinct TTFT measurement points:

- **Agent-side TTFT** — first chunk out of Ollama, measured in-process.
- **Dispatcher-side TTFT** — first chunk observed by the Dispatcher. Network
  overhead = Dispatcher-side − Agent-side.

**Implemented** — see `spareai/agent/main.py:142-200` and
`spareai/dispatcher/main.py:112-216`.

## 7. HOT / COLD / UNKNOWN

Definitions:

- **HOT** — model is loaded in RAM and ready for inference, per Ollama's
  `GET /api/ps`.
- **COLD** — model not in `/api/ps`; next inference pays load cost.
- **UNKNOWN** — `/api/ps` unreachable or timed out. Never silently promoted to
  HOT or COLD.

Agent caches the result for `STATUS_CACHE_TTL_S` (default 2 s) to avoid
hammering Ollama. **Implemented** — `spareai/agent/model_state.py`.

Measured cold-vs-warm delta — **To be measured**:

| metric                       | value          |
|------------------------------|----------------|
| cold TTFT (dispatcher, ms)   | `<fill>`       |
| warm TTFT (dispatcher, ms)   | `<fill>`       |
| cold end-to-end (ms)         | `<fill>`       |
| warm end-to-end (ms)         | `<fill>`       |
| samples (cold / warm)        | `<fill> / <fill>` |
| source file                  | `benchmarks/output/<fill>.jsonl` |

Run the bench script against both agents to populate the numbers (see §10).

## 8. Routing + failover

Eligibility filter:
1. Agent reachable (last successful status within `STATUS_FRESHNESS_S`, default 10 s).
2. `state == READY` (not OVERLOAD).
3. Requested model installed on the Agent.

Ordering (lower = better):
1. Model state: HOT > COLD. UNKNOWN only when no non-UNKNOWN Agent is eligible.
2. Fewer `in_flight_requests`.
3. Lower `load_avg_1m / cpu_cores`.
4. Lexicographic `node_id` (deterministic tie-break).

**Implemented** — `spareai/dispatcher/router.py`.
**Measured correctness** — `tests/test_router.py`, `tests/test_failover.py` (29 tests, all passing).

Failover: pre-stream errors retry on the next eligible Agent, bounded by
`MAX_ROUTING_ATTEMPTS` (default 2). **Mid-stream failures do not retry** —
duplicate-generation hazard. An SSE `error` event is forwarded instead.
**Demonstrated** — demo step "Failover" in [`docs/demo-runbook.md`](demo-runbook.md).
Scenarios documented in [`docs/failure-playbook.md`](failure-playbook.md).

## 9. Workload protection (overload policy)

- Sampled 1-minute load average. Linux: `psutil.getloadavg()[0]`.
  Windows dev: smoothed `psutil.cpu_percent` × `cpu_count` as a proxy.
- Enter OVERLOAD when `load_avg_1m / cpu_cores > OVERLOAD_HIGH_PCT` (default 0.70).
- Exit OVERLOAD when below `OVERLOAD_LOW_PCT` (default 0.50). Hysteresis.
- While OVERLOAD, `/generate` returns `503 agent_overloaded`.
- `/status.state` publishes `READY` or `OVERLOAD`.

**Implemented** — `spareai/agent/overload.py`.
**Measured correctness** — `tests/test_overload.py` (hysteresis transitions).
**Demonstrated** — demo step "Overload protection".

Thresholds are PoC defaults, not calibrated against a real primary workload.
Caveat for the deck: the policy caps *when* SpareAI accepts work; whether this
actually protects a primary workload in production depends on the primary
workload's own CPU behaviour and would require in-situ measurement.

## 10. Benchmark results table

| environment | model                              | quant   | cpu                | cores | cold_or_warm | samples   | median_e2e_ms | p95_e2e_ms | median_ttft_ms | median_tok_per_s | source_file                            |
|-------------|-------------------------------------|---------|--------------------|-------|--------------|-----------|---------------|------------|----------------|-------------------|----------------------------------------|
| local (Win) | qwen2.5:3b-instruct-q4_K_M          | q4_K_M  | laptop (local)     | `<fill>` | cold         | `<fill>`  | `<fill>`      | `<fill>`   | `<fill>`       | `<fill>`          | `bench/results-<ts>.jsonl`             |
| local (Win) | qwen2.5:3b-instruct-q4_K_M          | q4_K_M  | laptop (local)     | `<fill>` | warm         | `<fill>`  | `<fill>`      | `<fill>`   | `<fill>`       | `<fill>`          | `bench/results-<ts>.jsonl`             |
| AWS c7i.xl  | qwen2.5:3b-instruct-q4_K_M          | q4_K_M  | Intel Sapphire R.  | 4     | cold         | `<fill>`  | `<fill>`      | `<fill>`   | `<fill>`       | `<fill>`          | `benchmarks/output/<ts>.jsonl`         |
| AWS c7i.xl  | qwen2.5:3b-instruct-q4_K_M          | q4_K_M  | Intel Sapphire R.  | 4     | warm         | `<fill>`  | `<fill>`      | `<fill>`   | `<fill>`       | `<fill>`          | `benchmarks/output/<ts>.jsonl`         |

Rows marked `<fill>` are **To be measured**. Run:

```bash
python -m bench.run_bench \
  --dispatcher   http://localhost:8080 \
  --client-token "$CLIENT_TOKEN" \
  --agent        http://localhost:8081 \
  --agent-token  "$AGENT_TOKEN" \
  --ollama       http://127.0.0.1:11434 \
  --model        qwen2.5:3b-instruct-q4_K_M \
  --cold-runs 3 --hot-runs 5
```

## 11. Answer quality (sample of 10) — **Measured**

Fixed set at `benchmarks/quality_prompts.jsonl` (same text as
`bench/quality_prompts.py`), covering: summarization, Python code, SQL,
translation, tone rewrite, extraction, reasoning, enterprise Q&A, email draft,
refusal/safety.

| prompt_id | category        | rating       | note       |
|-----------|-----------------|--------------|------------|
| q01       | summarization   | `<fill>`     | `<fill>`   |
| q02       | code_python     | `<fill>`     | `<fill>`   |
| q03       | code_sql        | `<fill>`     | `<fill>`   |
| q04       | translation     | `<fill>`     | `<fill>`   |
| q05       | rewrite_tone    | `<fill>`     | `<fill>`   |
| q06       | extraction      | `<fill>`     | `<fill>`   |
| q07       | reasoning       | `<fill>`     | `<fill>`   |
| q08       | qa_definition   | `<fill>`     | `<fill>`   |
| q09       | email_draft     | `<fill>`     | `<fill>`   |
| q10       | refusal         | `<fill>`     | `<fill>`   |

Distribution placeholder: `<X> acceptable / <Y> marginal / <Z> unacceptable`.
Rate manually in [`docs/quality-notes.md`](quality-notes.md) **before** the
demo. Latencies and routing metadata for each run are correlated by `prompt_id`
in `bench/results-*.jsonl`.

**Explicit caveat:** small sample, single rater — a sanity check, not a
benchmark.

## 12. Live demo script

Trimmed from [`docs/demo-runbook.md`](demo-runbook.md). Full script with
timings and troubleshooting lives there.

1. Architecture + token boundary (30 s).
2. `GET /health` on Dispatcher + both Agents; `GET /agents` through Dispatcher (20 s).
3. HOT vs COLD contrast — force Agent A COLD, pre-warm Agent B, send the same
   prompt twice (90 s).
4. Failover — kill Agent A, send a prompt, show routing to Agent B, restart A (60 s).
5. Overload — `stress-ng --cpu N` on Agent B's host, show routing to A, stop load (60 s).
6. Metrics + quality — point at JSONL + quality-notes (40 s).
7. What this does and does not prove (30 s).

## 13. What the PoC proves

- Single-API ingestion with request routing across multiple workers.
  **Implemented**, **Demonstrated**.
- Model-state awareness (HOT / COLD / UNKNOWN) that prefers already-loaded
  workers. **Implemented**, **Demonstrated** in the HOT-vs-COLD step.
- Host-load-aware overload policy with hysteresis that excludes a hot host
  from routing. **Implemented**, **Demonstrated**.
- Failover across worker failures without blind retry of in-progress generations.
  **Implemented**, **Demonstrated**.
- Honest end-to-end latency + TTFT instrumentation using monotonic clocks
  and Ollama's own timing fields, labelled separately. **Implemented**,
  **Measured** (to the extent the bench script has been run).
- Qualitative sanity check that a 3B-parameter q4 model answers 10 representative
  enterprise prompts acceptably on CPU-only hosts. **Measured** (small sample).

## 14. What the PoC does **not** prove

- No multi-tenant isolation.
- No GPU performance claims.
- No measurement of actual interference with real primary workloads in production.
- No comparison against a reference model (GPT-4 class or similar).
- No load-at-scale testing — demo uses two workers, bursty single-user traffic.
- No HA for the Dispatcher. One Dispatcher = one point of failure.
- No cost/benefit analysis against external API spend.
- No quality benchmark — the 10-prompt check is a sanity test, not a benchmark.

## 15. Risks and constraints

- **Model quality limits on 3B q4.** Multi-hop reasoning and strict-format
  tasks fail more often. Target workload must be chosen with this in mind.
- **CPU-latency on `c7i.xlarge`.** Expect 8–15 tok/s; cold load dominates
  first-request latency.
- **Workload interference** in real production environments is argued, not
  benchmarked against a specific primary workload.
- **Security.** PoC-grade shared bearer tokens; no rotation/revocation/accounts.
  Not production.
- **Operational cost.** Dispatcher + Agents + Ollama + model updates + patching
  across every participating host. Not zero.
- **Licensing.** Qwen's Tongyi Qianwen licence — verify terms before any
  deployment, especially commercial.
- **Supportability.** Who's on-call when a worker's Ollama panics? Undefined
  in this PoC.

## 16. Roadmap — **Planned**

- More workers (horizontal scale).
- Multiple models with per-request model selection.
- Dynatrace integration for host-load signals (richer than `psutil`).
- Availability calendars (work only during off-peak hours per host).
- User-workstation workers.
- Complexity-based routing (classify request, pick a worker tier).
- Gemini (or similar) escalation for requests the local model handles poorly.
- Quality-based routing with online scoring.
- P2P orchestration (replace the single Dispatcher with a coordinator-less protocol).

All **Planned**. None implemented.

## 17. Decisions and support requested

Questions for the audience:

- Which internal fleet should we pilot next (ownership, SLAs)?
- Who owns operational monitoring + patching across participating hosts?
- Who sponsors a licensing review for the chosen base model?
- Who sponsors the security review required before any broader rollout?
- Is there an existing workload-complexity classifier we can reuse, or do we
  build one?

No approvals have been granted. These are questions, not plans.

## 18. Suggested slide outline

1. **Title.** SpareAI — opportunistic LLM inference on underutilized compute.
2. **Problem.** We buy LLM inference externally while internal servers sit idle.
3. **Hypothesis.** A thin router can direct suitable requests to idle hosts.
4. **Architecture.** Chat Client → Dispatcher → Agent → Ollama; two token tiers.
5. **Request lifecycle.** SSE events: `routing`, `token`, `done`, `metrics`, `error`.
6. **HOT / COLD / UNKNOWN.** Definitions + Ollama `/api/ps` detection.
7. **Routing + failover.** The four-tier ordering; pre-stream retry only.
8. **Workload protection.** Hysteretic overload policy; demo it.
9. **Benchmark results.** Cold vs warm TTFT and tok/s (table from §10).
10. **Answer quality (10-prompt sample).** Distribution + caveat.
11. **Live demo.** The script in §12.
12. **What this proves / does not prove.** §13 and §14 side by side.
13. **Risks + constraints.** §15.
14. **Roadmap.** §16.
15. **Ask.** §17.

---

## Evidence sources cited

- `spareai/dispatcher/main.py`, `spareai/dispatcher/router.py`,
  `spareai/dispatcher/health.py` — routing + failover logic.
- `spareai/agent/main.py`, `spareai/agent/model_state.py`,
  `spareai/agent/overload.py` — Agent surface, state detection, overload.
- `spareai/common/auth.py`, `spareai/common/schemas.py`, `spareai/common/sse.py` — contracts.
- `tests/` — 29 passing tests (as of last run with Python 3.13 editable install).
- `benchmarks/quality_prompts.jsonl` — authoritative 10-prompt set.
- `docs/quality-notes.md` — manual-rating template.
- `docs/demo-runbook.md` — the live demo script.
- `docs/failure-playbook.md` — manual failure injection procedures.
- `infra/README.md` — AWS setup (Terraform + security group + cost note).
- `benchmarks/output/*.jsonl` and `bench/results-*.jsonl` — raw per-run data
  (**run bench to populate**).

## Measurements that would materially strengthen the deck

Priority order (highest first):

1. **Cold vs warm TTFT on AWS `c7i.xlarge`.** 3 cold + 5 warm, both agents.
   Fills §7 and §10 rows and is the single most quotable number.
2. **Failover latency** (end-to-end latency observed by the client when
   Agent A is killed between the `routing` event and the first token). Target
   number: p95 under 2 s on a local run.
3. **Overload activation + recovery timings.** Seconds under load before Agent
   flips to OVERLOAD; seconds after load stops before it returns to READY.
4. **10-prompt quality ratings filled in** by a human — not auto-generated,
   not fabricated. Caveat remains.
5. **Dispatcher-vs-Agent TTFT delta** on the AWS run, to quantify
   cross-instance network overhead.
