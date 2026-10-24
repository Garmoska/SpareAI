# SpareAI — AWS live demo run (2026-10-24)

**Status: completed and fully torn down.** No AWS resources remain.

| | |
|---|---|
| AWS account | 993174291680 |
| Region | `eu-central-1` (Frankfurt) |
| Window | ~14:41–15:13 UTC (≈32 min) |
| Approx. compute cost | ≈$0.23 (2 × `c7i.xlarge` at ~$0.216/hr each) |
| Model | `qwen2.5:3b-instruct-q4_K_M` (CPU-only) |

## Topology

| Node | Role | Public IP | Private IP | Instance ID |
|---|---|---|---|---|
| `spareai-a` | Dispatcher + Agent A + Ollama | 63.180.248.180 | 172.31.18.99 | `i-01f019493d94b8508` |
| `spareai-b` | Agent B + Ollama | 3.65.199.235 | 172.31.17.159 | `i-0c72a0457cf7758a7` |

- AMI: `ami-0fa06da5547f46a7d` (Ubuntu 22.04 LTS), 2 × 4 vCPU / 8 GiB / 20 GB gp3.
- Security group `sg-0379d7f2846ed4c7a`: SSH 22 and Dispatcher 8080 from `193.179.60.31/32`; Agent 8081 self-referenced only (VPC-internal).
- `agents.yaml` on A pointed `worker-01` at `http://127.0.0.1:8081` and `worker-02` at `http://172.31.17.159:8081`.

## Live script results

| Metric | Value |
|---|---|
| COLD TTFT (dispatcher-side) | **3,066 ms** (agent 3,061 ms) |
| COLD end-to-end | **4,314 ms** |
| HOT TTFT (dispatcher-side) | **297 ms** (agent 291 ms) |
| HOT end-to-end | **1,497 ms** |
| Failover | kill A → `attempt=2`, `failover_attempts=["worker-01"]`, served by worker-02 |
| Failover recovery of A | re-registered `reachable=true`, `consecutive_failures=0` within one poll (~6 s) |
| Overload trigger | **~72 s** after load start; flipped at `load_per_core=0.702` |
| Overload routing | prompt served by worker-01 (`HOT`, TTFT 510 ms, no failover) |
| Overload recovery | **~43 s** after load stopped (~2 min total in `OVERLOAD`), READY at 0.472 |

COLD → HOT delta: **~2.77 s TTFT**, consistent with the 2.29 s model `load_duration` in the Ollama `done` event.

### Failover trace (worker-01 killed, prompt fired immediately)

```json
{
  "routing": {"node_id": "worker-02", "model_state_at_routing": "COLD", "attempt": 2},
  "metrics": {"selected_node": "worker-02", "failover_attempts": ["worker-01"]},
  "answer": "2+2 equals 4."
}
```

Eight seconds later: `worker-01 reachable=false, consecutive_failures=7, last_error=ConnectError`.

## Benchmark (host A, direct agent + dispatcher)

Artifacts: `bench/results-20261024-150200.jsonl`, `bench/results-20261024-150200-summary.md`.

| Phase | n | TTFT median | e2e median |
|---|---|---|---|
| cold | 3 | 3,414 ms (min 3,399 / max 3,907) | 4,404 ms |
| hot | 5 | 149 ms (min 148 / max 153) | 1,141 ms |
| quality (via dispatcher) | 10 | 628 ms | 12,537 ms |

Quality phase routed **10/10 HOT**, split **5 × worker-01 / 5 × worker-02**. e2e range was 2,752–53,259 ms (the `code_sql` prompt was the 53 s outlier).

## Quality answers for rating

Collected separately through the public Dispatcher; answers + blank rating lines in
`bench/results-20261024-150200-answers-aws.md`.

| id | category | node | TTFT ms | e2e ms |
|---|---|---|---|---|
| q01 | summarization | worker-01 | 1,818 | 15,178 |
| q02 | code_python | worker-02 | 766 | 26,133 |
| q03 | code_sql | worker-01 | 911 | 42,774 |
| q04 | translation | worker-02 | 433 | 6,525 |
| q05 | rewrite_tone | worker-01 | 483 | 2,770 |
| q06 | extraction | worker-02 | 777 | 5,910 |
| q07 | reasoning | worker-01 | 910 | 12,189 |
| q08 | qa_definition | worker-02 | 463 | 11,517 |
| q09 | email_draft | worker-01 | 513 | 11,195 |
| q10 | refusal | worker-02 | 315 | 11,354 |

