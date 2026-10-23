# SpareAI — Independent engineering review

Independent sanity pass against the Prompt #1 spec and the Prompt #9 review
checklist. Timebox: ~1 hour. **Findings only; no application code was
changed as part of this review.** Fixes landed outside this document are the
small Prompt #2–#5 contract alignments called out in the handoff summary.

## Executive summary

The PoC is in a demonstrable state. 29 pytest-collected tests pass on
Python 3.13 with the editable install. The HOT/COLD/UNKNOWN detection, overload
hysteresis, router ordering, and bearer-auth paths are each unit-tested and
correct against spec. The main demo-visible gaps are around the Dispatcher's
mid-stream handling (no explicit inactivity timeout wired to the SSE read
loop) and the fact that the Agent's `/status.in_flight_requests` is updated
without a corresponding "immediately-reject-after-OVERLOAD" check during a
race between pre-flight gate and real-time load spike. Neither is likely
visible in a 3–5 minute demo, so both are **Should fix if time permits**. The
Terraform/AWS story is minimal but correct for the two-node scenario.

## Tests executed

```
py -3.13 -m pytest -q
```

Result: **29 passed in 0.64 s** (final run after Prompt #2–#5 alignment).
Coverage spans: router eligibility, HOT>COLD>UNKNOWN ordering, in-flight and
load-norm tie-breaks, lexicographic `node_id` tie-break, overload hysteresis
state machine, model-state cache TTL + refresh + invalidate + UNKNOWN on
failure, bearer-auth happy and failure paths, YAML agents loader, SSE event
framing.

## Findings

Severity ladder: **Critical** (demo-blocking) → **High** (visible in demo) →
**Medium** → **Low**.

### C1 — None.

No demo-blocking defect was found. Routing, failover, and overload
behaviours match the spec at the resolution the demo exercises them.

### H1 — Dispatcher does not enforce `STREAM_INACTIVITY_TIMEOUT_S` on the token stream

- **Files:** `spareai/dispatcher/main.py:171-203`, `spareai/dispatcher/config.py` (field added as part of the Prompt #3 alignment).
- **What breaks:** if the upstream Agent accepts the request, emits no tokens,
  and holds the connection open, the Dispatcher waits up to
  `generate_read_timeout_s` (default 180 s / 600 s in `.env.example`) before
  giving up. There is no per-chunk idle timeout on `resp.aiter_lines()`.
- **Realistic failure scenario:** Ollama hangs on an unusually heavy prompt
  mid-stream; the live demo's "overload" step is more likely to look like a
  dead browser tab than a controlled error.
- **Smallest fix:** wrap the per-line read in `asyncio.wait_for(..., stream_inactivity_timeout_s)`
  and on `TimeoutError` emit `event: error` with code `stream_inactivity_timeout`
  and return.
- **Tag:** **Should fix if time permits.**

### H2 — `in_flight_requests` not checked in overload decision

- **Files:** `spareai/agent/main.py:122-127`, `spareai/agent/overload.py`.
- **What breaks:** the Agent gates `/generate` on `overload.state == "OVERLOAD"`
  only. If the sampler hasn't ticked recently (`OVERLOAD_SAMPLE_INTERVAL_S`
  default 2 s), the Agent may accept a request from a host already past the
  high-water mark. The next tick will catch it, but the current request is
  already in flight.
- **Realistic failure scenario:** rare in the demo; relevant if the stated
  invariant "don't disturb primary workloads" is pushed on.
- **Smallest fix:** either (a) re-sample on `/generate` entry (adds a sync
  `cpu_percent` call), or (b) also return 503 when `in_flight_requests >= 1`
  AND recent `load_avg_1m / cpu_cores` is above `OVERLOAD_LOW_PCT`. Prefer (a)
  for simplicity.
- **Tag:** **Should fix if time permits.**

### M1 — Agent SSE `token` event uses `chunk` field name; spec says `content`

- **File:** `spareai/agent/main.py:159` emits `{"chunk": piece, ...}`.
- **Spec:** Prompt #2 §Streaming calls the field `content`.
- **What breaks:** nothing in the current pipeline — the Dispatcher doesn't
  parse the field, and the Chat Client reads `payload.chunk`. External
  consumers that followed the spec would see empty tokens.
- **Smallest fix:** rename to `content` across Agent, Chat Client, and the two
  bench clients in `bench/run_bench.py`.
- **Tag:** **Should fix if time permits** (not demo-visible).

### M2 — Dispatcher endpoint names diverge from Prompt #3 spec

- **Spec names:** `GET /status`, `POST /generate`.
- **Code names:** `GET /agents`, `POST /chat`.
- **What breaks:** nothing functional. External pentesters/reviewers who
  diff the spec against the running endpoints will flag this.
- **Smallest fix:** add aliases (`@app.get("/status")` → delegate to
  `/agents`; `@app.post("/generate")` → delegate to `/chat`). Keep the current
  names as the primary route to avoid breaking the Chat Client and bench.
- **Tag:** **Should fix if time permits.**

### M3 — Agent `/status.in_flight_requests` is counted post-overload gate

- **File:** `spareai/agent/main.py:122-140`.
- **What breaks:** when `/generate` is rejected with 503, the in-flight counter
  is not incremented; good. When it accepts, the counter is incremented before
  the Ollama round-trip. If the handler coroutine is cancelled mid-stream the
  `finally` branch always runs and the counter is restored. So this is likely
  fine — flagging for completeness because the counter is a load-shedding
  signal and small lag windows exist (between `inc_in_flight` and the next
  `/status` poll).
- **Tag:** **Future work.**

### M4 — `.env.example` ships tokens that look real

- **File:** `.env.example` contains `AGENT_TOKEN=changeme-agent-dev-only` and
  `CLIENT_TOKEN=changeme-client-dev-only`.
- **What breaks:** these values are now explicitly rejected by the placeholder
  guards added to `AgentConfig.from_env` and `DispatcherConfig.from_env`, so
  the system refuses to start with them — safe. But a reader may copy the
  file and spend 60 s wondering why. Add a comment line.
- **Smallest fix:** prefix with `# Replace both tokens before running.` and
  change the strings to obviously-placeholder tokens (`REPLACE_ME` style).
- **Tag:** **Should fix if time permits.**

### L1 — `OllamaClient.list_running` uses a 1 s timeout, hard-coded

- **File:** `spareai/agent/ollama.py:25-28`.
- **What breaks:** nothing. 1 s is reasonable; just not configurable.
- **Tag:** **Future work.**

### L2 — `sse_end()` emits a non-standard `event: end` sentinel

- **File:** `spareai/common/sse.py:14`.
- **What breaks:** not part of the SSE spec; browsers ignore unknown events,
  which is correct behaviour, but third-party SSE clients may complain.
- **Tag:** **Future work.**

### L3 — Dispatcher cannot invalidate a stale status after `503 agent_overloaded` without a poll

- **File:** `spareai/dispatcher/main.py:148-151`.
- **What breaks:** per Prompt #3 "optimistically mark the Agent OVERLOAD in
  the local cache; the next status poll corrects it." The code just moves to
  the next candidate without the optimistic mark, so a very-fast burst of
  requests may each hit the already-overloaded Agent first, bounce, and
  failover. Latency cost per failed candidate: one connect + headers.
- **Smallest fix:** on 503, mutate `e.last_status.state = "OVERLOAD"` in the
  Dispatcher's local cache.
- **Tag:** **Should fix if time permits.**

### L4 — Bench script lives in `bench/run_bench.py`, spec requested `scripts/bench.py`

- **Files:** `bench/run_bench.py`.
- **What breaks:** nothing functional. `python -m bench.run_bench` still works.
- **Tag:** **Future work.**

## Review-area coverage summary

| Prompt #9 area                              | Finding                 | Verdict                        |
|---------------------------------------------|-------------------------|--------------------------------|
| 1. Architecture boundaries                   | No cross-boundary call  | OK                             |
| 2. HOT/COLD/UNKNOWN                          | Tag-match verified      | OK                             |
| 3. Routing                                   | Full tuple ordering     | OK                             |
| 4. Timeouts + retries                        | H1                      | Should fix                     |
| 5. Workload protection                       | H2, M3                  | Should fix                     |
| 6. Measurement validity                      | Monotonic + Ollama tags | OK                             |
| 7. Security (PoC-grade)                      | Placeholder guards added, 401 does not disclose | OK |
| 8. AWS deployment readiness                  | SG self-ref, chmod 400, `.gitignored` key, cost called out | OK |
| 9. Operational simplicity                    | `pip install -e ".[dev]"` + 3 shells | OK                   |
| 10. Presentation integrity                   | Every claim traces to code or doc; numeric cells left as `<fill>` | OK |

## Items explicitly deferred

- Automated test for mid-stream failure not retrying. Encoded in code
  (`first_token_seen` flag), but no fixture simulates it. Manual coverage in
  `docs/failure-playbook.md`.
- Automated test for `STREAM_INACTIVITY_TIMEOUT_S`. Pending H1.
- Automated test for recovery after a successful poll following failures.
- Chat Client UI tests. Prompt #4 made these optional.

---

## Prioritized action list

### Must fix before demo

- None.

### Should fix if time permits

- **H1** — wire `stream_inactivity_timeout_s` into the Dispatcher's `aiter_lines` loop. (`spareai/dispatcher/main.py:171-203`)
- **H2** — sample `cpu_percent` on `/generate` entry and reject on fresh overload. (`spareai/agent/main.py:122-127`)
- **L3** — optimistically mark 503-ed Agent as OVERLOAD in the Dispatcher cache. (`spareai/dispatcher/main.py:148-151`)
- **M1** — rename SSE `chunk` → `content` on the token event. (`spareai/agent/main.py:159`, `bench/run_bench.py`, `spareai/dispatcher/templates/index.html`)
- **M2** — add `/status` and `/generate` aliases on the Dispatcher. (`spareai/dispatcher/main.py`)
- **M4** — tweak `.env.example` tokens so no one is tempted to run with them. (`.env.example`)

### Future work

- **M3** — tighten in-flight accounting around the Agent's overload gate.
- **L1** — expose `list_running` timeout as a config.
- **L2** — drop the non-standard `event: end` sentinel.
- **L4** — move the bench entrypoint to `scripts/bench.py` (or alias both).
- Fixture-based tests for the mid-stream and inactivity scenarios.
