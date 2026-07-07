from fastapi import APIRouter, Depends, HTTPException

from app.db.repositories.cached_builds import CachedBuildRepository
from app.db.repositories.sessions import SessionRepository
from app.dependencies import get_build_repo, get_graph_runner, get_session_repo
from app.graph.runner import GraphRunner
from app.models.api import QueryRequest, QueryResponse
from app.models.build import BuildStateResponse

router = APIRouter(prefix="/api/v1/sessions", tags=["queries"])


@router.post("/{session_id}/query", response_model=QueryResponse)
async def submit_query(
    session_id: str,
    body: QueryRequest,
    runner: GraphRunner = Depends(get_graph_runner),
    build_repo: CachedBuildRepository = Depends(get_build_repo),
    session_repo: SessionRepository = Depends(get_session_repo),
) -> QueryResponse:
    # Check existence explicitly so a bad session_id gets a clean 404 instead
    # of an unhandled KeyError from BuildRepository.get() (which treats a
    # missing builds row as data corruption, not "not found" — see builds.py).
    session = await session_repo.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    build_state = await build_repo.get(session_id)
    result = await runner.run(session_id=session_id, player_query=body.query, build_state=build_state)
    await build_repo.update(session_id, result["updated_build_state"])

    updated = result["updated_build_state"]
    return QueryResponse(
        session_id=session_id,
        # final_response should be populated on every terminal path (synthesis,
        # Melina's reply, or an error fallback) — the "" default is defensive,
        # not an expected case.
        response=result.get("final_response") or "",
        agents_used=result.get("agents_used", []),
        citations=result.get("citations", []),
        updated_build_state=BuildStateResponse(
            player_class=updated.get("player_class"),
            stats=updated.get("stats"),
            weapons=updated.get("weapons", []),
            talismans=updated.get("talismans", []),
            spirit_ash=updated.get("spirit_ash"),
            target_bosses=updated.get("target_bosses", []),
            playstyle=updated.get("playstyle"),
        ),
        # Langfuse tracing is Phase 5 — not wired up yet, so there's no real
        # trace_id to report. Empty string rather than inventing a fake one.
        trace_id="",
    )
