---
type: plan
status: active
phase: 2
updated: 2026-06-13
related: ["[[handoff]]", "[[BUILD_PLAN]]", "[[PHASE_1_BUILD]]", "[[Ledgerlens_System_Design_FINAL]]"]
---

# Phase 2 Build Brief — Storage & Embeddings

Kick off in Composer with:

> "Build Phase 2 per docs/PHASE_2_BUILD.md and Ledgerlens_System_Design_FINAL.md (Stage 4 + Stage 6). Show the plan and file list first, then build, then pause for review."

**Goal:** turn the Phase 1 chunk records on disk (`data/processed/chunks.jsonl`) into a populated Neon Postgres store — flattened provenance columns for `WHERE`-filtering, a `vector(1024)` column with an **HNSW** index over `voyage-finance-2` embeddings, and a `tsvector` FTS column with a **GIN** index — then **reconcile the embedded count against the chunk count** and fail loud on any mismatch. Embedding goes through the existing `Embedder` seam; psycopg lives behind a new storage seam and is imported nowhere else. **No retrieval in this phase** — no query path, no RRF, no rerank. That is Phase 3.

**Authoritative references already in the repo**

- `Ledgerlens_System_Design_FINAL.md` — Stage 4 (Neon + pgvector + FTS, single DB), Stage 6 (voyage-finance-2), §7 build order (MVP).
- `docs/adr/0001-single-postgres-over-dedicated-vector-db.md` — the storage decision is already recorded; do not re-litigate it.
- `ledgerlens/interfaces/embedder.py` — `Embedder` seam is **already built** (`FakeEmbedder`, `VoyageEmbedder`, `get_embedder()`); Phase 2 consumes it, it does not rebuild it.
- `ledgerlens/ingestion/models.py` — `ChunkRecord` + `Provenance` are the input shape.
- `scripts/check_pgvector.py` — the connectivity / pgvector smoke check already exists.
- Conventions: `docs/CONVENTIONS.md`. Guardrails: `.cursor/rules/`.

## Human inputs (Ryan — needed before / at kickoff)

- **Neon project + `DATABASE_URL`.** Create the project, copy the pooled connection string into `.env`. Run `python scripts/check_pgvector.py` first — it must print `pgvector check OK` before any build work proceeds.
- **Voyage key + spend cap.** Create the key, **set a monthly spend cap in the Voyage console**, add `VOYAGE_API_KEY` to `.env`. Keep `EMBEDDER_BACKEND=fake` until the pipeline is validated end-to-end on fakes; flip to `voyage` only for the real run.
- **Schema-normalization ratification.** §3 recommends a single denormalized `chunks` table. If you'd rather split filing-level metadata into a `filings` table, that is the one Phase 2 decision worth an ADR — **author it by hand** (the ADR-in-your-voice pattern, like ADR-0002). The agent must not draft it.

## What to create

### 1. Config additions (`config.py`)

- `embed_batch_size: int = 128` — batch size for `embed_documents` calls.
- `hnsw_m: int = 16`, `hnsw_ef_construction: int = 64` — HNSW build params, named so the index DDL reads from config rather than magic numbers.
- `fts_language: str = "english"` — the `to_tsvector` configuration.
- Reuse the existing `embedder_dimensions` (1024) as the **single source of truth** for the `vector(...)` column width — the schema must not hardcode a second literal.
- `database_url` already exists; no change needed.

### 2. Storage seam (`ledgerlens/storage/`)

Mirror the seam pattern (same discipline as `FilingSource` in Phase 1 and `Embedder` in Phase 0). **psycopg is imported only inside this module.** A new model/provider is a config change; the dense leg can later be lifted to Qdrant behind this same interface (ADR-0001 escape hatch).

- `storage/store.py` — abstract `ChunkStore` with: `init_schema()`, `upsert_chunks(records: list[ChunkRecord], embeddings: dict[str, list[float]])`, `count_rows()`, `count_embedded()`, `count_by_type()`.
- `storage/postgres.py` — `PostgresChunkStore`: **lazy-imports psycopg inside methods**, reads `DATABASE_URL`, registers pgvector, runs the schema, performs the upsert. Fail with a clear message if `DATABASE_URL` is unset.
- `storage/fake.py` — `FakeChunkStore`: in-memory dict keyed by chunk id, no DB. This is what tests run against so `pytest` stays offline.
- `get_chunk_store()` factory (in `storage/__init__.py` or `factory.py`) switching on a `storage_backend` config value (`postgres` default, `fake` in tests). Keep it thin — there is only one real backend.

### 3. Schema (`ledgerlens/storage/schema.sql`)

One denormalized `chunks` table — flattened provenance keeps metadata filtering as ordinary `WHERE`, which is the whole point of the single-Postgres decision. Parent chunks live in the same table with a **NULL embedding** so Phase 3 parent-expansion is a plain self-join on `parent_id`.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id            TEXT PRIMARY KEY,
    chunk_type    TEXT NOT NULL,              -- parent | child | table
    text          TEXT NOT NULL,
    parent_id     TEXT REFERENCES chunks(id),
    is_table      BOOLEAN NOT NULL DEFAULT FALSE,
    token_count   INTEGER NOT NULL,
    summary       TEXT,
    table_data    JSONB,
    -- flattened provenance (the citation system; all filterable)
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
    -- dense leg (parents stay NULL; width must equal embedder_dimensions)
    embedding     vector(1024),
    -- sparse leg (generated; Phase 3 queries it)
    fts           tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS chunks_fts_gin   ON chunks USING gin (fts);
