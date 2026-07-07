from typing import Any

from anthropic import APIConnectionError, AsyncAnthropic, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.graph.state import BuildState
from app.utils.anthropic_response import extract_text, parse_state_updates, strip_state_updates

SPECIALIST_MODEL = "claude-sonnet-4-6"


@retry(
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
    wait=wait_random_exponential(min=1, max=20),
    stop=stop_after_attempt(4),
)
async def _call_anthropic(
    client: AsyncAnthropic,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    temperature: float,
):
    """Retried inner function — only rate-limit / connection errors are retried."""
    return await client.messages.create(
        model=SPECIALIST_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
        temperature=temperature,
    )


async def run_specialist(
    state: BuildState,
    system_prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.4,
) -> tuple[str, dict[str, Any] | None]:
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
        response = await _call_anthropic(
            client,
            system_prompt,
            f"Player Input: {state.get('player_query', '')}",
            max_tokens,
            temperature,
        )

    raw_text = extract_text(response.content).strip()
    cleaned_prose = strip_state_updates(raw_text)
    updates = parse_state_updates(raw_text)
    return cleaned_prose, updates

