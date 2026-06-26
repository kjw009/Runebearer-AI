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
│   │   ├── supervisor.py              # SupervisorAgent: intent classification + synthesis
│   │   ├── rag_agent.py               # RAGAgent: query rewrite + retrieval + rerank
│   │   ├── build_creation.py          # BuildCreationAgent
│   │   ├── stat_prioritisation.py     # StatPrioritisationAgent
│   │   ├── item_loot.py               # ItemLootAgent
│   │   ├── boss_optimisation.py       # BossOptimisationAgent
│   │   ├── combat_execution.py        # CombatExecutionAgent
│   │   └── status_effect.py           # StatusEffectAgent
│   │
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── supervisor.py
│   │   ├── rag_agent.py
│   │   ├── build_creation.py
│   │   ├── stat_prioritisation.py
│   │   ├── item_loot.py
│   │   ├── boss_optimisation.py
│   │   ├── combat_execution.py
│   │   └── status_effect.py
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

```
                        ┌─────────────────┐
                        │   Player Query  │
                        └────────┬────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
               ┌───│     SUPERVISOR NODE     │◄──────────────────────┐
               │   │  - Classify intents     │                       │
               │   │  - Pop intent queue     │                       │
               │   │  - Synthesise if done   │                       │
               │   └────────────────────────┘                       │
               │                │                                    │
               │    ┌───────────┼────────────┐                      │
               │    │           │            │                      │
               │    ▼           ▼            ▼                      │
               │ ┌──────┐  ┌──────┐   ┌──────────┐                 │
               │ │BUILD │  │ STAT │   │  ITEM &  │                 │
               │ │CREAT.│  │PRIOR.│   │   LOOT   │                 │
               │ └──┬───┘  └──┬───┘   └────┬─────┘                 │
               │   │          │             │                       │
               │   └──────────┼─────────────┘                      │
               │              │ (all specialists call RAG node)     │
               │              ▼                                     │
               │   ┌──────────────────────┐                        │
               │   │      RAG NODE        │                        │
               │   │  - Rewrite query     │                        │
               │   │  - Cosine search     │                        │
               │   │  - MMR diversify     │                        │
               │   │  - Cross-enc rerank  │                        │
               │   │  - Return citations  │                        │
               │   └──────────┬───────────┘                        │
               │              │                                     │
               │   ┌──────────┼────────────┐                       │
               │   │          │            │                        │
               │   ▼          ▼            ▼                       │
               │ ┌──────┐  ┌──────┐  ┌─────────┐                  │
               │ │ BOSS │  │COMBAT│  │ STATUS  │                  │
               │ │OPTIM.│  │ EXEC.│  │ EFFECT  │                  │
               │ └──┬───┘  └──┬───┘  └────┬────┘                  │
               │   └──────────┼────────────┘                       │
               │              │ (return to supervisor)              │
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

### Node Definitions

**File:** `app/graph/builder.py`

```python
from langgraph.graph import StateGraph, END
from app.graph.state import BuildState
from app.graph.edges import route_from_supervisor, route_from_specialist
from app.agents.supervisor import supervisor_node
from app.agents.rag_agent import rag_node
from app.agents.build_creation import build_creation_node
from app.agents.stat_prioritisation import stat_prioritisation_node
from app.agents.item_loot import item_loot_node
from app.agents.boss_optimisation import boss_optimisation_node
from app.agents.combat_execution import combat_execution_node
from app.agents.status_effect import status_effect_node


def build_graph() -> StateGraph:
    graph = StateGraph(BuildState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("rag", rag_node)
    graph.add_node("build_creation", build_creation_node)
    graph.add_node("stat_prioritisation", stat_prioritisation_node)
    graph.add_node("item_loot", item_loot_node)
    graph.add_node("boss_optimisation", boss_optimisation_node)
    graph.add_node("combat_execution", combat_execution_node)
    graph.add_node("status_effect", status_effect_node)

    graph.set_entry_point("supervisor")

    # Supervisor routes to a specialist or END
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "build_creation": "build_creation",
            "stat_prioritisation": "stat_prioritisation",
            "item_loot": "item_loot",
            "boss_optimisation": "boss_optimisation",
            "combat_execution": "combat_execution",
            "status_effect": "status_effect",
            END: END,
        },
    )

    # Each specialist goes to RAG first, then back to the specialist via a
    # sub-routing edge, then returns to supervisor
    for specialist in [
        "build_creation", "stat_prioritisation", "item_loot",
        "boss_optimisation", "combat_execution", "status_effect",
    ]:
        graph.add_conditional_edges(
            specialist,
            route_from_specialist,
            {"rag": "rag", "supervisor": "supervisor"},
        )

    # RAG always returns to the specialist that called it
    graph.add_conditional_edges(
        "rag",
        lambda s: s["calling_agent"],
        {
            "build_creation": "build_creation",
            "stat_prioritisation": "stat_prioritisation",
            "item_loot": "item_loot",
            "boss_optimisation": "boss_optimisation",
            "combat_execution": "combat_execution",
            "status_effect": "status_effect",
        },
    )

    return graph.compile()
