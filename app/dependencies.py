from typing import AsyncGenerator

import asyncpg
import redis.asyncio as aioredis

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
