from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.db.repositories.cached_builds import CachedBuildRepository
from app.db.repositories.sessions import SessionRepository
from app.dependencies import get_build_repo, get_session_repo
from app.models.api import BuildStateGetResponse, BuildStateUpdateResponse
from app.models.build import BuildStateResponse, BuildStateUpdate

router = APIRouter(prefix="/api/v1/sessions", tags=["builds"])


async def _require_session(session_id: str, session_repo: SessionRepository) -> None:
    session = await session_repo.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")


def _to_build_state_response(build_state: dict) -> BuildStateResponse:
    return BuildStateResponse(
        player_class=build_state.get("player_class"),
        stats=build_state.get("stats"),
        weapons=build_state.get("weapons", []),
        talismans=build_state.get("talismans", []),
        spirit_ash=build_state.get("spirit_ash"),
        target_bosses=build_state.get("target_bosses", []),
        playstyle=build_state.get("playstyle"),
    )


@router.get("/{session_id}/build", response_model=BuildStateGetResponse)
async def get_build(
    session_id: str,
    build_repo: CachedBuildRepository = Depends(get_build_repo),
    session_repo: SessionRepository = Depends(get_session_repo),
) -> BuildStateGetResponse:
    await _require_session(session_id, session_repo)
    build_state = await build_repo.get(session_id)
    return BuildStateGetResponse(
        session_id=session_id,
        build_state=_to_build_state_response(build_state),
        updated_at=datetime.fromisoformat(build_state["updated_at"]),
    )


@router.put("/{session_id}/build", response_model=BuildStateUpdateResponse)
async def update_build(
    session_id: str,
    body: BuildStateUpdate,
    build_repo: CachedBuildRepository = Depends(get_build_repo),
    session_repo: SessionRepository = Depends(get_session_repo),
) -> BuildStateUpdateResponse:
    await _require_session(session_id, session_repo)

    # Partial update: only overwrite fields the caller actually provided in
    # the request body — exclude_unset distinguishes "field omitted" from
    # "field explicitly set" — then merge onto the existing persisted state so
    # everything else (including onboarding_completed/player_profile/
    # current_level, which BuildStateUpdate doesn't even have fields for)
    # survives untouched.
    current = await build_repo.get(session_id)
    provided = body.model_dump(exclude_unset=True)
    merged = {**current, **provided}

    await build_repo.update(session_id, merged)
    updated = await build_repo.get(session_id)

    return BuildStateUpdateResponse(
        session_id=session_id,
        build_state=_to_build_state_response(updated),
        updated_at=datetime.fromisoformat(updated["updated_at"]),
    )
