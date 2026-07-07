# Elden Ring Multi-Agent RAG System — Implementation Plan

---

## 1. Project Structure

```
elden-rag/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
│
├── app/
│   ├── __init__.py
│   ├── main.py                        # FastAPI app factory and lifespan
│   ├── config.py                      # Pydantic Settings from env vars
│   ├── dependencies.py                # FastAPI DI: DB pool, Redis, Langfuse
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── middleware.py              # CORS, request ID, error handlers
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── health.py              # GET /health
│   │       ├── sessions.py            # POST /api/v1/sessions
│   │       ├── queries.py             # POST /api/v1/sessions/{id}/query
│   │       └── builds.py             # GET + PUT /api/v1/sessions/{id}/build
│   │
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py                   # BuildState TypedDict + domain models
│   │   ├── builder.py                 # StateGraph assembly
│   │   ├── edges.py                   # Conditional edge routing functions
│   │   └── runner.py                  # Async graph invocation wrapper
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── guidance_of_grace.py        # Supervisor: intent classification + synthesis
│   │   ├── maiden_melina.py            # Onboarding: player profile interview, gates access
│   │   ├── rag_agent.py                # RAGAgent: query rewrite + retrieval + rerank
│   │   ├── master_hewg.py              # build_creation
│   │   ├── queen_rennala.py            # stat_prioritisation
│   │   ├── merchant_kale.py            # item_loot
│   │   ├── sir_gideon_ofnir.py         # boss_optimisation + status_effect (merged)
│   │   └── iron_fist_alexander.py      # combat_execution
│   │
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── guidance_of_grace.py
│   │   ├── maiden_melina.py
│   │   ├── rag_agent.py
│   │   ├── master_hewg.py
│   │   ├── queen_rennala.py
│   │   ├── merchant_kale.py
│   │   ├── sir_gideon_ofnir.py
│   │   └── iron_fist_alexander.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── api.py                     # Request/response Pydantic models
│   │   ├── build.py                   # BuildStats, WeaponSlot, etc.
│   │   └── rag.py                     # RagChunk, Citation, RetrievalResult
│   │
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── embedder.py                # OpenAI text-embedding-3-small wrapper
│   │   ├── retriever.py               # pgvector similarity + MMR search
│   │   ├── reranker.py                # Cross-encoder reranking
│   │   └── query_rewriter.py          # LLM-based query expansion
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── postgres.py                # asyncpg connection pool factory
│   │   ├── redis.py                   # aioredis client factory
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── sessions.py            # SessionRepository
│   │   │   ├── builds.py              # BuildRepository
│   │   │   └── vectors.py             # VectorRepository (upsert + search)
│   │   └── migrations/
│   │       ├── 001_init.sql           # sessions + builds tables
│   │       └── 002_vectors.sql        # documents + embeddings tables
│   │
│   └── observability/
│       ├── __init__.py
│       └── langfuse.py                # Langfuse client + @observe decorator helpers
│
├── ingestion/
│   ├── __init__.py
│   ├── scraper.py                     # Async HTTP scraper (aiohttp + BeautifulSoup4)
│   ├── cleaner.py                     # HTML → clean text normalisation
│   ├── chunker.py                     # Recursive character text splitter
│   ├── embedder.py                    # Batch embedding + pgvector upsert
│   ├── pipeline.py                    # Top-level orchestration entrypoint
│   └── sources/
│       ├── wiki_urls.txt
│       └── patch_notes_urls.txt
│
└── tests/
    ├── conftest.py                    # Fixtures: test DB, mock LLM, mock embedder
    ├── unit/
    │   ├── test_state.py
    │   ├── test_edges.py
    │   ├── test_retriever.py
    │   ├── test_query_rewriter.py
    │   └── test_agents.py
    └── integration/
        ├── test_graph.py
        └── test_api.py
```

---

## 2. LangGraph Topology

### ASCII Graph Diagram

Node names below are the literal `next_agent` / routing-dict keys — Guidance of Grace's
supervisor prompt emits these persona-flavored tokens directly, so the graph's node ids
match the prompt's own routing table verbatim (no translation layer between the two).

