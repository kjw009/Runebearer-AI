import asyncpg
from langgraph.graph import END, StateGraph

from app.agents.guidance_of_grace import guidance_of_grace_node
from app.agents.iron_fist_alexander import alexander_combat_node
from app.agents.maiden_melina import maiden_melina_node
from app.agents.master_hewg import master_hewg_build_node
from app.agents.merchant_kale import kale_loot_routes_node
from app.agents.queen_rennala import rennala_stats_node
from app.agents.rag import make_rag_node
from app.agents.sir_gideon_ofnir import gideon_all_knowing_node
from app.graph.edges import route_from_specialist, route_from_supervisor
from app.graph.state import BuildState

SPECIALIST_NODES = {
    "master_hewg_build": master_hewg_build_node,
    "rennala_stats": rennala_stats_node,
    "kale_loot_routes": kale_loot_routes_node,
    "gideon_all_knowing": gideon_all_knowing_node,
    "alexander_combat": alexander_combat_node,
}


def build_graph(pool: asyncpg.Pool):
    graph = StateGraph(BuildState)

    graph.add_node("guidance_of_grace", guidance_of_grace_node)
    graph.add_node("melina_onboarding", maiden_melina_node)
    graph.add_node("rag", make_rag_node(pool))
    for name, node in SPECIALIST_NODES.items():
        graph.add_node(name, node)

    graph.set_entry_point("guidance_of_grace")

    # Supervisor routes to onboarding, a specialist, or END
    graph.add_conditional_edges(
        "guidance_of_grace",
        route_from_supervisor,
        {
            "melina_onboarding": "melina_onboarding",
            **{name: name for name in SPECIALIST_NODES},
            "__end__": END,
        },
    )

    # Melina never touches RAG, and her conversational reply IS the whole turn's
    # response — she ends the turn directly rather than looping back through the
    # supervisor (which would immediately re-check onboarding_completed, still False
    # this turn, and re-invoke her again with the same player_query, forever).
    graph.add_edge("melina_onboarding", END)

    # Each specialist goes to RAG first, then back to the specialist via RAG's own
    # routing, then returns to the supervisor once it has real work to report.
    for specialist in SPECIALIST_NODES:
        graph.add_conditional_edges(
            specialist,
            route_from_specialist,
            {"rag": "rag", "guidance_of_grace": "guidance_of_grace"},
        )

    # RAG always returns to whichever specialist called it.
    graph.add_conditional_edges(
        "rag",
        lambda s: s["calling_agent"],
        {name: name for name in SPECIALIST_NODES},
    )

    return graph.compile()
