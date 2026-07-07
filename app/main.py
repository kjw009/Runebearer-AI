from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.api.middleware import register_middleware
from app.api.routes.health import router as health_router
from app.db.postgres import create_pool
from app.db.redis import create_redis_client
from app.graph.builder import build_graph
from app.dependencies import set_pool, set_redis, set_graph

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    pool = await create_pool()
    redis = create_redis_client()
    graph = build_graph(pool)
    set_pool(pool)
    set_redis(redis)
    set_graph(graph)
    yield
    await pool.close()
    await redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Elden Ring RAG", version="0.1.0", lifespan=lifespan)
    register_middleware(app)
    app.include_router(health_router)
    return app


app = create_app()