```
                        ┌─────────────────┐
                        │   Player Query  │
                        └────────┬────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
               ┌───│  guidance_of_grace       │◄──────────────────────┐
               │   │  (supervisor)            │                       │
               │   │  - Classify intents      │                       │
               │   │  - Pop intent queue      │                       │
               │   │  - Synthesise if done    │                       │
               │   └────────────────────────┘                        │
               │                │                                     │
               │   onboarding_completed == false ──┐                  │
               │                │                  ▼                  │
               │                │      ┌────────────────────────┐    │
               │                │      │  melina_onboarding      │────┘
               │                │      │  (no RAG round-trip —   │
               │                │      │   returns to supervisor │
               │                │      │   directly)             │
               │                │      └────────────────────────┘
               │                ▼
               │    ┌───────────┼──────────────┬──────────────┬──────┐
               │    │           │              │              │      │
               │    ▼           ▼              ▼              ▼      │
               │ ┌──────┐  ┌────────┐   ┌───────────┐  ┌───────────┐│
               │ │MASTER│  │ QUEEN  │   │  MERCHANT │  │ IRON FIST ││
               │ │ HEWG │  │RENNALA │   │   KALÉ    │  │ ALEXANDER ││
               │ └──┬───┘  └───┬────┘   └─────┬─────┘  └─────┬─────┘│
               │   │          │               │              │      │
               │   │      ┌───┴───────────┐   │              │      │
               │   │      │ SIR GIDEON    │   │              │      │
               │   │      │ OFNIR (boss + │   │              │      │
               │   │      │ status_effect)│   │              │      │
               │   │      └───┬───────────┘   │              │      │
               │   └──────────┼───────────────┼──────────────┘      │
               │              │ (every specialist calls RAG node)   │
               │              ▼                                     │
               │   ┌──────────────────────┐                        │
               │   │      RAG NODE        │                        │
               │   │  - Rewrite query     │                        │
               │   │  - Cosine search     │                        │
               │   │  - MMR diversify     │                        │
               │   │  - Cross-enc rerank  │                        │
               │   │  - Return citations  │                        │
               │   └──────────┬───────────┘                        │
               │              │ (returns to whichever specialist     │
               │              │  set `calling_agent`, then that      │
               │              │  specialist returns to supervisor)   │
               └──────────────┴────────────────────────────────────┘
                              │
                (supervisor decides: next intent or END)
                              │
                              ▼
                    ┌─────────────────┐
                    │ Synthesised     │
                    │ Final Response  │
                    └─────────────────┘
```

All 5 specialists (Hewg, Rennala, Kalé, Alexander, Gideon) are structurally identical:
phase 1 sets `calling_agent` and routes to RAG, phase 2 runs with `rag_context` populated
and returns to the supervisor. Melina is the one exception — she never touches RAG.

### Node Definitions

**File:** `app/graph/builder.py`

```python
from langgraph.graph import StateGraph, END
from app.graph.state import BuildState
from app.graph.edges import route_from_supervisor, route_from_specialist
from app.agents.guidance_of_grace import guidance_of_grace_node
from app.agents.maiden_melina import melina_onboarding_node
from app.agents.rag_agent import rag_node
from app.agents.master_hewg import master_hewg_build_node
from app.agents.queen_rennala import rennala_stats_node
from app.agents.merchant_kale import kale_loot_routes_node
from app.agents.sir_gideon_ofnir import gideon_all_knowing_node
from app.agents.iron_fist_alexander import alexander_combat_node


SPECIALISTS = [
    "master_hewg_build", "rennala_stats", "kale_loot_routes",
    "gideon_all_knowing", "alexander_combat",
]


def build_graph() -> StateGraph:
    graph = StateGraph(BuildState)

    graph.add_node("guidance_of_grace", guidance_of_grace_node)
    graph.add_node("melina_onboarding", melina_onboarding_node)
    graph.add_node("rag", rag_node)
    graph.add_node("master_hewg_build", master_hewg_build_node)
    graph.add_node("rennala_stats", rennala_stats_node)
    graph.add_node("kale_loot_routes", kale_loot_routes_node)
    graph.add_node("gideon_all_knowing", gideon_all_knowing_node)
    graph.add_node("alexander_combat", alexander_combat_node)

    graph.set_entry_point("guidance_of_grace")

    # Supervisor routes to onboarding, a specialist, or END
    graph.add_conditional_edges(
        "guidance_of_grace",
        route_from_supervisor,
        {
            "melina_onboarding": "melina_onboarding",
            "master_hewg_build": "master_hewg_build",
            "rennala_stats": "rennala_stats",
            "kale_loot_routes": "kale_loot_routes",
            "gideon_all_knowing": "gideon_all_knowing",
            "alexander_combat": "alexander_combat",
            END: END,
        },
    )

    # Melina never touches RAG — she always returns straight to the supervisor
    graph.add_edge("melina_onboarding", "guidance_of_grace")

    # Each specialist goes to RAG first, then back to the specialist via a
    # sub-routing edge, then returns to supervisor
    for specialist in SPECIALISTS:
        graph.add_conditional_edges(
            specialist,
            route_from_specialist,
            {"rag": "rag", "guidance_of_grace": "guidance_of_grace"},
        )

    # RAG always returns to the specialist that called it
    graph.add_conditional_edges(
        "rag",
        lambda s: s["calling_agent"],
        {
            "master_hewg_build": "master_hewg_build",
            "rennala_stats": "rennala_stats",
            "kale_loot_routes": "kale_loot_routes",
            "gideon_all_knowing": "gideon_all_knowing",
            "alexander_combat": "alexander_combat",
        },
    )

    return graph.compile()
```

