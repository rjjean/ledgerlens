---
type: index
status: active
phase: 3
updated: 2026-06-23
related: ["[[handoff]]", "[[BUILD_PLAN]]", "[[PHASE_1_BUILD]]", "[[PHASE_2_BUILD]]"]
---

# Ledgerlens — Vault Home

The map of this vault/repo. Open this first in Obsidian and follow the links.
This folder is one thing wearing three hats: a **GitHub repo**, an **Obsidian
vault**, and a **Cursor workspace** (worked in Composer / Agent).

> Ledgerlens: a citation-grounded RAG product over SEC filings with a published
> evaluation harness. The flagship portfolio project.
> **Status: Phase 2 complete (storage + embeddings, offline-validated). Phase 3 active.**

## Start here
- [[handoff]] — where the build is right now. **Read first every session.**
- [[BUILD_PLAN]] — phase tracker; **Phase 3 (retrieval) is the active build task.**
- [[GETTING_STARTED]] — setup + how to work in Cursor + Composer.
- [[CONVENTIONS]] — how this vault/repo is organized and edited.

## Build
- [[Ledgerlens_System_Design_FINAL]] — locked architecture + stack (authoritative).
- [[BUILD_PLAN]] — phase tracker (MVP -> v1 -> v2); Phase 2 done, Phase 3 active.
- [[01_Ledgerlens_Project_Outline]] — the why / scope / direction.
- Build briefs: [[PHASE_0_BUILD]] (done) · [[PHASE_1_BUILD]] (done) · [[PHASE_2_BUILD]] (done).
- Decision records: [[0000-adr-template]] · [[0001-single-postgres-over-dedicated-vector-db]] · [[0002-chunking-strategy-for-SEC-filings]] (accepted).

> The AI guardrails Cursor follows live in `.cursor/rules/` (`00-project` always on;
> `10-python` and `20-obsidian-notes` attach by file type). `CLAUDE.md` is optional —
> only used if you run Claude Code.

## Strategy & roadmap
*(Kept outside this public repo. If you commit any of these to `docs/planning/`,
convert the lines below to wiki-links.)*
- Career Blueprint — career-targeting frame (where to aim).
- Project Portfolio Blueprint — what to build and why.
- Queued after Ledgerlens ships: MerchantIQ (transaction categorization /
  merchant matching), AskWarehouse (agentic text-to-SQL copilot).

## Current focus
**Phase 3 — retrieval.** Hybrid FTS + pgvector + RRF (k=60) + MiniLM rerank behind
the existing seams. See [[handoff]] and [[BUILD_PLAN]].
