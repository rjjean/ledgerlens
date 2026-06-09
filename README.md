# Ledgerlens

Citation-grounded RAG over a corpus of SEC filings, with a published evaluation
dashboard proving retrieval and answer quality.

**Status:** Phase 0 complete — runnable scaffold with swappable seams (fake backends
default). Phase 1 (ingestion + chunking) is next. No real ingestion, retrieval, or
LLM calls yet.

## What it is

Ledgerlens ingests SEC filings, chunks them with structure-aware provenance, embeds
and indexes them in Postgres (pgvector + FTS), retrieves with hybrid search + rerank,
and answers with citation-grounded synthesis. The data layer is the headline; models sit
behind swappable interfaces.

Authoritative architecture: `Ledgerlens_System_Design_FINAL.md`.

## Quickstart

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env

python scripts/smoke_test.py   # expect: Phase 0 plumbing is GREEN
pytest
```

Optional phase groups (install only when needed):

```bash
pip install -e ".[storage]"      # Phase 2 — Neon / pgvector
pip install -e ".[embeddings]"  # Phase 2 — Voyage
pip install -e ".[rerank]"      # Phase 3 — cross-encoder
pip install -e ".[llm]"         # Phase 4 — LiteLLM / Haiku
pip install -e ".[ingestion]"   # Phase 1 — edgartools
```

`scripts/check_pgvector.py` is a Phase 2 helper. It requires `DATABASE_URL` and
`pip install -e ".[storage]"`.

## Repo layout

```
ledgerlens/                 # Python package
  config.py                 # single source of truth (pydantic-settings)
  interfaces/               # Embedder, Reranker, LLMClient + factory
  ingestion/                # Phase 1
  retrieval/                # Phase 3
  api/                      # Phases 4–5
  eval/                     # Phase 7
  observability/            # Phase 5+
scripts/                    # smoke_test.py, check_pgvector.py
tests/
web/                        # Next.js UI (Phase 5) — sibling to Python package
infra/                      # Docker, GitHub Actions (later)
docs/                       # BUILD_PLAN, ADRs, architecture placeholder
```

## The seam pattern

Application code never calls vendor SDKs directly. It obtains implementations via
`ledgerlens/interfaces/factory.py`:

- `get_embedder()` — `fake` (default) or `voyage`
- `get_reranker()` — `fake` or `cross_encoder`
- `get_llm()` — `fake` or `litellm`

Backends are selected in `.env`. Heavy SDKs lazy-import inside the real implementation
only. `Fake*` backends run with core deps only (`pydantic`, `pydantic-settings`).

`embedder_dimensions` lives in config — fake and real embedders read the same value so
storage schema and A/B swaps stay aligned.

## Account setup checklist

Complete **before the first paid API call** (ordering matters — caps bound worst-case spend):

1. **Neon** — create a project; enable pgvector; copy `DATABASE_URL` into `.env`.
2. **Voyage** — create an API key; **set a monthly spend cap** in the console; add
   `VOYAGE_API_KEY` when switching `EMBEDDER_BACKEND=voyage`.
3. **Anthropic** — create an API key; **set a usage limit** (e.g. $15/mo); add
   `ANTHROPIC_API_KEY` when switching `LLM_BACKEND=litellm`.
4. **Langfuse** (Phase 5+) — cloud free tier for traces.
5. **Vercel** (Phase 5+) — Hobby tier for the Next.js frontend.

Keep `EMBEDDER_BACKEND`, `RERANKER_BACKEND`, and `LLM_BACKEND` on `fake` until the
matching build phase is ready.

## Docs map

- `handoff.md` — session state (read first in every build session)
- `docs/PHASE_0_BUILD.md` — Phase 0 spec
- `docs/BUILD_PLAN.md` — phase tracker
- `docs/adr/` — decision records (ADR-0001: single Postgres)
