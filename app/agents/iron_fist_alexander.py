import logging
from typing import Any

from app.graph.state import BuildState
from app.prompts.iron_fist_alexander import ALEXANDER_COMBAT_COACH_SYSTEM
from app.utils.build_state_to_json import build_state_to_json
from app.utils.specialist_llm import run_specialist

logger = logging.getLogger(__name__)

CALLING_AGENT = "alexander_combat"


async def alexander_combat_node(state: BuildState) -> dict:
    """
    Combat Coach (combat_execution). Advisory only — no state_updates.
    Two-phase: signal RAG first, then do the real work once rag_context is populated.
    """
    if not state.get("rag_context"):
        return {"calling_agent": CALLING_AGENT}

    system_prompt = ALEXANDER_COMBAT_COACH_SYSTEM.format(
        build_state_json=build_state_to_json(state),
        rag_context=state["rag_context"],
    )

    try:
        cleaned_prose, _updates = await run_specialist(state, system_prompt)
    except Exception as e:
        logger.error(f"Transient LLM failure in Iron Fist Alexander: {e}")
        cleaned_prose = "Ho, good friend! My voice is lost in the din of battle — call to me again!"

    payload: dict[str, Any] = {
        "agent_responses": {**state.get("agent_responses", {}), CALLING_AGENT: cleaned_prose},
    }
    return payload
