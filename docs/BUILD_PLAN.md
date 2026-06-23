---
type: plan
status: active
phase: 2
updated: 2026-06-13
related: ["[[handoff]]", "[[PHASE_0_BUILD]]", "[[PHASE_1_BUILD]]", "[[PHASE_2_BUILD]]", "[[Ledgerlens_System_Design_FINAL]]"]
---

# Build Plan & Phase Tracker

Ship rule: a live URL + README + eval numbers for ONE finished project beats three
unfinished repos. Build narrow, finish, then iterate.

## MVP — get to a live URL (~2–3 wks)
- [x] **Phase 0 — Foundations & seams.** *First task.* Repo scaffold, swappable
      Embedder / Reranker / LLM interfaces (stubs run), config single-source-of-truth,
      ADR-0001, spend-cap checklist. Build per `docs/PHASE_0_BUILD.md`.
      *Done-when:* `smoke_test.py` is green and `pytest` passes. *(2026-06-09 — complete.)*
- [x] **Phase 1 — Ingestion + chunking (the moat).** 18 tickers via edgartools,
      section extraction, structure-aware parent/child chunking, tables intact, full
      provenance metadata. ADR-0002 accepted.
      *Done-when:* 3-ticker validation succeeds; pytest offline; chunks on disk.
      *(2026-06-13 — complete.)*
- [ ] **Phase 2 — Storage + embeddings.** Neon schema, voyage-finance-2 behind the
      Embedder seam, HNSW + FTS indexes, embedding/chunk count reconciles.
      Build per `docs/PHASE_2_BUILD.md`.
- [ ] **Phase 3 — Retrieval.** FTS + pgvector + RRF (k=60) + MiniLM rerank. Informal
      recall check on ~10 hand questions. Validate rerank uplift.
- [ ] **Phase 4 — Synthesis + citations.** Thin custom RAG core, Haiku 4.5 via LiteLLM,
      citation-grounded prompt, abstain-when-weak.
- [ ] **Phase 5 — Product surface + deploy (MVP LIVE).** FastAPI + Next.js chat with
      inline citations, Langfuse from query #1, rate limits + spend cap held.

## v1 — the differentiators (+2–3 wks)
- [ ] **Phase 6 — Dagster incremental pipeline** in GitHub Actions; watermark, 10-K/A
      dedup, data-quality asset checks. ADR-0003 Dagster-over-Airflow.
- [ ] **Phase 7 — Eval harness + public /metrics.** Ragas golden set + hand-labeled
      core; recall@k, citation accuracy, faithfulness; judge = different family;
      publish embedder/reranker A/B delta.
- [ ] **Phase 8 — CI eval gate + docs.** DeepEval pass/fail on every PR; finalized
      ADRs + architecture diagram + one technical write-up.

## v2 — stretch
- [ ] LangGraph multi-doc comparison, MCP server, earnings transcripts, financial-sector
      corpus expansion, optional Cohere rerank A/B.

## Resolved (Phase 1)
- MVP ticker list locked (18 tickers in `config.py`).
