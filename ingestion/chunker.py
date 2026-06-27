from typing import Any
from dataclasses import dataclass

@dataclass
class Chunk:
    """A piece of text along with its metadata and token count."""
    content: str
    metadata: dict[str, Any]
    token_count: int