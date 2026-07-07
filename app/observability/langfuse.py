from collections.abc import Callable
from functools import wraps
from typing import Any

from langfuse import Langfuse, get_client, observe

from app.config import settings

langfuse_client = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    host=settings.langfuse_host,
)


def agent_span(name: str) -> Callable:
    """
    Wraps a LangGraph node (async, single ``state: BuildState`` arg, returns a
    partial-state dict) in an ``@observe(as_type="agent")`` span, and additionally
    tags the span with session_id / calling_agent metadata that ``@observe``'s
    automatic input capture wouldn't otherwise surface distinctly.
    """

    def decorator(fn: Callable) -> Callable:
        @observe(name=name, as_type="agent")
        @wraps(fn)
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            get_client().update_current_span(
                metadata={
                    "session_id": state.get("session_id"),
                    "calling_agent": state.get("calling_agent"),
                },
            )
            result = await fn(state)
            get_client().update_current_span(
                output={
                    "next_agent": result.get("next_agent"),
                    "final_response_preview": (result.get("final_response") or "")[:200],
                },
            )
            return result

        return wrapper

    return decorator


def rag_span(fn: Callable) -> Callable:
    """Instruments the RAG node specifically as a retriever-type observation."""

    @observe(name="rag_node", as_type="retriever")
    @wraps(fn)
    async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
        result = await fn(state)
        chunks = result.get("rag_results", [])
        get_client().update_current_span(
            metadata={"calling_agent": state.get("calling_agent")},
            output={
                "chunks_retrieved": len(chunks),
                "top_score": chunks[0].similarity_score if chunks else None,
            },
        )
        return result

    return wrapper
