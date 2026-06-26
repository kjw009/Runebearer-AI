# Phase 1 — Foundation

**Goal:** Running FastAPI skeleton with Postgres + pgvector, Redis, and Langfuse all connected. `GET /health` returns 200 with all services healthy.

**Estimated time:** 2–3 days  
**Test at the end:** `curl http://localhost:8000/health` → `{"status":"ok","postgres":true,"redis":true,"langfuse":true}`

---

## Step 1 — Project scaffold

Create the top-level files and directory tree. Nothing runs yet; this is structure only.

```
elden-rag/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .env                  ← copy from .env.example, fill in keys
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── middleware.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       └── health.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── postgres.py
│   │   ├── redis.py
│   │   ├── repositories/
│   │   │   └── __init__.py
│   │   └── migrations/
│   │       ├── 001_init.sql
│   │       └── 002_vectors.sql
│   ├── graph/
│   │   ├── __init__.py
│   │   └── state.py
│   └── models/
│       ├── __init__.py
│       ├── api.py
│       └── build.py
└── tests/
    └── __init__.py
```

**Checklist:**
- [ ] Run `mkdir -p` for all directories above
- [ ] Create every `__init__.py` (can be empty)

---

## Step 2 — `pyproject.toml`

Defines the package and all dependencies. Use `uv` for speed.

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "elden-rag"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "asyncpg>=0.29",
    "pgvector>=0.3",
    "redis[hiredis]>=5.0",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "langfuse>=2.53",
    "langgraph>=0.2",
    "langchain>=0.3",
    "langchain-anthropic>=0.2",
    "langchain-openai>=0.2",
    "anthropic>=0.34",
    "openai>=1.50",
    "python-dotenv>=1.0",
    "httpx>=0.27",         # for Langfuse health check
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.6",
    "mypy>=1.11",
]
```

**Checklist:**
- [ ] Write `pyproject.toml`
- [ ] Run `uv pip install -e ".[dev]"` — confirm no errors

---

## Step 3 — `.env.example` and `.env`

`.env.example` is committed to git. `.env` is your actual secrets — never commit it.

```dotenv
# .env.example

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
OPENAI_API_KEY=sk-...

# Postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=elden_rag
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Redis
REDIS_URL=redis://localhost:6379/0

# Langfuse (self-hosted via Docker)
LANGFUSE_PUBLIC_KEY=pk-lf-dev
LANGFUSE_SECRET_KEY=sk-lf-dev
LANGFUSE_HOST=http://localhost:3000
```

**Checklist:**
- [ ] Write `.env.example`
- [ ] Copy to `.env` and fill in your real `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`
- [ ] Add `.env` to `.gitignore`

---

## Step 4 — `app/config.py`

Single `Settings` object loaded from environment. Every other module imports from here — no raw `os.environ` calls anywhere.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # LLM
    anthropic_api_key: str
    openai_api_key: str

    # Postgres
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "elden_rag"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Langfuse
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_host: str = "http://localhost:3000"


settings = Settings()
```

**Checklist:**
- [ ] Write `app/config.py`
- [ ] Quick smoke test: `python -c "from app.config import settings; print(settings.postgres_dsn)"`

---

## Step 5 — SQL migrations

These run automatically when Postgres starts via the Docker Compose volume mount.

**`app/db/migrations/001_init.sql`**

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_name  TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS builds (
    session_id   UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    player_class TEXT,
    stats        JSONB,
    weapons      JSONB NOT NULL DEFAULT '[]',
    talismans    JSONB NOT NULL DEFAULT '[]',
    spirit_ash   TEXT,
    target_bosses JSONB NOT NULL DEFAULT '[]',
    playstyle    TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**`app/db/migrations/002_vectors.sql`**

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url    TEXT NOT NULL,
    page_title    TEXT NOT NULL,
    section       TEXT NOT NULL,
    entity_type   TEXT NOT NULL,
    content       TEXT NOT NULL,
    token_count   INTEGER NOT NULL,
    chunk_index   INTEGER NOT NULL,
    embedding     vector(1536),
    scraped_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS documents_embedding_idx
    ON documents USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS documents_entity_type_idx
    ON documents (entity_type);
```

**Checklist:**
- [ ] Write both migration files
- [ ] Note: these run automatically when Postgres container starts (Step 7)

---

## Step 6 — `app/db/postgres.py` and `app/db/redis.py`

Async connection factories. Both are called once at startup and shared across requests.

**`app/db/postgres.py`**

```python
import asyncpg
from app.config import settings


async def create_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=settings.postgres_dsn,
        min_size=2,
        max_size=10,
    )
```

**`app/db/redis.py`**

```python
import redis.asyncio as aioredis
from app.config import settings


def create_redis_client() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)
```

**Checklist:**
- [ ] Write both files

---

## Step 7 — `docker-compose.yml` and `Dockerfile`

Brings up Postgres (with pgvector), Redis, and Langfuse locally.

**`docker-compose.yml`**

```yaml
version: "3.9"

services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      POSTGRES_HOST: postgres
      REDIS_URL: redis://redis:6379/0
      LANGFUSE_HOST: http://langfuse-web:3000
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
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: elden_rag
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./app/db/migrations:/docker-entrypoint-initdb.d
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
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
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/langfuse
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      ENCRYPTION_KEY: "0000000000000000000000000000000000000000000000000000000000000000"
      SALT: "changeme"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  langfuse-web:
    image: langfuse/langfuse:3
    ports:
      - "3000:3000"
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/langfuse
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      NEXTAUTH_SECRET: "changeme"
      NEXTAUTH_URL: "http://localhost:3000"
      LANGFUSE_INIT_ORG_ID: "elden-rag"
      LANGFUSE_INIT_PROJECT_ID: "elden-rag-dev"
      LANGFUSE_INIT_PROJECT_PUBLIC_KEY: "pk-lf-dev"
      LANGFUSE_INIT_PROJECT_SECRET_KEY: "sk-lf-dev"
      ENCRYPTION_KEY: "0000000000000000000000000000000000000000000000000000000000000000"
      SALT: "changeme"
    depends_on:
      langfuse-worker:
        condition: service_started

