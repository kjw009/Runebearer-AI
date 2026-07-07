import logging
from typing import Any

from app.graph.state import BuildState, WeaponSlot
from app.observability.langfuse import agent_span
from app.prompts.master_hewg import MASTER_HEWG
from app.utils.build_state_to_json import build_state_to_json
from app.utils.specialist_llm import run_specialist

logger = logging.getLogger(__name__)

CALLING_AGENT = "master_hewg_build"

# Fields Master Hewg may report directly on his state_updates block, copied as-is.
_DIRECT_FIELDS = ["player_class", "playstyle", "talismans", "spirit_ash"]


def _coerce_weapons(raw_weapons: list[Any]) -> list[WeaponSlot]:
    """
    MASTER_HEWG's own example shows weapons as a flat list of name strings
    (e.g. ["Uchigatana"]), but BuildState.weapons is list[WeaponSlot]. Accept
    either shape so a plain string, a dict, or an already-built WeaponSlot all work.
    """
    coerced: list[WeaponSlot] = []
    for item in raw_weapons:
        if isinstance(item, WeaponSlot):
            coerced.append(item)
        elif isinstance(item, dict):
            coerced.append(WeaponSlot(**item))
        else:
            coerced.append(WeaponSlot(name=str(item)))
    return coerced


@agent_span("master_hewg_build")
async def master_hewg_build_node(state: BuildState) -> dict:
    """
    Equipment & Build Architect (build_creation). Two-phase: signal RAG first,
    then do the real work once rag_context is populated.
    """
    if not state.get("rag_context"):
        return {"calling_agent": CALLING_AGENT}

    system_prompt = MASTER_HEWG.format(
        build_state_json=build_state_to_json(state),
        rag_context=state["rag_context"],
    )

    try:
        cleaned_prose, updates = await run_specialist(state, system_prompt)
    except Exception as e:
        logger.error(f"Transient LLM failure in Master Hewg: {e}")
        cleaned_prose = "The forge fires have guttered. Return to the anvil shortly, Tarnished."
        updates = None

    payload: dict[str, Any] = {
        "agent_responses": {**state.get("agent_responses", {}), CALLING_AGENT: cleaned_prose},
    }

    if updates:
        for field in _DIRECT_FIELDS:
            if field in updates:
                payload[field] = updates[field]
        if "weapons" in updates and isinstance(updates["weapons"], list):
            payload["weapons"] = _coerce_weapons(updates["weapons"])

    return payload
