import logging
from typing import Any

from app.graph.state import BuildState
from app.prompts.merchant_kale import MERCHANT_KALE
from app.utils.build_state_to_json import build_state_to_json
from app.utils.specialist_llm import run_specialist

logger = logging.getLogger(__name__)

CALLING_AGENT = "kale_loot_routes"


async def kale_loot_routes_node(state: BuildState) -> dict:
    """
    Cartographer & Item Discovery (item_loot). Advisory only — no state_updates.
    Two-phase: signal RAG first, then do the real work once rag_context is populated.
    """
    if not state.get("rag_context"):
        return {"calling_agent": CALLING_AGENT}

    system_prompt = MERCHANT_KALE.format(
        build_state_json=build_state_to_json(state),
        rag_context=state["rag_context"],
    )

    try:
        cleaned_prose, _updates = await run_specialist(state, system_prompt)
    except Exception as e:
        logger.error(f"Transient LLM failure in Merchant Kalé: {e}")
        cleaned_prose = "The roads are unclear through the fog, traveler. Ask again shortly."

    payload: dict[str, Any] = {
        "agent_responses": {**state.get("agent_responses", {}), CALLING_AGENT: cleaned_prose},
    }
    return payload
