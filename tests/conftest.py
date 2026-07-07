import pytest
import asyncpg
import httpx
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


@pytest.fixture
async def api_client(db_pool: asyncpg.Pool, redis_client: aioredis.Redis) -> httpx.AsyncClient:
    """
    An HTTP client wired directly to the app over ASGI (no real socket).
    lifespan="on" runs app.main's own lifespan — which builds its own pool,
    redis client, and compiled graph via settings, independently of the
    db_pool/redis_client fixtures above. Both ultimately point at the same
    configured Postgres/Redis, so this is safe; the fixtures above mainly
    guarantee the infra is reachable before the app tries to use it.
    """
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", lifespan="on"
    ) as client:
        yield client
