# Answer quality — manual ratings

Model: `qwen2.5:3b-instruct-q4_K_M`.
Rate each row **A** (acceptable), **M** (marginal), **U** (unacceptable). One line of reasoning.

> Caveat: small sample, single rater — sanity check, not a benchmark.

| id | category | rating | note |
|---|---|---|---|
| q01 | summarization |  |  |
| q02 | code_python |  |  |
| q03 | code_sql |  |  |
| q04 | translation |  |  |
| q05 | rewrite_tone |  |  |
| q06 | extraction |  |  |
| q07 | reasoning |  |  |
| q08 | qa_definition |  |  |
| q09 | email_draft |  |  |
| q10 | refusal |  |  |

Latency and routing metadata per prompt are captured in `bench/results-*.jsonl`
and the matching `-summary.md`. Correlate by `prompt_id`.