volumes:
  pg_data:
```

**`Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
RUN uv pip install --system -e .

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Checklist:**
- [ ] Write `docker-compose.yml` and `Dockerfile`
- [ ] Run `docker compose up postgres redis -d`
- [ ] Verify Postgres: `docker compose exec postgres psql -U postgres elden_rag -c "\dt"` — should show `sessions` and `builds` tables
- [ ] Verify Redis: `docker compose exec redis redis-cli ping` → `PONG`
- [ ] Bring up Langfuse: `docker compose up langfuse-worker langfuse-web -d`
- [ ] Open `http://localhost:3000` — Langfuse dashboard should load

---

## Step 8 — `app/graph/state.py` and `app/models/`

Define the core data shapes. No logic here — just types.

**`app/graph/state.py`** — see implementation plan Section 3 for the full `BuildState` TypedDict and supporting models (`BuildStats`, `WeaponSlot`, `Citation`, `RagChunk`).

**`app/models/build.py`** — `BuildStateResponse` and `BuildStateUpdate` Pydantic models (used by the API layer, not the graph).

**`app/models/api.py`** — `CreateSessionRequest`, `CreateSessionResponse`, `QueryRequest`, `QueryResponse`, `HealthResponse` — see implementation plan Section 6.

**Checklist:**
- [ ] Write `app/graph/state.py`
- [ ] Write `app/models/build.py`
- [ ] Write `app/models/api.py`
- [ ] Smoke test: `python -c "from app.graph.state import BuildState; print('OK')"` — no import errors

---

## Step 9 — `app/dependencies.py`

FastAPI dependency injection. Holds the connection pool and Redis client as application-level singletons so they're created once, not per-request.

```python
from typing import AsyncGenerator
import asyncpg
import redis.asyncio as aioredis

# These are set at startup in main.py lifespan
_pool: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None


def set_pool(pool: asyncpg.Pool) -> None:
    global _pool
    _pool = pool


def set_redis(client: aioredis.Redis) -> None:
    global _redis
    _redis = client


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    assert _pool is not None, "DB pool not initialised"
    async with _pool.acquire() as conn:
        yield conn


async def get_redis() -> aioredis.Redis:
    assert _redis is not None, "Redis client not initialised"
    return _redis
```

**Checklist:**
- [ ] Write `app/dependencies.py`

---

## Step 10 — `app/main.py`

FastAPI app factory with `lifespan` context manager that opens/closes the DB pool and Redis client.

```python
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.config import settings
from app.db.postgres import create_pool
from app.db.redis import create_redis_client
from app.dependencies import set_pool, set_redis
from app.api.middleware import register_middleware
from app.api.routes.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    pool = await create_pool()
    redis = create_redis_client()
    set_pool(pool)
    set_redis(redis)
    yield
    await pool.close()
    await redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Elden Ring RAG", version="0.1.0", lifespan=lifespan)
    register_middleware(app)
    app.include_router(health_router)
    return app


app = create_app()
```

**Checklist:**
- [ ] Write `app/main.py`

---

## Step 11 — `app/api/middleware.py`

CORS and a global exception handler so unhandled errors return JSON rather than HTML.

```python
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


def register_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})
```

**Checklist:**
- [ ] Write `app/api/middleware.py`

---

## Step 12 — `app/api/routes/health.py`

The health endpoint checks all three downstream services and returns their status.

```python
import httpx
import asyncpg
import redis.asyncio as aioredis

from fastapi import APIRouter, Depends
from app.models.api import HealthResponse
from app.dependencies import get_db, get_redis
from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    conn: asyncpg.Connection = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> HealthResponse:
    postgres_ok = False
    redis_ok = False
    langfuse_ok = False

    try:
        await conn.fetchval("SELECT 1")
        postgres_ok = True
    except Exception:
        pass

    try:
        await redis.ping()
        redis_ok = True
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.langfuse_host}/api/public/health")
            langfuse_ok = resp.status_code == 200
    except Exception:
        pass

    return HealthResponse(
        status="ok" if all([postgres_ok, redis_ok, langfuse_ok]) else "degraded",
        postgres=postgres_ok,
        redis=redis_ok,
        langfuse=langfuse_ok,
    )
```

**Checklist:**
- [ ] Write `app/api/routes/health.py`

---

## Step 13 — Bring it all up and verify

**Checklist:**
- [ ] Start everything: `docker compose up -d`
- [ ] Watch logs for errors: `docker compose logs -f app`
- [ ] Hit the health endpoint: `curl -s http://localhost:8000/health | python -m json.tool`
- [ ] Expected response:
  ```json
  {
    "status": "ok",
    "postgres": true,
    "redis": true,
    "langfuse": true
  }
  ```
- [ ] Open FastAPI docs: `http://localhost:8000/docs` — `/health` endpoint visible
- [ ] Open Langfuse dashboard: `http://localhost:3000` — project `elden-rag-dev` visible

---

## Done — Phase 1 Complete

You now have:
- Postgres with pgvector schema (sessions, builds, documents tables)
- Redis running and connected
- Langfuse self-hosted and reachable
- FastAPI app with lifespan-managed connection pool
- Typed config via pydantic-settings
- All core domain models defined (BuildState, BuildStats, WeaponSlot)
- `/health` endpoint verifying all services

**Next:** Phase 2 — RAG pipeline (scraper → chunker → embedder → pgvector upsert → retriever).
