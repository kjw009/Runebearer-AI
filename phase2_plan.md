# Phase 2 Learning Plan — RAG Pipeline

The goal is not just to end up with working code. The goal is to understand *why* each piece exists, so you can reason about retrieval systems in any context, not just this project.

Each step has: a concept to understand first, a task to implement, and a way to verify it worked. Don't move to the next step until the verification passes — each step builds on the one before it.

---

## The map

```
Step 1 → VectorRepository          (SQL layer: write chunks to pgvector, read them back)
Step 2 → Chunk dataclass           (the data model that flows through the whole pipeline)
Step 3 → Scraper                   (async HTTP, rate limiting)
Step 4 → Cleaner                   (HTML → clean prose text)
Step 5 → Chunker                   (split text into embedding-sized pieces)
Step 6 → IngestEmbedder            (batch embed + upsert into pgvector)
Step 7 → Pipeline orchestration    (wire steps 3–6 together, run it)
Step 8 → RAG embedder wrapper      (query-time embedding, separate from ingestion)
Step 9 → Query rewriter            (LLM expands the query before retrieval)
Step 10 → Retriever                (cosine search + MMR diversification)
Step 11 → Reranker                 (cross-encoder precision pass)
Step 12 → Unit tests               (verify the retrieval stack returns sensible results)
```

---

## Step 1 — VectorRepository (`app/db/repositories/vectors.py`)

### Understand first

Read `app/db/migrations/002_vectors.sql` before touching any Python. Answer these questions:

- What does `vector(1536)` mean as a column type? Why 1536 specifically?
- What is an HNSW index? How is it different from a B-tree index (what Postgres uses for regular columns)?
- What does `vector_cosine_ops` mean? What is cosine similarity measuring?
- Why is there a separate index on `entity_type`?

Key insight: cosine similarity finds vectors pointing in the *same direction* in 1536-dimensional space. Text with similar meaning ends up pointing in similar directions because that's what the embedding model was trained to do. The HNSW index lets Postgres find approximate nearest neighbours in that space efficiently — brute-forcing 100k dot products per query would be too slow.

**HNSW parameters in our migration:**
- `m = 16` — each node in the graph has up to 16 neighbours. Higher = more accurate, slower builds and more memory.
- `ef_construction = 64` — how many candidates are considered when building each node's neighbour list. Higher = better index quality, slower to build.

### Implement

Create `app/db/repositories/vectors.py` with two methods:

```python
class VectorRepository:
    def __init__(self, pool: asyncpg.Pool) -> None: ...

    async def upsert_batch(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        # INSERT INTO documents (...) VALUES ... ON CONFLICT DO NOTHING
        # Use asyncpg's executemany or a single multi-row INSERT
        # Hint: pgvector expects the embedding as a string like '[0.1, 0.2, ...]'
        # Use the pgvector Python package's `register_vector` to handle this automatically
        ...

    async def similarity_search(
        self,
        query_vector: list[float],
        entity_types: list[str],
        top_k: int = 20,
    ) -> list[dict]:
        # SELECT id, content, source_url, page_title, section, entity_type,
        #        chunk_index, 1 - (embedding <=> $1) AS similarity_score
        # FROM documents
        # WHERE entity_type = ANY($2)
        # ORDER BY embedding <=> $1
        # LIMIT $3
        #
        # The <=> operator is pgvector's cosine distance (1 - similarity).
        # We ORDER BY distance ascending (most similar first) and return
        # 1 - distance as the similarity score.
        ...
```

Things to figure out:
- How do you pass a Python list as a `vector` type to asyncpg? (Look at the `pgvector` package — `register_vector(conn)`)
- What's the difference between `<=>` (cosine distance), `<->` (L2 distance), and `<#>` (negative inner product) in pgvector? Why do we use `<=>`?

### Verify

Write a small throwaway script (not a test file) that:
1. Creates a pool
2. Registers the vector type
3. Inserts two fake chunks with hand-crafted vectors (e.g., `[1.0, 0.0, 0.0, ...]` and `[0.9, 0.1, 0.0, ...]`)
4. Queries for the nearest neighbour to `[1.0, 0.0, 0.0, ...]`
5. Confirms it returns the first chunk with a high similarity score

