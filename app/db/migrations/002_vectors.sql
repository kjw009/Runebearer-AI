CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url    TEXT NOT NULL,
    page_title    TEXT NOT NULL,
    section       TEXT NOT NULL,
    entity_type   TEXT NOT NULL,
    content       TEXT NOT NULL,
    token_count   INTEGER NOT NULL,
    chunk_index   INTEGER NOT NULL,
    embedding     vector(1536),
    scraped_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS documents_embedding_idx
    ON documents USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS documents_entity_type_idx
    ON documents (entity_type);
