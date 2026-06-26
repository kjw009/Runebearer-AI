import pytest
import asyncpg
import redis.asyncio as aioredis

from app.config import settings
from app.dependencies import set_pool, set_redis


@pytest.fixture(scope="session")
async def db_pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn=settings.postgres_dsn)
    set_pool(pool)
    yield pool
    await pool.close()


@pytest.fixture(scope="session")
async def redis_client() -> aioredis.Redis:
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    set_redis(client)
    yield client
    await client.aclose()
