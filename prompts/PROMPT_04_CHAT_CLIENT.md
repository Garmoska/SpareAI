# Prompt #4 — Build the Minimal Chat Client

You are building the user-facing demo interface for **SpareAI**. Presentation in 2 days — timebox this to 1–2 hours.

## Goal
A single HTML page served by the Dispatcher at `GET /`. It must look like a simple chat, show demo-relevant metadata, and stream tokens as they arrive. Streaming is in scope (Prompt #1).

## Technology (pinned)
- Plain HTML + vanilla JS. No React / Vue / Svelte. No build step. No bundler.
- SSE via `fetch` + `ReadableStream` manual parsing (so the `Authorization: Bearer <CLIENT_TOKEN>` header can be set — `EventSource` doesn't support custom headers).
- Minimal CSS. Readable, not polished.

## Behavior
1. Only talks to the Dispatcher. Never calls Agents or Ollama directly.
2. Reads `window.SPAREAI_TOKEN` injected by the Dispatcher server-side; uses it for every call.
3. Multiline prompt input + Send button.
4. Loading state until the first `token` event arrives.
5. Streams tokens into the current assistant message as they arrive.
6. Per-response metadata panel populated from the `routing` and `done` events:
   - selected node (from the `routing` event);
   - model state at routing time (HOT / COLD / UNKNOWN);
   - routing reason;
   - end-to-end latency (ms);
   - TTFT (Dispatcher-side, ms);
   - output tokens per second (when `done` arrives).
7. "New conversation" button clears local state. No server-side persistence of chats.
8. Error states:
   - Pre-stream error (e.g., `503 no_eligible_agents`) → show the message, offer Retry.
   - Mid-stream `error` SSE event → mark the partial answer as interrupted, show the error, offer Retry (which sends a new request; never silently auto-retries).
9. Visible banner: "SpareAI PoC demo — not production."

## SSE event handling
Expect this sequence from `/generate`:
1. One `event: routing` with the selection payload.
2. Zero or more `event: token` with chunk content.
3. Exactly one terminal event: either `event: done` (with Ollama timings + TTFTs + token counts) or `event: error`.

Treat any other event type as a warning (log in console and ignore) — forward-compat.

## Configuration
No separate config file. The Dispatcher URL is the page's origin. `SPAREAI_TOKEN` is injected server-side at page load. Do not hard-code any production hostname.

## Tests
Optional for this PoC. If time permits, a manual test checklist is fine. Do not introduce a JS test framework and build pipeline.

## Deliverables
- `dispatcher/templates/index.html` (or the project's equivalent location).
- Any static CSS/JS referenced by it.
- A short section in the Dispatcher README on what the metadata panel means.

## Workflow
1. Confirm the Dispatcher's `/generate` SSE schema.
2. Build the page.
3. Click through the golden path and at least one error case in a real browser.
4. If you cannot run a browser, say so explicitly rather than claiming UI success.