### Edge Conditions

**File:** `app/graph/edges.py`

```python
from app.graph.state import BuildState


SPECIALIST_AGENTS = {
    "master_hewg_build", "rennala_stats", "kale_loot_routes",
    "gideon_all_knowing", "alexander_combat",
}
ONBOARDING_AGENT = "melina_onboarding"


def route_from_supervisor(state: BuildState) -> str:
    """Route supervisor output to onboarding, the next specialist, or END."""
    next_agent = state.get("next_agent", "END")
    if next_agent == "END":
        return "__end__"
    if next_agent != ONBOARDING_AGENT and next_agent not in SPECIALIST_AGENTS:
        return "__end__"
    return next_agent


def route_from_specialist(state: BuildState) -> str:
    """Route specialist: go to RAG if it hasn't been called yet, else return to supervisor."""
    if not state.get("rag_context") and not state.get("rag_results"):
        return "rag"
    return "guidance_of_grace"
```

---

## 3. Shared State Schema

**File:** `app/graph/state.py`

```python
from __future__ import annotations

from typing import Annotated, Optional
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class PlayerProfile(TypedDict):
    experience_level: str      # "total_beginner", "souls_veteran", "returning_player"
    skill_confidence: str      # "very_low", "low", "medium", "high", "very_high"
    preferred_archetype: str   # "HEAVY_MELEE", "FAST_AGGRESSIVE", "SPELLCASTER", "HYBRID"
    current_hurdle: Optional[str]  # e.g., "Stuck on Margit", "New Character"


class BuildStats(BaseModel):
    vigor: int = 10
    mind: int = 10
    endurance: int = 10
    strength: int = 10
    dexterity: int = 10
    intelligence: int = 10
    faith: int = 10
    arcane: int = 10

    @property
    def total_level(self) -> int:
        return sum(self.model_dump().values()) - 80  # offset by base total


class WeaponSlot(BaseModel):
    name: str
    affinity: Optional[str] = None
    upgrade_level: int = 0
    hand: str = "right"  # "right" | "left"


class Citation(BaseModel):
    source_url: str
    page_title: str
    section: str
    chunk_index: int


class RagChunk(BaseModel):
    content: str
    citation: Citation
    similarity_score: float


class BuildState(TypedDict):
    # ── Conversation ────────────────────────────────────────────
    messages: Annotated[list, add_messages]
    session_id: str
    player_query: str

    # ── Routing ─────────────────────────────────────────────────
    next_agent: str           # which node the supervisor sends to next
    calling_agent: str        # which specialist invoked the RAG node
    intent: list[str]         # all classified intents for this query
    intent_queue: list[str]   # remaining intents yet to be processed
    final_response: Optional[str]

    # ── Player Profile (onboarding) ───────────────────────────────
    onboarding_completed: bool
    player_profile: PlayerProfile
    current_level: Optional[int]

    # ── Build ────────────────────────────────────────────────────
    player_class: Optional[str]
    stats: Optional[BuildStats]
    weapons: list[WeaponSlot]
    talismans: list[str]
    spirit_ash: Optional[str]
    target_bosses: list[str]
    playstyle: Optional[str]  # e.g. "bleed dex", "int caster"

    # ── RAG ──────────────────────────────────────────────────────
    rag_query: Optional[str]           # rewritten query sent to retriever
    rag_results: list[RagChunk]        # ranked chunks with citations
    rag_context: Optional[str]         # formatted context string for agent

    # ── Agent outputs ────────────────────────────────────────────
    agent_responses: dict[str, str]    # keyed by agent name

    # ── Observability ────────────────────────────────────────────
    trace_id: Optional[str]
```

Onboarding-gated routing: Guidance of Grace (the supervisor) checks `onboarding_completed`
before classifying intent. While it's `false`, `next_agent` is forced to `melina_onboarding`
regardless of what the player asked — see `guidance_of_grace.py`'s prompt for the exact
wording of that rule.

**File:** `app/models/build.py`

