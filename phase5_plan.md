# Phase 5 Implementation Plan — Observability & Hardening

Straight implementation checklist, no teaching scaffolding. Goal: full Langfuse tracing,
retry/backoff on the external API calls that don't have it, HNSW query-time tuning,
streaming on the query endpoint, and a load-test harness.

**Important finding before starting:** the installed `langfuse` SDK is **v4.12.0**, not
the v2-era SDK `implementation_plan.md`'s Section 8 draft was written against. That draft
uses `from langfuse.decorators import langfuse_context, observe` — that module doesn't
exist in v4 at all (v4 is OTel-based). Everything below targets the real v4 API
(`from langfuse import observe, get_client`), not that stale draft. Section 8 of
`implementation_plan.md` should be treated as superseded by this document.

---

## What's already done (don't redo)

- **Cross-encoder reranking is already wired in** — `app/agents/rag.py`'s `make_rag_node`
  already calls `reranker.rerank(...)`. The original phase list treated this as a Phase 5
  item; it got built during Phase 3's RAG node work. Nothing to do here.
- `app/observability/langfuse.py` already constructs a bare `Langfuse(...)` client from
  `settings`. It has no decorators/instrumentation yet — that's this phase's job.
- `docker-compose.yml` already has `langfuse-web`/`langfuse-worker` services configured
  with matching dev keys (`pk-lf-dev`/`sk-lf-dev`) to `config.py`'s defaults.

---

## 1. Observability — Langfuse v4 instrumentation

### 1a. `app/observability/langfuse.py`

Replace the bare client construction with an `agent_span` decorator built on v4's real
`@observe()`:

```python
from functools import wraps
from typing import Any, Callable

from langfuse import Langfuse, get_client, observe

from app.config import settings

langfuse_client = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    host=settings.langfuse_host,
)


def agent_span(name: str) -> Callable:
    """
    Wraps a LangGraph node (async, single `state: BuildState` arg, returns a
    partial-state dict) in an @observe(as_type="agent") span, and additionally
    tags the span with session_id/calling_agent metadata that @observe's
    automatic input capture wouldn't otherwise surface distinctly.
    """
    def decorator(fn: Callable) -> Callable:
        @observe(name=name, as_type="agent")
        @wraps(fn)
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            get_client().update_current_span(
                metadata={
                    "session_id": state.get("session_id"),
                    "calling_agent": state.get("calling_agent"),
                },
            )
            result = await fn(state)
            get_client().update_current_span(
                output={
                    "next_agent": result.get("next_agent"),
                    "final_response_preview": (result.get("final_response") or "")[:200],
                },
            )
            return result
        return wrapper
    return decorator


def rag_span(fn: Callable) -> Callable:
    """Instruments the RAG node specifically as a retriever-type observation."""
    @observe(name="rag_node", as_type="retriever")
    @wraps(fn)
    async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
        result = await fn(state)
        chunks = result.get("rag_results", [])
        get_client().update_current_span(
            metadata={"calling_agent": state.get("calling_agent")},
            output={
                "chunks_retrieved": len(chunks),
                "top_score": chunks[0].similarity_score if chunks else None,
            },
        )
        return result
    return wrapper
```

**Verify the exact session-grouping field name against current Langfuse docs before
relying on it** — v4's ingestion API may expect a specific reserved key (historically
something like a top-level `session_id` on the trace, separate from arbitrary
`metadata`) for traces to actually group by session in the UI. Don't assume
`metadata={"session_id": ...}` alone gives you the grouped session view without
checking — that's exactly the kind of detail that silently changes between SDK
generations.

### 1b. Instrument every node

Add `@agent_span("<name>")` to all 7 LLM-backed node functions (`guidance_of_grace_node`,
`maiden_melina_node`, `master_hewg_build_node`, `rennala_stats_node`,
`kale_loot_routes_node`, `gideon_all_knowing_node`, `alexander_combat_node`) and
`@rag_span` to `rag_node` inside `make_rag_node`'s closure in `app/agents/rag.py`.

### 1c. Populate `QueryResponse.trace_id`

This has been an empty-string placeholder since Phase 4. Fix in
`app/graph/runner.py` / `app/api/routes/queries.py`:

- `get_client().get_current_trace_id()` inside `GraphRunner.run()` (call it right after
  `ainvoke()` completes, while still inside the same OTel context) — thread it through
  into the returned dict as `"trace_id"`.
- `queries.py`'s `submit_query` reads `result.get("trace_id", "")` instead of hardcoding
  `""`.

### 1d. Flush on shutdown

`app/main.py`'s `lifespan()` closes `pool`/`redis` after `yield` — add
`get_client().flush()` (or `.shutdown()`) there too, otherwise buffered spans from the
last few requests before shutdown can be dropped.

---

## 2. Retry/backoff on external API calls

