import asyncpg
from typing import Any
from pgvector.asyncpg import register_vector


class VectorRepository:
    """Handles vector storage and retrieval from the pgvector database."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        # We store the pool, not a single connection. The pool keeps multiple
        # connections open and lets us borrow one per operation, which is
        # efficient under concurrent requests.
        self.pool = pool

    async def upsert_batch(self, chunks: list[Any], vectors: list[list[float]]) -> None:
        """
        Upsert a batch of chunks and their vectors into the database.

        Args:
            chunks: List of Chunk objects to upsert
            vectors: List of vectors corresponding to the chunks
        """
        # $1, $2 ... are asyncpg's positional parameter placeholders.
        # The tuple order in `data` below must match this column order exactly.
        #
        # ON CONFLICT (source_url, chunk_index) targets the unique constraint
        # we added in 002_vectors.sql. If a row with the same source URL and
        # chunk position already exists (e.g. re-running ingestion after a wiki
        # update), we overwrite its content and embedding rather than skipping
        # it or erroring. EXCLUDED refers to the incoming row that was blocked
        # by the conflict.
        query = """
            INSERT INTO documents (source_url, page_title, section, entity_type, content, token_count, chunk_index, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (source_url, chunk_index) DO UPDATE
            SET content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                token_count = EXCLUDED.token_count;
        """

        # chunks and vectors are parallel lists — chunks[i] belongs to vectors[i].
        # zip() pairs them so we can build one tuple per row in a single pass.
        # The tuple order matches the $1..$8 placeholders in the SQL above.
        data = [
            (
                chunk.metadata["source_url"],
                chunk.metadata["page_title"],
                chunk.metadata["section"],
                chunk.metadata["entity_type"],
                chunk.content,
                chunk.token_count,
                chunk.metadata["chunk_index"],
                vector,                          # list[float] — pgvector accepts this after register_vector
            )
            for chunk, vector in zip(chunks, vectors)
        ]

        # acquire() borrows one connection from the pool for the duration of
        # this block, then returns it automatically — even if an exception is raised.
        #
        # register_vector() teaches asyncpg how to serialise a Python list[float]
        # into pgvector's binary wire format. Without this call, asyncpg doesn't
        # know what to do when it sees a vector column and will raise a TypeError.
        #
        # executemany() runs the same INSERT once per tuple in `data`, which is
        # far more efficient than calling execute() in a loop.
        async with self.pool.acquire() as conn:
            await register_vector(conn)
            await conn.executemany(query, data)

    async def similarity_search(
        self,
        query_vector: list[float],
        entity_types: list[str],
        top_k: int = 20,
    ) -> list[dict]:
        """
        Find the top_k most similar chunks to query_vector, filtered by entity type.

        Args:
            query_vector: The embedded query — a list of 1536 floats.
            entity_types: Only return chunks whose entity_type is in this list.
                          Each specialist agent passes its own relevant types
                          (e.g. boss_optimisation passes ['boss', 'mechanic']).
            top_k: How many results to return. Defaults to 20 so the retriever
                   can apply MMR to diversify before handing 10 to the reranker.

        Returns:
            List of dicts, one per matching row, including the embedding vector
            so the retriever can compute pairwise similarities for MMR.
        """
        # <=> is pgvector's cosine distance operator (range 0–2, lower = more similar).
        # We ORDER BY distance ascending so the most similar chunks come first.
        #
        # We compute 1 - (embedding <=> $1) as similarity_score to convert distance
        # back to similarity (range -1 to 1, higher = more similar), which is more
        # intuitive to reason about in the retriever and reranker.
        #
        # We SELECT embedding so the retriever has the vectors it needs to compute
        # pairwise similarities between candidates during MMR diversification.
        #
        # ANY($2) lets us pass a Python list as the filter — Postgres expands it
        # to "entity_type IN ('boss', 'mechanic', ...)" automatically.
        query = """
            SELECT id, content, source_url, page_title, section, entity_type, chunk_index, embedding,
                   1 - (embedding <=> $1) AS similarity_score
            FROM documents
            WHERE entity_type = ANY($2)
            ORDER BY embedding <=> $1
            LIMIT $3;
        """

        async with self.pool.acquire() as conn:
            await register_vector(conn)
            # Tune HNSW recall for this connection. The default ef_search (40) trades
            # recall for speed; 100 is a reasonable starting point to benchmark from.
            # Higher = better recall, slower query. Tune against real data with
            # EXPLAIN ANALYZE before committing to a final number.
            await conn.execute("SET hnsw.ef_search = 100")
            # fetch() returns all matching rows as a list of asyncpg Record objects.
            # We use fetch() rather than execute() because we need to read the results.
            # execute() is for writes (INSERT, UPDATE, DELETE) where we don't need rows back.
            result = await conn.fetch(query, query_vector, entity_types, top_k)

            # asyncpg Records behave like dicts but aren't — converting them lets
            # callers use plain dict access without importing asyncpg types.
            return [dict(row) for row in result]

        
        