```python
from pydantic import BaseModel, Field
from typing import Optional
from app.graph.state import BuildStats, WeaponSlot


class BuildStateResponse(BaseModel):
    player_class: Optional[str] = None
    stats: Optional[BuildStats] = None
    weapons: list[WeaponSlot] = Field(default_factory=list)
    talismans: list[str] = Field(default_factory=list)
    spirit_ash: Optional[str] = None
    target_bosses: list[str] = Field(default_factory=list)
    playstyle: Optional[str] = None


class BuildStateUpdate(BaseModel):
    player_class: Optional[str] = None
    stats: Optional[BuildStats] = None
    weapons: Optional[list[WeaponSlot]] = None
    talismans: Optional[list[str]] = None
    spirit_ash: Optional[str] = None
    target_bosses: Optional[list[str]] = None
    playstyle: Optional[str] = None
```

---

## 4. RAG Pipeline Design

### Ingestion Strategy

| Step | Tool / Library | Detail |
|------|---------------|--------|
| Scraping | `aiohttp` + `BeautifulSoup4` | Async batch, rate-limited (0.5 req/s per domain) |
| Cleaning | Custom cleaner | Strip nav, infoboxes, ads; keep body prose + tables |
| Chunking | `RecursiveCharacterTextSplitter` (LangChain) | 512 tokens, 50-token overlap, `cl100k_base` tokeniser |
| Embedding | OpenAI `text-embedding-3-small` | Batch of 100 chunks per API call |
| Storage | `pgvector` with HNSW index | `vector(1536)`, `ivfflat` for cosine similarity |

### Chunk Metadata Schema

Each chunk stored in pgvector carries:

```python
class ChunkMetadata(BaseModel):
    source_url: str
    page_title: str
    section_heading: str
    entity_type: str   # "boss" | "weapon" | "stat" | "item" | "mechanic" | "build" | "patch"
    last_scraped_at: datetime
    chunk_index: int
    token_count: int
```

### Retrieval Strategy

1. **Query Rewriting** (`app/rag/query_rewriter.py`)
   - LLM call with Claude claude-sonnet-4-6: expand abbreviations, add Elden Ring context, produce 3 query variants
   - Optionally use HyDE: generate a hypothetical answer chunk, embed that instead

2. **Primary Retrieval** (`app/rag/retriever.py`)
   - Cosine similarity search in pgvector, `top_k=20`
   - Metadata filter: restrict `entity_type` to domain of calling agent (e.g., boss_optimisation → `entity_type IN ('boss', 'mechanic')`)

3. **Diversification**
   - Apply MMR (Maximal Marginal Relevance) to top-20: λ=0.5, reduce to top-10

4. **Reranking** (`app/rag/reranker.py`)
   - Cross-encoder: `cross-encoder/ms-marco-MiniLM-L-6-v2` via `sentence-transformers`
   - Score each of the 10 candidates against the original query
   - Return top-5 with scores

5. **Citation Attachment**
   - Each returned chunk includes `Citation(source_url, page_title, section, chunk_index)`

### pgvector Schema

```sql
-- migrations/002_vectors.sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url  TEXT NOT NULL,
    page_title  TEXT NOT NULL,
    section     TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    content     TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    embedding   vector(1536),
    scraped_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX ON documents (entity_type);
```

---

## 5. Agent Prompt Templates

Prompt content is persona-driven rather than genre-generic — each specialist is written
as an in-universe Elden Ring character rather than a plainly-named role. The table below
is the current source of truth for which file backs which routing key; the full prompt
text lives in the actual files, not duplicated here, so there's only one place for it to
drift out of date.

| Routing key (`next_agent` / `calling_agent`) | Persona | File | Constant | Domain |
|---|---|---|---|---|
| `guidance_of_grace` (supervisor, entry point) | Guidance of Grace | `app/prompts/guidance_of_grace.py` | `GUIDANCE_OF_GRACE` | Intent classification, routing, synthesis |
| `melina_onboarding` | Maiden Melina | `app/prompts/maiden_melina.py` | `MAIDEN_MELINA` | Player profile interview; gates access until `onboarding_completed` |
| — (not a persona) | — | `app/prompts/rag_agent.py` | `RAG_CONTEXT_TEMPLATE` | Formats reranked chunks into `rag_context`; no LLM call |
| `master_hewg_build` | Master Hewg | `app/prompts/master_hewg.py` | `MASTER_HEWG` | build_creation — class, weapons, talismans, affinities |
| `rennala_stats` | Queen Rennala | `app/prompts/queen_rennala.py` | `QUEEN_RENNALA` | stat_prioritisation — soft caps, leveling roadmap |
| `kale_loot_routes` | Merchant Kalé | `app/prompts/merchant_kale.py` | `MERCHANT_KALE` | item_loot — acquisition routes, quest-lock warnings |
| `alexander_combat` | Iron Fist Alexander | `app/prompts/iron_fist_alexander.py` | `ALEXANDER_COMBAT_COACH_SYSTEM` | combat_execution — move-set piloting, stamina/FP, frame data |
| `gideon_all_knowing` | Sir Gideon Ofnir | `app/prompts/sir_gideon_ofnir.py` | `SIR_GIDEON_OFNIR` | boss_optimisation **and** status_effect (merged) — boss weaknesses, buff-stacking law, Bleed/Frost/Rot/Poison buildup math |

