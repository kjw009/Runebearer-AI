import asyncpg
import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.config import settings
from app.dependencies import get_db, get_redis
from app.models.api import HealthResponse

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
