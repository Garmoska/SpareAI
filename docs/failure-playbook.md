# SpareAI — Failure injection playbook

Manual procedures for the failover/resilience scenarios in Prompt #6. Each entry
lists the injection command, the expected observable behaviour, the log line to
watch for, and the restore command. Automated coverage of scenarios 1, 3, 4, 5,
7 is in `tests/test_router.py` + `tests/test_failover.py`.

## Shared setup

Terminals you need up before injecting any failure:

- Shell D: Dispatcher stdout (`python -m spareai.dispatcher.main`)
- Shell A: Agent A stdout
- Shell B: Agent B stdout
- Shell C: `curl -s -H "Authorization: Bearer $CLIENT_TOKEN" http://localhost:8080/agents | jq`
- Browser: Chat Client at `http://localhost:8080/`

Known-safe prompt for every scenario: `"In one sentence, what is 2+2?"`

---

## Scenario 1 — Baseline (healthy)

- **Precondition:** both Agents in `/agents` show `state=READY`, `reachable=true`,
  model `HOT` or `COLD` on at least one Agent.
- **Expected:** send a prompt → `routing` event names an Agent → tokens stream →
  `done` + `metrics` events arrive.
- **Automated:** `tests/test_router.py::test_eligibility_filters_unreachable`.

---

## Scenario 2 — Agent stops responding (staleness-based unavailability)

- **Inject (Windows, Agent B):** find the PID from the Agent's startup banner,
  then `taskkill /PID <pid> /F`.
- **Inject (Linux):** `kill <pid>` (prefer PID over `pkill python`).
- **Expected:** after `STATUS_FRESHNESS_S` (default 10 s) with no successful
  poll, `/agents` shows `reachable=false` for worker-02 and routing avoids it.
- **Log line (Dispatcher):** `agent worker-02 failed pre-stream: ConnectError`
  (if a request happens to arrive during the staleness window), or just silent
  pollster failures counted in `consecutive_failures`.
- **Restore:** restart the Agent process.
- **Automated:** staleness filter is covered by
  `tests/test_router.py::test_eligibility_filters_unreachable`; actual process
  death is manual.

---

## Scenario 3 — Pre-stream connect failure → failover

- **Inject (Windows):** block the Agent B port with a reversible firewall rule:
  ```powershell
  New-NetFirewallRule -DisplayName "spareai-block-8082" -Direction Inbound ^
    -LocalPort 8082 -Protocol TCP -Action Block
  ```
- **Inject (Linux):** `sudo iptables -I INPUT -p tcp --dport 8081 -j DROP`
- **Expected:** Dispatcher sees connect-timeout or RST on Agent B, retries
  Agent A, succeeds. `metrics` event lists `failover_attempts: ["worker-02"]`.
- **Log line (Dispatcher):** `agent worker-02 failed pre-stream: ReadTimeout`.
- **Restore (Windows):** `Remove-NetFirewallRule -DisplayName "spareai-block-8082"`
- **Restore (Linux):** `sudo iptables -D INPUT -p tcp --dport 8081 -j DROP`
- **Automated:** `tests/test_failover.py` covers the eligibility and ordering
  that drives the retry.

---

## Scenario 4 — `503 agent_overloaded` → failover

- **Inject:** force Agent B into OVERLOAD (see Scenario 10).
- **Expected:** first request to arrive while B is OVERLOAD is routed to A on
  the first attempt (B is skipped by the `state == READY` eligibility filter).
  If B's status is stale and the Dispatcher still tries it, the 503 response
  causes it to fall through to A.
- **Log line (Dispatcher):** `503` from worker-02 followed by routing to
  worker-01.
- **Restore:** stop the CPU load.

---

## Scenario 5 — All Agents ineligible

- **Inject:** kill both Agents, or block both ports.
- **Expected:** `/chat` returns `HTTP 503 {"error":"no_eligible_agent","model":...}`
  before any streaming starts. The Chat Client shows the error banner and
  surfaces a Retry affordance.
- **Restore:** restart Agents.

---

## Scenario 6 — Recovery

- **Inject:** kill Agent A. Confirm `/agents` marks it unreachable.
- **Expected:** after restarting, within one poll interval (default 3 s) it
  becomes `reachable=true` and the next request routes to it (or to whichever
  Agent now wins ordering).
