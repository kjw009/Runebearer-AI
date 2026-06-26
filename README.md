# Elden Ring RAG System

A multi-agent RAG (Retrieval-Augmented Generation) system that answers natural-language questions about Elden Ring — build optimisation, boss strategies, stat prioritisation, item locations, and combat mechanics. A player sends a query; a graph of AI agents classifies it, retrieves relevant knowledge from a vector database populated from the Elden Ring wiki, and synthesises a grounded response.

---

## What it does

```
"What stats should I prioritise for a bleed dex build and how do I beat Malenia?"
        │
        ▼
  Supervisor classifies → [stat_prioritisation, boss_optimisation]
        │
        ▼
  stat_prioritisation agent → RAG node (retrieves soft-cap docs) → generates stat advice
        │
        ▼
  boss_optimisation agent → RAG node (retrieves Malenia docs) → generates boss strategy
        │
        ▼
  Supervisor synthesises both responses into a single answer with citations
```

---

## Architecture

### Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI |
| Agent graph | LangGraph |
| LLM | Claude (Anthropic) |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector store | PostgreSQL + pgvector (HNSW index, cosine similarity) |
| Session cache | Redis |
| Observability | Langfuse |
| Scraping | aiohttp + BeautifulSoup4 |

### Agent graph

The core of the system is a LangGraph `StateGraph`. All nodes share a single `BuildState` dict — the player's class, stats, weapons, and RAG results all live there and flow through every node.

```
                    ┌─────────────────────┐
                    │   SUPERVISOR NODE   │ ◄──────────────────┐
                    │  classify intents   │                    │
                    │  pop intent queue   │                    │
                    │  synthesise if done │                    │
                    └────────────┬────────┘                    │
                                 │                             │
              ┌──────────────────┼──────────────────┐         │
              ▼                  ▼                  ▼         │
        build_creation   stat_prioritisation   item_loot      │
        boss_optimisation  combat_execution   status_effect    │
              │                  │                  │         │
              └──────────────────┼──────────────────┘         │
                                 ▼                            │
                          ┌─────────────┐                     │
                          │  RAG NODE   │                     │
                          │  rewrite    │                     │
                          │  retrieve   │                     │
                          │  MMR        │                     │
                          │  rerank     │                     │
                          └──────┬──────┘                     │
                                 │ (returns to calling agent) │
                                 └────────────────────────────┘
```

**Routing logic:**
- Supervisor pops the first intent from `intent_queue` and sets `next_agent`.
- Each specialist checks whether `rag_context` is already populated. If not, it routes to the RAG node first, then gets called again with context in hand.
- After generating its response, the specialist returns to the supervisor, which pops the next intent or synthesises the final answer.

### RAG pipeline

**Ingestion** (run once, offline):
```
Wiki URLs → scraper → HTML cleaner → chunker (512 tokens, 50 overlap)
         → OpenAI embeddings (batch 100) → pgvector upsert
```

**Retrieval** (per query, inside the RAG node):
```
player query → LLM query rewriter (3 expanded variants)
             → embed → cosine similarity (top-20)
             → MMR diversification (→ top-10)
             → cross-encoder reranker (ms-marco-MiniLM-L-6-v2) (→ top-5)
             → format as context string with [source_N] citations
```

Each retrieved chunk carries metadata: `source_url`, `page_title`, `section`, `entity_type`, `chunk_index`. Retrieval is filtered by `entity_type` to match the calling specialist (e.g. `boss_optimisation` only searches `entity_type IN ('boss', 'mechanic')`).

---

## Project structure

```
elden-rag/
├── app/
│   ├── main.py                 # FastAPI app factory + lifespan hooks
│   ├── config.py               # Pydantic Settings (from .env)
│   ├── dependencies.py         # FastAPI DI: DB pool, Redis, graph runner
│   │
│   ├── api/routes/             # health, sessions, queries, builds
│   ├── graph/                  # LangGraph state, builder, edges, runner
│   ├── agents/                 # supervisor + 6 specialists + rag_agent
│   ├── prompts/                # prompt templates, one file per agent
│   ├── models/                 # Pydantic request/response models
│   ├── rag/                    # embedder, retriever, reranker, query_rewriter
│   ├── db/
│   │   ├── postgres.py         # asyncpg connection pool
│   │   ├── redis.py            # aioredis client
│   │   ├── repositories/       # sessions, builds, vectors (SQL access layer)
│   │   └── migrations/         # 001_init.sql, 002_vectors.sql
│   └── observability/          # Langfuse client + @agent_span decorator
│
├── ingestion/                  # standalone pipeline: scrape → embed → store
│   ├── scraper.py
│   ├── cleaner.py
│   ├── chunker.py
│   ├── embedder.py
│   ├── pipeline.py
│   └── sources/                # wiki_*.txt and patch_notes_urls.txt
│
└── tests/
    ├── unit/                   # state, edges, retriever, query rewriter, agents
    └── integration/            # graph end-to-end, API endpoints
```

---

## Database schema

```sql
-- sessions and build state
sessions  (id, player_name, created_at, updated_at)
builds    (session_id → sessions, player_class, stats JSONB, weapons JSONB,
           talismans JSONB, spirit_ash, target_bosses JSONB, playstyle, updated_at)

-- knowledge base (pgvector)
documents (id, source_url, page_title, section, entity_type,
           content, token_count, chunk_index,
           embedding vector(1536),   -- HNSW index, cosine ops
           scraped_at)
```

`entity_type` is one of: `boss`, `weapon`, `stat`, `item`, `mechanic`, `build`, `patch`.

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Postgres + Redis + Langfuse status |
| `POST` | `/api/v1/sessions` | Create a new player session |
| `POST` | `/api/v1/sessions/{id}/query` | Submit a query, get a grounded response |
| `GET` | `/api/v1/sessions/{id}/build` | Retrieve current build state |
| `PUT` | `/api/v1/sessions/{id}/build` | Manually update build state |

### Example query response

```json
{
  "session_id": "...",
  "response": "For a bleed dex build, prioritise Dexterity to 55 (first soft cap)...",
  "agents_used": ["stat_prioritisation", "boss_optimisation"],
  "citations": [
    { "source_url": "...", "page_title": "Dexterity", "section": "Soft Caps", "chunk_index": 2 }
  ],
  "updated_build_state": { "playstyle": "bleed dex", "stats": { "dexterity": 55, ... } },
  "trace_id": "..."
}
```

---

## Running locally

```bash
# 1. Start infrastructure
docker compose up postgres redis -d

# 2. Start Langfuse observability (optional)
docker compose up langfuse-web langfuse-worker -d

# 3. Copy and fill in environment variables
cp .env.example .env

# 4. Install dependencies
uv pip install -e ".[dev]"

# 5. Run the API server
uvicorn app.main:app --reload --port 8000

# 6. Run the ingestion pipeline (populates pgvector — requires OPENAI_API_KEY)
python -m ingestion.pipeline
```

---

## Implementation status

| Phase | Description | Status |
|---|---|---|
| 1 | Foundation — FastAPI, DB, health endpoint | Complete |
| 2 | RAG pipeline — ingestion + retrieval | In progress |
| 3 | Agent graph — supervisor, specialists, routing | Not started |
| 4 | API layer — sessions, queries, build CRUD | Not started |
| 5 | Observability & hardening — Langfuse, streaming, load tests | Not started |
