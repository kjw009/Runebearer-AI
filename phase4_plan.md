# Phase 4 Learning Plan — API Layer

Phase 3 gave you a working graph: a supervisor that classifies and routes, an onboarding
gate, five specialists, and a RAG node — all wired together and invocable via
`GraphRunner`. Phase 4 is where that graph becomes a real API a player can actually talk
to over HTTP, with state persisted between requests.

The goal is not just "wire up some endpoints." The goal is to understand *why* a thin API
layer sitting in front of a stateful graph needs the specific pieces it needs — a
repository layer, a cache, and a dependency-injection wiring point — so you can reason
about this pattern in any backend, not just this one.

Each step has: a concept to understand first, a task to implement, and a verification
step.

---

## What already exists (don't redo this)

- `app/models/build.py`, `app/models/api.py` — response/request Pydantic models already
  defined (`BuildStateResponse`, `QueryRequest`, `QueryResponse`, session models, etc.)
- `app/db/migrations/001_init.sql` — `sessions` and `builds` tables already exist
- `app/api/routes/health.py` — health endpoint already complete (Phase 1)
- `app/api/middleware.py` — CORS + a catch-all exception handler already registered
- `app/dependencies.py` — `get_db`/`get_redis` providers already exist, plus module-level
  `set_pool`/`set_redis` used by `main.py`'s lifespan

---

## The map

```
Step 1 → Understand the request lifecycle (HTTP → repo → graph → repo → HTTP)
Step 2 → Migration: add onboarding fields to the builds table
Step 3 → SessionRepository       (create, get)
Step 4 → BuildRepository         (get, update — including onboarding fields)
Step 5 → Redis cache-aside layer (1-hour TTL on build state reads)
Step 6 → Dependency wiring       (app/dependencies.py + main.py lifespan)
Step 7 → Sessions endpoint       (POST /api/v1/sessions)
Step 8 → Query endpoint          (POST /api/v1/sessions/{id}/query — the real integration point)
Step 9 → Build CRUD endpoints    (GET + PUT /api/v1/sessions/{id}/build)
Step 10 → Integration test       (create session → query → verify persisted state)
```

---

## Step 1 — Understand the request lifecycle

### Understand first

A query request has to travel through several distinct layers, and each layer exists to
solve one specific problem:

```
HTTP request
  → FastAPI route handler (parses/validates the request body)
  → BuildRepository.get() (load this session's persisted build fields)
  → GraphRunner.run()     (the actual LangGraph invocation — this is all of Phase 3)
  → BuildRepository.update() (persist whatever changed)
  → HTTP response
```

Answer these before writing any code:

- `GraphRunner.run()` takes a `build_state: dict` parameter and returns an
  `updated_build_state` dict (see `app/graph/runner.py`, already written). Where does
  the *first* `build_state` dict for a brand-new session come from, before any query has
  ever been run? (Hint: look at what `BuildRepository.get()` would return for a session
  row that was just inserted with all-default columns.)