Notes for whoever implements the agent nodes (Steps 4–7 of `phase3_plan.md`):
- Melina, Hewg, Rennala, Alexander, and Gideon all end their `state_updates` output the
  same way the original generic-named specialists did — only the persona voice and the
  routing key changed, not the JSON contract.
- Gideon absorbing status_effect means his RAG entity-type filter must cover both boss
  and status/mechanic content — see the `ENTITY_TYPE_MAP` note in `phase3_plan.md` Step 5.
- `boss_optimisation`/`combat_execution`/`item_loot` are advisory-only (no `state_updates`),
  matching the original plan; Hewg and Rennala do modify build fields.

---

## 6. API Design

**File:** `app/models/api.py`

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.models.build import BuildStateResponse, BuildStateUpdate
from app.graph.state import Citation


class CreateSessionRequest(BaseModel):
    player_name: str
    starting_class: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str
    player_name: str
    created_at: datetime
    build_state: BuildStateResponse


class QueryRequest(BaseModel):
    query: str
    stream: bool = False


class QueryResponse(BaseModel):
    session_id: str
    response: str
    agents_used: list[str]
    citations: list[Citation]
    updated_build_state: BuildStateResponse
    trace_id: str


class BuildStateGetResponse(BaseModel):
    session_id: str
    build_state: BuildStateResponse
    updated_at: datetime


class BuildStateUpdateResponse(BaseModel):
    session_id: str
    build_state: BuildStateResponse
    updated_at: datetime


class HealthResponse(BaseModel):
    status: str
    postgres: bool
    redis: bool
    langfuse: bool
```

**File:** `app/api/routes/sessions.py`

```python
from fastapi import APIRouter, Depends
from app.models.api import CreateSessionRequest, CreateSessionResponse
from app.db.repositories.sessions import SessionRepository
from app.dependencies import get_session_repo

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.post("", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    repo: SessionRepository = Depends(get_session_repo),
) -> CreateSessionResponse:
    session = await repo.create(body.player_name, body.starting_class)
    return CreateSessionResponse(
        session_id=session.id,
        player_name=session.player_name,
        created_at=session.created_at,
        build_state=session.build_state,
    )
```

**File:** `app/api/routes/queries.py`

```python
from fastapi import APIRouter, Depends
from app.models.api import QueryRequest, QueryResponse
from app.graph.runner import GraphRunner
from app.dependencies import get_graph_runner, get_session_repo

router = APIRouter(prefix="/api/v1/sessions", tags=["queries"])


@router.post("/{session_id}/query", response_model=QueryResponse)
async def submit_query(
    session_id: str,
    body: QueryRequest,
    runner: GraphRunner = Depends(get_graph_runner),
    repo: SessionRepository = Depends(get_session_repo),
) -> QueryResponse:
    session = await repo.get(session_id)
    result = await runner.run(
        session_id=session_id,
        player_query=body.query,
        build_state=session.build_state,
    )
    await repo.update_build(session_id, result.updated_build_state)
    return result
```

**File:** `app/api/routes/builds.py`

```python
from fastapi import APIRouter, Depends
from app.models.api import BuildStateGetResponse, BuildStateUpdateResponse
from app.models.build import BuildStateUpdate
from app.db.repositories.builds import BuildRepository
from app.dependencies import get_build_repo

router = APIRouter(prefix="/api/v1/sessions", tags=["builds"])


@router.get("/{session_id}/build", response_model=BuildStateGetResponse)
async def get_build(
    session_id: str,
    repo: BuildRepository = Depends(get_build_repo),
) -> BuildStateGetResponse:
    build = await repo.get(session_id)
    return BuildStateGetResponse(
        session_id=session_id,
        build_state=build.to_response(),
        updated_at=build.updated_at,
    )


