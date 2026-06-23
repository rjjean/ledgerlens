---
type: handoff
status: active
phase: 3
updated: 2026-06-23
related: ["[[index]]", "[[BUILD_PLAN]]", "[[PHASE_1_BUILD]]", "[[PHASE_0_BUILD]]", "[[PHASE_2_BUILD]]"]
---

# Ledgerlens — Session Handoff

*Last updated: 2026-06-23 — Phase 2 complete; starting Phase 3.*
*Update at the close of every build session.*

## Goal

Build Ledgerlens to a fully deployed, monitored, documented finish — the flagship
portfolio project. A citation-grounded RAG product over SEC filings with a published
evaluation harness. Current-arc goal: ship the MVP (tech filings → hybrid retrieval →
cited answers) to a live URL before the v1 differentiators.
Ship rule: a live URL + eval numbers for one finished project beats unfinished repos.

## Locked decisions

- MVP corpus: 18 large-cap tech/software tickers (locked in `config.py`).
- Full stack locked in `Ledgerlens_System_Design_FINAL.md` §6 — do not re-litigate.
- ADR-0002 (chunking) accepted — structure-aware parent/child + intact tables.
- MVP ingestion selects **original 10-K only** — 10-K/A amendments excluded until v1.

## Current state of the code

**Phase 2 complete.** Storage + embedding pipeline (offline-green on fakes; full
18-ticker corpus embedded and reconciled live in Neon):

- `ledgerlens/storage/` — `ChunkStore` seam (`PostgresChunkStore` / `FakeChunkStore`),
  denormalized `chunks` table DDL (pgvector HNSW + GIN FTS), batched idempotent upsert.
- `ledgerlens/storage/pipeline.py` — load jsonl → embed child + table targets → upsert
  (parents with NULL embedding) → reconciliation gate → `storage_report.json`.
- `scripts/embed_and_store.py` — mirrors `ingest.py` CLI (`--tickers` / `--all`;
  default MSFT, SNOW, NVDA).
- **Embed targets:** children + tables only; parents never embedded (ADR-0002 / Stage 5).
- **Table embed text:** linearized `text` only — summaries excluded (auto-generated
  summaries have wrong column counts and add vector noise).
- **Upsert:** parents-first ordering; `executemany` batched by `embed_batch_size`;
  `ON CONFLICT (id) DO UPDATE` for idempotent re-runs.
- psycopg + pgvector imported only inside `ledgerlens/storage/postgres.py`.
- Phase boundary held: no query path, no FTS/vector search, no RRF, no rerank.

Verified offline: `FakeEmbedder` + `FakeChunkStore` — reconciliation passes on fixture;
upsert idempotent; Postgres integration test (opt-in, `DATABASE_URL`) verifies 1024-d
vector round-trip and NULL parent embedding via `register_vector`. `pytest` 33 passed,
1 skipped; smoke test GREEN. Committed on `development` (`91e191c`).

**Real run — complete.** Full 18-ticker embed reconciled in Neon (prerequisite for
Phase 3 retrieval — hybrid search queries these embeddings). Reconciliation PASSED:
`total_chunks=5780`, `rows=5780`, `embedded=5368` (children 3576 + tables 1792),
`parents=412` (0 embedded), `by_type={child: 3576, parent: 412, table: 1792}`.
Ran with `STORAGE_BACKEND=postgres`, `EMBEDDER_BACKEND=voyage` (`voyage-finance-2`);
Voyage spend cap set beforehand.

## Files currently being edited / in-flight

- None.

## Next steps — Phase 3 (Retrieval)

1. Query embedding via `Embedder.embed_query()` (separate from document encoding).
2. Hybrid retrieval: FTS + pgvector ANN + RRF (k=60).
3. In-process MiniLM rerank behind `Reranker` seam.
4. Informal recall check on ~10 hand questions; measure rerank uplift.

## What was tried that failed / dead-ends

- **Soft-max token QC quarantined valid filings** — fixed: `child_max_tokens` is a warning;
  `child_hard_max_tokens` (800) quarantines only. MSFT/SNOW/NVDA were failing on borderline
  Item 8 paragraphs before the fix.
- **Tables had `parent_id: null`** — fixed: tables now reference their section parent for
  synthesis expansion and section-scoped retrieval in Phase 3+.
- **CRM Item 6 `[Reserved]` quarantined whole filing** — fixed: critical vs non-critical
  section gate; placeholders are legitimately empty.
- **AMD partial 10-K/A selected over complete 10-K** — fixed: MVP excludes amendments from
  candidate selection (`select_filing_candidate`). TODO(v1): partial-amendment detect + merge.
- **Table summary prepended to embed text** — dropped: summaries have wrong column counts;
  table embed target is linearized body only.

## Phase completion log

- **Phase 0** — complete (2026-06-09). Scaffold + seams + ADR-0001; smoke test GREEN;
  pytest 4 passed; committed on `development` (`d868eea`).
- **Phase 1** — complete (2026-06-13). Ingestion + chunking + ADR-0002; 3-ticker validation
  100%; pytest 18 passed; committed on `development` (`1c5068d` + follow-ups).
- **Phase 2** — complete (2026-06-23). Storage seam + schema + embed/store pipeline +
  reconciliation; offline green on fakes; committed on `development` (`91e191c`).
