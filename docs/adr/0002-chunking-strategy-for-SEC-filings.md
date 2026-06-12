---
type: adr
status: accepted
phase: 1
updated: 2026-06-12
related: ["[[BUILD_PLAN]]", "[[Ledgerlens_System_Design_FINAL]]", "[[PHASE_1_BUILD]]"]
---

# ADR-0002: Chunking strategy for SEC filings

- **Status:** Accepted
- **Date:** 2026-06-12

## Context
When dealing with financial documents 100–200 pages in length, the entire document cannot be embedded as a single vector; this blurs details together, resulting in fuzzy retrieval that doesn't quite hit what is being asked. If you split at intervals too small — a single sentence, for example — you get vectors devoid of meaningful context. This is where chunking comes in. Chunking provides the system with reasonably sized pieces to embed as vectors, which carry enough context to lead to more accurate retrieval and meaningful citations. This makes it the most important decision in the pipeline, the one upon which all others build.

## Decision
The decision is to use structure-aware splitting along the section boundaries the filings already provide, rather than an arbitrary fixed window.

On top of this, a parent/child strategy is used. The document is divided along its provided boundaries into parent sections, and each parent is then divided into 300–500-token children that are embedded as vectors. Serving both retrieval and generation with a single chunk size forces a bad compromise; parent/child decouples them. The small, precise child is what gets embedded and retrieved, but at synthesis time the LLM is handed the larger parent section the child belongs to. Retrieval gets precision, generation gets context, and neither pays for the other.

Tables are handled separately. Slicing a table produces unaligned numbers stripped of their headers and context, data that looks real but is useless. To avoid this, tables are extracted fully intact and paired with a short text summary, so the table is both retrievable (via the summary) and citable (as the intact table).

## Consequences
**Harder / accepted:**
- This approach is more complex to build and maintain than fixed-size chunking — there are more moving parts in ingestion that can break. It also carries a hard external dependency on `edgartools` parsing Item boundaries cleanly; when a filer formats a 10-K oddly and section extraction misfires, the structure-aware strategy degrades for that filing.
- chunking sets the ceiling on retrieval recall, so a regression here stays invisible until it degrades answers downstream, which is why the Phase 7 eval must track recall@k.

**Escape hatch:**
- Chunking lives entirely behind the ingestion layer, so the corpus can be re-chunked and re-embedded without touching retrieval, synthesis, or the API. The decision is contained: any unforeseen consequences have a minimal blast radius and can be handled in isolation.

## Alternatives considered
- **Fixed-size chunking (every N tokens):** Structure-blind. It would invalidate table data, split claims from their context, and cut off mid-sentence. The major consequence is that it would effectively neutralize the reranker, since the cross-encoder would be asked to score ambiguous half-passages.
- **Recursive character splitting:** Respects natural text boundaries, so it is better than fixed-size, but it is still blind to the *filing's* semantics. It can't tell an Item 1A from a footnote, and it still slices tables.
- **Semantic chunking (split on embedding-similarity drops):** Considered, and effective in principle. But because these filings already have a well-defined structure, the benefit over the structure-aware approach is marginal, and the cost (compute, tuning fragility) isn't worth it. Deferred rather than rejected.