---

## Step 2 — Chunk dataclass (`ingestion/chunker.py` — data model only)

### Understand first

Before writing any splitting logic, just understand what a `Chunk` is. It's the unit of data that flows from the cleaner through the chunker into the embedder and finally into the database.

```python
@dataclass
class Chunk:
    content: str           # the actual text
    metadata: dict         # source_url, page_title, section, entity_type, chunk_index
    token_count: int       # how many tokens this chunk contains
```

Why do we store `token_count`? Two reasons:
1. We can audit the ingestion later to check no chunk exceeded the embedding model's context limit.
2. It's useful for debugging — if a chunk has 1 token it probably means the cleaner produced an empty section.

### Implement

Just the dataclass for now. You'll add the `Chunker` class in Step 5.

---

## Step 3 — Scraper (`ingestion/scraper.py`)

### Understand first

We're scraping the Elden Ring wiki (Fextralife or the wiki.gg). Why async HTTP?

A synchronous scraper fetches one URL, waits for the response, then fetches the next. All the waiting time (network round-trips) is wasted. An async scraper using `aiohttp` can have many requests in flight simultaneously — while one response is arriving, the event loop is sending the next request.

**Rate limiting:** even with async, we must not hammer a wiki server. `0.5 req/s` means one request every 2 seconds. The standard pattern is `asyncio.Semaphore(1)` combined with `asyncio.sleep(2.0)` — the semaphore ensures only one request runs at a time, the sleep provides the spacing.

### Implement

```python
class Scraper:
    def __init__(self, rate_limit: float = 0.5) -> None:
        # rate_limit is requests per second
        # store the delay (1 / rate_limit) and a semaphore
        ...

    async def fetch(self, url: str) -> str:
        # acquire semaphore → GET url with aiohttp → sleep(delay) → release → return HTML
        # set a reasonable timeout (10s) and a User-Agent header
        # raise on non-200 status
        ...

    async def iter_pages(self, urls: list[str]) -> AsyncIterator[tuple[str, str]]:
        # yield (url, html) for each URL
        # catch and log exceptions per URL rather than aborting the whole batch
        ...
```

Things to figure out:
- Why use `asyncio.Semaphore` rather than just `asyncio.sleep` between requests?
- What's an `aiohttp.ClientSession` and why should you create one and reuse it rather than making a new one per request?
- What does a `User-Agent` header do and why should you set one when scraping?

### Verify

Pick two or three wiki URLs manually, instantiate the scraper, and call `fetch()` on them. Check that you get back HTML strings and that the delay between requests is working.

---

## Step 4 — Cleaner (`ingestion/cleaner.py`)

### Understand first

Raw HTML from a wiki page contains navigation bars, sidebars, infoboxes, ads, edit buttons, category lists, and footers — none of which is useful for a knowledge base. A RAG system needs clean prose.

BeautifulSoup gives you a parsed DOM tree. You can:
- Remove entire tags by name: `soup.find_all('nav')` → `tag.decompose()`
- Extract text from specific elements: `soup.find('div', class_='mw-parser-output')`
- Get just the text content: `element.get_text(separator='\n')`

The section heading is valuable metadata. We want to know that a chunk came from the "Weaknesses" section of the Malenia page, not just that it came from the Malenia page.

### Implement

```python
class Cleaner:
    def clean(
        self,
        html: str,
        source_url: str,
        entity_type: str,
    ) -> tuple[str, dict]:
        # 1. Parse with BeautifulSoup
        # 2. Remove: nav, footer, aside, .infobox, .toc, script, style tags
        # 3. Extract the page title (usually <h1> or <title>)
        # 4. Extract the main content element (e.g. div.mw-parser-output for MediaWiki)
        # 5. Walk the content, extracting headings as section markers
        # 6. Return (clean_text, metadata_dict)
        #    metadata = {source_url, page_title, section, entity_type, last_scraped_at}
        ...
```

