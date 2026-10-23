# SpareAI — Claude Prompt Pack

Prompts for building SpareAI, a 2-day PoC that routes LLM inference across underutilized compute, using Claude as the implementation partner.

## Decisions and rationale
All design decisions are captured in [`clarifications.md`](./clarifications.md). Read it before running any prompt. Highlights:
- Target: on-prem HPE DL380 Gen10. Dev/test: Windows laptop + 1 small cloud VM.
- Model pinned: `qwen2.5:3b-instruct-q4_K_M`.
- Stack pinned: Python 3.11 + FastAPI + plain HTML/JS.
- Streaming (SSE) end-to-end so TTFT is honestly measurable.
- Shared bearer tokens: `CLIENT_TOKEN` (browser → Dispatcher), `AGENT_TOKEN` (Dispatcher → Agent).
- Load-average hysteresis for overload (70% / 50% × cores).
- 10-prompt human-rated quality sanity check.

## Order of use

1. **Prompt 1 — Architecture & Project Setup** (`prompt1.md`) — approve the design before implementation.
2. **Prompt 2 — Worker Agent** (`PROMPT_02_AGENT.md`) — implement the per-host Agent.
3. **Prompt 3 — Central Dispatcher** (`PROMPT_03_DISPATCHER.md`) — route requests + serve the Chat Client page.
4. **Prompt 4 — Chat Client** (`PROMPT_04_CHAT_CLIENT.md`) — polish the HTML page.
5. **Prompt 5 — Metrics and Benchmarking** (`PROMPT_05_METRICS.md`) — instrument and benchmark cold vs warm; capture the 10-prompt quality set.
6. **Prompt 6 — Failover and Resilience** (`PROMPT_06_FAILOVER_AND_RESILIENCE.md`) — validate failure handling, including overload demo.
7. **Prompt 7 — Demo Runbook** (`PROMPT_07_DEMO_RUNBOOK.md`) — produce the 3–5 minute live script.
8. **Prompt 8 — Presentation Source** (`PROMPT_08_PRESENTATION_SOURCE.md`) — evidence pack for the exec deck.
9. **Prompt 9 — Independent Engineering Review** (`PROMPT_09_ARCHITECTURE_REVIEW.md`) — findings-only sanity pass.

## Timeline
Presentation in 2 days. Every prompt is timeboxed; cut scope before extending time. The demo runbook (Prompt 7) and presentation source (Prompt 8) are the highest-priority non-implementation deliverables.

## Rules of engagement
- Use one prompt at a time in Claude, in the same project context.
- Review the proposed plan before allowing substantial changes.
- If Claude discovers that an approved contract conflicts with a later prompt, ask it to reconcile before implementation.
- Prompts 2–4 depend on shared contracts and files; do not run them in parallel.
- Prompts 5–7 can follow once the request path works.
- Prompt 8 is best after benchmark output and `docs/quality-notes.md` exist.
- Prompt 9 is a sanity check, not an audit.
- Every claim that lands in the exec presentation must be backed by code, a committed test result, a benchmark file, or `docs/quality-notes.md`.

## Scope reminder
- **Target: 2× AWS EC2 `c7i.xlarge` in `eu-central-1`** (revised 2026-10-23). Local Windows laptop is used first for debugging the full stack with Claude; AWS is used to prove cross-host dispatching and for the live demo. Terraform in `infra/` provisions the AWS environment.
- No Kubernetes, broker, database, or auth framework beyond shared bearer tokens.
- The headline exec claim is "underutilized compute, without disturbing primary workloads." The overload policy must demonstrably back that up during the live demo.
