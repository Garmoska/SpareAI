# Prompt #5 — Add Inference Metrics and Benchmarking

You are adding trustworthy instrumentation to **SpareAI**. Presentation in 2 days — timebox this to 2–4 hours.

## Goal
Capture enough measurements to credibly show the difference between a cold model load and warm inference, and to support the exec claim that "suitable requests can be served locally."

## Metrics (per request)
- `request_id` (UUID).
- `request_start_ts`, `request_end_ts` (ISO 8601 wall clock for logs; monotonic durations for math).
- `selected_node`, `model`, `model_state_at_route` (HOT / COLD / UNKNOWN).
- `routing_reason`, `routing_attempts`.
- `agent_ttft_ms` (first chunk out of Ollama, measured by the Agent).
- `dispatcher_ttft_ms` (first chunk observed by the Dispatcher).
- `end_to_end_latency_ms` (Dispatcher accept → `done` event).
- From Ollama's final chunk (when provided): `total_duration`, `load_duration`, `prompt_eval_duration`, `prompt_eval_count`, `eval_duration`, `eval_count`.
- `output_tokens_per_sec = eval_count / (eval_duration / 1e9)` when both are present.
- `in_flight_at_route` (value of `in_flight_requests` on the selected Agent at the moment of selection).
- Success / failure, error code if failure.

## Measurement rules
1. Durations use monotonic clocks. Wall-clock timestamps are for logs only.
2. Clearly label which fields are **Ollama-reported** vs **SpareAI-measured** in the output schema.
3. TTFT is strictly "time to first non-empty token chunk." Do not label end-to-end latency as TTFT.
4. Never log prompt text or generated text. Correlate everything by `request_id`.
5. Collect metrics for failed requests too (status code, error class, which stage failed).
6. Lightweight: write to JSONL (one request per line) and optionally stdout. No database, no Prometheus, no OpenTelemetry for this PoC.
7. Metrics writing must not block the response path — use a background queue or async append.

## Benchmark script — `scripts/bench.py`
Takes `--mode {cold,warm,quality}`, `--dispatcher-url`, `--token`, `--model`, `--prompt-file`, `--runs`, `--output-jsonl`.

- **`--mode cold`**: forces COLD by issuing a direct Ollama `POST /api/generate` with `"keep_alive": 0` (or an Agent admin endpoint if you add one), verifies the model is absent from `/api/ps`, then issues the timed inference request through the Dispatcher.
- **`--mode warm`**: issues one pre-warm request, verifies the model is present in `/api/ps`, then runs `N` timed requests back-to-back through the Dispatcher.
- **`--mode quality`**: reads `benchmarks/quality_prompts.jsonl` (the 10-prompt set, see below) and runs each prompt once through the Dispatcher, saving per-request records plus a response excerpt (first 200 chars) to `benchmarks/output/quality_runs.jsonl`.

The script writes raw per-request records to the JSONL output and prints a summary table at the end: count, min, p50, p95, max for `end_to_end_latency_ms`, `agent_ttft_ms` (and `dispatcher_ttft_ms`), and `output_tokens_per_sec`. Also prints model name + quant, environment identifier, and sample size.

On any failed verification (model still present after unload, model absent after warm-up), abort and print a clear diagnostic. Do not silently reinterpret a run as the other mode.

## Quality sample integration
- Authoritative prompt set at `benchmarks/quality_prompts.jsonl`, 10 lines, each with `prompt_id`, `category`, `prompt`. Content from `prompts/clarifications.md` entry 8.
- `--mode quality` runs each prompt once and writes `benchmarks/output/quality_runs.jsonl`.
- Also generate `docs/quality-notes.md` **template** with one row per prompt plus empty `rating` and `note` columns for the user to fill in manually.

## Tests
- Unit tests for metric calculations (TTFT math, tokens-per-second from Ollama fields, success/failure aggregation).
- Mock the Ollama final chunk to verify derived fields.

## Deliverables
- Instrumentation in Agent and Dispatcher.
- `scripts/bench.py` + a README section with example invocations.
- `benchmarks/quality_prompts.jsonl` with the 10 prompts.
- `docs/quality-notes.md` template.
- Report template for a run: environment, model + quant, context length, sample count, test conditions, cold vs warm medians/p95, raw file reference.
- Any numeric results you include must be from runs you actually executed. If you did not run them, provide the exact command for the user to run and leave the numbers as placeholders.

## Workflow
1. Instrument first (Agent + Dispatcher).
2. Verify records appear in JSONL via a single `/generate` call.
3. Write bench script.
4. Run a quick cold/warm pair locally; report actual results.
5. Hand off cloud-VM runs to the user if the VM isn't ready.
