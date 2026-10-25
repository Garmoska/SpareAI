# SpareAI on AWS — live test (24 Oct 2026)

**Two cloud machines, no GPU. The whole system worked end to end in ~32 minutes, for about $0.23.**

| | First answer (model still loading) | Next answers (model ready) |
|---|---|---|
| Wait for first word | 3.1 s | **0.3 s** |
| Whole answer | 4.3 s | 1.5 s |

- **One machine died — the other one answered.** The dead machine came back by itself in about 6 seconds.
- **Too much load? It stops taking requests.** It noticed after ~72 s, and calmed down 43 s after the load stopped.
- **Requests were shared evenly.** All 10 test prompts went to a machine that already had the model loaded — 5 to each.
- **Main point:** the first answer is slow because the model has to be loaded into memory (about 2.3 s). After that it is roughly 10× faster.
