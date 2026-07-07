from app.graph.edges import route_from_specialist, route_from_supervisor


def test_route_from_supervisor_to_specialist():
    state = {"next_agent": "master_hewg_build"}
    assert route_from_supervisor(state) == "master_hewg_build"


def test_route_from_supervisor_to_onboarding():
    state = {"next_agent": "melina_onboarding"}
    assert route_from_supervisor(state) == "melina_onboarding"


def test_route_from_supervisor_to_end():
    state = {"next_agent": "END"}
    assert route_from_supervisor(state) == "__end__"


def test_route_from_supervisor_unknown_agent_ends():
    state = {"next_agent": "not_a_real_agent"}
    assert route_from_supervisor(state) == "__end__"


def test_route_from_supervisor_missing_next_agent_ends():
    assert route_from_supervisor({}) == "__end__"


def test_route_from_specialist_to_rag_when_no_context():
    state = {"rag_context": None, "rag_results": []}
    assert route_from_specialist(state) == "rag"


def test_route_from_specialist_to_supervisor_when_context_present():
    state = {"rag_context": "some retrieved context", "rag_results": []}
    assert route_from_specialist(state) == "guidance_of_grace"


def test_route_from_specialist_to_supervisor_when_results_present():
    state = {"rag_context": None, "rag_results": ["placeholder"]}
    assert route_from_specialist(state) == "guidance_of_grace"
