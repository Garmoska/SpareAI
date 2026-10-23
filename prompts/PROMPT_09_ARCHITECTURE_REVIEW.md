# Prompt #9 — Independent Engineering Review

Act as an independent senior engineer reviewing **SpareAI**. Presentation in 2 days — this review is a sanity pass, not an audit. Timebox to ~1 hour. Produce findings only; do not change application code.

## Goal
Find material correctness, reliability, security, and scope problems that would be visible or embarrassing during the live demo. Prioritize demo-blocking issues.

## Review areas
1. **Architecture boundaries** — Chat Client → Central Dispatcher → Agent → local Ollama. Does the Dispatcher ever call Ollama directly? Does the browser ever call Agents directly? Is Ollama bound to `127.0.0.1` on each worker?
2. **HOT / COLD / UNKNOWN detection** — does the Agent treat `/api/ps` failure as `UNKNOWN`, not silently as HOT or COLD? Is the cache TTL honored? Is the model name compared with the full tag (including quant)?
3. **Routing correctness** — HOT preference, UNKNOWN handling, in-flight tie-break, load tie-break, deterministic lex tie-break. Are stale statuses actually excluded?
4. **Timeouts and retries** — bounded by `MAX_ROUTING_ATTEMPTS`; no retry after streaming has started; inactivity timeout distinct from total request timeout. Does any code path silently retry mid-stream?
5. **Workload protection** — does the overload policy actually protect host workloads, or only cap LLM concurrency? Is the hysteresis implemented (no flapping)? Are thresholds reasonable PoC defaults or arbitrary magic numbers?
6. **Measurement validity** — TTFT definitions correct and distinct from end-to-end latency; monotonic clocks for durations; Ollama-reported vs SpareAI-measured labeled; sample counts recorded; cold-run cold-state actually verified via `/api/ps` before timing.
7. **Security (PoC-grade)** — `AGENT_TOKEN` and `CLIENT_TOKEN` never logged; 401 responses don't leak which token was wrong; `/health` returns only liveness; prompts never logged; Ollama bound to `127.0.0.1` on each worker; the Dispatcher's `GET /` injects `CLIENT_TOKEN` into the HTML server-side rather than exposing it as a URL parameter.
8. **AWS deployment readiness** — Terraform in `infra/` is minimal and correct: security group restricts SSH + Dispatcher 8080 to the user's IP; Agent 8081 is only reachable via SG self-reference (not public); Ollama bound to `127.0.0.1`; private key file in `infra/spareai-key.pem` with chmod 400 and `.gitignored`; no credentials in state. Process start order on each instance; cleanup via `terraform destroy` / `aws ec2 stop-instances` is documented; cost-of-leaving-running is called out.
9. **Operational simplicity** — one `pip install -r requirements.txt`, clear start commands, deterministic ports, logs on stdout, no hidden state files.
10. **Presentation integrity** — every claim in `docs/presentation-source.md` traces to code, test, demo step, benchmark file, or `docs/quality-notes.md`.

## Review method
- Read code and docs first; form opinions after.
- Run existing tests. Report what you ran and what passed/failed.
- Do not run destructive operations. Do not expose services publicly during the review.
- Distinguish confirmed defects from risks, trade-offs, and future enhancements.
- The stack is pinned (Python + FastAPI + plain HTML/JS). Do not propose stack rewrites.
- Do not propose large architectural changes with 2 days left.

## Output
Create `docs/engineering-review.md` with:
- Executive summary (3–5 sentences).
- Findings ordered by severity: `Critical` (demo-blocking), `High` (visible in demo), `Medium`, `Low`.
- Per finding: file path(s), line reference, what breaks, realistic failure scenario, smallest recommended fix.
- Each finding tagged **Must fix before demo** / **Should fix if time permits** / **Future work**.
- Tests actually executed and their results.
- Items explicitly deferred.

End with a tight prioritized action list:
- **Must fix before demo** (bullets with file paths).
- **Should fix if time permits**.
- **Future work**.

Do not silently change application code during the review. Report first; wait for approval before implementing fixes.
