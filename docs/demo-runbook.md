# SpareAI — Live demo runbook

A **3–5 minute** live script that demonstrates the PoC's core claims, plus a
longer setup/troubleshooting section. Prefer reliability over coverage.

## Architecture — one paragraph

A browser-based Chat Client (served by the Dispatcher at `/`) sends prompts to
the **Central Dispatcher** with a bearer `CLIENT_TOKEN`. The Dispatcher picks
one eligible **Agent** (HOT > COLD > UNKNOWN; lowest in-flight; lowest
load-per-core; lex tie-break), passes the request through with `AGENT_TOKEN`,
and streams tokens back as SSE. Each Agent manages one local **Ollama** bound to
`127.0.0.1`. Token boundary:

```
Chat Client ─ CLIENT_TOKEN ─▶ Dispatcher ─ AGENT_TOKEN ─▶ Agent ─ localhost ─▶ Ollama
```

Model pinned: `qwen2.5:3b-instruct-q4_K_M` on every worker. CPU-only.

---

## Prerequisites (both local & AWS)

- Python 3.11+ (verified on 3.13 in this project).
- Ollama with the pinned model on every worker host:
  ```bash
  ollama pull qwen2.5:3b-instruct-q4_K_M
  ```
- `pip install -e ".[dev]"` from the repo root.
- `.env` and `agents.yaml` configured. Tokens **must not** be placeholders —
  Agent and Dispatcher refuse to start with values like `changeme-*`.

### Env vars (critical)

- `CLIENT_TOKEN`, `AGENT_TOKEN` — real secrets, not the `.env.example` strings.
- `MODEL=qwen2.5:3b-instruct-q4_K_M`
- For Stage 2, Agent URLs in `agents.yaml` must use **private** IPs.

---

## Stage 1 — Local (Windows laptop, `C:\Leonov\SpareAI`)

Three shells, same `.env`:

```bash
# Shell 1 — Ollama
ollama serve

# Shell 2 — Agent A (port 8081)
python -m spareai.agent.main

# Shell 3 — Dispatcher + Chat Client (port 8080)
python -m spareai.dispatcher.main
```

Open <http://localhost:8080/>.

Optional second Agent on the same host (routing dry-run):

```bash
NODE_ID=worker-02 LISTEN_PORT=8082 python -m spareai.agent.main
```

Add it to `agents.yaml`.

---

## Stage 2 — AWS demo (2× `c7i.xlarge`, `eu-central-1`)

Terraform-side setup is in [`infra/README.md`](../infra/README.md). After
`terraform apply`, you have two instances with Ollama + the model pre-pulled.

### Start order (per instance)

**Instance A (Dispatcher + Agent A + Ollama):**
```bash
# ssh ubuntu@<public_ip_a>
cd ~/spareai && source .venv/bin/activate
export AGENT_TOKEN=... CLIENT_TOKEN=... NODE_ID=worker-01
nohup python -m spareai.agent.main > agent.log 2>&1 &
# wait a second; verify
curl -s http://127.0.0.1:8081/health
# Dispatcher:
nohup python -m spareai.dispatcher.main > dispatcher.log 2>&1 &
curl -s http://127.0.0.1:8080/health
```

`agents.yaml` on Instance A points at **private IPs**:
```yaml
agents:
  - node_id: worker-01
    url: http://127.0.0.1:8081
  - node_id: worker-02
    url: http://<private-ip-b>:8081
```

**Instance B (Agent B + Ollama):**
```bash
# ssh ubuntu@<public_ip_b>
cd ~/spareai && source .venv/bin/activate
export AGENT_TOKEN=... NODE_ID=worker-02
nohup python -m spareai.agent.main > agent.log 2>&1 &
curl -s http://127.0.0.1:8081/health
```

**Browser → `http://<public_ip_a>:8080/`**

---

## Pre-flight check (do this before the audience is watching)

```bash
# Local
curl -s http://localhost:8080/health
curl -s http://localhost:8081/health
# AWS
curl -s http://<public_ip_a>:8080/health
```

Then — through the Dispatcher — confirm both Agents visible:

```bash
curl -s -H "Authorization: Bearer $CLIENT_TOKEN" \
  http://<public_ip_a>:8080/agents | jq '.agents[] | {node_id, state, reachable, models}'
```

Expect `reachable=true` and `state=READY` on both.

---

## The 3–5 minute live script

### 0:00 — Architecture (30 s)

Show the one-paragraph architecture + token boundary diagram.

### 0:30 — Pre-flight (20 s)

`curl /health` on Dispatcher and both Agents in a single terminal.
Point at the `/agents` output in the sidebar of the Chat Client.

### 0:50 — HOT vs COLD contrast (90 s)

Force Agent A **COLD**, pre-warm Agent B.

```bash
# On Instance A — unload the model from the local Ollama
curl -s http://127.0.0.1:11434/api/generate \
  -d '{"model":"qwen2.5:3b-instruct-q4_K_M","keep_alive":0,"prompt":"","stream":false}'
curl -s http://127.0.0.1:11434/api/ps | jq '.models'   # expect [] (empty)

# On Instance B — pre-warm with a short prompt via the Chat Client
# (just send "hi" and let it finish). Then verify:
curl -s http://127.0.0.1:11434/api/ps | jq '.models'   # expect model listed
```

