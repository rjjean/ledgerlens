---
type: plan
status: active
phase: 3
updated: 2026-06-23
related: ["[[handoff]]", "[[BUILD_PLAN]]", "[[PHASE_2_BUILD]]", "[[Ledgerlens_System_Design_FINAL]]"]
---

# Phase 3 Build Brief — Hybrid Retrieval

Kick off in Composer with:
> "Build Phase 3 per docs/PHASE_3_BUILD.md and Ledgerlens_System_Design_FINAL.md (retrieval stage). Show the plan and file list first, then build, then pause for review."

**Goal:** turn the populated Neon store into a retrieval function. Given a question,
embed it as a *query*, run two legs over the `chunks` table — sparse FTS (`tsvector`) and
dense ANN (pgvector cosine) — fuse them with **Reciprocal Rank Fusion (k=60)**, rerank the
fused candidates with the in-process MiniLM cross-encoder, and return the top-k child/table
chunks with full provenance. Then run an **informal recall check on ~10 hand questions** and
**measure the rerank uplift** (recall@k with rerank on vs off). Retrieval reads the existing
Neon DB; it does not re-embed. **No synthesis and no API in this phase** — no LLM call, no
FastAPI, no frontend. Output is a `retrieve()` function, a recall number, and a rerank-uplift
number.

**Authoritative references already in the repo**
- `Ledgerlens_System_Design_FINAL.md` — the retrieval stage (hybrid FTS + dense → RRF → rerank),
  §6 locked stack (RRF k=60, in-process MiniLM rerank, Cohere excluded).
- `ledgerlens/storage/` — `ChunkStore` seam is **already built** (Phase 2); Phase 3 *extends*
  it with query methods. psycopg/pgvector stay confined to `postgres.py`.
- `ledgerlens/interfaces/embedder.py` — `get_embedder().embed_query()` already exists and is
  **separate from `embed_documents`** (asymmetric encoding — do not mix them).
- `ledgerlens/interfaces/reranker.py` — `Reranker` seam already built:
  `rerank(query, documents, top_k) -> list[RerankResult(index, score)]` (descending; `index`
  points into the input list). `FakeReranker` preserves order; `CrossEncoderReranker`
  lazy-imports `sentence_transformers` and uses `reranker_model` (MiniLM).
- The Phase 2 `chunks` schema: `embedding vector(1024)` (HNSW, `vector_cosine_ops`),
  `fts tsvector` (GIN), flattened provenance columns, `parent_id`. Parents have NULL embedding.
- Conventions: `docs/CONVENTIONS.md`. Guardrails: `.cursor/rules/`.

## Human inputs (Ryan — needed before / at kickoff)
- **The ~10 hand questions.** Write a small labeled set: each question + the filing(s)/section(s)
  that should answer it (e.g. "What are NVIDIA's main risk factors?" → NVDA Item 1A). This is the
  recall yardstick — it encodes domain judgment, so it is **yours to author**, not the agent's
  (same principle as ADRs). Put it in a fixture file the eval script reads. The full Ragas golden
  set is Phase 7; this is the informal check.
- **Reranker decision is already locked** (MiniLM, in-process, Cohere excluded for the
  non-production restriction). Don't let the agent reopen it.

## What to create

### 1. Config additions (`config.py`)
- `rrf_k: int = 60` — the RRF constant (locked by the design doc).
- `dense_candidates: int = 50`, `fts_candidates: int = 50` — how many each leg returns
  before fusion.
- `rerank_candidates: int = 30` — how many fused candidates are fed to the cross-encoder.
- `retrieval_top_k: int = 10` — final result count after rerank.
- `rerank_enabled: bool = True` — toggle so the eval can measure rerank on/off.

### 2. Extend the `ChunkStore` seam (`storage/store.py`, `postgres.py`, `fake.py`)
Retrieval queries are a storage concern — keep psycopg inside `postgres.py`.
- `search_dense(query_embedding: list[float], k: int, filters: dict | None) -> list[ScoredChunk]`
  — pgvector cosine: `ORDER BY embedding <=> %(q)s LIMIT k`, **only over rows where
  `embedding IS NOT NULL`** (children + tables; never parents). Return chunk + distance/score.
- `search_fts(query_text: str, k: int, filters: dict | None) -> list[ScoredChunk]`
  — `WHERE fts @@ websearch_to_tsquery(%(lang)s, %(q)s)` ordered by `ts_rank(...)`, `LIMIT k`.
- `fetch_parent(parent_id: str) -> ChunkRecord | None` — fetch the parent section text by id.
  Phase 4 (synthesis) needs this for parent expansion; expose it now, but ranking stays on
  children/tables.
- `filters` apply as plain `WHERE` on the flattened provenance columns (ticker, form_type,
  fiscal_period) — this is the single-Postgres payoff (ADR-0001); metadata filtering is just SQL.
- `FakeChunkStore` implements the same three methods over its in-memory dict (canned, deterministic)
  so retrieval is testable fully offline.

### 3. RRF fusion (`retrieval/fusion.py`)
- `reciprocal_rank_fusion(ranked_lists: list[list[str]], k: int) -> list[tuple[str, float]]`
  — standard RRF: a chunk's fused score is `sum(1 / (k + rank))` across the lists it appears in
  (rank is 1-based position within each leg). Return chunk ids ordered by fused score, descending.
