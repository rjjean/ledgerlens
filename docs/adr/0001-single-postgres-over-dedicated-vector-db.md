---
type: adr
status: accepted
phase: 0
updated: 2026-06-09
related: ["[[Ledgerlens_System_Design_FINAL]]", "[[BUILD_PLAN]]", "[[PHASE_0_BUILD]]"]
---

# ADR-0001: Single Postgres (Neon + pgvector + FTS) over a dedicated vector DB

- **Status:** Accepted
- **Date:** 2026-06-09

## Context

Ledgerlens needs hybrid retrieval: dense vectors for semantic match and full-text search
for exact tickers, defined terms, and line items. Metadata filters (company, form type,
fiscal period) are first-class — they are the citation system.

At MVP scale (~15–20 large-cap tech filings, tens of thousands of chunks), a dedicated
vector database solves a performance problem we do not have. The design principles favor
a small ops surface, free-tier-first hosting, and a data layer that is legible in SQL.

Neon Postgres supports pgvector (HNSW) and native `tsvector` FTS in one store with
scale-to-zero economics suitable for a solo portfolio project.

## Decision

We will use **Neon Postgres as the single database** for metadata, chunk text, dense
embeddings (pgvector / HNSW), and sparse FTS (`tsvector`). Hybrid retrieval and metadata
filtering run inside this one database. The dense retrieval leg stays behind the existing
retrieval interface so it can be lifted out later if scale demands it.

## Consequences

**Easier**

- One deployment, one backup target, one connection string.
- Hybrid search and `WHERE` metadata filters are ordinary SQL — no cross-store joins.
- Neon free tier + scale-to-zero matches portfolio traffic and cost goals.
- Clean data-engineering narrative: "hybrid, metadata-filtered retrieval inside Postgres."

**Harder**

- pgvector is not the fastest ANN engine past ~1M vectors; we accept that at current scale.
- Vector and FTS index tuning live in Postgres expertise, not a purpose-built vector UI.
- If we outgrow single-DB latency, we must execute the escape hatch (below).

**Escape hatch:** If dense-leg latency or vector volume crosses ~1M embeddings with
measurable pain, lift only the dense ANN leg into Qdrant (or similar) behind the same
retrieval interface. Metadata and FTS can remain in Postgres; the seam was designed for
this swap from Phase 0 onward.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **Qdrant** | Best vector perf at scale, but a second service to run and wire for a problem we do not have at MVP volume. |
| **Pinecone / Weaviate (managed)** | Paid; splits chunk text, metadata, and vectors across systems — weaker hybrid + filter story. |
| **Self-hosted vector DB** | Ops burden and cost for a solo builder; Neon + pgvector is $0 at portfolio traffic. |
