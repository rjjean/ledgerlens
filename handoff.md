---
type: handoff
status: active
phase: 2
updated: 2026-06-13
related: ["[[index]]", "[[BUILD_PLAN]]", "[[PHASE_1_BUILD]]", "[[PHASE_0_BUILD]]"]
---

# Ledgerlens — Session Handoff

*Last updated: 2026-06-13 — Phase 1 complete; starting Phase 2.*
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

## Current state of the code
**Phase 1 complete.** One-shot ingestion pipeline:
- `ledgerlens/ingestion/` — `FilingSource` seam (`EdgarFilingSource` / `FakeFilingSource`),
  section extraction, parent/child/table chunking, full provenance, data-quality checks.
- `scripts/ingest.py` — defaults to 3-ticker validate-first; `--all` for 18.
- Output: `data/processed/chunks.jsonl` (gitignored) + committed `data/samples/chunks_sample.jsonl`.
- Table chunks link to section parent via `parent_id`; soft token overflows warn, hard max quarantines.
- Phase boundary held: no embedding, no database.

Verified: 3-ticker live run (MSFT, SNOW, NVDA) — 3/3 succeeded, 904 chunks; `pytest` 18 passed;
smoke test GREEN.

## Files currently being edited / in-flight
- None.

## Next steps — Phase 2 (Storage + embeddings)
1. Neon schema (chunks, parents, metadata, pgvector + FTS).
2. `voyage-finance-2` behind the `Embedder` seam — embed children + table summaries.
3. Upsert into Neon; reconcile embedding count vs chunk count.

## What was tried that failed / dead-ends
- **Soft-max token QC quarantined valid filings** — fixed: `child_max_tokens` is a warning;
  `child_hard_max_tokens` (800) quarantines only. MSFT/SNOW/NVDA were failing on borderline
  Item 8 paragraphs before the fix.
- **Tables had `parent_id: null`** — fixed: tables now reference their section parent for
  synthesis expansion and section-scoped retrieval in Phase 2+.

## Phase completion log
- **Phase 0** — complete (2026-06-09). Scaffold + seams + ADR-0001; smoke test GREEN;
  pytest 4 passed; committed on `development` (`d868eea`).
- **Phase 1** — complete (2026-06-13). Ingestion + chunking + ADR-0002; 3-ticker validation
  100%; pytest 18 passed; committed on `development` (`1c5068d` + follow-ups).
