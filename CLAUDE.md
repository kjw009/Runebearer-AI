# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the API server (from repo root, with venv active)
.venv/bin/uvicorn app.main:app --reload --port 8000

# Run tests
.venv/bin/pytest

# Run a single test file
.venv/bin/pytest tests/integration/test_health.py

# Lint
.venv/bin/ruff check .

# Type check
.venv/bin/mypy app

# Start infrastructure (postgres + redis)
docker compose up postgres redis -d

# Start Langfuse observability stack
docker compose up langfuse-web langfuse-worker -d

# Run ingestion pipeline
.venv/bin/python -m ingestion.pipeline
```

## Architecture

This is a multi-agent RAG system built on LangGraph. A player sends a natural-language query about Elden Ring; a supervisor classifies it into one or more intents, routes to specialist agents in sequence, each specialist calls a shared RAG node for retrieval, then the supervisor synthesises a final response.

### Request flow

```
POST /api/v1/sessions/{id}/query
  → GraphRunner.run()
    → supervisor node  (intent classification, pops intent_queue)
    → specialist node  (build_creation / stat_prioritisation / item_loot / boss_optimisation / combat_execution / status_effect)
    → rag node         (query rewrite → cosine search → MMR → cross-encoder rerank)
    → specialist node  (generates agent response using rag_context)
    → supervisor node  (pops next intent or synthesises final_response)
```

### Key design decisions

- **RAG as a graph node, not a tool.** The RAG node sits in the LangGraph graph proper and is routed to by specialists via a `calling_agent` state field. After retrieval it returns to the specialist that called it.
- **`BuildState` is the single shared context.** It flows through every node as a `TypedDict` (`app/graph/state.py`). Routing fields (`next_agent`, `calling_agent`, `intent_queue`) live alongside domain fields (build stats, weapons) and RAG results in the same dict.
- **`messages` uses LangGraph's `add_messages` reducer** (`Annotated[list[BaseMessage], add_messages]`), which appends rather than replaces on each state update — required for correct conversation history in LangGraph.
- **Specialists route to RAG first, then back to supervisor.** `route_from_specialist` in `app/graph/edges.py` checks whether `rag_context` is already populated; if not it sends to `rag`, otherwise back to `supervisor`.

### Module map

| Directory | Purpose |
|-----------|---------|
| `app/graph/` | LangGraph state, graph assembly (`builder.py`), edge conditions (`edges.py`), async runner |
| `app/agents/` | One file per node: supervisor + 6 specialists + rag_agent |
| `app/prompts/` | Prompt templates, one file per agent |
| `app/rag/` | Embedder, retriever (cosine + MMR), cross-encoder reranker, query rewriter |
| `app/db/` | asyncpg pool, aioredis client, repositories (sessions, builds, vectors), SQL migrations |
| `app/api/` | FastAPI routes (health, sessions, queries, builds), CORS + error middleware |
| `app/models/` | Pydantic request/response models (`api.py`, `build.py`) |
| `app/observability/` | Langfuse client + `@agent_span` / `@rag_span` decorators |
| `ingestion/` | Standalone pipeline: scraper → cleaner → chunker → embedder → pgvector upsert |

### Database

- **PostgreSQL** (pgvector extension) — `sessions`, `builds`, and `documents` tables. Migrations in `app/db/migrations/` are mounted into the Postgres container via Docker Compose and run automatically on first start.
- **`documents` table** stores embeddings as `vector(1536)` (OpenAI `text-embedding-3-small`) with an HNSW index on cosine ops. Each row carries an `entity_type` column (`boss`, `weapon`, `stat`, `item`, `mechanic`, `patch`) used to filter retrieval by calling agent.
- **Redis** — session caching with 1-hour TTL (wired in `app/dependencies.py`).

### Config

All settings come from `.env` via `app/config.py` (Pydantic Settings). Required: `OPENAI_API_KEY`. Optional: `ANTHROPIC_API_KEY`, `OPENAI_BASE_URL`. Langfuse keys default to dev values.

### Testing

`tests/conftest.py` provides `db_pool` and `redis_client` session-scoped async fixtures that hit the real running containers — no mocks for infrastructure. Mock the LLM and embedder in unit tests instead.

### Implementation status

- **Phase 1 (Foundation):** Complete — health endpoint returns 200 with postgres + redis green.
- **Phase 2 (RAG Pipeline):** Not started — `ingestion/` is empty, `app/rag/` is empty, `app/db/repositories/vectors.py` does not exist.
- **Phases 3–5:** Not started.

Full implementation plan with class names and function signatures: `implementation_plan.md`.
