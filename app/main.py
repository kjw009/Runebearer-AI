from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langfuse import get_client

from app.api.middleware import register_middleware
from app.api.routes.builds import router as builds_router
from app.api.routes.health import router as health_router
from app.api.routes.queries import router as queries_router
from app.api.routes.sessions import router as sessions_router
from app.db.postgres import create_pool
from app.db.redis import create_redis_client
from app.dependencies import set_graph, set_pool, set_redis
from app.graph.builder import build_graph


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    pool = await create_pool()
    redis = create_redis_client()
    graph = build_graph(pool)
    set_pool(pool)
    set_redis(redis)
    set_graph(graph)
    yield
    # Flush any buffered Langfuse spans before closing connections —
    # otherwise the last few requests' traces can be silently dropped.
    get_client().flush()
    await pool.close()
    await redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Elden Ring RAG", version="0.1.0", lifespan=lifespan)
    register_middleware(app)
    app.include_router(health_router)
    app.include_router(sessions_router)
    app.include_router(queries_router)
    app.include_router(builds_router)
    return app


app = create_app()