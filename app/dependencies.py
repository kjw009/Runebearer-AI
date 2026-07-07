from app.db.repositories.builds import BuildRepository
from app.db.repositories.cached_builds import CachedBuildRepository
from app.db.repositories.sessions import SessionRepository
from app.graph.runner import GraphRunner
from langgraph.graph.state import CompiledStateGraph
from typing import AsyncGenerator

import asyncpg
import redis.asyncio as aioredis

_pool: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None
_graph: CompiledStateGraph | None = None

def set_pool(pool: asyncpg.Pool) -> None:
    global _pool
    _pool = pool

def set_redis(client: aioredis.Redis) -> None:
    global _redis
    _redis = client

def set_graph(graph: CompiledStateGraph) -> None:
    global _graph
    _graph = graph

async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    assert _pool is not None, "DB pool not initialised"
    async with _pool.acquire() as conn:
        yield conn

async def get_redis() -> aioredis.Redis:
    assert _redis is not None, "Redis client not initialised"
    return _redis

async def get_session_repo() -> SessionRepository:
    assert _pool is not None, "DB pool not initialised"
    return SessionRepository(_pool)

async def get_build_repo() -> CachedBuildRepository:
    assert _pool is not None, "DB pool not initialised"
    assert _redis is not None, "Redis client not initialised"
    return CachedBuildRepository(BuildRepository(_pool), _redis)

async def get_graph_runner() -> GraphRunner:
    assert _graph is not None, "Graph not initialised"
    assert _pool is not None, "DB pool not initialised"
    return GraphRunner(_graph, _pool)