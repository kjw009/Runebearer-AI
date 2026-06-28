from typing import Any
from dataclasses import dataclass

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass
class Chunk:
    """
    A single piece of text ready for embedding and storage in pgvector.

    content      — the raw text that gets embedded
    metadata     — source_url, page_title, section, entity_type, chunk_index,
                   last_scraped_at; inherited from the Cleaner and stored
                   alongside the embedding in the documents table
    token_count  — how many tokens this chunk contains, stored for auditing
                   (lets us verify no chunk exceeded the embedding model limit)
    """
    content: str
    metadata: dict[str, Any]
    token_count: int


class Chunker:
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50) -> None:
        # cl100k_base is the tokeniser used by text-embedding-3-small and GPT-4.
        # We use the same tokeniser to count tokens so that chunk_size=512 means
        # exactly 512 tokens as the embedding model sees them — not 512 characters,
        # which would be an inaccurate and inconsistent measure across languages
        # and punctuation-heavy text.
        self.encoder = tiktoken.get_encoding("cl100k_base")

        # RecursiveCharacterTextSplitter tries each separator in order, falling
        # through to the next if a chunk is still too long after splitting.
        #
        # "\n\n" — paragraph boundaries (most natural split point)
        # "\n"   — line breaks within paragraphs
        # ". "   — sentence boundaries
        # " "    — individual words (last resort)
        #
        # This hierarchy means chunks tend to end at paragraph or sentence
        # boundaries rather than mid-word, preserving readable prose.
        #
        # chunk_overlap=50 means the last ~50 tokens of chunk N are repeated at
        # the start of chunk N+1. This prevents a concept that spans a chunk
        # boundary from being split across two chunks with neither capturing
        # enough context to score well in retrieval.
        self.splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", ". ", " "],
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            # length_function tells the splitter how to measure "size".
            # We plug in our tiktoken encoder so the splitter counts tokens,
            # not characters. Without this it would use len(text) which counts
            # characters — wrong for our 512-token budget.
            length_function=lambda text: len(self.encoder.encode(text)),
        )

    def split(self, text: str, base_metadata: dict) -> list[Chunk]:
        """
        Split a cleaned page of text into a list of embedding-sized Chunks.

        base_metadata comes from the Cleaner and contains source_url, page_title,
        section, entity_type, and last_scraped_at. Each chunk inherits these and
        gets its own chunk_index added.
        """
        raw_splits = self.splitter.split_text(text)
        chunks = []

        for idx, split_text in enumerate(raw_splits):
            # .copy() is critical here. Without it, every chunk would reference
            # the same dict object. Setting chunk_metadata["chunk_index"] = idx
            # would then overwrite the index on every previously created chunk,
            # leaving them all with the index of the last chunk.
            chunk_metadata = base_metadata.copy()
            chunk_metadata["chunk_index"] = idx

            # We re-encode each chunk to get its exact token count rather than
            # trusting the splitter's internal accounting. The splitter may
            # produce chunks slightly under chunk_size due to overlap logic —
            # re-encoding gives us the ground truth for the token_count column.
            token_count = len(self.encoder.encode(split_text))

            chunks.append(
                Chunk(
                    content=split_text,
                    metadata=chunk_metadata,
                    token_count=token_count,
                )
            )

        return chunks