```

### Edge Conditions

**File:** `app/graph/edges.py`

```python
from app.graph.state import BuildState


SPECIALIST_AGENTS = {
    "build_creation", "stat_prioritisation", "item_loot",
    "boss_optimisation", "combat_execution", "status_effect",
}


def route_from_supervisor(state: BuildState) -> str:
    """Route supervisor output to next specialist or END."""
    next_agent = state.get("next_agent", "END")
    if next_agent == "END" or next_agent not in SPECIALIST_AGENTS:
        return "__end__"
    return next_agent


def route_from_specialist(state: BuildState) -> str:
    """Route specialist: go to RAG if it hasn't been called yet, else return to supervisor."""
    if not state.get("rag_context") and not state.get("rag_results"):
        return "rag"
    return "supervisor"
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

**File:** `app/prompts/supervisor.py`

```python
SUPERVISOR_SYSTEM = """\
You are the Elden Ring AI Game Master coordinating specialist agents to help players \
optimise their journey through the Lands Between.

## Current Build State
{build_state_summary}

## Available Specialist Agents
- build_creation       — character builds, class selection, weapon/armour combos
- stat_prioritisation  — soft cap / hard cap investment advice
- item_loot            — item locations, acquisition methods, NPC questlines
- boss_optimisation    — boss strategies, weaknesses, phase transitions
- combat_execution     — moment-to-moment mechanics, timing, stamina management
- status_effect        — bleed, poison, frost, rot, madness — application and countering

## Instructions
1. Classify the player's query into one or more of the agents above.
2. Populate `intent` (full list) and `intent_queue` (ordered by relevance).
3. If all intents have been addressed (intent_queue is empty), set next_agent to "END" \
and synthesise a final response from agent_responses.
4. Otherwise pop the first intent from intent_queue, set next_agent accordingly.

Respond with valid JSON only:
{{
  "intents": ["<agent_name>", ...],
  "intent_queue": ["<next_agent>", ...],
  "next_agent": "<agent_name> | END",
  "reasoning": "<one sentence>",
  "final_response": "<synthesised response if next_agent == END, else null>"
}}
"""

SUPERVISOR_HUMAN = "Player query: {player_query}"
```

**File:** `app/prompts/rag_agent.py`

```python
RAG_SYSTEM = """\
You are the Elden Ring knowledge retrieval specialist. Your sole task is to synthesise \
the retrieved knowledge base chunks into a concise, factual context block.

Calling agent: {calling_agent}
Build context: {build_state_summary}

## Retrieved Chunks
{retrieved_chunks}

Rules:
- Include every relevant fact from the chunks.
- Attach a citation tag [source_N] after each fact, where N maps to the chunk index.
- Do not hallucinate facts not present in the chunks.
- Output plain prose, not bullet points.
"""
```

**File:** `app/prompts/build_creation.py`

```python
BUILD_CREATION_SYSTEM = """\
You are the Build Creation specialist for Elden Ring. You design optimal character \
builds from the ground up or refine existing ones based on the player's desired playstyle.

## Current Build State
{build_state_json}

## Knowledge Base Context
{rag_context}

## Instructions
- Recommend starting class if player_class is null.
- Propose stat targets at key soft caps (Vigor 40→60, damage stats 40→60→80).
- Suggest primary and backup weapons with affinity (e.g., Cold Uchigatana, Blood Nagakiba).
- Recommend 4 talismans with reasoning.
- Set spirit_ash recommendation.
- Conclude with a `state_updates` JSON block updating player_class, stats, weapons, \
talismans, spirit_ash, and playstyle.

Output format:
<reasoning>
...prose explanation...
</reasoning>
<state_updates>
{{ "player_class": "...", "stats": {{...}}, "weapons": [...], "talismans": [...], \
"spirit_ash": "...", "playstyle": "..." }}
</state_updates>
"""
```

**File:** `app/prompts/stat_prioritisation.py`