Things to figure out:
- What CSS classes does Fextralife / the wiki use for the main content area? You'll need to inspect a real page.
- How do you preserve section structure? One approach: as you walk the DOM, track the current `<h2>` or `<h3>` text as the active "section" variable.
- What do you do with tables? (Wiki pages have a lot of them — stat tables, drop tables etc.) `table.get_text()` can produce reasonable plain text.

### Verify

Pass the raw HTML from one scraped URL through your cleaner. Print the output. Does it look like clean readable prose with no nav or infobox junk? Are the sections labelled correctly?

---

## Step 5 — Chunker (`ingestion/chunker.py`)

### Understand first

`RecursiveCharacterTextSplitter` from LangChain splits text by trying a list of separators in order: `["\n\n", "\n", ". ", " "]`. It tries to split on double newlines (paragraph boundaries) first. If a paragraph is still too long, it splits on single newlines. Then on sentence boundaries. Then on spaces. This hierarchy means chunks tend to end at natural linguistic breaks rather than mid-sentence.

**Why tiktoken instead of `len(text)`?**

Embedding models have token limits, not character limits. The ratio of characters to tokens varies — code, punctuation-heavy text, and non-English text have different ratios. Counting with `tiktoken` (the same tokeniser OpenAI uses) gives you an accurate token count. `cl100k_base` is the encoding used by `text-embedding-3-small`.

**Why 512 tokens with 50-token overlap?**

512 is well under the 8192-token limit, keeping each chunk focused on a narrow topic. 50 tokens of overlap means the last ~3-4 sentences of chunk N are also the first ~3-4 sentences of chunk N+1. This prevents a concept that spans a chunk boundary from becoming unretrievable — neither chunk captures it fully, but both capture enough to score well in retrieval.

### Implement

```python
class Chunker:
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50) -> None:
        # Create a tiktoken encoder for cl100k_base
        # Create a RecursiveCharacterTextSplitter with:
        #   separators=["\n\n", "\n", ". ", " "]
        #   chunk_size=chunk_size
        #   chunk_overlap=chunk_overlap
        #   length_function = lambda t: len(encoder.encode(t))
        ...

    def split(self, text: str, base_metadata: dict) -> list[Chunk]:
        # Split the text
        # Return a list of Chunk dataclasses
        # Each chunk gets base_metadata plus chunk_index (its position in the list)
        # Each chunk gets its actual token_count computed
        ...
```

### Verify

Take a long piece of plain text (a few paragraphs of Elden Ring lore you can copy-paste). Run it through the chunker. Check:
- Are all chunks ≤ 512 tokens?
- Do adjacent chunks share ~50 tokens at their boundary?
- Does the `chunk_index` start at 0 and increment?

---

## Step 6 — IngestEmbedder (`ingestion/embedder.py`)

### Understand first

The OpenAI embeddings endpoint accepts a list of strings and returns a list of 1536-float vectors — one per input string. We batch 100 chunks per API call because:
- One API call per chunk would be 10,000+ round trips to embed a modest knowledge base. That's slow and burns rate limit quota.
- Very large batches can hit API payload size limits.
- 100 is a good middle ground that OpenAI handles without complaint.

The `IngestEmbedder` ties together the OpenAI client and the `VectorRepository`. It's the only place in the ingestion pipeline that knows about both embedding and database storage.

### Implement

```python
class IngestEmbedder:
    def __init__(self, pool: asyncpg.Pool, batch_size: int = 100) -> None:
        self._client = AsyncOpenAI()
        self._repo = VectorRepository(pool)
        self._batch_size = batch_size

    async def embed_and_upsert(self, chunks: list[Chunk]) -> None:
        # For each batch of self._batch_size chunks:
        #   1. Call client.embeddings.create(model="text-embedding-3-small", input=[...])
        #   2. Extract the embedding vectors from the response
        #   3. Call self._repo.upsert_batch(batch_chunks, vectors)
        ...
```

