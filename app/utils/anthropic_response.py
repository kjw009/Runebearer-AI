from anthropic.types import ContentBlock, TextBlock


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
