# Prompt #8 — Extract Presentation Material from the Working PoC

You are preparing source material for the exec presentation on **SpareAI**. Presentation in 2 days — timebox to 1–2 hours. This is the second-highest priority after the demo runbook.

## Goal
Inspect the repo, docs, benchmark output, and quality notes, then produce a presentation-ready evidence pack. Do not create slides. Produce one Markdown document that can be read into a slide tool later or copied into the deck.

## Audience
Mixed technical + management. The presentation should explain the problem, the idea, what has been demonstrated, limitations, and next steps. Avoid implying business impact that was not measured.

## Evidence rules — critical
Tag every claim as one of:
- **Implemented** — verifiable in committed code.
- **Demonstrated** — run live during a demo; cite the specific demo step.
- **Measured** — supported by `benchmarks/output/*.jsonl` or `docs/quality-notes.md`, with sample size and test conditions.
- **Planned** — intended future capability; not implemented.
- **Hypothesis** — plausible but not validated by this PoC.

Never invent metrics, test outcomes, projected savings, counts of candidate company machines, or business impact figures. If a measurement is missing, mark it as "to be measured" with a clear placeholder — do not fabricate.

## Inspect
- Repository code and configuration.
- FastAPI's auto-generated OpenAPI docs if present.
- Existing tests and test commands.
- `docs/demo-runbook.md`.
- `scripts/bench.py` and `benchmarks/output/*.jsonl`.
- `docs/quality-notes.md`.
- `docs/failure-playbook.md`.
- Known limitations and deployment notes.

## Create `docs/presentation-source.md` with these sections

1. **One-sentence project description.**
2. **Problem statement** — underutilized always-on compute (long-running internal servers like the HPE DL380 class) and the opportunity it may represent. Honest; no numbers unless cited.
3. **Core hypothesis** — what the PoC is intended to validate.
4. **Proposed value** — explicitly tagged **Hypothesis**.
5. **Architecture** — Chat Client, Central Dispatcher, Worker Agents, local Ollama. Token boundary diagram.
6. **Request lifecycle** — from user prompt to selected worker to streamed response. Include the `routing` SSE event and the two TTFT measurement points.
7. **HOT vs COLD** — precise definitions. If measured, include the observed delta from `benchmarks/output/*.jsonl` with sample size, tagged **Measured**.
8. **Routing + failover** — rules from Prompt #3, demonstrated scenarios from Prompt #6.
9. **Workload protection** — overload policy, hysteresis thresholds, and the live demo that triggers it.
10. **Benchmark results table** — columns: `environment`, `model`, `quant`, `cpu`, `cores`, `cold_or_warm`, `samples`, `median_e2e_ms`, `p95_e2e_ms`, `median_ttft_ms`, `median_tok_per_s`, `source_file`. If a column has no data, write `n/a` and tag the row **To be measured**.
11. **Answer quality (sample of 10)** — table with `prompt_id`, `category`, `rating`, `note`. Rating distribution summary (e.g., 6 acceptable / 3 marginal / 1 unacceptable). Explicit caveat: "small sample, single rater — a sanity check, not a benchmark." Tag **Measured**.
12. **Live demo script** — concise sequence (copied/trimmed from the demo runbook).
13. **What the PoC proves.** Tight bullets. Tag each with the evidence category.
14. **What the PoC does not prove.** Equally honest: no multi-tenant isolation, no GPU numbers, no production-workload interference measurement in situ, no quality comparison vs. a reference model, no load-at-scale testing.
15. **Risks and constraints** — model quality limits on 3B q4, CPU-latency on current hosts, workload interference in real production environments, security (PoC-grade auth), operational cost, licensing (Qwen's Tongyi Qianwen license — verify terms), supportability.
16. **Roadmap** — more workers, additional models, Dynatrace integration, availability calendars, user-workstation workers, complexity-based routing, Gemini escalation, quality-based routing, P2P orchestration. All tagged **Planned**.
17. **Decisions and support requested** — questions for the audience (which internal fleet to pilot next, who owns operational monitoring, licensing review, security review for broader rollout). Phrase as questions; do not imply approval has been granted.
18. **Suggested slide outline** — title + one-sentence key message per slide.

## Framing rules
- Do not position SpareAI as a replacement for Gemini. Position it as an experiment to determine which classes of request can be served by existing underutilized compute, with potential future escalation of harder requests.
- Do not use "free" as a factual claim. Hardware opportunity cost, power, operations, security, and maintenance are not zero.
- Do not imply the business case is proven. The PoC proves a mechanism and provides small-sample quality evidence.

## Deliverables
- `docs/presentation-source.md`.
- A short list at the end citing every evidence file used (relative paths).
- A list of "measurements that would materially strengthen the deck if run before the presentation" so the user can prioritize what to run next.
- No code changes.

## Workflow
Inspect first. Then write. Cite file paths and sample counts in-line so claims can be traced.
