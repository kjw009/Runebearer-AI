from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from typing_extensions import TypedDict


class BuildStats(BaseModel):
    vigor: int = 10
    mind: int = 10
    endurance: int = 10
    strength: int = 10
    dexterity: int = 10
    intelligence: int = 10
    faith: int = 10
    arcane: int = 10

    @property
    def total_level(self) -> int:
        return sum(self.model_dump().values()) - 80


class WeaponSlot(BaseModel):
    name: str
    affinity: Optional[str] = None
    upgrade_level: int = 0
    hand: str = "right"


class Citation(BaseModel):
    source_url: str
    page_title: str
    section: str
    chunk_index: int


class RagChunk(BaseModel):
    content: str
    citation: Citation
    similarity_score: float


class BuildState(TypedDict):
    # Conversation
    messages: Annotated[list[BaseMessage], add_messages]
    session_id: str
    player_query: str

    # Routing
    next_agent: str
    calling_agent: str
    intent: list[str]
    intent_queue: list[str]
    final_response: Optional[str]

    # Build
    player_class: Optional[str]
    stats: Optional[BuildStats]
    weapons: list[WeaponSlot]
    talismans: list[str]
    spirit_ash: Optional[str]
    target_bosses: list[str]
    playstyle: Optional[str]

    # RAG
    rag_query: Optional[str]
    rag_results: list[RagChunk]
    rag_context: Optional[str]

    # Agent outputs
    agent_responses: dict[str, str]

    # Observability
    trace_id: Optional[str]
