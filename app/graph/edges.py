from app.graph.state import BuildState

SPECIALIST_AGENTS = {
    "master_hewg_build", "rennala_stats", "kale_loot_routes",
    "gideon_all_knowing", "alexander_combat",
}
ONBOARDING_AGENT = "melina_onboarding"


def route_from_supervisor(state: BuildState) -> str:
    """Route supervisor output to onboarding, the next specialist, or END."""
    next_agent = state.get("next_agent", "END")
    if next_agent == "END":
        return "__end__"
    if next_agent != ONBOARDING_AGENT and next_agent not in SPECIALIST_AGENTS:
        return "__end__"
    return next_agent


def route_from_specialist(state: BuildState) -> str:
    """
    Route specialist: go to RAG if it hasn't been called yet this turn, else
    return to the supervisor. Only ever invoked for the 5 specialists — Melina
    has her own unconditional edge straight to END and never passes through here.
    """
    if not state.get("rag_context") and not state.get("rag_results"):
        return "rag"
    return "guidance_of_grace"
