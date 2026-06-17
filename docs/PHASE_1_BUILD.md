---
type: plan
status: active
phase: 1
updated: 2026-06-12
related: ["[[handoff]]", "[[BUILD_PLAN]]", "[[PHASE_0_BUILD]]", "[[Ledgerlens_System_Design_FINAL]]"]
---

# Phase 1 Build Brief — Ingestion & Chunking (the moat)

Kick off in Composer with:
> "Build Phase 1 per docs/PHASE_1_BUILD.md and Ledgerlens_System_Design_FINAL.md (Stage 2 + Stage 5)."
Show the plan and file list first, then build, then pause for review.

**Goal:** a one-shot ingestion pipeline that downloads the locked tech filings,
extracts Item-level sections, chunks them structure-aware (parent/child + intact
tables), stamps every chunk with full provenance, runs data-quality checks, and
writes chunk records to disk — **ready for Phase 2 to embed and store. No
embedding and no database in this phase.** Chunking quality gates every downstream
answer, so over-invest here.

**Authoritative references already in the repo**
- `Ledgerlens_System_Design_FINAL.md` — Stage 2 (edgartools), Stage 5 (the locked
  chunking strategy), §7 build order (MVP).
- `docs/planning/01_Ledgerlens_Project_Outline.md` — §4 (data layer / pipeline).
- Conventions: `docs/CONVENTIONS.md`. Guardrails: `.cursor/rules/`.

## Human inputs (Ryan — needed before / at kickoff)
- **Ticker list is locked** (the 18 below). 
- **EDGAR identity string** — a real name + email for the declared User-Agent (SEC
  fair-access requires it). Set it in `.env` as `EDGAR_IDENTITY`. The pipeline must
  fail with a clear message if it's missing.
- **ADR-0002 (chunking) is authored BY HAND by Ryan.** The agent must NOT write,
  draft, or generate it — it is a deliberate IC→lead portfolio signal.

## What to create

### 1. Config additions (`config.py`)
- `tickers: list[str]` — the locked MVP corpus:
  `MSFT, AAPL, GOOGL, META, NVDA, ADBE, CRM, ORCL, NOW, INTU, WDAY, SNOW, DDOG,
  CRWD, PANW, MDB, AMD, AVGO`.
- `edgar_identity: str | None` — loaded from `.env`; required before any EDGAR call.
- `form_types: list[str] = ["10-K"]` — MVP ingests the latest 10-K per company;
  10-Qs are deferred to a later iteration.
- Chunking params: `child_target_tokens` (~400, valid range 300–500),
  `child_max_tokens`, optional small overlap.
- Output paths: `processed_dir` (`data/processed/`), `sample_path`
  (`data/samples/chunks_sample.jsonl`).

### 2. FilingSource seam (`ingestion/sources.py`)
Mirror the Phase 0 seam pattern — edgartools sits behind an interface; nothing else
imports it directly.
- Abstract `FilingSource` (e.g. `get_latest(ticker, form_type) -> RawFiling`).
- `EdgarFilingSource` — lazy-imports `edgartools`, sets identity from config,
  declares the User-Agent, and throttles requests to respect SEC rate limits. Pin
  the version (already pinned in `pyproject.toml`).
- `FakeFilingSource` — returns a small bundled fixture filing so tests and CI run
  fully offline.
- `get_filing_source()` factory switching on config (default `edgar`, `fake` in tests).

### 3. Section extraction (`ingestion/sections.py`)
- Use edgartools to pull Item-level sections (Item 1A Risk Factors, Item 7 MD&A,
  Item 8 financial statements, and the rest).
- Return typed `Section` objects carrying the Item label, raw text, and table blocks.
- Handle missing or renamed Items gracefully — log and continue, never crash.

### 4. Chunk models (`ingestion/models.py`)
Pydantic v2 models. Provenance is mandatory on every chunk — the citation system is
born here.
- `Provenance`: company, ticker, CIK, form_type, fiscal_period, item/section,
  accession_no, source_url, char_start, char_end.
