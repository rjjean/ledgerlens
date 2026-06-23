-- Reference DDL for the chunks table. init_schema() renders this from config
-- (embedder_dimensions, hnsw_m, hnsw_ef_construction, fts_language) — do not
-- hardcode a second vector width literal here.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id            TEXT PRIMARY KEY,
    chunk_type    TEXT NOT NULL,
    text          TEXT NOT NULL,
    parent_id     TEXT REFERENCES chunks(id),
    is_table      BOOLEAN NOT NULL DEFAULT FALSE,
    token_count   INTEGER NOT NULL,
    summary       TEXT,
    table_data    JSONB,
    company       TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    cik           TEXT NOT NULL,
    form_type     TEXT NOT NULL,
    fiscal_period TEXT NOT NULL,
    section       TEXT NOT NULL,
    accession_no  TEXT NOT NULL,
    source_url    TEXT NOT NULL,
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    embedding     vector({embedder_dimensions}),
    fts           tsvector GENERATED ALWAYS AS (
        to_tsvector('{fts_language}', text)
    ) STORED
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = {hnsw_m}, ef_construction = {hnsw_ef_construction});

CREATE INDEX IF NOT EXISTS chunks_fts_gin   ON chunks USING gin (fts);
CREATE INDEX IF NOT EXISTS chunks_parent_id ON chunks (parent_id);
CREATE INDEX IF NOT EXISTS chunks_meta      ON chunks (ticker, form_type, fiscal_period);
