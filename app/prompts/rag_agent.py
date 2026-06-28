# Unlike the supervisor and specialist prompts, the RAG agent doesn't call an LLM
# to generate a response. It calls the retriever, reranker, and query rewriter
# directly — all of which are already implemented in app/rag/.
#
# The only "prompt" the RAG agent needs is this template, which controls how
# each retrieved chunk is formatted into the rag_context string that gets
# injected into the specialist's system prompt.
#
# Usage in rag_node:
#   formatted_chunks = [
#       RAG_CONTEXT_TEMPLATE.format(index=i+1, **chunk_fields)
#       for i, chunk in enumerate(reranked_chunks)
#   ]
#   rag_context = "\n".join(formatted_chunks)

RAG_CONTEXT_TEMPLATE = """\
[{index}] {page_title} — {section}
{content}
Source: {source_url}
"""
