# Prompt #6 — Validate Failover and Basic Resilience

You are hardening the **SpareAI** PoC enough to demonstrate basic worker failure handling reliably. Presentation in 2 days — timebox to ~2 hours.

## Goal
Prove that the Dispatcher avoids unhealthy or overloaded workers and can route a new request to another eligible Agent, without duplicate generation and without logging prompt text.

## Scenarios (tests + manual demo steps)
1. **Baseline** — one Agent healthy; requests route normally and complete.
2. **Agent stops responding** — Dispatcher marks it unavailable after `STATUS_FRESHNESS_S` elapses with no successful status poll. Confirm via the Dispatcher's `/status`.
3. **Connect failure on `/generate`** — Dispatcher tries the next eligible Agent (bounded by `MAX_ROUTING_ATTEMPTS`).
4. **503 `agent_overloaded`** — Dispatcher tries another eligible Agent. The failing Agent is marked OVERLOAD in the local cache optimistically; next status poll corrects it.
5. **All Agents ineligible** — client receives `503 no_eligible_agents` with a stable message.
6. **Recovery** — a previously-down Agent returns; after one successful status poll it becomes eligible again.
7. **HOT vs COLD** — one Agent HOT, one COLD, both READY; HOT is preferred (verifies the full routing rule end-to-end).
8. **Mid-stream failure** — Agent connection drops after the `routing` event and some tokens have been emitted. Dispatcher must **not** retry on another Agent. It must forward an `error` SSE event with a clear code and close the stream.
9. **Timeout mid-stream** — no tokens for `STREAM_INACTIVITY_TIMEOUT_S`. Dispatcher terminates the attempt and emits an `error` event. No retry.
10. **Overload demo** — induce real load on one Agent's host (`stress-ng --cpu 10 --timeout 60s` on Linux; equivalent Python busy loop on Windows for dev) and verify the Dispatcher routes to the other Agent while the first is OVERLOAD. Stop the load; verify return to READY.

## Correctness rules
- No blind retry after generation may have started. Document this behavior.
- Retry policy and timeouts configurable via env vars (see Prompt #3).
- Agent health is distinct from model readiness: a READY Agent may be COLD; HOT is a routing preference, not an eligibility gate.
- Never log prompt text in failure paths. Log structured fields: `request_id`, `selected_node`, `attempt`, `failure_category`, `retried` boolean.

## Failure-injection playbook (manual demo)
Document commands for each failure, on both the laptop host and the cloud VM:
- Kill the Agent process (`taskkill /IM python.exe /F` on Windows for the right PID, or `kill <pid>` on Linux — note that `python.exe` may match multiple processes; prefer PID).
- Block the port with a firewall rule you can revert (`netsh advfirewall` on Windows, `iptables` / `firewall-cmd` on Linux).
- Stop Ollama on one host (demonstrates COLD recovery when restarted).
- Load the CPU to trigger OVERLOAD (`stress-ng` on Linux; tiny Python busy loop on Windows).
- Restore each above.

Each entry includes: expected observable behavior in the Chat Client, expected log line to look for, and the restore command.

## Tests
Add unit/integration tests for scenarios 1, 3, 4, 5, 7, 8, 9 at minimum. Scenarios 2, 6, 10 are easier to demo manually; include manual steps for them in `docs/failure-playbook.md`. Report which tests you actually ran and their results.

## Deliverables
- Targeted code changes only.
- Updated tests + results.
- `docs/failure-playbook.md` with the manual injection commands and expected behavior per scenario.
- Known-limitations section listing anything explicitly not handled (e.g., Dispatcher failure, Ollama disk full, network partitions).

## Workflow
Review current timeouts and retry semantics. Make the smallest changes needed to pass the scenarios. Avoid unrelated refactoring.
