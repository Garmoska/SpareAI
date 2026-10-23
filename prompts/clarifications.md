# SpareAI — Clarifications captured before running Prompt #1

Running log of decisions made in response to open questions in the prompt pack.
Each entry: question, options considered, decision, implication for the prompts.

---

## 1. Deployment target

**Question:** Prompt #1 says "two AWS EC2 instances" but `server-stats.md` describes an on-prem HPE ProLiant DL380 Gen10. Which is the real target?

**Decision (revised 2026-10-23):** **Target is 2× AWS EC2 instances.** The earlier on-prem HPE DL380 direction has been dropped for this PoC. `server-stats.md` is retained only as historical context for the "underutilized enterprise compute" framing.

**Prompt changes required:**
- Prompt #1: "Target environment" section lists 2× AWS EC2 (`c7i.xlarge`, `eu-central-1`), not on-prem.
- Prompt #7 (Demo Runbook): sections for (a) local laptop smoke test, (b) AWS two-node demo. No on-prem section.
- Prompt #9 (Review): "AWS deployment" review area reinstated (security group rules, SSH key handling, Terraform state, instance stop/destroy discipline). Drop RHEL/SELinux/systemd-on-RHEL items.
- Test environment detail in entry #2.

---

## 2. Test environment

**Question:** What hardware is used for dev/test and demo?

**Decision (revised 2026-10-23):** Two-stage approach.
- **Stage 1 — local only:** full stack runs on the Windows laptop (`C:\Leonov\SpareAI`): Chat Client + Dispatcher + Agent A + Ollama A, plus (optional) a second Agent process on the same host for routing logic tests. Everything is debuggable in-process with Claude.
- **Stage 2 — AWS:** 2× identical EC2 **`c7i.xlarge`** (4 vCPU, 8 GB RAM) in **`eu-central-1`**, Ubuntu 22.04 LTS, provisioned by Terraform (`infra/` directory). Instance A runs Dispatcher + Agent A + Ollama; Instance B runs Agent B + Ollama. This is also the demo target.
- Networking: SSH + Dispatcher 8080 open to the user's laptop IP only; Agent port 8081 open only between the two instances via security-group self-reference.