@router.put("/{session_id}/build", response_model=BuildStateUpdateResponse)
async def update_build(
    session_id: str,
    body: BuildStateUpdate,
    repo: BuildRepository = Depends(get_build_repo),
) -> BuildStateUpdateResponse:
    build = await repo.update(session_id, body)
    return BuildStateUpdateResponse(
        session_id=session_id,
        build_state=build.to_response(),
        updated_at=build.updated_at,
    )
```

---

## 7. Data Ingestion Pipeline

**File:** `ingestion/pipeline.py`

```python
import asyncio
import logging
from pathlib import Path
from ingestion.scraper import Scraper
from ingestion.cleaner import Cleaner
from ingestion.chunker import Chunker
from ingestion.embedder import IngestEmbedder

logger = logging.getLogger(__name__)

SOURCES_DIR = Path(__file__).parent / "sources"


async def run_pipeline(entity_type: str, urls_file: str) -> None:
    urls = (SOURCES_DIR / urls_file).read_text().splitlines()
    scraper = Scraper(rate_limit=0.5)
    cleaner = Cleaner()
    chunker = Chunker(chunk_size=512, chunk_overlap=50)
    embedder = IngestEmbedder(batch_size=100)

    async for url in scraper.iter_pages(urls):
        try:
            html = await scraper.fetch(url)
            text, metadata = cleaner.clean(html, source_url=url, entity_type=entity_type)
            chunks = chunker.split(text, base_metadata=metadata)
            await embedder.embed_and_upsert(chunks)
            logger.info("Ingested %d chunks from %s", len(chunks), url)
        except Exception:
            logger.exception("Failed to ingest %s", url)


async def main() -> None:
    await asyncio.gather(
        run_pipeline("boss",    "wiki_boss_urls.txt"),
        run_pipeline("weapon",  "wiki_weapon_urls.txt"),
        run_pipeline("stat",    "wiki_stat_urls.txt"),
        run_pipeline("item",    "wiki_item_urls.txt"),
        run_pipeline("mechanic","wiki_mechanic_urls.txt"),
        run_pipeline("patch",   "patch_notes_urls.txt"),
    )


if __name__ == "__main__":
    asyncio.run(main())
```

**File:** `ingestion/chunker.py`

```python
from dataclasses import dataclass
from typing import Any
from langchain_text_splitters import RecursiveCharacterTextSplitter
import tiktoken


@dataclass
class Chunk:
    content: str
    metadata: dict[str, Any]
    token_count: int


class Chunker:
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50) -> None:
        self._enc = tiktoken.get_encoding("cl100k_base")
        self._splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", ". ", " "],
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=lambda t: len(self._enc.encode(t)),
        )

    def split(self, text: str, base_metadata: dict[str, Any]) -> list[Chunk]:
        raw_chunks = self._splitter.split_text(text)
        return [
            Chunk(
                content=c,
                metadata={**base_metadata, "chunk_index": i},
                token_count=len(self._enc.encode(c)),
            )
            for i, c in enumerate(raw_chunks)
        ]
```

**File:** `ingestion/embedder.py`

```python
from openai import AsyncOpenAI
from app.db.repositories.vectors import VectorRepository
from ingestion.chunker import Chunk


class IngestEmbedder:
    def __init__(self, batch_size: int = 100) -> None:
        self._client = AsyncOpenAI()
        self._repo = VectorRepository()
        self._batch_size = batch_size

    async def embed_and_upsert(self, chunks: list[Chunk]) -> None:
        for i in range(0, len(chunks), self._batch_size):
            batch = chunks[i : i + self._batch_size]
            response = await self._client.embeddings.create(
                model="text-embedding-3-small",
                input=[c.content for c in batch],
            )
            vectors = [e.embedding for e in response.data]
            await self._repo.upsert_batch(batch, vectors)
```

---

## 8. Observability Setup

**File:** `app/observability/langfuse.py`

```python
from functools import wraps
from typing import Any, Callable
from langfuse import Langfuse
from langfuse.decorators import langfuse_context, observe
from app.config import settings

_langfuse = Langfuse(
    public_key=settings.LANGFUSE_PUBLIC_KEY,
    secret_key=settings.LANGFUSE_SECRET_KEY,
    host=settings.LANGFUSE_HOST,
)


def agent_span(name: str) -> Callable:
    """Decorator that wraps a LangGraph node function in a Langfuse span."""
    def decorator(fn: Callable) -> Callable:
        @observe(name=name)
        @wraps(fn)
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            langfuse_context.update_current_observation(
                input={
                    "player_query": state.get("player_query"),
                    "build_summary": _summarise_build(state),
                },
                metadata={"session_id": state.get("session_id")},
            )
            result = await fn(state)
            langfuse_context.update_current_observation(
                output={
                    "next_agent": result.get("next_agent"),
                    "response_preview": (result.get("final_response") or "")[:200],
                },
            )
            return result
        return wrapper
    return decorator


