import asyncio
import logging
from pathlib import Path

import asyncpg

from app.config import settings
from ingestion.cleaner import Cleaner
from ingestion.chunker import Chunker
from ingestion.embedder import IngestEmbedder
from ingestion.scraper import Scraper

# basicConfig sets up a default handler that writes to stdout with level INFO.
# This means all logger.info() calls across every ingestion module will appear
# in the terminal when the pipeline runs. Set level=logging.DEBUG to see more
# verbose output during development.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path(__file__) is the absolute path of this file (pipeline.py).
# .parent gives the ingestion/ directory, so SOURCES_DIR always resolves to
# ingestion/sources/ regardless of which directory you run the script from.
SOURCES_DIR = Path(__file__).parent / "sources"


async def run_pipeline(entity_type: str, urls_file: str, pool: asyncpg.Pool) -> None:
    """
    Run the full ingestion pipeline for one entity type: scrape → clean → chunk → embed → upsert.

    entity_type: one of 'boss', 'weapon', 'stat', 'item', 'mechanic', 'patch'.
                 Stored on every chunk so the retriever can filter by calling agent.
    urls_file:   filename inside ingestion/sources/ listing URLs to scrape, one per line.
    pool:        shared asyncpg connection pool passed in from main().
    """
    file_path = SOURCES_DIR / urls_file
    if not file_path.exists():
        # Log and return rather than raising — main() uses asyncio.gather() which
        # runs all pipelines concurrently. A missing file for one entity type
        # should not abort the others.
        logger.error("Sources file %s not found", file_path)
        return

    # splitlines() handles \n, \r\n, and \r line endings correctly.
    # The list comprehension strips whitespace and skips blank lines and lines
    # starting with # so you can comment out URLs in the source files during dev.
    urls = file_path.read_text().splitlines()
    urls = [url.strip() for url in urls if url.strip() and not url.startswith("#")]
    logger.info("Found %d URLs to ingest for entity type: %s", len(urls), entity_type)

    # All four pipeline stages are stateless — no shared mutable state between URLs.
    # A fresh instance per run_pipeline() call keeps things simple and makes each
    # entity type pipeline fully independent.
    scraper = Scraper(rate_limit=0.5)
    cleaner = Cleaner()
    chunker = Chunker()
    embedder = IngestEmbedder(pool)

    logger.info("Starting ingestion for %d URLs of type: %s", len(urls), entity_type)

    # iter_pages() is an async generator — it yields (url, html) one at a time
    # as each page is fetched, rather than fetching all pages first. This means
    # cleaning and embedding start as soon as the first page arrives.
    async for url, html in scraper.iter_pages(urls):
        try:
            # Each stage passes its output directly to the next:
            # clean() → (text, metadata)
            # split() → list[Chunk]  (each Chunk carries both text and metadata)
            # embed_and_upsert() → writes to pgvector, returns nothing
            text, metadata = cleaner.clean(html, source_url=url, entity_type=entity_type)
            chunks = chunker.split(text, base_metadata=metadata)
            await embedder.embed_and_upsert(chunks)
            logger.info("Ingested %d chunks from %s", len(chunks), url)
        except Exception:
            # logger.exception includes the full traceback automatically.
            # We catch broadly and continue so one bad page doesn't abort the
            # rest of the URLs for this entity type.
            logger.exception("Failed to process %s", url)


async def main() -> None:
    """
    Entry point: create the DB connection pool and run all entity pipelines concurrently.

    asyncio.gather() starts all six run_pipeline() coroutines at the same time.
    They run concurrently — while one pipeline is waiting on an HTTP response or
    an OpenAI API call, the event loop can make progress on another. This is much
    faster than running them sequentially.

    The try/finally ensures pool.close() is always called, even if a pipeline
    raises an unhandled exception. This sends proper connection termination
    messages to Postgres rather than leaving dangling connections.
    """
    pool = await asyncpg.create_pool(dsn=settings.postgres_dsn)
    try:
        await asyncio.gather(
            run_pipeline("boss",     "wiki_boss_urls.txt",     pool),
            run_pipeline("weapon",   "wiki_weapon_urls.txt",   pool),
            run_pipeline("stat",     "wiki_stat_urls.txt",     pool),
            run_pipeline("item",     "wiki_item_urls.txt",     pool),
            run_pipeline("mechanic", "wiki_mechanic_urls.txt", pool),
            run_pipeline("patch",    "patch_notes_urls.txt",   pool),
        )
    finally:
        await pool.close()


# __name__ is "__main__" only when this file is run directly:
#   python -m ingestion.pipeline
# When pipeline.py is imported by another module (e.g. in tests), __name__ is
# "ingestion.pipeline" and this block is skipped — asyncio.run() is not called.
if __name__ == "__main__":
    asyncio.run(main())