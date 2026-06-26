import asyncpg
from app.config import settings


async def create_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=settings.postgres_dsn,
        min_size=2,
        max_size=10,
    )