def rag_span(fn: Callable) -> Callable:
    """Decorator that instruments the RAG node with retrieval metrics."""
    @observe(name="rag_node")
    @wraps(fn)
    async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
        langfuse_context.update_current_observation(
            input={"rag_query": state.get("rag_query"), "calling_agent": state.get("calling_agent")},
        )
        result = await fn(state)
        chunks = result.get("rag_results", [])
        langfuse_context.update_current_observation(
            output={
                "chunks_retrieved": len(chunks),
                "top_score": chunks[0].similarity_score if chunks else None,
            },
        )
        return result
    return wrapper


def _summarise_build(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "class": state.get("player_class"),
        "playstyle": state.get("playstyle"),
        "level": state.get("stats", {}).get("total_level") if state.get("stats") else None,
    }
```

Usage in every agent node:

```python
# app/agents/master_hewg.py
from app.observability.langfuse import agent_span

@agent_span("master_hewg_build_agent")
async def master_hewg_build_node(state: BuildState) -> BuildState:
    ...
```

Langfuse trace structure per query (first-ever query for a session, onboarding not yet done):
```
Trace: session_id / player_query
  └── Span: guidance_of_grace_agent    (sees onboarding_completed=false, routes to Melina)
  └── Span: melina_onboarding_agent    (interview turn — no rag_node span, she skips RAG)
  └── Span: guidance_of_grace_agent    (onboarding still incomplete → END for this turn)
```

Langfuse trace structure per query (onboarding already complete):
```
Trace: session_id / player_query
  └── Span: guidance_of_grace_agent    (intent classification)
  └── Span: master_hewg_build_agent    (first intent)
      └── Span: rag_node               (retrieval for build)
  └── Span: rennala_stats_agent        (second intent)
      └── Span: rag_node               (retrieval for stats)
  └── Span: guidance_of_grace_agent    (synthesis)
```

---

## 9. Docker Compose Setup

**File:** `docker-compose.yml`

```yaml
version: "3.9"

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./app:/app/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: elden_rag
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./app/db/migrations:/docker-entrypoint-initdb.d
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres}"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  langfuse-worker:
    image: langfuse/langfuse-worker:3
    env_file: .env.langfuse
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  langfuse-web:
    image: langfuse/langfuse:3
    ports:
      - "3000:3000"
    env_file: .env.langfuse
    depends_on:
      postgres:
        condition: service_healthy
      langfuse-worker:
        condition: service_started

volumes:
  pg_data:
```

**File:** `.env.example`

```dotenv
# LLM
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=elden_rag
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# Redis
REDIS_URL=redis://redis:6379/0

# Langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://langfuse-web:3000
```

**File:** `.env.langfuse`

```dotenv
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/langfuse
REDIS_HOST=redis
REDIS_PORT=6379
NEXTAUTH_SECRET=change-me-in-production
NEXTAUTH_URL=http://localhost:3000
LANGFUSE_INIT_ORG_ID=elden-rag
LANGFUSE_INIT_PROJECT_ID=elden-rag-dev
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=pk-lf-dev
LANGFUSE_INIT_PROJECT_SECRET_KEY=sk-lf-dev
```

**File:** `Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system -e .

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 10. Implementation Phases

### Phase 1 — Foundation (Days 1–3)

**Goal:** Runnable skeleton with database connectivity and health check passing.

| Task | File(s) |
|------|---------|
| Docker Compose up with postgres + redis + langfuse | `docker-compose.yml` |
| SQL migrations | `app/db/migrations/001_init.sql`, `002_vectors.sql` |
| Pydantic Settings | `app/config.py` |
| asyncpg + aioredis connection factories | `app/db/postgres.py`, `app/db/redis.py` |
| FastAPI app factory with lifespan | `app/main.py` |
| Health endpoint (checks DB + Redis + Langfuse) | `app/api/routes/health.py` |
| BuildState TypedDict + domain models | `app/graph/state.py`, `app/models/` |

**Test:** `GET /health` returns 200 with all services `true`.

---

### Phase 2 — RAG Pipeline (Days 4–7)

**Goal:** Elden Ring knowledge base populated in pgvector with working retrieval.

