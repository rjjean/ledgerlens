---
type: plan
status: active
phase: 0
updated: 2026-06-09
related: ["[[handoff]]", "[[BUILD_PLAN]]", "[[Ledgerlens_System_Design_FINAL]]"]
---

# Phase 0 Build Brief — Foundations & Seams

The first task in this repo. Kick off in Composer with:
> "Build Phase 0 per docs/PHASE_0_BUILD.md and Ledgerlens_System_Design_FINAL.md."
Then review the diffs before accepting.

**Goal:** a runnable skeleton — the three swappable interfaces (the seams), config
as a single source of truth, a smoke test, the first ADR, and the docs scaffold.
**No** real ingestion / retrieval / LLM logic yet. Done-when is a green smoke test.

**Authoritative references already in the repo**
- `Ledgerlens_System_Design_FINAL.md` — §6 locked decisions, §11 repo structure,
  Stage 4 (storage rationale → ADR-0001).
- `docs/planning/01_Ledgerlens_Project_Outline.md` — §11 structure, roadmap.
- Conventions: `docs/CONVENTIONS.md`. Guardrails: `.cursor/rules/`.

## What to create

### 1. Package + tooling
- `pyproject.toml` (PEP 621, hatchling, `requires-python = ">=3.12"`). Core deps:
  `pydantic`, `pydantic-settings` ONLY. Everything heavy goes in
  `[project.optional-dependencies]` keyed by phase: `storage`, `embeddings`,
  `rerank`, `llm`, `ingestion`, `api`, `evaluation`, `obs`, `dev`.
- `.env.example` (backend selectors default `fake`; secrets blank).
- `infra/.gitkeep`, `web/.gitkeep`.

### 2. Repo structure (match design doc §11)
Package `ledgerlens/` with subpackages `interfaces/`, `ingestion/`, `retrieval/`,
`api/`, `eval/`, `observability/`. The latter five are empty placeholders whose
`__init__.py` docstring names the phase that fills them. Plus `scripts/`, `tests/`.

### 3. config.py — single source of truth
`Settings(BaseSettings)` (pydantic-settings, reads `.env`). Fields:
- backend selectors `embedder_backend` / `reranker_backend` / `llm_backend`, default `"fake"`.
- locked model ids: `voyage-finance-2`, `cross-encoder/ms-marco-MiniLM-L-6-v2`,
  `anthropic/claude-haiku-4-5`, and a placeholder different-family judge.
- secrets (optional): `database_url`, `anthropic_api_key`, `voyage_api_key`.
- `max_output_tokens`.
Expose `get_settings()`.

### 4. The three seams (interfaces/)
Each = an ABC + a dependency-free `Fake*` (the default) + a lazy-import real impl.
- `Embedder`: `model_name`, `dimensions`, `embed_documents(texts)`, `embed_query(text)`.
  Keep document vs query encoding SEPARATE (they are asymmetric — mixing them
  silently hurts recall). `FakeEmbedder` returns deterministic vectors;
  `VoyageEmbedder` lazy-imports `voyageai`.
- `Reranker`: `rerank(query, documents, top_k) -> list[RerankResult(index, score)]`,
  descending. `FakeReranker` = identity order; `CrossEncoderReranker` lazy-imports
  `sentence_transformers`.
- `LLMClient`: `generate(system, messages, max_tokens) -> LLMResponse(text, usage, model)`.
  `FakeLLM` returns a canned, abstaining answer; `LiteLLMClient` lazy-imports `litellm`.
- `factory.py`: `get_embedder()` / `get_reranker()` / `get_llm()` switch on the config backend.

### 5. Scripts + tests
- `scripts/smoke_test.py`: build each seam via the factory, exercise the fake,
  assert shapes, print "Phase 0 plumbing is GREEN". This is the done-when gate.
- `scripts/check_pgvector.py`: connect to `DATABASE_URL`, `CREATE EXTENSION IF NOT
  EXISTS vector`, report versions (used in Phase 2).
- `tests/test_interfaces.py`: pytest mirror — shapes, determinism, ordering.

### 6. Docs produced during Phase 0
- `docs/adr/0001-single-postgres-over-dedicated-vector-db.md` — write from
  `docs/adr/0000-adr-template.md` using design doc Stage 4 (Context / Decision /
  Consequences / Alternatives; record Qdrant / Pinecone / self-hosted as rejected).
- `README.md` — flesh out: what it is, status, layout, quickstart, the seam pattern,
  account-setup checklist.
- `docs/architecture.md` — placeholder pointing at the design doc.

## Hard constraints (from `.cursor/rules/`)
- The seam pattern: nothing outside an interface implementation calls a vendor SDK.
- Lazy-import heavy SDKs inside methods so the fakes stay dependency-free.
- Phase 0 is plumbing only — no real ingestion / retrieval / LLM logic.

## Done-when
- `pip install -e .` succeeds; `cp .env.example .env`.
- `python scripts/smoke_test.py` prints "Phase 0 plumbing is GREEN".
- `pytest` passes.
- ADR-0001 written; README reflects the layout.

## After Phase 0
Update `handoff.md` (Phase 0 complete) and tick the Phase 0 box in `docs/BUILD_PLAN.md`.
Next is **Phase 1 (ingestion + chunking)**; its first action is settling the ticker list,
and ADR-0002 (chunking) is authored by hand with Ryan.
