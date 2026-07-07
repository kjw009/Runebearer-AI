from typing import Any

import asyncpg

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

    async def run(
        self,
        session_id: str,
        player_query: str,
        build_state: dict[str, Any],
    ) -> dict[str, Any]:
        initial_state: BuildState = {
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

        final_state = await self._graph.ainvoke(initial_state)

        return {
            "final_response": final_state.get("final_response"),
            "agents_used": list(final_state.get("agent_responses", {}).keys()),
            "citations": final_state.get("citations", []),
            "updated_build_state": {
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
            },
        }