| Task | File(s) |
|------|---------|
| URL lists for wiki and patch notes | `ingestion/sources/*.txt` |
| Async wiki scraper with rate limiting | `ingestion/scraper.py` |
| HTML cleaner (prose extraction) | `ingestion/cleaner.py` |
| Recursive character chunker | `ingestion/chunker.py` |
| Batch embedding + pgvector upsert | `ingestion/embedder.py` |
| Full ingestion pipeline orchestration | `ingestion/pipeline.py` |
| VectorRepository (upsert + cosine search) | `app/db/repositories/vectors.py` |
| OpenAI embedder wrapper | `app/rag/embedder.py` |
| Retriever (cosine + MMR) | `app/rag/retriever.py` |
| Cross-encoder reranker | `app/rag/reranker.py` |
| LLM query rewriter | `app/rag/query_rewriter.py` |

**Test:** Run ingestion pipeline; confirm >10k documents in pgvector. Write unit tests asserting retriever returns top-5 plausible chunks for sample queries ("Malenia weaknesses", "bleed build stats").

---

### Phase 3 — Agent Graph (Days 8–13)

**Goal:** Full LangGraph pipeline processes a query end-to-end.

| Task | File(s) |
|------|---------|
| Prompt templates for all 8 persona agents | `app/prompts/` |
| Guidance of Grace (supervisor): intent classification + synthesis | `app/agents/guidance_of_grace.py` |
| Maiden Melina (onboarding): profile interview, gates access | `app/agents/maiden_melina.py` |
| RAGAgent: query rewrite → retrieve → rerank → format | `app/agents/rag_agent.py` |
| 5 specialist agents (Hewg, Rennala, Kalé, Alexander, Gideon) | `app/agents/*.py` |
| Edge condition functions | `app/graph/edges.py` |
| StateGraph assembly | `app/graph/builder.py` |
| GraphRunner: async invocation + state extraction | `app/graph/runner.py` |

**Test:** Integration test with mock LLM confirming routing: guidance_of_grace → master_hewg_build → rag → master_hewg_build → guidance_of_grace (END). Test multi-intent query triggers two sequential specialist calls. Test onboarding gate: fresh session routes to melina_onboarding regardless of query until `onboarding_completed` is `true`.

---

### Phase 4 — API Layer (Days 14–17)

**Goal:** REST API fully wired to the graph; sessions and build state persisted.

| Task | File(s) |
|------|---------|
| SessionRepository (create, get, update) | `app/db/repositories/sessions.py` |
| BuildRepository (get, update) | `app/db/repositories/builds.py` |
| Sessions endpoint | `app/api/routes/sessions.py` |
| Query endpoint (graph invocation) | `app/api/routes/queries.py` |
| Build CRUD endpoints | `app/api/routes/builds.py` |
| Redis session caching (TTL 1 hour) | `app/dependencies.py` |
| FastAPI DI wiring | `app/dependencies.py` |
| CORS + error handling middleware | `app/api/middleware.py` |

**Test:** Integration tests: create session → POST query → verify response contains citations and `agents_used`. GET build returns persisted state. PUT build updates state.

---

### Phase 5 — Observability & Hardening (Days 18–21)

**Goal:** Full Langfuse tracing, reranker enabled, production-ready.

| Task | File(s) |
|------|---------|
| Langfuse client + `@agent_span` decorator | `app/observability/langfuse.py` |
| Instrument all agent nodes and RAG node | All `app/agents/*.py` |
| Enable cross-encoder reranking in retriever | `app/rag/retriever.py` |
| Add streaming support to query endpoint | `app/api/routes/queries.py` |
| Load testing (locust) against `/query` | `tests/load/` |
| Tune HNSW index params (`ef_search`) | `app/db/migrations/002_vectors.sql` |
| Error handling: retry on rate limit (OpenAI/Anthropic) | `app/rag/embedder.py`, all agents |

**Test:** Confirm Langfuse dashboard shows trace tree with spans per agent. Confirm median latency <4s on retrieval-only queries.

---

## Appendix — Key Dependencies (`pyproject.toml`)

```toml
[project]
name = "elden-rag"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "langgraph>=0.2",
    "langchain>=0.3",
    "langchain-anthropic>=0.2",
    "langchain-openai>=0.2",
    "langchain-text-splitters>=0.3",
    "anthropic>=0.34",
    "openai>=1.50",
    "asyncpg>=0.29",
    "pgvector>=0.3",
    "redis[hiredis]>=5.0",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "langfuse>=2.53",
    "sentence-transformers>=3.0",
    "aiohttp>=3.10",
    "beautifulsoup4>=4.12",
    "tiktoken>=0.7",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "ruff>=0.6",
    "mypy>=1.11",
]
```
