from anthropic import AsyncAnthropic
from app.prompts.guidance_of_grace import GUIDANCE_OF_GRACE
from app.graph.state import BuildState
from langchain_core.messages import AIMessage
import json
import logging
from anthropic.types import ContentBlock, TextBlock

logger = logging.getLogger(__name__)

def _extract_text(content: list[ContentBlock]) -> str:
    for block in content:
        if isinstance(block, TextBlock):
            return block.text
    return ""

async def guidance_of_grace_node(state: BuildState) -> dict:
    """
    State-based routing node for the Guidance of Grace supervisor.

    Interprets the user's request and populates the intent_queue for specialist agents.
    Returns the updated state with the intent_queue.
    """
    build_state_summary = build_state_to_summary(state)

    async with AsyncAnthropic() as client:
        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4000,
                system=GUIDANCE_OF_GRACE.format(build_state_summary=build_state_summary),
                messages=[{"role": "user", "content": f"Player Input: {state['player_query']}"}],
                temperature=0.1,  # Very low temperature for consistent routing decisions
            )
        except Exception as e:
            logger.error(f"Error in Guidance of Grace node: {e}")
            return {"messages": [AIMessage(content="The Grace is clouded. Try again.")]}

    response_text = _extract_text(response.content).strip()
    
    # Parse the JSON response from Claude
    try:
        parsed_response = json.loads(response_text)
        next_agent = parsed_response.get("next_agent", "melina_onboarding")
        intent_queue = parsed_response.get("intent_queue", [])
        final_response = parsed_response.get("final_response")
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON from Guidance of Grace: {response_text}")
        next_agent = "melina_onboarding"
        intent_queue = []
        final_response = None
    
    # Create AIMessage for the assistant's response
    assistant_message = AIMessage(content=final_response if final_response else "")
    
    return {
        "messages": [assistant_message],
        "next_agent": next_agent,
        "intent_queue": intent_queue,
        "calling_agent": "guidance_of_grace"
    }