Add `tenacity` to `pyproject.toml` (`tenacity>=9.0`) — nothing in this codebase currently
retries a rate-limited or transiently-failed OpenAI/Anthropic call; every one of these
just lets the exception propagate to the node's own generic `except Exception` fallback,
which silently swallows it into an apologetic in-character message rather than actually
retrying first.

Apply `@retry(...)` at the point of the actual API call, not at the node level (so
in-character fallback messages still only fire after retries are genuinely exhausted):

- `app/rag/embedder.py` — `Embedder.embed()`
- `ingestion/embedder.py` — `IngestEmbedder.embed_and_upsert()`'s batch call
- `app/rag/query_rewriter.py` — `QueryRewriter.rewrite()` (currently has a bare
  `except Exception` fallback to `[query]` — decide whether retry-then-fallback or
  fallback-without-retry is correct here; probably retry first, since a transient 429
  shouldn't immediately degrade to the un-rewritten query)
- `app/utils/specialist_llm.py` — `run_specialist()`'s `client.messages.create()` call
- `app/agents/guidance_of_grace.py` / `app/agents/maiden_melina.py` — their own separate
  `client.messages.create()` calls (they don't go through `run_specialist`)

Suggested policy, consistent across all of them:
```python
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type
from anthropic import RateLimitError, APIConnectionError
# (or openai.RateLimitError / openai.APIConnectionError for the OpenAI-calling ones)

@retry(
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
    wait=wait_random_exponential(min=1, max=20),
    stop=stop_after_attempt(4),
)
```
Only retry on rate-limit/connection errors — not on e.g. a genuine 400 from a malformed
request, which retrying won't fix and just wastes the budget of attempts.

---

## 3. HNSW query-time tuning

`002_vectors.sql` already sets `ef_construction = 64` at index-build time — that's fixed
once the index is built. `ef_search` is a **per-session runtime GUC**, not an index
param, and isn't set anywhere currently — Postgres uses its default (40) for every query.

In `app/db/repositories/vectors.py`'s `similarity_search()`, set it explicitly per
connection before the similarity query:
```python
async with self.pool.acquire() as conn:
    await register_vector(conn)
    await conn.execute("SET hnsw.ef_search = 100")  # tune this value against real data
    result = await conn.fetch(query, query_vector, entity_types, top_k)
```
Actual tuning value needs real ingested data to benchmark against (higher = better
recall, slower query) — 100 is a reasonable starting point to measure from, not a final
answer. Benchmark with `EXPLAIN ANALYZE` against a representative query set before
committing to a number.

---

## 4. Streaming support for the query endpoint

`QueryRequest.stream: bool` has existed since Phase 4 and has always been ignored.
LangGraph's compiled graph supports `.astream()` (state updates after each node) and
`.astream_events()` (finer-grained, including token-level streaming from within a node
if the underlying LLM call streams).

Given `GraphRunner` currently only exposes `.run()` (a single `ainvoke()`), add a second
method:
```python
# app/graph/runner.py
from typing import AsyncIterator

async def stream(self, session_id: str, player_query: str, build_state: dict) -> AsyncIterator[dict]:
    initial_state = self._build_initial_state(session_id, player_query, build_state)  # extract this from run()
    async for chunk in self._graph.astream(initial_state):
        yield chunk
```

In `app/api/routes/queries.py`, branch on `body.stream`:
```python
if body.stream:
    async def event_stream():
        async for chunk in runner.stream(session_id, body.query, build_state):
            yield f"data: {json.dumps(chunk, default=str)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```
Decide: does a streamed response still need to call `build_repo.update()` at the end
with the final accumulated state? Yes — the persistence step can't be skipped just
because the transport changed; the last chunk from `astream()` (or accumulating state
across chunks) needs to feed `updated_build_state` the same way the non-streaming path
does.

---

## 5. Load testing

Create `tests/load/locustfile.py`:
```python
from locust import HttpUser, task, between

class QueryUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        resp = self.client.post("/api/v1/sessions", json={"player_name": "LoadTestUser"})
        self.session_id = resp.json()["session_id"]

    @task
    def query(self):
        self.client.post(
            f"/api/v1/sessions/{self.session_id}/query",
            json={"query": "what stats should I prioritise for a bleed build"},
        )
```
Add `locust>=2.31` to `pyproject.toml`'s dev dependencies. Run against a real deployed
instance (not the ASGI test transport) — `locust -f tests/load/locustfile.py --host
http://localhost:8000`. Given every query round-trips through Claude + OpenAI, expect
this to surface API rate limits (which is exactly why section 2's retry/backoff needs to
land before this is meaningful) rather than pure infra bottlenecks.

---

## Order

```
1. Retry/backoff (section 2) — do this first; load testing without it just produces
   noise from rate-limit failures, not real signal
2. Observability (section 1) — instrument before load testing so the load test run
   itself produces useful traces to look at
3. HNSW tuning (section 3) — independent, can happen any time relative to the above
4. Streaming (section 4) — independent feature, no dependency on the others
5. Load testing (section 5) — do this last, once 1–2 are in place
```
