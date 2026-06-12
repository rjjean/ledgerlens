---
type: index
status: active
phase: 1
updated: 2026-06-12
related: ["[[handoff]]", "[[PHASE_1_BUILD]]", "[[BUILD_PLAN]]"]
---

# Ledgerlens — Vault Home

The map of this vault/repo. Open this first in Obsidian and follow the links.
This folder is one thing wearing three hats: a **GitHub repo**, an **Obsidian
vault**, and a **Cursor workspace** (worked in Composer / Agent).

> Ledgerlens: a citation-grounded RAG product over SEC filings with a published
> evaluation harness. The flagship portfolio project.
> **Status: Phase 0 complete (scaffold + seams, reviewed). Phase 1 active.**

## Start here
- [[handoff]] — where the build is right now. **Read first every session.**
- [[PHASE_1_BUILD]] — the active build task (ingestion + chunking).
- [[GETTING_STARTED]] — setup + how to work in Cursor + Composer.
- [[CONVENTIONS]] — how this vault/repo is organized and edited.

## Build
- [[Ledgerlens_System_Design_FINAL]] — locked architecture + stack (authoritative).
- [[BUILD_PLAN]] — phase tracker (MVP -> v1 -> v2); Phase 0 done, Phase 1 active.
- [[01_Ledgerlens_Project_Outline]] — the why / scope / direction.
- Build briefs: [[PHASE_0_BUILD]] (done) · [[PHASE_1_BUILD]] (active).
- Decision records: [[0000-adr-template]] · [[0001-single-postgres-over-dedicated-vector-db]] (accepted) · ADR-0002 (chunking — write by hand this phase).

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
**Phase 1 — ingestion + chunking.** First: write **ADR-0002 (chunking)** by hand,
then build per [[PHASE_1_BUILD]]. First build action: set `EDGAR_IDENTITY` in `.env`,
validate on 3 tickers (MSFT, SNOW, NVDA), then run the full 18. See [[handoff]].