---
type: handoff
status: active
phase: 4
updated: 2026-07-14
related: ["[[index]]", "[[BUILD_PLAN]]", "[[PHASE_3_BUILD]]", "[[PHASE_2_BUILD]]", "[[PHASE_1_BUILD]]", "[[PHASE_0_BUILD]]"]
---

# Ledgerlens — Session Handoff

*Last updated: 2026-07-14 — Phase 3 complete; starting Phase 4.*
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
- **Shipped retrieval config:** `ticker_filter_enabled=True`, `rerank_enabled=False`.
  Reranker seam + `CrossEncoderReranker` remain; default is off (finance-tuned
  cross-encoder later is a config change). Ryan authors the retrieval ADR by hand.

## Current state of the code

**Phase 3 complete.** Hybrid retrieval measured and shipped (ticker filter ON, rerank OFF).

- `ledgerlens/retrieval/` — `HybridRetriever`: query embed (`Embedder.embed_query`) →
  sparse FTS (OR lexemes via `to_tsquery`) + dense pgvector ANN → RRF (k=60) →
  optional MiniLM cross-encoder behind the `Reranker` seam.
- **Ticker pre-filter:** `retrieval/entities.py` static alias map →
  `resolve_ticker(query)`. When exactly one ticker resolves and
  `ticker_filter_enabled`, both legs get `{"ticker": X}`. Zero or 2+ → no filter.
  Explicit caller `filters=` are never overridden.
- **`fetch_parent(parent_id)`** on `ChunkStore` — ready for Phase 4 parent expansion.
- **Eval:** `scripts/eval_retrieval.py` — recall@1/3/5/10 + MRR, per-leg counts,
  breadth scoring, negative controls, 2×2 (filter × rerank).
- Junk page-header tables filtered at chunk time (0 data rows and/or repeated exact
  text ≥ threshold); `embed_and_store.py --truncate` clears Neon before reload.
- Phases 0–2 unchanged underneath (seams, ingestion, storage + voyage embeddings).

**Corpus (post junk-table cleanup):** 5,339 chunks — 412 parents / 3,576 children /
1,351 tables.

**Shipped eval** (2×2, filter × rerank; 9 scored + 1 negative control):

```
filter   rerank      R@1     R@3     R@5    R@10     MRR
OFF      OFF       0.333   0.667   0.778   1.000   0.507
OFF      ON        0.333   0.667   0.778   1.000   0.546
ON       OFF       0.556   0.889   0.889   1.000   0.704   ← shipped
ON       ON        0.444   0.778   0.889   1.000   0.633
```

Verified offline: FakeEmbedder + FakeChunkStore + FakeReranker; pytest green;
smoke GREEN. Opt-in Postgres integration tests guarded by `DATABASE_URL`.

## Files currently being edited / in-flight

- None.

## Next steps — Phase 4 (synthesis + citations)

1. Thin custom RAG core consuming `retrieve()`.
2. Parent expansion via `fetch_parent`.
3. Haiku 4.5 via LiteLLM behind the `LLMClient` seam.
4. Citation-grounded prompt; abstain-when-weak (see Phase 4 constraints below).
5. Do **not** build API/frontend (Phase 5).

### Phase 4 design constraints (do not omit)

- **Top score is NOT a usable abstain signal.** The negative control (q10,
  unanswerable) scores +1.87 at rank 1 — higher than several answerable questions.
  Abstain-when-weak needs a different signal: score margin, dense-distance
  distribution, or an LLM-side check.
- **The static alias map is brittle by construction** — it works because the corpus
  is a fixed 18 tickers and eval questions use canonical company names. LLM-based
  entity extraction is the v1 path.

### Still deferred (carry forward)

- **Table-parser gap:** space-aligned columns not split; `table_data` unreliable;
  linearized `text` is clean so retrieval is unaffected. Revisit when synthesis
  needs structured cells.

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
- **FTS leg was silently dead** — `websearch_to_tsquery` ANDs all terms, so natural-language
  questions matched nothing and "hybrid" retrieval was effectively dense-only. Fixed with
  OR semantics over query lexemes.
- **Junk table chunks polluted retrieval** — 441 contentless page-header artifacts
  (INTU/NOW/GOOGL) were being embedded and ranked; five occupied top-10 slots on a real
  eval question. Fixed by filtering 0-data-row and repeated-text tables at chunk time.
- **Cross-encoder reranker rejected on measurement** — neutral at every cutoff before the
  ticker filter, and actively harmful after it (R@1 0.556 → 0.444, MRR 0.704 → 0.633).
  Default off.

## Phase completion log

- **Phase 0** — complete (2026-06-09). Scaffold + seams + ADR-0001; smoke test GREEN;
  pytest 4 passed; committed on `development` (`d868eea`).
- **Phase 1** — complete (2026-06-13). Ingestion + chunking + ADR-0002; 3-ticker validation
  100%; pytest 18 passed; committed on `development` (`1c5068d` + follow-ups).
- **Phase 2** — complete (2026-06-23). Storage seam + schema + embed/store pipeline +
  reconciliation; offline green on fakes; committed on `development` (`91e191c`).
- **Phase 3** — complete (2026-07-14). Hybrid FTS+ANN+RRF + ticker pre-filter; junk-table
  cleanup; informal recall eval. Shipped filter ON / rerank OFF (R@1 0.556, R@10 1.000,
  MRR 0.704).
