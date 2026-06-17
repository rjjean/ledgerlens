---
type: plan
status: active
phase: 0
updated: 2026-06-09
related: ["[[Ledgerlens_System_Design_FINAL]]", "[[BUILD_PLAN]]"]
---

# Architecture

This note will grow with diagrams and module-level detail as phases land.

**Authoritative source:** `Ledgerlens_System_Design_FINAL.md` (locked stack, §6 decisions,
reference architecture diagram, build order).

Phase 0 establishes only the package scaffold and swappable seams (`Embedder`, `Reranker`,
`LLMClient`) behind `ledgerlens/interfaces/factory.py`. Ingestion, retrieval, synthesis,
and deployment are added in later phases per `docs/BUILD_PLAN.md`.
