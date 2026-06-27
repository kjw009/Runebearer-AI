from openai import AsyncOpenAI
import asyncpg
from app.config import settings
from app.db.repositories.vectors import VectorRepository
from ingestion.chunker import Chunk


class IngestEmbedder:
    """
    Embeds chunks of text using OpenAI and writes them to pgvector.

    This is the only class in the ingestion pipeline that touches both the
    OpenAI API and the database — everything upstream (scraper, cleaner,
    chunker) produces plain Python objects, and this class is responsible
    for the two external side effects: API call and DB write.
    """

    def __init__(self, pool: asyncpg.Pool, batch_size: int = 100) -> None:
        # Pass credentials explicitly from pydantic settings rather than relying
        # on environment variables being set in the shell. This also handles
        # Azure OpenAI — if OPENAI_BASE_URL is set in .env, the client routes
        # requests to the Azure endpoint instead of api.openai.com.
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

        # VectorRepository owns all SQL for the documents table. IngestEmbedder
        # delegates storage to it rather than writing SQL directly, keeping
        # embedding logic and database logic in separate places.
        self._repo = VectorRepository(pool)

        # How many chunks to send to OpenAI in a single API call.
        # One call per chunk = thousands of round trips for a full knowledge base.
        # Too large a batch can exceed the API's payload size limit.
        # 100 is a reliable middle ground.
        self._batch_size = batch_size

    async def embed_and_upsert(self, chunks: list[Chunk]) -> None:
        """
        Embed all chunks in batches and upsert each batch into pgvector.

        Processes chunks in sliding windows of self._batch_size. For each
        window: embed → extract vectors → upsert. This means data starts
        reaching the database after the first batch, rather than waiting
        for all chunks to be embedded first.
        """
        if not chunks:
            # Nothing to do — avoids a pointless API call if the cleaner
            # produced an empty page (e.g. a redirect or stub article).
            return

        # range(start, stop, step) produces indices 0, 100, 200, ...
        # chunks[i : i + batch_size] slices out each batch without copying.
        for i in range(0, len(chunks), self._batch_size):
            batch_chunks = chunks[i : i + self._batch_size]

            # Extract just the text content — the API doesn't need metadata.
            input_texts = [chunk.content for chunk in batch_chunks]

            response = await self._client.embeddings.create(
                model="text-embedding-3-small",
                input=input_texts,
            )

            # response.data is a list of Embedding objects in the same order
            # as input_texts. OpenAI guarantees this ordering, so vectors[0]
            # corresponds to batch_chunks[0], vectors[1] to batch_chunks[1], etc.
            # Each .embedding is a list of 1536 floats.
            vectors = [item.embedding for item in response.data]

            # upsert_batch handles both insertion and conflict resolution —
            # if a chunk for this (source_url, chunk_index) already exists,
            # it updates the content and embedding rather than duplicating the row.
            await self._repo.upsert_batch(batch_chunks, vectors)