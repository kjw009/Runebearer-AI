import json
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
from langfuse import get_client, observe

from app.graph.state import BuildState


class GraphRunner:
    """
    Thin wrapper around the compiled graph's ainvoke(). The API layer calls
    runner.run(...) and gets back a plain dict — it never needs to know
    anything about LangGraph, BuildState, or how the graph is wired.
    """

    def __init__(self, graph: Any, pool: asyncpg.Pool) -> None:
        self._graph = graph
        self._pool = pool

    def _build_initial_state(
        self,
        session_id: str,
        player_query: str,
        build_state: dict[str, Any],
    ) -> BuildState:
        """Shared initial-state construction for both run() and stream()."""
        return {
            "messages": [],
            "session_id": session_id,
            "player_query": player_query,
            "next_agent": "",
            "calling_agent": "",
            "intent": [],
            "intent_queue": [],
            "final_response": None,
            "onboarding_completed": build_state.get("onboarding_completed", False),
            "player_profile": build_state.get("player_profile", {}),
            "current_level": build_state.get("current_level"),
            "player_class": build_state.get("player_class"),
            "stats": build_state.get("stats"),
            "weapons": build_state.get("weapons", []),
            "talismans": build_state.get("talismans", []),
            "spirit_ash": build_state.get("spirit_ash"),
            "target_bosses": build_state.get("target_bosses", []),
            "playstyle": build_state.get("playstyle"),
            "rag_query": None,
            "rag_results": [],
            "rag_context": None,
            "citations": [],
            "agent_responses": {},
            "trace_id": None,
        }

    @staticmethod
    def _extract_build_state(final_state: dict[str, Any]) -> dict[str, Any]:
        """Pull the persisted build fields from a completed graph state."""
        return {
            "onboarding_completed": final_state.get("onboarding_completed", False),
            "player_profile": final_state.get("player_profile", {}),
            "current_level": final_state.get("current_level"),
            "player_class": final_state.get("player_class"),
            "stats": final_state.get("stats"),
            "weapons": final_state.get("weapons", []),
            "talismans": final_state.get("talismans", []),
            "spirit_ash": final_state.get("spirit_ash"),
            "target_bosses": final_state.get("target_bosses", []),
            "playstyle": final_state.get("playstyle"),
        }

    @observe(name="graph_runner", as_type="chain")
    async def run(
        self,
        session_id: str,
        player_query: str,
        build_state: dict[str, Any],
    ) -> dict[str, Any]:
        initial_state = self._build_initial_state(session_id, player_query, build_state)

        final_state = await self._graph.ainvoke(initial_state)

        # Capture the Langfuse trace_id while still inside the @observe context
        trace_id = get_client().get_current_trace_id() or ""

        return {
            "final_response": final_state.get("final_response"),
            "agents_used": list(final_state.get("agent_responses", {}).keys()),
            "citations": final_state.get("citations", []),
            "updated_build_state": self._extract_build_state(final_state),
            "trace_id": trace_id,
        }

    async def stream(
        self,
        session_id: str,
        player_query: str,
        build_state: dict[str, Any],
    ) -> AsyncIterator[str]:
        """
        Yields SSE-formatted ``data:`` lines as the graph progresses through nodes.
        The last chunk is always the full terminal state so callers can persist
        the updated build state identically to the non-streaming path.
        """
        initial_state = self._build_initial_state(session_id, player_query, build_state)
        last_state: dict[str, Any] = {}

        async for chunk in self._graph.astream(initial_state):
            last_state.update(chunk)
            yield f"data: {json.dumps(chunk, default=str)}\n\n"

        # Emit a final event with the fully resolved terminal state so the API
        # layer can persist build state without special-casing.
        terminal = {
            "__terminal__": True,
            "updated_build_state": self._extract_build_state(last_state),
        }
        yield f"data: {json.dumps(terminal, default=str)}\n\n"