```python
STAT_SOFT_CAPS = {
    "vigor":        [40, 60],
    "mind":         [55, 60],
    "endurance":    [50, 60],
    "strength":     [54, 80],
    "dexterity":    [55, 80],
    "intelligence": [60, 80],
    "faith":        [60, 80],
    "arcane":       [45, 60, 80],
}

STAT_PRIORITISATION_SYSTEM = """\
You are the Stat Prioritisation specialist for Elden Ring. You advise on stat investment \
given diminishing returns at soft caps and hard caps.

## Soft / Hard Cap Reference
{soft_cap_table}

## Current Build State
{build_state_json}

## Knowledge Base Context
{rag_context}

## Instructions
- Identify which stats are below their first soft cap and prioritise those.
- Explain the ROI curve at each threshold.
- Propose a level-by-level investment roadmap until the next soft cap milestone.
- Note two-hand Strength formula (effective STR = floor(STR × 1.5)).
- Output state_updates with updated stats.
"""
```

**File:** `app/prompts/item_loot.py`

```python
ITEM_LOOT_SYSTEM = """\
You are the Item & Loot specialist for Elden Ring. You know the acquisition method, \
location, and stat requirements for every weapon, armour set, talisman, and key item.

## Current Build State
{build_state_json}

## Knowledge Base Context
{rag_context}

## Instructions
- For each requested item, give: location, NPC/questline dependency, enemy drop rate if applicable.
- Flag items gated behind missable questlines.
- Note stat requirements vs current build.
- If multiple viable options exist, rank by accessibility.
"""
```

**File:** `app/prompts/boss_optimisation.py`

```python
BOSS_OPTIMISATION_SYSTEM = """\
You are the Boss Optimisation specialist for Elden Ring. You provide precise strategies \
for defeating bosses given the player's current build.

## Current Build State
{build_state_json}

## Knowledge Base Context
{rag_context}

## Instructions
- State boss HP, phase thresholds, and immunity/weakness to damage types and status effects.
- Recommend summon (spirit ash or co-op) based on build.
- Describe punish windows by move name.
- Advise on positioning for each phase.
- Suggest one-time consumable usage (Preserving Boluses, Clarifying Horn Charm, etc.).
"""
```

**File:** `app/prompts/combat_execution.py`

```python
COMBAT_EXECUTION_SYSTEM = """\
You are the Combat Execution specialist for Elden Ring. You advise on moment-to-moment \
mechanics: timing, stamina management, poise, hyper-armour, and attack chains.

## Current Build State
{build_state_json}

## Knowledge Base Context
{rag_context}

## Instructions
- Reference specific weapon movesets (e.g., "R2 → R1 follow-up on Greatsword").
- Advise on poise thresholds for hyper-armour on heavy weapons.
- Explain roll timing windows (iframes: 13 on regular, 17 on quick roll).
- Describe stamina cost per attack type and recommend stamina management patterns.
- Cover guard counter opportunities where applicable.
"""
```

**File:** `app/prompts/status_effect.py`

```python
STATUS_EFFECT_SYSTEM = """\
You are the Status Effect specialist for Elden Ring. You advise on applying, stacking, \
and countering bleed, poison, scarlet rot, frost, sleep, and madness.

## Current Build State
{build_state_json}

## Knowledge Base Context
{rag_context}

## Instructions
- Give buildup thresholds for target enemies/bosses (scaled by resistance stat).
- Explain proc damage formulas (e.g., bleed: 15% + flat 150 HP).
- List optimal weapons, incantations, and sorceries for proc application.
- State proc duration and whether it can re-stack immediately.
- Advise on countering status effects (consumables, talismans, armour sets).
"""
```

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
# app/agents/build_creation.py
from app.observability.langfuse import agent_span

@agent_span("build_creation_agent")
async def build_creation_node(state: BuildState) -> BuildState:
    ...
```

Langfuse trace structure per query:
```
Trace: session_id / player_query
  └── Span: supervisor_agent          (intent classification)
  └── Span: build_creation_agent      (first intent)
      └── Span: rag_node              (retrieval for build)
  └── Span: stat_prioritisation_agent (second intent)
      └── Span: rag_node              (retrieval for stats)
  └── Span: supervisor_agent          (synthesis)
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
| Prompt templates for all 8 agents | `app/prompts/` |
| SupervisorAgent: intent classification + synthesis | `app/agents/supervisor.py` |
| RAGAgent: query rewrite → retrieve → rerank → format | `app/agents/rag_agent.py` |
| All 6 specialist agents | `app/agents/*.py` |
| Edge condition functions | `app/graph/edges.py` |
| StateGraph assembly | `app/graph/builder.py` |
| GraphRunner: async invocation + state extraction | `app/graph/runner.py` |

**Test:** Integration test with mock LLM confirming routing: supervisor → build_creation → rag → build_creation → supervisor (END). Test multi-intent query triggers two sequential specialist calls.

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
