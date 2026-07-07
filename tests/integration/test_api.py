import httpx
import pytest


async def _create_session(api_client: httpx.AsyncClient, player_name: str = "Tarnished") -> str:
    resp = await api_client.post("/api/v1/sessions", json={"player_name": player_name})
    assert resp.status_code == 201, resp.text
    return resp.json()["session_id"]


@pytest.mark.asyncio
async def test_create_session_and_query(api_client: httpx.AsyncClient):
    session_id = await _create_session(api_client)

    # Fresh session: onboarding_completed defaults to False, so the supervisor's
    # onboarding gate should route straight to Melina regardless of the query —
    # her conversational interview text is the response, not a specialist answer.
    resp = await api_client.post(
        f"/api/v1/sessions/{session_id}/query",
        json={"query": "hi, first time playing Elden Ring"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == session_id
    assert body["response"]  # Melina's reply, non-empty
    assert body["agents_used"] == ["melina_onboarding"]
    assert body["citations"] == []  # Melina never touches RAG

    # The build endpoint should reflect whatever this turn changed (if the
    # single turn wasn't enough to complete onboarding, that's fine — this
    # just confirms the round-trip persisted without erroring).
    get_resp = await api_client.get(f"/api/v1/sessions/{session_id}/build")
    assert get_resp.status_code == 200, get_resp.text


@pytest.mark.asyncio
async def test_query_unknown_session_returns_404(api_client: httpx.AsyncClient):
    fake_session_id = "00000000-0000-0000-0000-000000000000"
    resp = await api_client.post(
        f"/api/v1/sessions/{fake_session_id}/query",
        json={"query": "hello"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_build_put_is_partial(api_client: httpx.AsyncClient):
    session_id = await _create_session(api_client)

    before = await api_client.get(f"/api/v1/sessions/{session_id}/build")
    assert before.status_code == 200
    before_build = before.json()["build_state"]

    put_resp = await api_client.put(
        f"/api/v1/sessions/{session_id}/build",
        json={"playstyle": "dexterity_bleed_melee"},
    )
    assert put_resp.status_code == 200, put_resp.text
    updated_build = put_resp.json()["build_state"]

    assert updated_build["playstyle"] == "dexterity_bleed_melee"
    # Every other field should be untouched by a PUT that only set playstyle.
    for field in ("player_class", "stats", "weapons", "talismans", "spirit_ash", "target_bosses"):
        assert updated_build[field] == before_build[field]
