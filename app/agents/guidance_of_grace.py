import json
import logging
from typing import Any
from anthropic import AsyncAnthropic
from langchain_core.messages import AIMessage

from app.graph.state import BuildState
from app.prompts.guidance_of_grace import GUIDANCE_OF_GRACE
from app.utils.anthropic_response import extract_text, safely_extract_json
from app.utils.build_state_to_summary import build_state_to_summary

logger = logging.getLogger(__name__)

async def guidance_of_grace_node(state: BuildState) -> dict:
    """
    State-based routing node for the Guidance of Grace supervisor.
    Interprets the user's request, populates the execution queue, and routes to specialists.
    """
    # 1. Strict Onboarding Guard
    if not state.get("onboarding_completed", False):
        return {
            "next_agent": "melina_onboarding", 
            "intent_queue": [],
            "intent": []
        }

    build_state_summary = build_state_to_summary(state)

    # 2. Execute LLM Routing Call
    async with AsyncAnthropic() as client:
        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                system=GUIDANCE_OF_GRACE.format(build_state_summary=build_state_summary),
                messages=[{"role": "user", "content": f"Player Input: {state.get('player_query', '')}"}],
                temperature=0.1,
            )
            response_text = extract_text(response.content).strip()
        except Exception as e:
            logger.error(f"Transient LLM failure in Guidance of Grace: {e}")
            return {
                "messages": [AIMessage(content="The Guidance of Grace is clouded by the fog. Please try again.")],
                "next_agent": "END",
                "final_response": "The Guidance of Grace is clouded by the fog. Please try again."
            }

    # 3. Balanced JSON Extraction
    json_string = safely_extract_json(response_text)
    try:
        if not json_string:
            raise ValueError("No balanced JSON structure found in raw model output.")
            
        parsed_response = json.loads(json_string)
        intent = parsed_response.get("intent", [])            # <-- FIXED: Captures the immutable layout list
        intent_queue = parsed_response.get("intent_queue", [])
        final_response = parsed_response.get("final_response")
        next_agent = parsed_response.get("next_agent", "END")
    except (json.JSONDecodeError, ValueError) as parse_err:
        logger.error(f"Failed to extract structural routing from Grace response: {response_text} | Error: {parse_err}")
        return {
            "messages": [AIMessage(content="The golden rays of grace scattered. Please rephrase your intent.")],
            "next_agent": "END",
            "final_response": "The golden rays of grace scattered. Please rephrase your intent."
        }

    # 4. State Modification: Pop the active target out of the draining queue
    if next_agent and next_agent in intent_queue:
        intent_queue.remove(next_agent)

    # 5. Compile Payload
    payload: dict[str, Any] = {
        "next_agent": next_agent,
        "intent_queue": intent_queue,
        "intent": intent,                                    # <-- FIXED: Persists to BuildState
        "final_response": final_response
    }

    if final_response:
        payload["messages"] = [AIMessage(content=final_response)]

    return payload