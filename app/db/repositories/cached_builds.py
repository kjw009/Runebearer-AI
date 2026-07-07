import json
import logging
from typing import Any, Optional
import redis.asyncio as redis

from app.db.repositories.builds import BuildRepository

logger = logging.getLogger(__name__)

class CachedBuildRepository:
    def __init__(self, build_repo: BuildRepository, redis_client: redis.Redis) -> None:
        self.build_repo = build_repo
        self.redis_client = redis_client

    async def get(self, session_id: str) -> dict:
        redis_key = f"build:{session_id}"

        # Try fetch from cache first (1-hour TTL)
        cached = await self.redis_client.get(redis_key)
        if cached:
            logger.info(f"[CACHE HIT] Build state for session {session_id}")
            # create_redis_client() sets decode_responses=True, so this is
            # already a str, not bytes — no .decode() needed (or possible).
            return json.loads(cached)

        logger.info(f"[CACHE MISS] Fetching build state from Postgres for session {session_id}")
        # Not in cache — fetch from DB
        build_state = await self.build_repo.get(session_id)

        # Populate cache for future reads
        await self.redis_client.setex(redis_key, 3600, json.dumps(build_state))
        logger.info(f"[CACHE POPULATE] Set cache for session {session_id} (TTL: 1 hour)")

        return build_state

    async def update(self, session_id: str, updated_build_state: dict) -> None:
        # Update DB first
        await self.build_repo.update(session_id, updated_build_state)
        logger.info(f"[PERSIST] Updated build state in Postgres for session {session_id}")

        # Invalidate rather than overwrite: updated_build_state can hold live
        # Pydantic objects (BuildStats, WeaponSlot) straight from the graph,
        # which json.dumps() can't serialize — BuildRepository.get() already
        # knows how to convert Postgres's JSONB columns back into plain dicts,
        # so just let the next get() repopulate the cache from there instead
        # of duplicating that serialization logic here.
        redis_key = f"build:{session_id}"
        await self.redis_client.delete(redis_key)
        logger.info(f"[CACHE INVALIDATE] Cleared cache for session {session_id} after update")

    async def clear_stale_cache(self, session_id: str) -> None:
        """Invalidate cache for a session (e.g. after a manual edit)."""
        redis_key = f"build:{session_id}"
        await self.redis_client.delete(redis_key)
        logger.info(f"[CACHE CLEAR] Cleared cache for session {session_id}")    