CREATE INDEX IF NOT EXISTS chunks_parent_id ON chunks (parent_id);
CREATE INDEX IF NOT EXISTS chunks_meta      ON chunks (ticker, form_type, fiscal_period);
```

Notes for the agent:

- `vector_cosine_ops` — voyage embeddings are normalized, so cosine is the right operator class. Phase 3 must use the matching distance operator.
- The `vector(1024)` width and the HNSW `m` / `ef_construction` values must be rendered from config (`embedder_dimensions`, `hnsw_m`, `hnsw_ef_construction`), not duplicated as literals. If you template the SQL, template these.
- Keep the DDL idempotent (`IF NOT EXISTS`) so `init_schema()` is safe to re-run.

### 4. Embedding step (inside the Phase 2 pipeline, via the seam)

- Read `data/processed/chunks.jsonl` into `ChunkRecord`s.
- **Embed children and tables only — never parents.** Parents are the context unit, retrieved by `parent_id` expansion at synthesis time (ADR-0002 / design Stage 5).
- Children: embed `text`. Tables: embed the searchable representation — `summary` joined with the linearized table text — so numeric/table queries hit the right unit. Be explicit and consistent about which field(s) you embed.
- Encode through `get_embedder().embed_documents(...)` (document input type — keep it separate from query encoding, which Phase 3 owns). Batch by `embed_batch_size`.
- The fake backend already returns deterministic 1024-d vectors, so the whole pipeline runs and is testable before a single paid Voyage call.

### 5. Upsert + reconciliation (`scripts/embed_and_store.py`)

Mirror `scripts/ingest.py` (same `--tickers` / `--all` validate-first ergonomics; default to `MSFT,SNOW,NVDA`).

- Orchestrate: load chunks → select embed targets (child + table) → embed in batches → `upsert_chunks(...)` (parents included, embedding NULL) → ensure indexes.
- **Idempotent upsert:** `INSERT ... ON CONFLICT (id) DO UPDATE`. Re-running the script must not duplicate rows or double-embed.
- **Reconciliation gate** (this is the Phase 2 data-quality discipline — the RBC count reconciliation, modernized):
  - `count_rows()` == total chunks in the jsonl.
  - `count_embedded()` == number of child + table chunks.
  - parent rows have NULL embedding.
  - **Fail loud** on any mismatch; write a small report to `data/processed/storage_report.json` (rows, embedded, by-type counts, mismatches).
- Print per-batch progress and a final reconciliation summary.

### 6. Tests (`tests/test_storage.py`)

Run fully offline — `FakeEmbedder` + `FakeChunkStore`. Assert:

- embed-target selection: children + tables get vectors, **parents do not**;
- every embedding has length `embedder_dimensions` (1024);
- upsert is idempotent (run twice → same row count);
- reconciliation passes on a clean fixture and **raises** on a deliberately broken one (e.g. a dropped embedding);
- `ChunkRecord` → row mapping round-trips provenance fields intact.
- The real Postgres round-trip (pgvector insert + HNSW) is an **opt-in integration test** guarded by `DATABASE_URL` and skipped when unset — so default `pytest` needs no DB.

## Hard constraints (from `.cursor/rules/` + the design doc)

- **Phase boundary:** Phase 2 embeds and stores. It does **NOT** build retrieval — no query embedding, no FTS/vector search, no RRF, no rerank. Output is a populated Neon DB and a passing reconciliation report. Phase 3 owns the query path.
- **Seam pattern, strict:** psycopg is imported only inside `ledgerlens/storage/`; voyageai only inside `VoyageEmbedder` (already true). Embedding always goes through `get_embedder()`; storage always through `get_chunk_store()`.
- **Never embed parents.** Children + tables are the retrieval units.
- `embedder_dimensions` **is the single source of truth** for vector width — schema reads it; no second literal.
- **Idempotent upsert** keyed on chunk `id`.
- **Spend discipline:** Voyage spend cap set *before* the first `EMBEDDER_BACKEND=voyage` run; stay on `fake` until the pipeline is green on fakes.
- **No Dagster, no watermarking, no incremental-embed bookkeeping** — that's Phase 6. A one-shot script is the MVP form. Idempotent upsert covers re-runs for now.
- **Don't re-litigate ADR-0001.** Single Postgres is locked.

## Done-when

- `python scripts/check_pgvector.py` prints `pgvector check OK` against Neon.
- `init_schema()` applied: `chunks` table + HNSW + GIN + supporting indexes exist; DDL is re-runnable.
- Validate-first run on `MSFT,SNOW,NVDA`: rows land in Neon; the ~904 Phase 1 chunks are present with the right by-type split.
- Reconciliation passes — embedded count == child+table count, total rows == total chunks, parents NULL — and `data/processed/storage_report.json` is written.
- Re-running `scripts/embed_and_store.py` is idempotent (row count unchanged).
- `pytest` passes offline (FakeEmbedder + FakeChunkStore; Postgres test skipped without `DATABASE_URL`).
- Real Voyage run completed once on the 3-ticker set, under the spend cap.

## After Phase 2

- If you split out a `filings` table (or make any schema call you consider decision-grade), **write that ADR by hand** (ADR-0003 candidate) — the agent does not draft it.
- Update `handoff.md` (Phase 2 complete: schema, embeddings, reconciliation; note the embedded/row counts and any quarantines) and tick the Phase 2 box in `docs/BUILD_PLAN.md`.
- Next is **Phase 3 (retrieval):** FTS + pgvector + RRF (k=60) + MiniLM rerank, with an informal recall check on ~10 hand questions and a measured rerank-uplift check.