- `Chunk`: id, text, parent_id, is_table (bool), token_count, provenance.
- `ParentChunk`: id, text, item, provenance.

### 5. Chunking (`ingestion/chunking.py`) — the heart of the phase
Implements the locked Stage 5 strategy:
- **Structure-aware:** split on the Item sections first.
- **Parent/child (small-to-big):** each long section becomes a `ParentChunk`;
  sub-chunk it into ~300–500-token children at paragraph boundaries; set
  `child.parent_id`. Children are the retrieval unit; the parent is the context unit.
- **Tables:** extract intact; store the structured table plus a linearized text and a
  one-line summary as a chunk with `is_table=True`. **Never slice a table mid-row.**
- **Tokenizer:** use a consistent counter for sizing (tiktoken `cl100k` is a fine
  approximation — exact voyage parity is not needed before embedding). Add it to the
  `[ingestion]` optional-deps if used.
- Stamp full provenance (including char offsets) on every chunk.

### 6. Data-quality checks (`ingestion/quality.py`)
Echoes the RBC validation discipline; log everything.
- Section-presence validation (were the expected Items found?).
- Empty / garbled-extraction detection → quarantine + log, never silently drop.
- Dedup + amendment handling (a 10-K/A supersedes its 10-K; don't double-ingest).
- Provenance-completeness check (100%; fail loud if any chunk is missing fields).
- Token-size sanity (children within the target range).
- Emit a quality report (per-filing counts, failures, quarantined filings) to logs
  and a manifest file.

### 7. Pipeline + script (`ingestion/pipeline.py`, `scripts/ingest.py`)
- Orchestrate per ticker: fetch latest 10-K (FilingSource) → extract sections →
  clean → chunk → quality-check → collect.
- Write all chunks to `data/processed/chunks.jsonl` (gitignored — regenerable data).
  Write a small committed sample `data/samples/chunks_sample.jsonl` (~20 chunks) for
  review and as a test basis.
- Throttle EDGAR calls; print per-filing progress and a final quality summary.
- **Validate-first:** support running on just 3 tickers (`MSFT, SNOW, NVDA`) before
  the full 18 — cheaper to debug chunking on three filings than eighteen.

### 8. Tests (`tests/test_chunking.py`, `tests/test_ingestion.py`)
Use `FakeFilingSource` so they run offline. Assert: section boundaries respected;
tables never sliced; children within the token range; 100% provenance completeness;
parent/child links resolve; dedup/amendment handling works.

## Hard constraints (from `.cursor/rules/` + the design doc)
- **Respect EDGAR:** declared User-Agent (Ryan's identity) + throttling, visible in
  the code. No identity set → fail with a clear message.
- **Phase boundary:** Phase 1 does NOT embed and does NOT touch the database. Its
  output is chunk records on disk. Phase 2 owns embedding + storage.
- **Tables are never sliced. 100% provenance on every chunk.**
- **Don't build the Dagster pipeline** (that's Phase 6) — a one-shot script is the
  MVP form. Don't add 10-Qs yet.
- **Seam pattern:** edgartools sits behind `FilingSource`; nothing else imports it.
- **ADR-0002 is Ryan's to write by hand — do not generate it.**

## Done-when
- ≥90–95% of the target filings download and section-extract without error; the rest
  logged and quarantined, never silently dropped.
- 100% of chunks carry complete provenance metadata.
- Spot-check ~20 chunks (the committed sample): section boundaries respected, tables
  intact, no empty/garbled text.
- Data-quality checks run and their report is written/logged.
- Child chunks within the ~300–500-token target; parent/child links intact.
- `pytest` passes offline (via `FakeFilingSource`).

## After Phase 1
- **Ryan writes ADR-0002 (chunking) by hand.**
- Update `handoff.md` (Phase 1 complete) and tick the Phase 1 box in `docs/BUILD_PLAN.md`.
- Next is **Phase 2 (storage + embeddings)**: embed children with `voyage-finance-2`
  behind the `Embedder` seam, upsert into Neon (pgvector + FTS), and reconcile the
  embedding count against the chunk count.