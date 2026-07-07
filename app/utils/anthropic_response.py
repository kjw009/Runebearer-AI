import json
import logging
import re
from typing import Any, Optional

from anthropic.types import ContentBlock, TextBlock

logger = logging.getLogger(__name__)

_STATE_UPDATES_PATTERN = re.compile(r"<state_updates>(.*?)</state_updates>", re.DOTALL)


def extract_text(content: list[ContentBlock]) -> str:
    for block in content:
        if isinstance(block, TextBlock):
            return block.text
    return ""


def safely_extract_json(text: str) -> str:
    """
    Finds the first occurring '{' and extracts a structurally balanced
    JSON string block to prevent greedy matching failures from trailing
    curly braces in markdown content or code examples.
    """
    start_idx = text.find('{')
    if start_idx == -1:
        return ""

    brace_count = 0
    for idx in range(start_idx, len(text)):
        char = text[idx]
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                return text[start_idx:idx + 1]
    return ""


def parse_state_updates(text: str) -> Optional[dict[str, Any]]:
    """
    Locates text within <state_updates> tags and parses the inner balanced JSON.
    Returns a Python dictionary if successful, otherwise None (either no tag was
    found, or its contents weren't valid JSON — both are treated as "no updates
    yet" rather than an error, since specialists are expected to omit the tag
    entirely until they have something complete to report).
    """
    match = _STATE_UPDATES_PATTERN.search(text)
    if not match:
        return None

    inner_content = match.group(1).strip()
    json_string = safely_extract_json(inner_content)
    if not json_string:
        return None

    try:
        return json.loads(json_string)
    except json.JSONDecodeError as err:
        logger.error(f"Emitted invalid JSON syntax inside state_updates tags: {json_string} | Error: {err}")
        return None


def strip_state_updates(text: str) -> str:
    """Removes the <state_updates> block, leaving just the player-facing prose."""
    return _STATE_UPDATES_PATTERN.sub("", text).strip()
