from fastapi import APIRouter, Depends

from app.db.repositories.sessions import SessionRepository
from app.dependencies import get_session_repo
from app.models.api import CreateSessionRequest, CreateSessionResponse
from app.models.build import BuildStateResponse

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.post("", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    repo: SessionRepository = Depends(get_session_repo),
) -> CreateSessionResponse:
    session = await repo.create(body.player_name, body.starting_class)
    return CreateSessionResponse(
        session_id=session["id"],
        player_name=session["player_name"],
        created_at=session["created_at"],
        # A freshly created session's build row is all defaults/NULLs — no
        # need to round-trip to BuildRepository just to confirm that.
        build_state=BuildStateResponse(player_class=body.starting_class),
    )
