import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

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
) -> QueryResponse | StreamingResponse:
    # Check existence explicitly so a bad session_id gets a clean 404 instead
    # of an unhandled KeyError from BuildRepository.get() (which treats a
    # missing builds row as data corruption, not "not found" — see builds.py).
    session = await session_repo.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    build_state = await build_repo.get(session_id)

    # ── Streaming path ──────────────────────────────────────────────────
    if body.stream:
        async def event_stream():
            last_build_state = {}
            async for sse_line in runner.stream(session_id, body.query, build_state):
                # Parse the terminal event to persist build state
                try:
                    payload = json.loads(sse_line.removeprefix("data: ").strip())
                    if payload.get("__terminal__"):
                        last_build_state = payload.get("updated_build_state", {})
                except (json.JSONDecodeError, AttributeError):
                    pass
                yield sse_line

            # Persist the final build state exactly as the non-streaming path does
            if last_build_state:
                await build_repo.update(session_id, last_build_state)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # ── Non-streaming path (original) ───────────────────────────────────
    result = await runner.run(
        session_id=session_id,
        player_query=body.query,
        build_state=build_state,
    )
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
        trace_id=result.get("trace_id", ""),
    )