- Why does the repository layer exist at all — why not just have the route handler run
  raw SQL directly? (Hint: think about what Step 5's caching layer needs to wrap, and
  what Phase 3's tests would need to mock.)
- `BuildState.session_id` is a plain string field the graph carries around, but nothing
  in Phase 3 ever reads or writes it meaningfully inside a node. Why does it need to be
  in the state at all, if no *node* uses it? (Hint: think about observability — Langfuse
  traces, Phase 5 — and about what a specialist's error log message might want to
  reference.)

### No implementation in this step

Just read `app/graph/runner.py` and `app/models/build.py` in full, and answer the
questions above.

### Verify

Without looking at any code, draw the full round-trip on paper for the query
`"what stats should I prioritise"` on a *returning* session (onboarding already done,
some stats already set). Label which layer reads from Postgres, which layer calls Claude,
and which layer writes back to Postgres.

---

## Step 2 — Migration: add onboarding fields to the builds table

### Understand first

`BuildState` (Phase 3) has `onboarding_completed: bool`, `player_profile: PlayerProfile`,
and `current_level: Optional[int]` — but `001_init.sql`'s `builds` table only has
`player_class`, `stats`, `weapons`, `talismans`, `spirit_ash`, `target_bosses`,
`playstyle`. That table predates Melina's onboarding system entirely.

If you don't fix this, here's exactly what breaks: `BuildRepository.get()` would have no
column to read `onboarding_completed` from, so it would have to default to `False` on
*every* load — meaning a player who already completed onboarding last week would get
routed straight back to Melina's interview on their very next query, forever.

Look at how `stats`, `weapons`, and `talismans` are already stored — as `JSONB` — and
decide whether `player_profile` (a small nested object: `experience_level`,
`skill_confidence`, `preferred_archetype`, `current_hurdle`) should follow the same
pattern.

### Implement

Create `app/db/migrations/003_onboarding.sql`. Things to figure out:
- `onboarding_completed` — a plain column type, with a default that makes sense for a
  brand-new row.
- `player_profile` — `JSONB`, following the existing convention.
- `current_level` — a plain integer column, nullable (a fresh character has no level yet).
- Should this migration also backfill existing rows, or is `IF NOT EXISTS` /
  column-level defaults enough since there's no production data yet?

### Verify

Restart your Postgres container (`docker compose up postgres -d` after a fresh volume,
or manually apply the migration) and confirm `\d builds` in `psql` shows all three new
columns with sane defaults.

---

## Step 3 — SessionRepository (`app/db/repositories/sessions.py`)

### Understand first

Look at `VectorRepository` (`app/db/repositories/vectors.py`) for the established
pattern in this codebase: constructor takes a `pool: asyncpg.Pool`, methods `acquire()` a
connection per call, parameterized queries via `$1, $2, ...`. `SessionRepository` follows
the same shape, just against the `sessions` table instead of `documents`.

A session needs exactly two operations for what Phase 4 requires: `create` (a new player
starting up) and `get` (loading an existing session by id).

### Implement

```python
# app/db/repositories/sessions.py

class SessionRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def create(self, player_name: str) -> dict:
        # INSERT into sessions, RETURNING the full row
        # Also INSERT a corresponding row into builds (session_id FK) with all
        # defaults — a session without a builds row would make Step 4's get() fail
        ...

    async def get(self, session_id: str) -> Optional[dict]:
        # SELECT the session row; return None if it doesn't exist
        # (the route handler decides whether that's a 404)
        ...
```

Things to figure out:
- Since `builds.session_id` is a foreign key to `sessions.id`, does `create()` need to
  do two separate `INSERT`s in one transaction, or can you structure the SQL as a single
  statement? (Hint: look at Postgres's `WITH ... AS` / CTE syntax, or just do two
  `execute()` calls inside one `async with self.pool.acquire() as conn:` block using
  `conn.transaction()`.)
- What should `get()` return if the session doesn't exist — raise, or return `None` and
  let the caller decide? (Hint: `VectorRepository`'s methods never have to make this
  call, since a similarity search returning zero rows isn't an error. A session lookup
  is different — think about what a 404 vs. a 500 should look like from the API.)

### Verify

Write a small script that creates a session, then fetches it back by id, and prints
both. Confirm the returned session id round-trips correctly and that a random UUID that
was never created returns `None`.

---

## Step 4 — BuildRepository (`app/db/repositories/builds.py`)

### Understand first

This is the repository `GraphRunner` actually depends on for its `build_state` input,
and the one that persists `updated_build_state` afterward. It needs to translate between
two different shapes:

- **Postgres row** — flat columns, `JSONB` for `stats`/`weapons`/`talismans`/`player_profile`
- **`BuildState`-shaped dict** — `stats` as a `BuildStats` Pydantic model,
  `weapons` as `list[WeaponSlot]`, `player_profile` as a plain nested dict

Answer before implementing: when `asyncpg` reads a `JSONB` column back, what Python type
do you get — a string, or an already-parsed dict/list? (Hint: check whether this project
registers a JSON codec anywhere, e.g. alongside `register_vector()` in
`VectorRepository`, or whether you'll need `json.loads()` yourself.)

### Implement

```python
# app/db/repositories/builds.py

class BuildRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def get(self, session_id: str) -> dict:
        # SELECT the builds row, convert JSONB columns + stats into the shapes
        # GraphRunner.run()'s build_state parameter expects
        ...

    async def update(self, session_id: str, updated_build_state: dict) -> None:
        # UPSERT (or plain UPDATE, since create() already inserted the row) all
        # the fields GraphRunner returned in updated_build_state
        ...
```

Things to figure out:
- `stats` comes back from `GraphRunner` as a `BuildStats` Pydantic model (or `None`).
  What do you call on it to get something `asyncpg` can serialize into `JSONB`?
- `weapons` is `list[WeaponSlot]` — same question, but for a list of models.
- If `update()` is called with a `build_state` dict where `stats` is still `None`
  (nothing set it yet this turn), should the column be overwritten with `NULL`, or
  left alone? Which one matches what `GraphRunner.run()` actually returns in
  `updated_build_state` — does it return *all* fields every time, or only changed ones?
  (Go re-read `runner.py`'s return statement to answer this precisely — it matters for
  whether a plain `UPDATE ... SET x = $1` is safe here.)

### Verify

Write a script: create a session, call `BuildRepository.update()` with a fake
`updated_build_state` dict containing a `BuildStats` instance and a couple of
`WeaponSlot`s, then call `get()` and confirm the round-tripped dict has real
`BuildStats`/`WeaponSlot` objects (not raw JSON strings) with the same values.

---

## Step 5 — Redis cache-aside layer

### Understand first

`CLAUDE.md` specifies a 1-hour TTL on session caching. The pattern is *cache-aside*: on
a read, check Redis first; on a miss, fall back to Postgres and populate the cache; on a
write, update Postgres and either update or invalidate the cache entry.

Answer first:
- Why cache the *build state* specifically, rather than caching, say, the RAG retrieval
  results? (Hint: which one gets read on literally every single query for a session,
  and which one varies per query?)
- What's the cache key naming scheme going to be — plain `session_id`, or something
  namespaced like `f"build_state:{session_id}"`? Why does namespacing matter once you
  have more than one thing you might want to cache under a session id?
- What happens on a cache hit if the *underlying schema* changed (e.g. you just ran
  Step 2's migration and old cached entries don't have the new fields)? Is this a real
  risk given the TTL, or a non-issue?

### Implement

Decide where this lives: a thin wrapper class (`CachedBuildRepository`) that composes
`BuildRepository` and a `redis.asyncio.Redis` client, or a decorator-style function.
Given this codebase's existing style (plain classes over decorators), a wrapper class
composing `BuildRepository` fits better.

```python
# app/db/repositories/builds.py (or a new cached_builds.py — your call)

class CachedBuildRepository:
    def __init__(self, repo: BuildRepository, redis: aioredis.Redis, ttl_seconds: int = 3600) -> None:
        ...

    async def get(self, session_id: str) -> dict:
        # Check Redis; on miss, delegate to self.repo.get(), then cache the result
        ...

    async def update(self, session_id: str, updated_build_state: dict) -> None:
        # Delegate to self.repo.update(), then update (or invalidate) the cache entry
        ...
```

Things to figure out:
- Redis stores strings/bytes, not Python dicts or Pydantic models. What do you serialize
  to before `SET`, and deserialize after `GET`? (Hint: `json.dumps`/`json.loads`, same
  problem as Step 4's `JSONB` handling, but now on the Python side both ways.)
- On `update()`, is it cheaper/safer to overwrite the cache entry with the new value
  directly, or to just delete the key and let the next `get()` repopulate it from
  Postgres? Which one risks a stale cache if `update()` and a concurrent `get()` race?

### Verify

Write a script that calls `get()` twice in a row for the same session and add a
`print`/log statement inside `BuildRepository.get()` itself — confirm the *second*
call never reaches it (cache hit), then call `update()` and confirm the *next* `get()`
reflects the change (not stale).

---

## Step 6 — Dependency wiring (`app/dependencies.py`, `app/main.py`)

### Understand first

`app/dependencies.py` already has `get_db`/`get_redis` as FastAPI dependency providers,
and module-level `set_pool`/`set_redis` called from `main.py`'s lifespan. You need to
extend this same pattern for the repositories and the compiled graph.

The compiled graph (`build_graph(pool)` from `app/graph/builder.py`) only needs to be
built *once*, at startup — not once per request. Where in `main.py`'s existing
`lifespan` function does that construction belong, relative to where `pool` is created?

### Implement

```python
# app/dependencies.py — add alongside the existing get_db/get_redis

_graph = None  # or whatever type build_graph(...) returns

def set_graph(graph) -> None:
    ...

async def get_session_repo() -> SessionRepository:
    ...

async def get_build_repo() -> CachedBuildRepository:
    ...

async def get_graph_runner() -> GraphRunner:
    ...
```

```python
# app/main.py — extend the existing lifespan()

@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await create_pool()
    redis = create_redis_client()
    set_pool(pool)
    set_redis(redis)
    # Build the graph once here, using `pool` — not inside a route handler
    ...
    yield
    await pool.close()
    await redis.aclose()
```

Things to figure out:
- `get_graph_runner()` needs both the compiled graph and the pool to construct a
  `GraphRunner`. Does it construct a new `GraphRunner` on every request, or reuse a
  singleton like the graph itself? (Hint: `GraphRunner.__init__` is cheap — it just
  stores references — so which approach avoids needless repeated work without risking
  shared mutable state between concurrent requests?)

### Verify

Start the API server (`uvicorn app.main:app --reload`) and confirm it boots without
errors — that alone proves the lifespan wiring didn't break anything you already had
working (health endpoint should still return 200).

---

## Step 7 — Sessions endpoint (`app/api/routes/sessions.py`)

### Understand first

`CreateSessionRequest`/`CreateSessionResponse` already exist in `app/models/api.py`.
This endpoint is a thin wrapper: validate the request, call
`SessionRepository.create()`, shape the result into `CreateSessionResponse`.

### Implement

```python
# app/api/routes/sessions.py

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

@router.post("", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    repo: SessionRepository = Depends(get_session_repo),
) -> CreateSessionResponse:
    ...
```

Things to figure out:
- `CreateSessionRequest` has an optional `starting_class` field. Does
  `SessionRepository.create()` (Step 3) need to accept and use this, or does it only
  matter once Melina's onboarding interview runs? (Hint: which one is the source of
  truth for `player_class` once onboarding actually starts — a value set at session
  creation, or whatever Melina extracts from the conversation?)

### Verify

Register the router in `main.py` (`app.include_router(sessions_router)`), then
`curl -X POST localhost:8000/api/v1/sessions -d '{"player_name": "Tarnished"}'` and
confirm you get back a `session_id` plus a default (all-empty) `build_state`.

---

## Step 8 — Query endpoint (`app/api/routes/queries.py`)

### Understand first

This is the one endpoint that actually exercises everything you built in Phase 3. The
full round-trip from Step 1's diagram happens here:

```python
async def submit_query(session_id, body, runner, build_repo) -> QueryResponse:
    build_state = await build_repo.get(session_id)
    result = await runner.run(session_id, body.query, build_state)
    await build_repo.update(session_id, result["updated_build_state"])
    return QueryResponse(...)
```

Answer first:
- `QueryResponse.trace_id` is a required `str` field, but nothing in Phase 3's
  `GraphRunner.run()` return dict currently populates a `trace_id`. What should you put
  there for now — a placeholder, or is this the moment to notice Langfuse tracing
  (Phase 5) hasn't been wired up yet and this field is legitimately not ready?
- What HTTP status should a request to a `session_id` that doesn't exist return? Where
  does that check belong — inside this route handler, or inside `BuildRepository.get()`?

### Implement

```python
# app/api/routes/queries.py

router = APIRouter(prefix="/api/v1/sessions", tags=["queries"])

@router.post("/{session_id}/query", response_model=QueryResponse)
async def submit_query(
    session_id: str,
    body: QueryRequest,
    runner: GraphRunner = Depends(get_graph_runner),
    build_repo: CachedBuildRepository = Depends(get_build_repo),
) -> QueryResponse:
    ...
```

Things to figure out:
- `body.stream` exists on `QueryRequest` already — is streaming in scope for Phase 4,
  or does `CLAUDE.md`'s phase breakdown put that in Phase 5? (Check the module map / phase
  table before building anything for it — building it now would be scope creep.)
- `GraphRunner.run()`'s `final_response` can be `None` (e.g. mid-onboarding, or an
  intermediate routing turn). What should `QueryResponse.response` contain in that case,
  given the response model requires a `str`, not `Optional[str]`?