Ratings are intentionally left blank — single-rater manual review, per `docs/quality-notes.md`.

## Deviations from `docs/demo-runbook.md`

1. **Overload timing is optimistic.** The runbook says B flips “within one or two
   `OVERLOAD_SAMPLE_INTERVAL_S` ticks”. The policy uses the 1-minute load average
   (`load_avg_1m / cpu_cores`), so with 4 saturated cores it took **~72 s** to cross
   `OVERLOAD_HIGH_PCT=0.70` and **~43 s** to fall back under `OVERLOAD_LOW_PCT=0.50`.
   For a live demo, start the load ~90 s before you need the flip.
2. **`infra/README.md` §4 is stale.** It says to copy `agent dispatcher requirements.txt`;
   the repo now ships one package (`spareai/`, `pyproject.toml`). Deployment used
   `git archive` + `pip install -e`.
3. **Windows-authored shell/env files need LF.** CRLF left a trailing `\r` on every
   value, producing `[Errno -2] Name or service not known` (bad bind host) and
   `Agents file not found` (`agents.yaml\r`). Files were normalized to LF before deploy.
4. **Terraform + `aws login` needs a credential bridge.** Terraform's SDK does not
   understand the CLI-only `login_session` profile key. A temporary `spareai` profile
   used `credential_process` via the AWS CLI's short path
   (`C:\PROGRA~1\Amazon\AWSCLIV2\aws.exe`); a `.cmd` wrapper was not executable by
   Terraform's launcher. The profile was removed at teardown.
5. **OpenSSH on Windows rejected the generated PEM** until inherited ACLs were removed
   (`icacls <key> /inheritance:r /grant:r "<user>:(R)"`).
6. **Token hygiene.** Tokens were generated on the workstation, written straight to
   `0600` env files, never committed, and rotated once when one value was accidentally
   echoed into the session log.

## Teardown record

- `terraform destroy -auto-approve -var="my_ip=193.179.60.31"` → **7/7 resources destroyed**.
- Verified afterwards in AWS: security group gone, key pair `spareai-key` returns
  `InvalidKeyPair.NotFound`, both instances `terminated`.
- Local cleanup: `infra/spareai-key.pem`, `infra/terraform.tfstate*`,
  `infra/.terraform*` and `dist/` (deployment scripts + token files) deleted; the
  temporary `[profile spareai]` removed from `~/.aws/config`.
- Kept: the three `bench/results-20261024-150200*` artifacts and this report.
- Left installed (not AWS resources): AWS CLI 2.38.5 and Terraform 1.16.6.

## Reproduce (outline)

```powershell
# Tooling + auth (one-time)
winget install --id Amazon.AWSCLI
winget install --id Hashicorp.Terraform
aws login

# Provision
cd infra
terraform init
terraform apply -var="my_ip=<laptop-public-ip>"

# Deploy (repo archived with `git archive`, copied with scp), then per host:
bash ~/setup-remote.sh
bash ~/start-b.sh          # on B
bash ~/start-a.sh          # on A (agent + dispatcher)

# Verify
curl http://<a-public-ip>:8080/health
curl -H "Authorization: Bearer $CLIENT_TOKEN" http://<a-public-ip>:8080/agents

# Bench (on A, tokens sourced from the env file)
python -m bench.run_bench --dispatcher http://127.0.0.1:8080 \
  --client-token "$CLIENT_TOKEN" --agent http://127.0.0.1:8081 \
  --agent-token "$AGENT_TOKEN" --ollama http://127.0.0.1:11434

# Teardown
terraform destroy -var="my_ip=<laptop-public-ip>"
```

## What this run does and does not prove

- **Proves:** two-host dispatch over private networking; HOT-aware ordering; pre-stream
  failover with exactly-once avoidance (mid-stream failures still do not retry);
  load-based admission with hysteresis; end-to-end SSE timings measured at both layers.
- **Does not prove:** GPU-class latency (CPU-only 4-vCPU VMs); production interference
  behaviour; more than two workers; production auth (static PoC bearer tokens, no TLS).
