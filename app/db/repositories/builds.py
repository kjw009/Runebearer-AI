import json
import logging
import asyncpg

from app.utils.db_json import parse_jsonb

logger = logging.getLogger(__name__)


class BuildRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def get(self, session_id: str) -> dict:
        """
        Fetches the persistent build fields GraphRunner.run() needs for this
        session, shaped into a plain dict. Only returns the fields GraphRunner
        actually reads off its build_state parameter (see app/graph/runner.py) —
        session_id, player_query, messages, intent, intent_queue, and
        agent_responses are all set fresh by GraphRunner itself on every call
        and are never read from persisted storage.
        """
        query = """
            SELECT
                onboarding_completed,
                player_profile,
                player_class,
                current_level,
                stats,
                weapons,
                talismans,
                spirit_ash,
                target_bosses,
                playstyle,
                updated_at
            FROM builds
            WHERE session_id = $1::uuid;
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, session_id)
            if not row:
                # SessionRepository.create() inserts the sessions + builds rows
                # atomically, so a session that exists should always have a
                # matching builds row. A miss here means real data corruption,
                # not a normal "not found" — that's SessionRepository.get()'s job.
                raise KeyError(f"No build record found for session {session_id}")

            data = dict(row)
            return {
                "onboarding_completed": data["onboarding_completed"],
                "player_profile": parse_jsonb(data["player_profile"]),
                "player_class": data["player_class"],
                "current_level": data["current_level"],
                "stats": parse_jsonb(data["stats"]),
                "weapons": parse_jsonb(data["weapons"]),
                "talismans": parse_jsonb(data["talismans"]),
                "spirit_ash": data["spirit_ash"],
                "target_bosses": parse_jsonb(data["target_bosses"]),
                "playstyle": data["playstyle"],
                # ISO string, not a datetime — CachedBuildRepository.get() caches
                # this whole dict via json.dumps(), which can't serialize datetime.
                "updated_at": data["updated_at"].isoformat(),
            }

    async def update(self, session_id: str, updated_build_state: dict) -> None:
        """Persists the fields GraphRunner.run() returned in updated_build_state."""
        query = """
            UPDATE builds
            SET onboarding_completed = $2,
                player_profile = $3::jsonb,
                player_class = $4,
                current_level = $5,
                stats = $6::jsonb,
                weapons = $7::jsonb,
                talismans = $8::jsonb,
                spirit_ash = $9,
                target_bosses = $10::jsonb,
                playstyle = $11,
                updated_at = NOW()
            WHERE session_id = $1::uuid;
        """

        # Serialize Optional[BuildStats] safely
        stats_data = updated_build_state.get("stats")
        if stats_data is not None:
            if hasattr(stats_data, "model_dump"):
                stats_json = json.dumps(stats_data.model_dump())
            elif hasattr(stats_data, "dict"):
                stats_json = json.dumps(stats_data.dict())
            else:
                stats_json = json.dumps(stats_data) if isinstance(stats_data, dict) else None
        else:
            stats_json = None

        # Serialize list[WeaponSlot] safely
        weapons_raw = updated_build_state.get("weapons") or []
        weapons_serialized_list = []
        for slot in weapons_raw:
            if hasattr(slot, "model_dump"):
                weapons_serialized_list.append(slot.model_dump())
            elif hasattr(slot, "dict"):
                weapons_serialized_list.append(slot.dict())
            else:
                weapons_serialized_list.append(slot if isinstance(slot, dict) else str(slot))
        weapons_json = json.dumps(weapons_serialized_list)

        profile_json = json.dumps(updated_build_state.get("player_profile") or {})
        talismans_json = json.dumps(updated_build_state.get("talismans") or [])
        bosses_json = json.dumps(updated_build_state.get("target_bosses") or [])

        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                session_id,
                updated_build_state.get("onboarding_completed", False),
                profile_json,
                updated_build_state.get("player_class"),
                updated_build_state.get("current_level", 1),
                stats_json,
                weapons_json,
                talismans_json,
                updated_build_state.get("spirit_ash"),
                bosses_json,
                updated_build_state.get("playstyle"),
            )
        logger.info(f"Successfully persisted build state mutations for session: {session_id}")