- **Log line (Dispatcher):** poller succeeds; `consecutive_failures` resets to 0
  (visible in the next `/agents` snapshot via `last_error=null`).

---

## Scenario 7 — HOT vs COLD preference

- **Inject (Agent A — force COLD):**
  ```bash
  curl -s http://127.0.0.1:11434/api/generate \
    -d '{"model":"qwen2.5:3b-instruct-q4_K_M","keep_alive":0,"prompt":"","stream":false}'
  curl -s http://127.0.0.1:11434/api/ps | jq '.models'   # should NOT list the model
  ```
- **Inject (Agent B — force HOT):** send one short prompt via the Chat Client
  targeted at B (either stop A, or just send twice and let B win once), then
  verify `curl http://<B>/api/ps | jq`.
- **Expected:** next request `routing` event shows `node_id=worker-02` (HOT)
  with `model_state_at_routing=HOT`.
- **Automated:** `tests/test_failover.py::test_failover_candidate_list_order`.

---

## Scenario 8 — Mid-stream failure (no retry)

- **Inject:** after `routing` event is observed in the browser dev tools, kill
  Agent A on the host carrying the stream.
- **Expected:** Dispatcher emits an SSE `error` event (`where=mid_stream`) and
  closes the stream. **No `routing` event with another worker.** The browser
  marks the partial answer as interrupted and shows Retry.
- **Log line (Dispatcher):** `agent worker-01 failed pre-stream: ...` is NOT
  what you want to see here — look for the mid-stream warning path and the
  absence of a second `routing` event.
- **Automated:** behaviour is encoded in `spareai/dispatcher/main.py` — the
  `first_token_seen` flag gates retry; direct automated test is deferred (needs
  real streaming fixtures).

---

## Scenario 9 — Mid-stream inactivity timeout

- **Config:** `STREAM_INACTIVITY_TIMEOUT_S=5` (lower than default 60 for the
  demo, if you want to show it quickly).
- **Inject:** pause Ollama on Agent A (e.g., `taskkill` the `ollama.exe` process
  mid-generation; or `kill -STOP <pid>` on Linux).
- **Expected:** Dispatcher terminates the attempt and surfaces an SSE `error`
  event. No failover.
- **Restore (Linux):** `kill -CONT <pid>`; or restart Ollama on Windows.
- **Automated:** behaviour is deferred to manual verification; inactivity-timeout
  wiring is in `spareai/dispatcher/config.py` as `stream_inactivity_timeout_s`.

---

## Scenario 10 — Overload demo

- **Inject (Linux):** `stress-ng --cpu $(nproc) --timeout 60s`
- **Inject (Windows dev):**
  ```python
  # cpu_hog.py — run with: python cpu_hog.py 60
  import time, sys, multiprocessing
  def burn(end):
      while time.monotonic() < end:
          pass
  if __name__ == "__main__":
      secs = int(sys.argv[1])
      end = time.monotonic() + secs
      ps = [multiprocessing.Process(target=burn, args=(end,))
            for _ in range(multiprocessing.cpu_count())]
      for p in ps: p.start()
      for p in ps: p.join()
  ```
- **Expected:** Agent B's `/status` reports `state=OVERLOAD` within one or two
  `OVERLOAD_SAMPLE_INTERVAL_S` ticks. New requests route to Agent A. Stop the
  load — within another interval or two B returns to `READY` (hysteresis).
- **Automated:** hysteresis is unit-tested in `tests/test_overload.py`; the
  live demo is manual.

---

## Correctness rules (reminders)

- Dispatcher **must not** retry on another Agent after a token has been seen.
  Duplicate-generation hazard; verified by code inspection, not a test fixture.
- Prompt text is never logged. Only `request_id`, `node_id`, status codes.
- `AGENT_TOKEN` and `CLIENT_TOKEN` are never logged.

## Known limitations (not handled by the PoC)

- **Dispatcher failure.** The Dispatcher is a single point of failure. No HA, no
  checkpointing. If it dies mid-stream, all in-flight chats die with it.
- **Ollama disk full.** Not detected; manifests as model-load errors surfaced
  verbatim.
- **Network partitions between the Dispatcher and both Agents simultaneously.**
  Returns `no_eligible_agent` to clients; no graceful degradation.
- **Mid-stream resumption.** Explicitly not implemented. Users retry.
