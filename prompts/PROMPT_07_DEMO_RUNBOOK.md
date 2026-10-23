# Prompt #7 — Create a Repeatable Live Demo Runbook

You are preparing the live demonstration of **SpareAI**. Presentation in 2 days — this is the single highest-priority non-implementation deliverable. Timebox to ~2 hours.

## Goal
A 3–5 minute live demo script that proves the PoC's core claims with real system behavior, plus a longer troubleshooting + setup section. Prefer reliability over coverage.

## Environment
Two environments. The runbook must cover both.

**Local (Stage 1 — for debugging and dry runs):**
- 1× Windows laptop (`C:\Leonov\SpareAI`) runs Dispatcher + Agent A + Ollama + Chat Client. Optionally a second Agent on another port for routing dry-runs.

**AWS (Stage 2 — the live demo):**
- 2× EC2 `c7i.xlarge` in `eu-central-1`, provisioned by Terraform (`infra/`). Instance A: Dispatcher + Agent A + Ollama. Instance B: Agent B + Ollama.
- Dispatcher reaches Agents by **private IP** on port 8081. Browser reaches the Dispatcher by the public IP of Instance A on port 8080.
- Model pinned: `qwen2.5:3b-instruct-q4_K_M`. CPU-only on both hosts.

Terraform-side setup (install Terraform + AWS CLI, provision, destroy) is documented in `infra/README.md` — don't duplicate; link to it.

## Required demo sequence
1. **Architecture slide** — four components and the token boundary.
2. **Pre-flight check** —
   - `GET /health` on Dispatcher and both Agents returns `{"ok": true}`.
   - `GET /status` on each Agent (through `curl` or the Dispatcher's `/status`) shows the installed model and current HOT/COLD state.
3. **Cold vs HOT contrast** —
   - Force Agent A COLD: direct call to Ollama `POST /api/generate` with `"keep_alive": 0` on that host. Verify `COLD` via `curl $AGENT_A/status` (or `curl $OLLAMA/api/ps`).
   - Pre-warm Agent B with one short request through the Dispatcher. Verify `HOT`.
   - Submit the same representative prompt via the Chat Client. Show the `routing` event names Agent B (HOT). Show measured TTFT and total latency.
   - Repeat with Agent A COLD only. Show the cold-start cost in the latency panel.
4. **Failover** — stop Agent A (`taskkill` on the specific PID). Submit a new request from the Chat Client. Show the `routing` event names Agent B. Restart Agent A. Show it becoming eligible on the Dispatcher's `/status`.
5. **Overload protection** — induce CPU load on Agent B's host (`stress-ng --cpu 10 --timeout 60s` on Linux; Python busy loop on Windows). Show Agent B transitions to OVERLOAD, Dispatcher routes to Agent A. Stop the load; show recovery.
6. **Metrics + quality** — show `benchmarks/output/*.jsonl` records; call out HOT vs COLD TTFT delta. Show `docs/quality-notes.md` filled with the 10-prompt ratings (fill these in before the demo).
7. **What the PoC does and does not prove** — brief, honest.

## Reliability
- Pre-demo checklist: all processes started in a known order; model pulled on both hosts (`ollama pull qwen2.5:3b-instruct-q4_K_M`); both Agents visible on Dispatcher `/status`.
- Known-safe prompts: short, bland, deterministic enough that the demo doesn't hinge on a specific answer.
- Cleanup commands: stop processes; `terraform destroy` (or `aws ec2 stop-instances` for pause) after the demo to stop billing (~$10/day while running).
- No external service dependencies (no Gemini, no OpenAI, no third-party APIs). Everything local or on the cloud VM.
- If a request hangs: documented recovery (kill the Dispatcher, restart; do not attempt to continue a hung stream).

## Commands
Every command must correspond to the actual implementation. Do not invent endpoint paths, env var names, or admin routes. If an operation isn't implemented (e.g., a dedicated Agent-side unload endpoint), either call Ollama directly from the host via `curl` or add a minimal admin endpoint — don't document a fictional command.

## Deliverables
Create `docs/demo-runbook.md` with:
- One-paragraph architecture summary + token boundary.
- Prerequisites (`pip install -r requirements.txt`; `ollama pull qwen2.5:3b-instruct-q4_K_M` on both hosts; env vars set).
- Start-up order and exact commands for each process on each host.
- The 3–5 minute live script with timing cues and the exact commands to type/paste.
- A results table template to fill in during the live run (cold TTFT, warm TTFT, failover latency, overload-trigger time).
- Troubleshooting (common failure modes: port in use, model not pulled, token mismatch, EC2 instance unreachable because of a changed laptop IP, security-group misconfig, Windows firewall prompt during first local run, `user_data` still running on fresh EC2).
- Cleanup (stop processes; `terraform destroy` or `aws ec2 stop-instances`).
- Explicit non-claims: this is CPU inference on 4-vCPU cloud instances; latency numbers do not represent GPU-class performance; sample sizes are small; the demo exercises exactly two nodes.

## Workflow
Inspect the actual implementation first. Write commands that work. Rehearse the sequence mentally while writing — anything that requires more than one window-switch, add a scripted shortcut.