### Verify

With a session that hasn't completed onboarding, POST a query and confirm the response
is Melina's conversational interview text, not an error. Then manually flip
`onboarding_completed` to `true` in the database for that session and POST a build
question — confirm you now get a specialist's response with populated `citations`.

---

## Step 9 — Build CRUD endpoints (`app/api/routes/builds.py`)

### Understand first

These two endpoints let something *other* than the graph read or directly edit a
player's build (e.g. a frontend showing/editing the character sheet without going
through a conversational query). They talk to `BuildRepository`/`CachedBuildRepository`
directly — no `GraphRunner` involved at all.

### Implement

```python
# app/api/routes/builds.py

router = APIRouter(prefix="/api/v1/sessions", tags=["builds"])

@router.get("/{session_id}/build", response_model=BuildStateGetResponse)
async def get_build(session_id, repo: CachedBuildRepository = Depends(get_build_repo)):
    ...

@router.put("/{session_id}/build", response_model=BuildStateUpdateResponse)
async def update_build(session_id, body: BuildStateUpdate, repo=Depends(get_build_repo)):
    ...
```

Things to figure out:
- `BuildStateUpdate` has every field as `Optional`. A `PUT` with only `playstyle` set
  and everything else `None` — should that overwrite `stats`/`weapons`/etc. with `NULL`,
  or only touch the fields the caller actually provided? (This is the same "partial vs.
  full overwrite" question from Step 4, now on the API's own input side too.)

### Verify

`GET` a build right after creating a session (should be all defaults), `PUT` a change to
just `playstyle`, then `GET` again — confirm the other fields weren't wiped out.

---

## Step 10 — Integration test

### Write these tests

**`tests/integration/test_api.py`:**

```python
async def test_create_session_and_query(db_pool, redis_client):
    # POST /api/v1/sessions -> 201, session_id present
    # POST /api/v1/sessions/{id}/query with a query -> Melina's onboarding response
    #   (fresh session, onboarding_completed defaults to False)
    # GET /api/v1/sessions/{id}/build -> reflects whatever Melina's turn changed, if anything

async def test_build_put_is_partial(db_pool):
    # Create a session, PUT only {"playstyle": "..."} 
    # Assert: playstyle updated, all other fields unchanged from their defaults
```

Use `tests/conftest.py`'s existing `db_pool`/`redis_client` fixtures — you'll likely also
need an `httpx.AsyncClient` (or FastAPI's `TestClient`) fixture to actually hit the app.

---

## Concept checkpoints

**After Steps 1–2:**
- Why does the build-state round-trip need a repository layer instead of the route
  handler talking to Postgres directly?
- What would silently break if you forgot Step 2's migration entirely?

**After Steps 3–5:**
- `SessionRepository` and `BuildRepository` are two separate classes even though
  `sessions` and `builds` are joined 1:1 by foreign key. Why not one `SessionRepository`
  that handles both tables?
- What's the actual failure mode of a cache-aside bug where `update()` writes to
  Postgres but forgets to touch Redis?

**After Steps 6–9:**
- Why does the compiled graph get built once in `main.py`'s lifespan, instead of once
  per request inside the query endpoint?
- The query endpoint and the build-CRUD endpoints both eventually touch
  `BuildRepository`, but only one of them goes through `GraphRunner`. What's the actual
  dividing line between "this belongs in a graph node" vs. "this belongs directly in a
  route handler"?

---

## Order matters

```
Migration (Step 2) → needs to exist before BuildRepository can read/write the new columns
  ↓
SessionRepository (Step 3), BuildRepository (Step 4) → independent of each other, but
  both needed before...
  ↓
Redis cache-aside (Step 5) → wraps BuildRepository
  ↓
Dependency wiring (Step 6) → needs the compiled graph (Phase 3, already done) + all repos
  ↓
Sessions endpoint (Step 7) → needs SessionRepository
Query endpoint (Step 8) → needs GraphRunner + BuildRepository — the real integration test
Build CRUD endpoints (Step 9) → needs BuildRepository only
  ↓
Integration test (Step 10) → needs a running Postgres + Redis, real API keys
```

If you skip Step 2 and jump straight to Step 4, `BuildRepository` will either crash on
missing columns or silently drop the onboarding fields — and you won't notice until a
returning player gets bounced back into Melina's interview for no visible reason.