Things to figure out:
- What does the OpenAI embeddings response object look like? (`response.data` is a list of `Embedding` objects, each has `.embedding` — a list of floats.)
- What order does OpenAI guarantee the embeddings are returned in? (Same order as the input — but worth knowing explicitly.)

### Verify

Embed 5 fake chunk strings and print the first 5 values of the returned vectors. They should be floats between roughly -1 and 1. Then confirm they were inserted into the database by querying `SELECT count(*) FROM documents`.

---

## Step 7 — Pipeline orchestration (`ingestion/pipeline.py`)

### Understand first

The pipeline is a thin orchestration layer. It doesn't do any of the work itself — it just connects the pieces in the right order and handles logging and errors per URL.

The key design decision is error isolation: if one URL fails (404, timeout, bad HTML), that shouldn't abort the entire pipeline. Wrap each URL's processing in a `try/except` and log the failure, then continue with the next URL.

### Implement

Start with a simple sequential version first, then make it concurrent if you want:

```python
async def run_pipeline(entity_type: str, urls_file: str, pool: asyncpg.Pool) -> None:
    urls = (SOURCES_DIR / urls_file).read_text().splitlines()
    scraper = Scraper(rate_limit=0.5)
    cleaner = Cleaner()
    chunker = Chunker()
    embedder = IngestEmbedder(pool)

    async for url, html in scraper.iter_pages(urls):
        try:
            text, metadata = cleaner.clean(html, source_url=url, entity_type=entity_type)
            chunks = chunker.split(text, base_metadata=metadata)
            await embedder.embed_and_upsert(chunks)
            logger.info("Ingested %d chunks from %s", len(chunks), url)
        except Exception:
            logger.exception("Failed to ingest %s", url)
```

You'll also need to create the URL source files. Start small — 5–10 URLs per category, not hundreds. You can expand later.

**Create `ingestion/sources/` text files:**
- `wiki_boss_urls.txt` — Malenia, Radahn, Morgott, Maliketh, Rykard (etc.)
- `wiki_weapon_urls.txt` — Moonveil, Rivers of Blood, Bloodhound's Fang (etc.)
- `wiki_stat_urls.txt` — the Vigor, Dexterity, Strength pages
- `wiki_item_urls.txt` — key talismans and consumables
- `wiki_mechanic_urls.txt` — Bleed, Frost, Status Effects pages

### Verify

Run `python -m ingestion.pipeline` with 3-5 URLs. Watch the logs. Then:
```sql
SELECT entity_type, count(*) FROM documents GROUP BY entity_type;
```
You should see rows grouped by type with reasonable counts.

---

## Step 8 — RAG embedder wrapper (`app/rag/embedder.py`)

### Understand first

This is a separate file from `ingestion/embedder.py` even though it calls the same OpenAI API. The difference:

| | `ingestion/embedder.py` | `app/rag/embedder.py` |
|---|---|---|
| Caller | Ingestion pipeline (offline) | RAG node (per query, at runtime) |
| Input | Batch of 100 chunks | Single query string |
| Output | Stored to DB | Returns a vector for similarity search |
| Has DB access | Yes | No |

They're kept separate because mixing offline ingestion logic with online query logic would make both harder to understand and test.

### Implement

```python
class Embedder:
    def __init__(self) -> None:
        self._client = AsyncOpenAI()

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding
```

That's it. Simple wrapper. Its value is testability — you can mock `Embedder` in unit tests without patching the entire OpenAI module.

---

## Step 9 — Query rewriter (`app/rag/query_rewriter.py`)

### Understand first

Why rewrite at all? Consider the query: `"good weapon for bleed build"`.

The wiki content looks like: *"Rivers of Blood is a Katana that scales primarily with Dexterity and Arcane. It has a unique Ash of War — Corpse Piler — which rapidly applies Hemorrhage buildup."*

The word "bleed" doesn't appear in that passage. The embedding of the raw query may not be close to the embedding of that passage. Rewriting to `"weapons that apply hemorrhage blood loss buildup katana arcane dexterity"` gets much closer.

