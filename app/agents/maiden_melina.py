import json
import logging
from typing import Any
from anthropic import AsyncAnthropic
from langchain_core.messages import AIMessage

from app.graph.state import BuildState
from app.prompts.maiden_melina import MAIDEN_MELINA
from app.utils.anthropic_response import extract_text, parse_state_updates, strip_state_updates

logger = logging.getLogger(__name__)

async def maiden_melina_node(state: BuildState) -> dict:
    """
    Onboarding assessment node handled by Melina.
    Conducts a fluid conversational interview to collect player parameters 
    and flip the global onboarding safety locks.
    """
    # 1. Serialize current profile data to pass to the system instructions
    build_state_json = json.dumps({
        "player_profile": state.get("player_profile", {}),
        "player_class": state.get("player_class"),
        "current_level": state.get("current_level"),
        "onboarding_completed": state.get("onboarding_completed", False)
    }, indent=2)

    # 2. Invoke conversational model
    async with AsyncAnthropic() as client:
        try:
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                system=MAIDEN_MELINA.format(build_state_json=build_state_json),
                messages=[{"role": "user", "content": f"Player Input: {state.get('player_query', '')}"}],
                temperature=0.7,
            )
            raw_response_text = extract_text(response.content).strip()
        except Exception as e:
            logger.error(f"Transient LLM failure during Melina onboarding turn: {e}")
            fallback_text = "Thy guidance is faded. Please repeat thy words near the fire."
            return {
                "messages": [AIMessage(content=fallback_text)],
                "final_response": fallback_text
            }

    # 3. Clean conversational prose text by stripping out the XML updates suffix block
    cleaned_prose = strip_state_updates(raw_response_text)

    # 4. Initialize payload with messaging values (Tracking response history under 'melina_onboarding')
    payload: dict[str, Any] = {
        "messages": [AIMessage(content=cleaned_prose)],
        "final_response": cleaned_prose,
        "agent_responses": {**state.get("agent_responses", {}), "melina_onboarding": cleaned_prose}
    }

    # 5. Extract and parse structural phase-completion markers
    updates = parse_state_updates(raw_response_text)
    
    if updates:
        logger.info(f"Melina interview completed successfully. Extracting player configurations: {updates}")
        # Explicitly map updates into core state properties
        payload["onboarding_completed"] = updates.get("onboarding_completed", True)
        payload["player_class"] = updates.get("player_class")
        payload["current_level"] = updates.get("current_level", 1)
        
        # Populate the structural nested player_profile dictionary safely
        # (MAIDEN_MELINA's state_updates schema nests these under "player_profile";
        # playstyle is a sibling top-level BuildState field, not part of the profile)
        profile_updates = updates.get("player_profile", {})
        payload["player_profile"] = {
            "experience_level": profile_updates.get("experience_level"),
            "skill_confidence": profile_updates.get("skill_confidence"),
            "preferred_archetype": profile_updates.get("preferred_archetype"),
            "current_hurdle": profile_updates.get("current_hurdle"),
        }
        payload["playstyle"] = updates.get("playstyle")
    else:
        logger.debug("Melina onboarding parameters incomplete. Continuing dialog sequence loop...")
        
    # Note: next_agent is intentionally left unset. Melina has no RAG round-trip and
    # her reply above IS the whole turn's response, so the graph routes her straight
    # to END (see builder.py) rather than back through the supervisor — looping back
    # to guidance_of_grace would immediately re-check onboarding_completed (still False
    # this turn) and re-invoke Melina again with the same player_query, forever.
    return payload