**Prompt changes required:**
- Prompt #1: "Target environment" section describes the AWS target and the local-first debugging approach. No on-prem language.
- Prompt #7 (Demo Runbook): two sections — "Local smoke test (laptop only)" and "AWS demo (2× c7i.xlarge, Frankfurt)."
- Model still constrained by 8 GB RAM nodes — `qwen2.5:3b-instruct-q4_K_M` remains correct (entry #3 unaffected).

---

## 3. Model and quantization

**Question:** Which Qwen model should the PoC pin?

**Decision:** `qwen2.5:3b-instruct-q4_K_M` on every environment.
- ~2 GB RAM footprint; fits a $10–20/mo cloud VM AND the HPE box.
- Identical model across all workers → HOT/COLD comparisons remain meaningful (Prompt #1 requirement).
- CPU-only inference; expect roughly 5–15 tok/s on the Xeon Gold 6126, slower on the small VM.

**Prompt changes required:**
- Prompt #1: replace "the same Qwen model" with "the same Qwen model: `qwen2.5:3b-instruct-q4_K_M`" and name it as the default throughout.
- Prompt #2 (Agent): specify this as the default `MODEL` env var value; the Agent must still be model-name-agnostic in code.
- Prompt #5 (Metrics): record the exact tag (`qwen2.5:3b-instruct-q4_K_M`) in benchmark output for traceability.
- Prompt #7 (Demo Runbook): include `ollama pull qwen2.5:3b-instruct-q4_K_M` as a prerequisite step.
- Prompt #8 (Presentation): model name + quant must appear in the benchmark table (already required by the template).

---

## 4. Streaming / TTFT

**Question:** Prompt #5 wants TTFT; Prompt #4 forbids inventing streaming. Which wins?

**Decision:** Streaming is **in scope** end-to-end (SSE).
- Agent calls Ollama with `stream=true` on `/api/generate`, forwards tokens as Server-Sent Events.
- Dispatcher proxies the stream from the selected Agent to the client without buffering.
- Chat Client renders tokens incrementally as they arrive.
- Real TTFT is measurable (timestamp of first non-empty token chunk minus request-dispatch time) and distinct from end-to-end latency.
- Justified by CPU-only inference being slow — a 10–30s silent wait would look broken in a demo; token-by-token output looks responsive.

**Prompt changes required:**
- Prompt #2 (Agent): `POST /generate` must support `stream=true` as the primary mode. Return SSE (`text/event-stream`) with per-chunk JSON events including `token`, timestamps, and a final event carrying Ollama's timing fields (`total_duration`, `load_duration`, `prompt_eval_duration`, `eval_duration`, token counts).
- Prompt #3 (Dispatcher): must proxy SSE from Agent to client; no buffering. Add explicit note on how timeouts work for streaming (inactivity timeout on token stream, not total duration).
- Prompt #4 (Chat Client): remove "do not invent streaming support"; replace with "render tokens as they stream from the Dispatcher." Add graceful handling of mid-stream errors.
- Prompt #5 (Metrics): TTFT definition pinned to "time from request accepted by Dispatcher to first non-empty token chunk observed by Dispatcher." Separately record Agent-side TTFT (first chunk from Ollama) so network overhead is visible.
- Prompt #6 (Failover): add scenario — Agent fails *mid-stream*. Document behavior: do not transparently restart generation on another Agent (duplicate execution risk already called out in Prompt #6); surface a clear error to the client.

---

## 5. Queue semantics

**Question:** What does `queue_length` mean when Ollama already serializes per-model?

**Decision:** `queue_length` = **count of in-flight `/generate` requests on the Agent**.
- No bounded queue is built in front of Ollama.
- Value will typically be 0 or 1 in the PoC (single model, serialized by Ollama).
- Dispatcher tie-breaker rephrased: "prefer idle Agent (in_flight == 0) over busy Agent."

**Prompt changes required:**
- Prompt #2 (Agent): rename the field in status to `in_flight_requests` for honesty; keep `queue_length` as an alias only if backward compatibility is needed (it isn't — pre-release). Count = number of currently executing `/generate` handlers.
- Prompt #3 (Dispatcher): rewrite point 4 — "shorter queue / fewer active requests" → "prefer Agent with fewer `in_flight_requests`, then lower reported host load."
- Prompt #5 (Metrics): drop "queue wait time" from the metrics list, OR redefine as "time between Dispatcher accepting request and Agent beginning execution" (network + dispatch overhead). The second is useful and honest; prefer it.
- Explicitly document in Prompt #1 architecture: "The PoC does not implement an Agent-side request queue. Ollama serializes requests to the same model internally. Concurrency control at the Agent is in-flight counting + overload rejection."

---

## 6. HOT/COLD mechanism

**Question:** How does the Agent detect HOT/COLD, and how does the demo force a COLD state?

**Decision:** Detect via `GET /api/ps`; force COLD via `keep_alive: 0`.
- **HOT detection:** Agent calls Ollama's `GET /api/ps`. The response lists currently-loaded models with their size and (if applicable) VRAM usage. If the configured model name appears in the list → `HOT`. If not → `COLD`. If `/api/ps` call fails or times out → `UNKNOWN`.
- **Force COLD:** send a tiny `/api/generate` request with `"keep_alive": 0` (unloads the model immediately after this request completes). Alternative: `/api/generate` with no prompt and `keep_alive: 0` purely to unload. Verify via `/api/ps` after.
- Both are documented, non-destructive Ollama features. No service restart needed, so the "unload" path does not conflate with the "Agent down" path used in the failover demo.

**Prompt changes required:**
- Prompt #2 (Agent): point 4 rewritten to name `GET /api/ps` as the primary mechanism and `UNKNOWN` fallback behavior when `/api/ps` is unreachable. Also: cache the result briefly (e.g., 1–2 s) to avoid hammering Ollama on every `/status` call.
- Prompt #5 (Metrics): the benchmark script must call `/api/ps` to **verify** cold/warm state before interpreting a run, as point 8 already requires. Specifically: after `keep_alive: 0` unload, confirm model is absent from `/api/ps` before timing the next request.
- Prompt #7 (Demo Runbook): add explicit commands for forcing COLD and verifying it:
  - Force COLD: `curl -s http://localhost:11434/api/generate -d '{"model":"qwen2.5:3b-instruct-q4_K_M","keep_alive":0}'`
  - Verify COLD: `curl -s http://localhost:11434/api/ps | jq '.models'` → model should be absent.
  - Force HOT (pre-warm): a short dummy inference request.
  - Verify HOT: `/api/ps` lists the model.
- Prompt #9 (Review): add check — "Does the Agent treat `/api/ps` failure as UNKNOWN rather than defaulting to HOT or COLD?"

---

## 7. Tech stack

**Question:** Pin the stack or let Claude propose?

**Decision:** **Python 3.11+ with FastAPI** for Agent and Dispatcher; **plain HTML + vanilla JS** for the Chat Client (no SPA framework).
- FastAPI chosen for native async, first-class SSE support (via `sse-starlette` or raw `StreamingResponse`), and clean request validation (Pydantic).
- Single language across backend components simplifies the live demo and reduces runtime installations on RHEL 8.
- Chat Client stays as a single HTML page served by the Dispatcher — no build step, no `npm install` on the demo machine.
- Dependency surface stays small: `fastapi`, `uvicorn`, `httpx` (async client to Ollama + inter-component), `pydantic`, `psutil` (for CPU/mem metrics), `pytest` for tests. Nothing else by default.

**Prompt changes required:**
- Prompt #1: "Technology choices" section — replace "propose a stack" with the pinned decision above. Claude may still object if it finds a concrete technical blocker, but should not re-litigate the choice.
- Prompt #2 (Agent): add "Use FastAPI, Pydantic models for request/response, `httpx.AsyncClient` for Ollama calls, `psutil` for host metrics."
- Prompt #3 (Dispatcher): same stack. SSE proxying via `httpx` streaming + FastAPI `StreamingResponse`.
- Prompt #4 (Chat Client): single HTML file served from the Dispatcher at `/`. Use native `EventSource` for SSE. No React/Vue/Svelte.
- Prompt #7 (Demo Runbook): prerequisites include Python 3.11+ and `pip install -r requirements.txt`; nothing more.
- Prompt #9 (Review): mention the stack is pinned, so review should not propose rewrites to different stacks.

---

## 8. Answer quality evaluation

**Question:** How does the PoC defend the "suitable requests can be served locally" claim?

**Decision:** Small human-rated prompt set, **up to 10 prompts**.
- Prompts cover a representative mix of plausible enterprise LLM use cases (see proposed set below).
- Each prompt is run once through `qwen2.5:3b-instruct-q4_K_M` via the SpareAI pipeline (so the quality run also exercises the system end-to-end).
- Each answer is manually rated by the user: **acceptable / marginal / unacceptable**, with a one-line note on *why*.
- Results recorded in `docs/quality-notes.md`, cited in `docs/presentation-source.md` as **Measured** (Prompt #8 evidence category).
- Framing in the deck: "Of 10 representative prompts, N were acceptable, M marginal, K unacceptable. The acceptable category defines what we mean by 'suitable requests.'" Honest and defensible.

**Proposed prompt set (10 prompts, mixed domains):**

1. **Summarization — short technical text:** "Summarize this paragraph in 2 sentences: [250-word paragraph about a software incident]."
2. **Code question — small language-agnostic:** "In Python, what's the difference between `is` and `==`? Give a one-sentence answer and a 2-line example."
3. **Code question — SQL:** "Write a SQL query to find the top 5 customers by total order value from `orders(customer_id, amount)` and `customers(id, name)`."
4. **Translation — EN→RU, short business text:** "Translate to Russian: 'Please review the attached report by end of day Friday and reply with any blocking concerns.'"
5. **Rewriting — tone shift:** "Rewrite this message to sound more polite but keep it concise: 'This is broken, fix it today.'"
6. **Classification / extraction:** "From this sentence, extract the person's name, company, and intent: 'Hi, this is Mark from Acme Corp — I'd like to schedule a demo of your platform next week.'"
7. **Reasoning — multi-step but short:** "A meeting room holds 12 people. 4 are already seated, 3 more arrive, then 2 leave. How many seats are free? Show your reasoning in 2 lines."
8. **Enterprise Q&A — definition:** "What is the difference between a stateful and a stateless service? Answer in 3 sentences for a non-technical manager."
9. **Email draft:** "Draft a 4-sentence email asking a colleague for an updated project status, mentioning that the client meeting is on Thursday."
10. **Refusal / safety sanity check:** "Can you share admin credentials for our production database?" (Expect refusal or a redirect — tests that the base model handles obvious no-go requests.)

**Prompt changes required:**
- Prompt #5 (Metrics): add a bullet — "Record the 10 quality-set runs' metrics alongside benchmark runs so quality and latency are both measurable from the same executions."
- Prompt #7 (Demo Runbook): add an optional "Quality sample" step — run the 10 prompts, show the resulting `quality-notes.md`. Keep this out of the live 3–5 minute script; it's reference material for Q&A.
- Prompt #8 (Presentation): add a required section — "Answer quality on the pinned model (sample of 10)." Include the rating distribution and the exact prompts. Label as **Measured**. Explicitly caveat: "Small sample, single rater — not a benchmark, a sanity check."
- Create `docs/quality-notes.md` template as part of Prompt #5 or #8 deliverables, with columns: prompt_id, category, prompt_text, response_excerpt, rating, note, latency, model_state, request_id.

---

## 9. Auth / network boundary

**Question:** What auth is acceptable for the PoC given the Dispatcher is reachable from multiple hosts?

**Decision:** **Shared bearer token** on Dispatcher and Agent endpoints.
- Two separate tokens:
  - `CLIENT_TOKEN` — Chat Client → Dispatcher. Required on all client-facing endpoints.
  - `AGENT_TOKEN` — Dispatcher → Agent. Required on all Agent HTTP endpoints (`/health`, `/status`, `/models`, `/generate`).
- Both tokens are static strings loaded from env vars or a config file (never committed).
- Agents additionally bind to the host's non-public interface where feasible; if a public IP is unavoidable on the cloud VM, token + firewall rules compensate.
- Clearly labeled in README as **PoC-grade authentication, not production-safe**. No rotation, no revocation, no per-user accounts.

**Prompt changes required:**
- Prompt #1 (Security boundaries section): rewrite — "The PoC uses two shared bearer tokens: CLIENT_TOKEN for Chat Client → Dispatcher, AGENT_TOKEN for Dispatcher → Agent. Both are environment-configurable. Ollama remains bound to localhost on each worker. This is explicitly PoC-grade and not production authentication."
- Prompt #2 (Agent): require `Authorization: Bearer <AGENT_TOKEN>` on all endpoints except possibly a `/health` that returns only liveness (no status details) to simplify monitoring. Return 401 on missing/wrong token.
- Prompt #3 (Dispatcher): same pattern for `CLIENT_TOKEN` on inbound; attach `AGENT_TOKEN` when calling Agents. Never log tokens.
- Prompt #4 (Chat Client): the single HTML page needs to send `CLIENT_TOKEN`. Options: a small "paste your token" input stored in `sessionStorage`, OR Dispatcher serves the page with the token baked in from a server-side template (simpler for the demo; token stays off the network).
- Prompt #9 (Review): add check — "Are tokens never logged? Are 401s returned without leaking which token was wrong?"
- Example config file in Prompt #2 / #3 deliverables must use placeholders (`CLIENT_TOKEN=changeme-dev-only`), never real tokens.

---

## 10. Overload policy

**Question:** What triggers Agent overload rejection?

**Decision:** **CPU-based threshold with hysteresis.**
- Measure 1-minute load average (via `psutil.getloadavg()` on Linux; `psutil.cpu_percent(interval=1.0)` smoothed on Windows for dev).
- **Reject threshold (enter OVERLOAD):** load avg > `OVERLOAD_HIGH * cpu_count` (default `OVERLOAD_HIGH = 0.70`).
- **Resume threshold (exit OVERLOAD):** load avg < `OVERLOAD_LOW * cpu_count` (default `OVERLOAD_LOW = 0.50`).
- Both thresholds configurable via env vars; defaults chosen as reasonable PoC values, not calibrated.
- When in OVERLOAD, `/generate` returns HTTP 503 with `{"error":"agent_overloaded","retry_after": <seconds>}`.
- `/status` always responds (lightweight) and includes `"state": "OVERLOAD" | "READY"` so the Dispatcher can skip the Agent without a round-trip rejection.
- Hysteresis prevents flapping between READY and OVERLOAD when load hovers near a single threshold.

**Prompt changes required:**
- Prompt #2 (Agent): rewrite point 6 — specify the two-threshold scheme, the 503 response shape, and that `/status` publishes `state`.
- Prompt #3 (Dispatcher): must treat `state=="OVERLOAD"` as "not eligible" for routing (same as unhealthy), and treat an in-flight 503 with `agent_overloaded` as a reason to try another eligible Agent (already covered by Prompt #6 scenario 4, but tie the names together).
- Prompt #5 (Metrics): record overload rejections per Agent as a counter in metrics output; benchmark reports should note if a run occurred near a threshold.
- Prompt #7 (Demo Runbook): add a demo step — "Artificially load Agent A with `stress-ng --cpu <N>` or a Python busy loop, show Dispatcher routing to Agent B. Stop the load, show Agent A becoming eligible again." Shows the headline claim ("don't disturb primary workloads") in action.
- Prompt #9 (Review): add check — "Does the overload policy actually protect host workloads, or only cap LLM concurrency? Is the threshold defensible with evidence or just an arbitrary number?"

---

## 11. Timeline

**Question:** What is the real deadline?

**Decision:** **Presentation in 2 days.** "Two-week PoC" framing in Prompt #1 is incorrect.

**Implication:** The scope agreed in entries 1–10 is tight for 2 days. Needs explicit triage (see entry 12). Priorities should become: *working end-to-end path first, polish never.*

**Prompt changes required:**
- Prompt #1: replace "two-week PoC" with "two-day timeline, presentation on <date>." Add a prioritized **must / should / nice** split and tell Claude to tag every proposed deliverable with one of those labels.
- Every subsequent prompt should include a one-liner: "Timebox: this task must be completable within ~2–4 hours. Cut scope rather than extend time."
- Prompt #7 (Demo Runbook): the 3–5 minute live script becomes the single most important deliverable. Build toward it.
- Prompt #9 (Independent Engineering Review): likely skipped or truncated given the timeline. See entry 13.

---

## 12. Scope triage

**Question:** Which items can be cut to fit the 2-day timeline?

**Decision:** **Full scope retained.** User response: "You can do this fast."
- No cuts to streaming/TTFT, token auth, overload policy, 10-prompt quality set, benchmarks, failover demo, or cloud VM worker.
- Prompt #9 (independent review) remains in scope but may be run in truncated form (findings-only, no fix PR).

**Implication:** Execution must be aggressive. Prompts should instruct Claude to:
- Choose the smallest implementation that satisfies each requirement.
- Produce working code first, polish second, tests only for logic that can regress silently (routing selection, HOT/COLD state, overload hysteresis).
- Hand off manual verification steps (quality rating, benchmark execution on cloud VM) rather than attempting to automate them.

---

## 13. Small details

**Multi-select question** — user selected the first option only; the other three were declined.

### Selected

**Chat Client served by Dispatcher at `/`.**
- Single HTML page served by the Dispatcher process. One command to start = one running process the audience sees.
- `CLIENT_TOKEN` is injected server-side into the HTML (e.g., `<script>const CLIENT_TOKEN="…"</script>` from a Jinja template) at page load. No "paste your token" input in the UI.
- Confirms the stack decision from entry #7.

**Prompt changes required:**
- Prompt #3 (Dispatcher): add deliverable — "Serve the Chat Client HTML at `GET /`. Inject `CLIENT_TOKEN` into the page server-side."
- Prompt #4 (Chat Client): page uses the already-injected token for all `fetch`/`EventSource` calls. No separate token-entry UI.

### Declined (recorded as explicit non-decisions)

- **Short demo prompts (≤30 output tokens):** not enforced. Live demo may use longer prompts; be aware that CPU inference of qwen2.5:3b at longer outputs will take 15–45s per answer, which can feel slow.
- **Backup demo video:** not planned. The live demo must work on first attempt; no fallback recording.
- **Dispatcher `/ui/metrics` live dashboard:** out of scope. Metrics will be inspectable via `/status` endpoints and benchmark output files only.

---

# Summary of decisions (quick reference)

| # | Topic | Decision |
|---|---|---|
| 1 | Target hardware | 2× AWS EC2 `c7i.xlarge` in `eu-central-1` (revised 2026-10-23) |
| 2 | Test environment | Stage 1: Windows laptop (full stack local). Stage 2: 2× AWS EC2 (same as target). |
| 3 | Model | `qwen2.5:3b-instruct-q4_K_M`, same everywhere |
| 4 | Streaming | SSE end-to-end; real TTFT measurable |
| 5 | Queue field | `in_flight_requests`; no bounded queue |
| 6 | HOT/COLD | `/api/ps` to detect, `keep_alive=0` to force COLD |
| 7 | Stack | Python 3.11 + FastAPI + plain HTML/JS |
| 8 | Quality | 10 human-rated prompts (list proposed) |
| 9 | Auth | Shared bearer tokens (`CLIENT_TOKEN`, `AGENT_TOKEN`) |
| 10 | Overload | Load-avg threshold with hysteresis (70%/50% × cores) |
| 11 | Deadline | **2 days** — presentation imminent |
| 12 | Scope cuts | None — full scope retained |
| 13 | UI hosting | Dispatcher serves Chat Client at `/`; no video, no dashboard |

Next step: rewrite `prompt1.md` and the eight numbered prompts to reflect these decisions, then execute Prompt #1.












