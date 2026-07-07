import logging
from typing import Any

from app.graph.state import BuildState, BuildStats
from app.observability.langfuse import agent_span
from app.prompts.queen_rennala import QUEEN_RENNALA
from app.utils.build_state_to_json import build_state_to_json
from app.utils.specialist_llm import run_specialist

logger = logging.getLogger(__name__)

CALLING_AGENT = "rennala_stats"


@agent_span("rennala_stats")
async def rennala_stats_node(state: BuildState) -> dict:
    """
    Stat & Leveling Optimizer (stat_prioritisation). Two-phase: signal RAG first,
    then do the real work once rag_context is populated.
    """
    if not state.get("rag_context"):
        return {"calling_agent": CALLING_AGENT}

    system_prompt = QUEEN_RENNALA.format(
        build_state_json=build_state_to_json(state),
        rag_context=state["rag_context"],
    )

    try:
        cleaned_prose, updates = await run_specialist(state, system_prompt)
    except Exception as e:
        logger.error(f"Transient LLM failure in Queen Rennala: {e}")
        cleaned_prose = "The Rebirth ritual falters, sweetings. Approach the Grand Rune again shortly."
        updates = None

    payload: dict[str, Any] = {
        "agent_responses": {**state.get("agent_responses", {}), CALLING_AGENT: cleaned_prose},
    }

    if updates:
        if "current_level" in updates:
            payload["current_level"] = updates["current_level"]
        if "stats" in updates and isinstance(updates["stats"], dict):
            payload["stats"] = BuildStats(**updates["stats"])

    return payload
