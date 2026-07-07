import asyncpg

from app.graph.state import BuildState, Citation, RagChunk
from app.observability.langfuse import rag_span
from app.prompts.rag import RAG_CONTEXT_TEMPLATE
from app.rag.query_rewriter import QueryRewriter
from app.rag.reranker import Reranker
from app.rag.retriever import Retriever

# Which entity_type rows each specialist is allowed to retrieve from.
# gideon_all_knowing covers both boss_optimisation and status_effect since
# those two were merged into one persona (Sir Gideon Ofnir).
ENTITY_TYPE_MAP: dict[str, list[str]] = {
    "master_hewg_build": ["weapon", "stat", "item"],
    "rennala_stats": ["stat"],
    "kale_loot_routes": ["item", "weapon"],
    "alexander_combat": ["mechanic", "weapon"],
    "gideon_all_knowing": ["boss", "mechanic"],
}


def make_rag_node(pool: asyncpg.Pool):
    """
    Factory so the node function can close over a single Retriever/Reranker/
    QueryRewriter instead of constructing them (and reloading the cross-encoder
    model) on every single call.
    """
    retriever = Retriever(pool)
    reranker = Reranker()
    rewriter = QueryRewriter()

    @rag_span
    async def rag_node(state: BuildState) -> dict:
        calling_agent = state["calling_agent"]
        entity_types = ENTITY_TYPE_MAP.get(calling_agent, [])

        variants = await rewriter.rewrite(state["player_query"], calling_agent)

        # Retrieve for every rewritten variant and merge, deduping by the
        # (source_url, chunk_index) identity of a chunk and keeping whichever
        # occurrence scored higher if the same chunk turned up more than once.
        merged: dict[tuple[str, int], RagChunk] = {}
        for variant in variants:
            results = await retriever.retrieve(variant, entity_types)
            for chunk in results:
                key = (chunk.citation.source_url, chunk.citation.chunk_index)
                existing = merged.get(key)
                if existing is None or chunk.similarity_score > existing.similarity_score:
                    merged[key] = chunk

        reranked = reranker.rerank(state["player_query"], list(merged.values()))

        formatted_chunks = [
            RAG_CONTEXT_TEMPLATE.format(
                index=i + 1,
                page_title=chunk.citation.page_title,
                section=chunk.citation.section,
                content=chunk.content,
                source_url=chunk.citation.source_url,
            )
            for i, chunk in enumerate(reranked)
        ]
        rag_context = "\n".join(formatted_chunks)

        new_citations: list[Citation] = [chunk.citation for chunk in reranked]

        return {
            "rag_context": rag_context,
            "rag_results": reranked,
            # Accumulate rather than replace — LangGraph merges by replacing a
            # key's value outright, so we read the existing list ourselves and
            # append to it, since multiple specialists each trigger their own
            # RAG call across a single multi-intent query.
            "citations": state.get("citations", []) + new_citations,
        }

    return rag_node
