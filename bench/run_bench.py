"""SpareAI benchmark driver.

Runs:
  (a) a cold/hot timing experiment against ONE agent directly (needs OLLAMA_URL on that host),
  (b) the fixed 10-prompt quality set through the DISPATCHER's /chat endpoint.

Usage:
    python -m bench.run_bench --dispatcher http://localhost:8080 \
        --client-token "$CLIENT_TOKEN" \
        --agent http://localhost:8081 --agent-token "$AGENT_TOKEN" \
        --ollama http://127.0.0.1:11434 \
        --model qwen2.5:3b-instruct-q4_K_M

Writes:
    bench/results-<ts>.jsonl         raw per-event log
    bench/results-<ts>-summary.md    human summary
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .quality_prompts import QUALITY_PROMPTS

BENCH_DIR = Path(__file__).parent


# ---------- Helpers ----------

async def _verify_cold(ollama: str, model: str, http: httpx.AsyncClient) -> bool:
    r = await http.get(f"{ollama}/api/ps", timeout=5)
    r.raise_for_status()
    names = {m.get("name") for m in r.json().get("models", [])}
    return model not in names


async def _verify_hot(ollama: str, model: str, http: httpx.AsyncClient) -> bool:
    r = await http.get(f"{ollama}/api/ps", timeout=5)
    r.raise_for_status()
    names = {m.get("name") for m in r.json().get("models", [])}
    return model in names


async def _force_cold(ollama: str, model: str, http: httpx.AsyncClient) -> None:
    await http.post(f"{ollama}/api/generate",
                    json={"model": model, "keep_alive": 0, "prompt": "", "stream": False},
                    timeout=30)


async def _one_shot_through_agent(
    agent: str, agent_token: str, model: str, prompt: str,
    http: httpx.AsyncClient,
) -> dict:
    """Call the Agent /generate endpoint directly and collect timing."""
    request_id = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {agent_token}", "Accept": "text/event-stream"}
    payload = {"request_id": request_id, "model": model, "prompt": prompt}

    start = time.monotonic_ns()
    ttft_ms = None
    out_chars = 0
    done_payload: dict = {}
    err = None

    try:
        async with http.stream("POST", f"{agent}/generate", headers=headers,
                               json=payload, timeout=httpx.Timeout(connect=5, read=600, write=5, pool=5)) as r:
            if r.status_code != 200:
                body = await r.aread()
                return {"request_id": request_id, "status": r.status_code,
                        "error": body.decode("utf-8", "replace")}
            event = None
            async for line in r.aiter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = line.split(":", 1)[1].strip()
                    if not data:
                        continue
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if event == "token":
                        if ttft_ms is None:
                            ttft_ms = (time.monotonic_ns() - start) // 1_000_000
                        out_chars += len(obj.get("chunk", ""))
                    elif event == "done":
                        done_payload = obj
                    elif event == "error":
                        err = obj
    except Exception as e:
        err = {"code": "transport", "detail": str(e)}

    e2e_ms = (time.monotonic_ns() - start) // 1_000_000
    return {
        "request_id": request_id,
        "ttft_ms": ttft_ms,
        "e2e_ms": e2e_ms,
        "out_chars": out_chars,
        "done": done_payload,
        "error": err,
    }


async def _one_shot_through_dispatcher(
    dispatcher: str, client_token: str, model: str, prompt: str,
    http: httpx.AsyncClient,
) -> dict:
    headers = {"Authorization": f"Bearer {client_token}", "Accept": "text/event-stream",
               "Content-Type": "application/json"}
    payload = {"model": model, "prompt": prompt}

    start = time.monotonic_ns()
    ttft_ms = None
    out_chars = 0
    routing: dict = {}
    done_payload: dict = {}
    metrics: dict = {}
    err = None

    try:
        async with http.stream("POST", f"{dispatcher}/chat", headers=headers,
                               json=payload, timeout=httpx.Timeout(connect=5, read=600, write=5, pool=5)) as r:
            if r.status_code != 200:
                body = await r.aread()
                return {"status": r.status_code, "error": body.decode("utf-8", "replace")}
            event = None
            async for line in r.aiter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = line.split(":", 1)[1].strip()
                    if not data:
                        continue
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if event == "routing":
                        routing = obj
                    elif event == "token":
                        if ttft_ms is None:
                            ttft_ms = (time.monotonic_ns() - start) // 1_000_000
                        out_chars += len(obj.get("chunk", ""))
                    elif event == "done":
                        done_payload = obj
                    elif event == "metrics":
                        metrics = obj
                    elif event == "error":
                        err = obj
    except Exception as e:
        err = {"code": "transport", "detail": str(e)}

    e2e_ms = (time.monotonic_ns() - start) // 1_000_000
    return {
        "ttft_ms": ttft_ms,
        "e2e_ms": e2e_ms,
        "out_chars": out_chars,
        "routing": routing,
        "done": done_payload,
        "metrics": metrics,
        "error": err,
    }


# ---------- Phases ----------

async def phase_cold_hot(args, http: httpx.AsyncClient, jsonl):
    results = {"cold": [], "hot": []}
    prompt = "In one sentence, what is 2+2?"
    # Cold runs
    for i in range(args.cold_runs):
        await _force_cold(args.ollama, args.model, http)
        assert await _verify_cold(args.ollama, args.model, http), "model still loaded after unload"
        r = await _one_shot_through_agent(args.agent, args.agent_token, args.model, prompt, http)
        r.update({"phase": "cold", "iter": i, "model_state_pre": "COLD"})
        results["cold"].append(r)
        jsonl.write(json.dumps(r) + "\n"); jsonl.flush()
        print(f"[cold {i}] ttft={r.get('ttft_ms')}ms e2e={r.get('e2e_ms')}ms")

    # Pre-warm then hot runs
    await _one_shot_through_agent(args.agent, args.agent_token, args.model, prompt, http)
    assert await _verify_hot(args.ollama, args.model, http), "model not loaded after warm-up"
    for i in range(args.hot_runs):
        r = await _one_shot_through_agent(args.agent, args.agent_token, args.model, prompt, http)
        r.update({"phase": "hot", "iter": i, "model_state_pre": "HOT"})
        results["hot"].append(r)
        jsonl.write(json.dumps(r) + "\n"); jsonl.flush()
        print(f"[hot  {i}] ttft={r.get('ttft_ms')}ms e2e={r.get('e2e_ms')}ms")
    return results


async def phase_quality(args, http: httpx.AsyncClient, jsonl):
    results = []
    for p in QUALITY_PROMPTS:
        r = await _one_shot_through_dispatcher(
            args.dispatcher, args.client_token, args.model, p["prompt"], http,
        )
        r.update({"phase": "quality", "prompt_id": p["id"], "category": p["category"]})
        results.append(r)
        jsonl.write(json.dumps(r) + "\n"); jsonl.flush()
        print(f"[quality {p['id']}] ttft={r.get('ttft_ms')}ms e2e={r.get('e2e_ms')}ms")
    return results


def _summarize(label: str, items: list[dict]) -> str:
    e2e = [x["e2e_ms"] for x in items if x.get("e2e_ms") is not None]
    ttft = [x["ttft_ms"] for x in items if x.get("ttft_ms") is not None]
    if not e2e:
        return f"### {label}\n(no successful runs)\n"
    def stats(xs):
        if not xs: return "-"
        med = int(statistics.median(xs))
        p95 = int(xs[int(0.95 * (len(xs) - 1))]) if len(xs) > 1 else xs[0]
        return f"n={len(xs)}, median={med}ms, p95={p95}ms, min={min(xs)}ms, max={max(xs)}ms"
    return (f"### {label}\n"
            f"- e2e: {stats(sorted(e2e))}\n"
            f"- ttft: {stats(sorted(ttft))}\n")


async def main_async(args) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    jsonl_path = BENCH_DIR / f"results-{ts}.jsonl"
    summary_path = BENCH_DIR / f"results-{ts}-summary.md"

    async with httpx.AsyncClient() as http:
        with jsonl_path.open("w", encoding="utf-8") as jsonl:
            cold_hot = {}
            if not args.skip_cold_hot:
                print("== cold/hot phase ==")
                cold_hot = await phase_cold_hot(args, http, jsonl)
            print("== quality phase ==")
            quality = await phase_quality(args, http, jsonl)

    lines = [f"# SpareAI bench — {ts}",
             f"- model: `{args.model}`",
             f"- dispatcher: `{args.dispatcher}`",
             f"- agent: `{args.agent}`",
             ""]
    if cold_hot:
        lines.append(_summarize("cold", cold_hot["cold"]))
        lines.append(_summarize("hot",  cold_hot["hot"]))
    lines.append(_summarize("quality (through dispatcher)", quality))
    lines.append("## Quality rating template")
    lines.append("")
    lines.append("| id | category | ttft_ms | e2e_ms | node | model_state | rating | note |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in quality:
        node = r.get("routing", {}).get("node_id", "-")
        st = r.get("routing", {}).get("model_state_at_routing", "-")
        lines.append(f"| {r['prompt_id']} | {r['category']} | {r.get('ttft_ms','-')} | "
                     f"{r.get('e2e_ms','-')} | {node} | {st} |  |  |")

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {jsonl_path}")
    print(f"wrote {summary_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--dispatcher", required=True, help="e.g. http://localhost:8080")
    p.add_argument("--client-token", required=True)
    p.add_argument("--agent", required=True, help="e.g. http://localhost:8081")
    p.add_argument("--agent-token", required=True)
    p.add_argument("--ollama", required=True, help="e.g. http://127.0.0.1:11434")
    p.add_argument("--model", default="qwen2.5:3b-instruct-q4_K_M")
    p.add_argument("--cold-runs", type=int, default=3)
    p.add_argument("--hot-runs", type=int, default=5)
    p.add_argument("--skip-cold-hot", action="store_true")
    return p.parse_args()


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
