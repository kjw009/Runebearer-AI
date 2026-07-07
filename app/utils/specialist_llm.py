from typing import Any, Optional

from anthropic import AsyncAnthropic

from app.graph.state import BuildState
from app.utils.anthropic_response import extract_text, parse_state_updates, strip_state_updates

SPECIALIST_MODEL = "claude-sonnet-4-6"


async def run_specialist(
    state: BuildState,
    system_prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.4,
) -> tuple[str, Optional[dict[str, Any]]]:
    """
    Shared LLM-call + response-parsing logic for the two-phase specialist pattern.

    Returns (cleaned_prose, state_updates_or_None). Callers decide what to do with
    state_updates since each specialist maps different fields (or none at all, for
    the advisory-only agents) — this helper only handles the identical 80%: calling
    Claude, pulling text back out, and separating prose from any <state_updates> tag.

    Exceptions from the API call are NOT caught here — each specialist has its own
    in-character fallback message, so callers wrap this in their own try/except.
    """
    async with AsyncAnthropic() as client:
        response = await client.messages.create(
            model=SPECIALIST_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Player Input: {state.get('player_query', '')}"}],
            temperature=temperature,
        )

    raw_text = extract_text(response.content).strip()
    cleaned_prose = strip_state_updates(raw_text)
    updates = parse_state_updates(raw_text)
    return cleaned_prose, updates
