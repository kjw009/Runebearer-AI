from typing import Optional
import logging
import asyncpg
from asyncpg.exceptions import InvalidTextRepresentationError

logger = logging.getLogger(__name__)

class SessionRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def create(self, player_name: str) -> dict:
        """
        Creates a new player session along with its default character build row
        atomically inside a database transaction.
        """
        session_query = """
            INSERT INTO sessions (player_name)
            VALUES ($1)
            RETURNING id, player_name, created_at, updated_at;
        """

        # onboarding_completed/player_profile/current_level and the rest of the
        # build columns all have sensible column-level defaults (see
        # 001_init.sql / 003_onboarding.sql) — session_id is the only value
        # that actually needs to be supplied here.
        build_query = """
            INSERT INTO builds (session_id)
            VALUES ($1);
        """

        # Wrap both inserts inside an atomic transaction block
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # 1. Insert session record
                session_row = await conn.fetchrow(session_query, player_name)
                if not session_row:
                    raise RuntimeError("Failed to insert record into sessions table.")

                session_data = dict(session_row)

                # 2. Insert blank default build row using the generated session UUID
                await conn.execute(build_query, session_data["id"])

                logger.info(f"Initialized fresh session and default build entry for tracker UUID: {session_data['id']}")

                # Coerce UUID type to a plain string for clean cross-layer parsing
                session_data["id"] = str(session_data["id"])

                return session_data

    async def get(self, session_id: str) -> Optional[dict]:
        """
        Fetches a session row by its primary key. Returns None if not found.
        """
        query = """
            SELECT id, player_name, created_at, updated_at
            FROM sessions
            WHERE id = $1::uuid;
        """

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, session_id)
                if not row:
                    return None

                session_data = dict(row)
                session_data["id"] = str(session_data["id"])

                return session_data

        except InvalidTextRepresentationError as err:
            # Catches malformed string conversions into Postgres UUID tokens early
            logger.warning(f"Invalid UUID string format requested during profile search: {session_id} | Error: {err}")
            return None