**HyDE (Hypothetical Document Embeddings):** instead of rewriting the *question*, you ask the LLM to write a *hypothetical answer*. A fake answer looks like real wiki content, so its embedding lands near real wiki chunks in vector space. You then embed the hypothetical answer and use that as the search vector.

We'll implement the simpler variant: 3 expanded query strings. HyDE is an optional extension.

### Implement

```python
class QueryRewriter:
    def __init__(self) -> None:
        self._client = AsyncAnthropic()

    async def rewrite(self, query: str, calling_agent: str) -> list[str]:
        # Call Claude with a prompt that explains:
        # - You are an Elden Ring expert
        # - The calling agent is: {calling_agent}
        # - The player's query is: {query}
        # - Produce 3 search-optimised reformulations
        #   that expand abbreviations and add domain vocabulary
        # - Return them as a JSON list of strings
        # Parse and return the list
        ...
```

Things to figure out:
- What's the right prompt? Think about what information you want the LLM to add. Domain-specific terms ("hemorrhage" not "bleed"), entity names (full boss names), relevant stat names.
- Should you pass `calling_agent` to the prompt? Yes — a `boss_optimisation` rewrite should add boss-specific vocabulary; a `stat_prioritisation` rewrite should add soft cap vocabulary.
- How do you parse JSON from a Claude response reliably? (`response.content[0].text`, then `json.loads()` — but Claude may wrap it in markdown, so strip ` ```json ` fences.)

### Verify

Call `rewriter.rewrite("malenia tips", "boss_optimisation")` and print the result. The three variants should be noticeably richer in Elden Ring vocabulary than the original.

---

## Step 10 — Retriever (`app/rag/retriever.py`)

### Understand first

This is the most algorithmically interesting step in the whole project.

**Cosine search** returns the top-20 most similar chunks. But "most similar" doesn't mean "most useful" — it means "most like the query vector". Two adjacent chunks on the same wiki page section might both score 0.92, pushing a more relevant but differently-worded chunk from another page off the list. You want diversity.

**MMR — Maximal Marginal Relevance:**

```
score(candidate) = λ × sim(candidate, query) − (1 − λ) × max(sim(candidate, selected))
```

The second term penalises candidates that are too similar to chunks already selected. The algorithm:

```
selected = []
candidates = top-20 results from cosine search

while len(selected) < 10:
    best = argmax over candidates of MMR score
    selected.append(best)
    candidates.remove(best)

return selected
```

λ = 0.5 weights relevance and diversity equally. This is a hyperparameter you could tune.

**Implementing MMR requires having the embedding vectors of the candidates**, not just their content. So `similarity_search` needs to return the stored embeddings too. Update your SQL query in `VectorRepository` to also `SELECT embedding`.

### Implement

```python
class Retriever:
    def __init__(self, pool: asyncpg.Pool, embedder: Embedder) -> None: ...

    async def retrieve(
        self,
        query: str,
        entity_types: list[str],
        top_k_cosine: int = 20,
        top_k_mmr: int = 10,
        mmr_lambda: float = 0.5,
    ) -> list[RagChunk]:
        # 1. Embed the query
        # 2. Call VectorRepository.similarity_search(query_vector, entity_types, top_k_cosine)
        # 3. Apply MMR to reduce to top_k_mmr
        # 4. Return list[RagChunk] with content, citation, similarity_score
        ...

    def _mmr(
        self,
        query_vector: list[float],
        candidates: list[dict],   # each has 'embedding' and 'similarity_score'
        top_k: int,
        lambda_: float,
    ) -> list[dict]:
        # Implement the greedy MMR selection loop
        ...
```

For the cosine similarity calculation inside MMR you can use `numpy`:
```python
import numpy as np

def _cosine(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
```

### Verify

With some data in the database from Step 7, call `retriever.retrieve("Malenia scarlet rot weakness", ["boss", "mechanic"])`. Print the returned chunks. Do they look relevant? Are they from different sections (diversity working)?

---

## Step 11 — Reranker (`app/rag/reranker.py`)

### Understand first

We have 10 chunks from MMR. The cross-encoder re-scores all 10 against the original query and we keep the top 5.

The model is `cross-encoder/ms-marco-MiniLM-L-6-v2` from HuggingFace. It was trained on the MS MARCO passage ranking dataset — given a (query, passage) pair, predict how relevant the passage is. It outputs a raw logit score (not a probability), where higher = more relevant.

This runs locally via `sentence-transformers`, not via an API call. The model is small (~80MB) and fast enough on CPU for 10 candidates. The first call will download the model weights.

### Implement

```python
from sentence_transformers import CrossEncoder

class Reranker:
    def __init__(self) -> None:
        self._model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

    def rerank(self, query: str, chunks: list[RagChunk], top_k: int = 5) -> list[RagChunk]:
        # 1. Build pairs: [(query, chunk.content) for chunk in chunks]
        # 2. Call self._model.predict(pairs) → list of scores
        # 3. Sort chunks by score descending
        # 4. Return top_k
        ...
```

Note: `CrossEncoder.predict()` is synchronous (it runs local inference, no I/O). Call it directly — no `await`.

Things to figure out:
- `self._model.predict(pairs)` returns a numpy array. How do you sort the chunks by these scores while keeping chunks and scores paired? (`zip(chunks, scores)`, then `sorted(..., key=lambda x: x[1], reverse=True)`)

### Verify

Pass the 10 chunks from Step 10 through the reranker. Print the titles/sections of the top 5. Do the ones at the top seem more on-topic for the query than the ones that were filtered out?

---

## Step 12 — Unit tests

### Write these tests

**`tests/unit/test_retriever.py`:**
```python
async def test_mmr_reduces_to_top_k(): ...
    # Create 5 fake candidates with known vectors
    # Two of them are nearly identical (high mutual cosine similarity)
    # Assert MMR picks only one of the near-duplicate pair

async def test_retriever_returns_rag_chunks(): ...
    # Mock the embedder and the DB call
    # Assert the returned objects are RagChunk instances with correct fields
```

**`tests/unit/test_query_rewriter.py`:**
```python
async def test_rewriter_returns_three_variants(): ...
    # Mock the Anthropic client to return a fixed JSON list
    # Assert the result is a list of 3 strings
```

**`tests/integration/test_retriever.py`:**
```python
async def test_retrieval_returns_relevant_chunks(db_pool): ...
    # Assumes ingestion has been run
    # Call retrieve("Malenia weaknesses bleed", ["boss"])
    # Assert at least one chunk mentions "Malenia"
    # Assert all returned chunks have similarity_score > 0.5
```

---

## Concept checkpoints

After you finish each group, you should be able to answer these without looking at the code:

**After Steps 1–2:**
- Why does cosine similarity work for semantic search? What does it measure geometrically?
- Why does pgvector use an HNSW index instead of scanning every row?

**After Steps 3–5:**
- What would go wrong if you embedded whole wiki pages instead of chunks?
- Why does the chunker count tokens rather than characters?
- Why does asyncio help the scraper but not the chunker?

**After Steps 6–7:**
- What is the OpenAI embedding endpoint actually doing? (Hint: it's a transformer encoder with a pooling layer — not a generative model.)
- Why do we batch embedding requests?

**After Steps 8–11:**
- What is the fundamental tradeoff between bi-encoder (cosine search) and cross-encoder (reranking)?
- Why does MMR produce better retrieval results than pure cosine search? When would pure cosine search be better?
- What does "query rewriting" actually add to the system? What queries would benefit most?

---

## Order matters

Do not skip ahead. Each step produces an output that the next step consumes:

```
002_vectors.sql → VectorRepository (Step 1)
VectorRepository + Chunk → IngestEmbedder (Step 6)
Scraper + Cleaner + Chunker + IngestEmbedder → Pipeline (Step 7)
  [Run pipeline → data in DB]
Embedder (Step 8) → Retriever (Step 10) → Reranker (Step 11)
QueryRewriter (Step 9) → Retriever (Step 10)
```

If you try to test the retriever before running the pipeline, you'll be searching an empty database.
