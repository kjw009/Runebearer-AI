from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.graph.state import Citation
from app.models.build import BuildStateResponse, BuildStateUpdate  # noqa: F401


class CreateSessionRequest(BaseModel):
    player_name: str
    starting_class: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str
    player_name: str
    created_at: datetime
    build_state: BuildStateResponse


class QueryRequest(BaseModel):
    query: str
    stream: bool = False


class QueryResponse(BaseModel):
    session_id: str
    response: str
    agents_used: list[str]
    citations: list[Citation]
    updated_build_state: BuildStateResponse
    trace_id: str


class BuildStateGetResponse(BaseModel):
    session_id: str
    build_state: BuildStateResponse
    updated_at: datetime


class BuildStateUpdateResponse(BaseModel):
    session_id: str
    build_state: BuildStateResponse
    updated_at: datetime


class HealthResponse(BaseModel):
    status: str
    postgres: bool
    redis: bool
    langfuse: bool
