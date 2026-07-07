import logging
from typing import Any

from app.graph.state import BuildState
from app.prompts.sir_gideon_ofnir import SIR_GIDEON_OFNIR
from app.utils.build_state_to_json import build_state_to_json
from app.utils.specialist_llm import run_specialist

logger = logging.getLogger(__name__)

CALLING_AGENT = "gideon_all_knowing"


async def gideon_all_knowing_node(state: BuildState) -> dict:
    """
    Ultimate Combat, Boss & Status-Effect Tactician (boss_optimisation + status_effect,
    merged). Advisory only — no state_updates. Two-phase: signal RAG first, then do
    the real work once rag_context is populated.
    """
    if not state.get("rag_context"):
        return {"calling_agent": CALLING_AGENT}

    system_prompt = SIR_GIDEON_OFNIR.format(
        build_state_json=build_state_to_json(state),
        rag_context=state["rag_context"],
    )

    try:
        cleaned_prose, _updates = await run_specialist(state, system_prompt)
    except Exception as e:
        logger.error(f"Transient LLM failure in Sir Gideon Ofnir: {e}")
        cleaned_prose = "Even the All-Knowing's archives falter momentarily. Pose your query again."

    payload: dict[str, Any] = {
        "agent_responses": {**state.get("agent_responses", {}), CALLING_AGENT: cleaned_prose},
    }
    return payload