- Pure function, no I/O — unit-test the math directly.

### 4. Hybrid retriever (`retrieval/retriever.py`, `retrieval/models.py`)
- `models.py`: `ScoredChunk` (ChunkRecord + leg score) and `RetrievalResult` (the chunk +
  final rank + scores, carrying full provenance).
- `HybridRetriever.retrieve(query: str, top_k: int | None, filters: dict | None) -> list[RetrievalResult]`:
  1. `vec = get_embedder().embed_query(query)` — **query encoding, not document.**
  2. dense = `store.search_dense(vec, dense_candidates, filters)`;
     fts = `store.search_fts(query, fts_candidates, filters)`.
  3. fuse ids via `reciprocal_rank_fusion([dense_ids, fts_ids], rrf_k)`.
  4. take the top `rerank_candidates`, fetch their text, and if `rerank_enabled`,
     `get_reranker().rerank(query, texts, retrieval_top_k)`; map `RerankResult.index` back to
     chunk ids. If rerank disabled, take the top `top_k` fused directly.
  5. return `RetrievalResult`s with provenance attached.
- Construct dependencies via the factories (`get_chunk_store()`, `get_embedder()`, `get_reranker()`).

### 5. Eval / recall script (`scripts/eval_retrieval.py`)
- Load the hand-question fixture (Ryan's ~10 Q + expected source filings/sections).
- For each question, run `retrieve()` and check whether the expected source appears in the
  top-k (provenance ticker/section match). Print per-question hits and an aggregate recall@k.
- Run it **twice — `rerank_enabled` true and false** — and print the delta. That delta is the
  Phase 3 headline number (does the cross-encoder actually help on this corpus?).
- Pretty-print each result's provenance (ticker, section, accession) so retrieval quality is
  eyeballable, not just a score.

### 6. Tests (`tests/test_retrieval.py`)
Offline — `FakeEmbedder` + `FakeChunkStore` + `FakeReranker`. Assert:
- RRF math is correct on hand-built ranked lists (including a chunk appearing in both legs
  ranking above one appearing in a single leg);
- `retrieve()` returns results with full provenance, honoring `top_k`;
- `filters` restrict results (e.g. a ticker filter excludes other tickers);
- dense search never returns parent chunks (NULL-embedding rows excluded);
- rerank-disabled vs enabled both return well-formed results.
- The real pgvector + FTS queries are an **opt-in integration test** guarded by `DATABASE_URL`
  (verifies cosine ordering and `websearch_to_tsquery` actually run against Neon).

## Hard constraints (from `.cursor/rules/` + the design doc)
- **Phase boundary:** retrieval only. NO LLM/synthesis (Phase 4), NO FastAPI/frontend (Phase 5).
  Output is `retrieve()` + the recall and rerank-uplift numbers.
- **Query vs document encoding stays separate:** use `embed_query()` for the question. The stored
  vectors were written with `embed_documents()` in Phase 2; mixing the two silently hurts recall.
- **Seam pattern, strict:** psycopg/pgvector only inside `storage/postgres.py`;
  `sentence_transformers` only inside `CrossEncoderReranker`. Retrieval depends on
  `get_chunk_store()`, `get_embedder()`, `get_reranker()` — never a vendor SDK directly.
- **Dense leg ranks embedded units only** (children + tables). Parents are context for Phase 4
  via `fetch_parent`, never ranked directly.
- **RRF k=60 is locked.** Don't substitute weighted-sum fusion; if you want to, that's a NEW ADR.
- **Reranker is locked** (in-process MiniLM; Cohere excluded). Don't add a Cohere backend.
- **Don't re-embed and don't mutate the store.** Phase 3 reads the Phase 2 corpus.

## Done-when
- `HybridRetriever.retrieve(query, filters)` returns ranked child/table chunks with full
  provenance, via the seams.
- RRF (k=60) implemented and unit-tested; metadata filters work as `WHERE` clauses.
- MiniLM rerank wired through `get_reranker()` and toggleable via `rerank_enabled`.
- `pytest` green offline (fakes); the Postgres integration test passes when `DATABASE_URL` is set.
- `scripts/eval_retrieval.py` runs against the live Neon corpus (`STORAGE_BACKEND=postgres`,
  `EMBEDDER_BACKEND=voyage` so query vectors share the stored vectors' space) and prints
  recall@k on the ~10 hand questions **plus the rerank on/off delta**.
- Spot-check: the top results for a few questions cite the right filing/section.

## After Phase 3
- If a retrieval design call is decision-grade (RRF vs weighted fusion, candidate-k tuning,
  rerank-vs-no-rerank given the measured delta), **author the ADR by hand** (ADR-0004 candidate;
  ADR-0003 is the amendment-supersession one already queued).
- Update `handoff.md` (Phase 3 complete: recall@k, rerank uplift, any filter/candidate tuning)
  and tick the Phase 3 box in `docs/BUILD_PLAN.md`.
- Next is **Phase 4 (synthesis + citations):** thin custom RAG core, Haiku 4.5 via LiteLLM,
  citation-grounded prompt, abstain-when-weak — consuming `retrieve()` and expanding to parents
  via `fetch_parent`.