Submit this prompt from the Chat Client:

> *In one sentence, what is 2+2?*

- `routing` event names `worker-02` (HOT).
- Record `agent_ttft_ms`, `dispatcher_ttft_ms`, `e2e_latency_ms` (shown in the
  metadata panel; also in the `done`/`metrics` SSE events).
- Repeat targeting the COLD agent (stop B, or force B cold too). Record the
  cold TTFT. Show the delta.

### 2:20 — Failover (60 s)

Kill Agent A's process (Windows: `taskkill /PID <pid> /F`; Linux: `kill <pid>`).
In the Chat Client, send another prompt. The `routing` event now names
`worker-02`. In the `metrics` event, `failover_attempts` lists `worker-01`
(or `worker-01` disappears entirely from `/agents` after staleness).

Restart Agent A. Within one poll interval (3 s), it reappears in `/agents`.

### 3:20 — Overload protection (60 s)

On Instance B, induce load:

```bash
# Linux (preferred)
sudo apt-get install -y stress-ng  # one-time
stress-ng --cpu $(nproc) --timeout 60s &
```

Windows dev fallback: run `cpu_hog.py 60` (snippet in
[`docs/failure-playbook.md`](failure-playbook.md) scenario 10).

Within one or two `OVERLOAD_SAMPLE_INTERVAL_S` ticks, Agent B's `/status`
flips to `state=OVERLOAD`. Submit a prompt; it routes to Agent A. Stop the
load; show B returning to `READY` on `/agents`.

### 4:20 — Metrics + quality (40 s)

```bash
ls benchmarks/output/*.jsonl  # or bench/results-*.jsonl
cat docs/quality-notes.md
```

Point out: cold-vs-warm TTFT delta, the 10-prompt rating distribution with its
explicit caveat ("small sample, single rater — sanity check, not a benchmark").

### 5:00 — What this does and does not prove (30 s)

Read the "What the PoC proves / does not prove" section from
[`docs/presentation-source.md`](presentation-source.md).

---

## Results table (fill in during the live run)

| Metric                              | Value       |
|-------------------------------------|-------------|
| COLD TTFT (dispatcher-side, ms)     |             |
| COLD end-to-end (ms)                |             |
| HOT  TTFT (dispatcher-side, ms)     |             |
| HOT  end-to-end (ms)                |             |
| Failover switch latency (ms)        |             |
| Overload trigger time (s under load)|             |
| Overload recovery time (s)          |             |

Reference the raw `.jsonl` file name in the row for traceability.

---

## Troubleshooting

- **Port already in use on `8080` / `8081`.** Find the owner:
  `netstat -ano | findstr :8081` on Windows, `ss -ltnp | grep 8081` on Linux.
  Kill it, or override via `LISTEN_PORT=`.
- **Model not pulled.** `ollama list` doesn't show
  `qwen2.5:3b-instruct-q4_K_M`. Run `ollama pull qwen2.5:3b-instruct-q4_K_M`.
- **Token mismatch (`401` from Dispatcher).** Browser is using the token baked
  into the HTML. Hard-refresh after an env-var change. Agents being called by
  the Dispatcher: check `AGENT_TOKEN` matches in both processes.
- **EC2 unreachable because your laptop IP changed.** Re-apply with the new IP:
  `terraform apply -var="my_ip=<new-ip>"` (updates only the SG rule).
- **Security group misconfig.** Dispatcher can't reach Agent B: check that
  `agents.yaml` uses the **private** IP of Instance B (port 8081 is not open
  to the internet by design).
- **Windows firewall prompt on first local run.** Allow Python on private
  networks; deny public to keep the dev host off the LAN.
- **`user_data` still running on fresh EC2.** `ls /var/log/spareai-provisioned.marker`
  — if absent, wait 2–3 minutes.
- **Request hangs.** `Ctrl-C` the Dispatcher and restart. Do not attempt to
  resume a hung stream — the system has no mid-stream resumption.

---

## Cleanup

```bash
# Local
# Just Ctrl-C the three shells.

# AWS — stop (preserves disks + model, ~$10/day in EBS is negligible)
aws ec2 stop-instances --instance-ids <id-a> <id-b>

# AWS — destroy (full teardown, cheapest)
cd infra
terraform destroy -var="my_ip=<current-ip>"
```

Running cost reminder: **~$10/day** while both `c7i.xlarge` are up in Frankfurt.
Stop immediately after the demo.

---

## Explicit non-claims

- CPU inference on 4-vCPU VMs — latency numbers do **not** represent GPU-class
  performance.
- Sample sizes are small (benchmark: ~3–8 timed runs; quality: 10 prompts,
  single rater).
- The demo exercises exactly **two** worker nodes.
- No measurement of real production-workload interference in situ — the
  overload policy's effectiveness is argued, not benchmarked against a
  real primary workload.
- PoC-grade shared bearer tokens; no rotation, no revocation, no accounts.
