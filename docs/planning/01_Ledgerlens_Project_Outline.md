# Project 1 — Ledgerlens

*Build-context outline. Companion to `Career_Blueprint_Ryan_Jean.md` and `Project_Portfolio_Blueprint_Ryan_Jean.md`.*
*Purpose: give a future build session full context on the why, scope, architecture, and direction of this project.*

---

## 1. Identity

**Name:** Ledgerlens
**One-liner:** A deployed RAG product that answers grounded, **citation-backed** questions over a continuously-ingested corpus of public-company filings (and optionally earnings calls), with a **published evaluation dashboard** proving retrieval and answer quality.
**Build priority:** #1 of 3 — build this to a fully-deployed, monitored finish before starting Project 2.

---

## 2. Why This Project (the strategic frame)

This is the flagship because it hits all five portfolio requirements at once, is the most *visible* product (chat UI + citations + a metrics page), is fintech-flavored (Ryan's domain pull), and doubles as a literal **"submit a working AI system"** artifact for Wealthsimple's AI Builders hiring track.

**The convergent 2026 thesis it embodies:** every top target has bet on the same pattern — *AI agents/RAG grounded on real, messy, governed data, with production-grade evaluation, observability, and permissions.* That pattern is exactly the data-engineering + applied-AI intersection Ryan owns but hasn't shown. Ledgerlens puts the whole thing on display.

**What it proves (mapped to the blueprint's decision criteria):**
1. *Product around AI, not model from scratch* — RAG sits inside a real product with a user job.
2. *Data engineering as the differentiator* — a scheduled ingestion pipeline over genuinely messy filings is the centerpiece, not an afterthought.
3. *Fintech/B2B flavor* — financial filings = domain leverage from RBC.
4. *Real value / not a wrapper* — the moat is the curated, continuously-updated corpus + retrieval quality + measured faithfulness, none of which a bare LLM call provides.
5. *0-to-1 ownership* — solo end-to-end build, scoped/shipped/iterated.
6. *Maps to target stacks* — Python, vector DB, orchestration, MCP, eval harness.
7. *Leadership narrative* — architecture decisions + an eval-first framing read as systems thinking.

**Which targets it speaks to and what they're building that this mirrors:**
- **Ramp** — publishes RAG-for-finance work (merchant matching, industry classification) and *production LLM benchmarks on real financial tasks*. Ledgerlens's eval harness is the portfolio-scale version of that.
- **Glean** — permissions-aware RAG over messy enterprise data with citations back to source. Ledgerlens's grounded-citation requirement is the same discipline.
- **Databricks** — Agent Bricks = RAG pipelines on governed data + auto-generated benchmarks + LLM judges + MLflow tracing. Ledgerlens is the same shape.
- **Wealthsimple** — AI-native financial workflows; they hire off a working system. This *is* a working system in their domain.
- **Stripe / Snowflake** — financial data + the agentic data layer.

---

## 3. Definition of Done (success criteria)

- A **live, public URL** where anyone can ask questions and get answers with inline, clickable source citations.
- A **scheduled ingestion pipeline** that pulls new filings, parses/cleans/chunks/embeds them incrementally, with data-quality checks — visible (DAG screenshot + README).
- A **published evaluation page** reporting, against a versioned labeled question set: retrieval recall@k, context precision, faithfulness, citation accuracy, plus latency and cost per query.
- **Observability**: every query traced (retrieved chunks, tokens, latency, cost).
- **CI/CD**: tests + an eval gate run on every push (regressions blocked).
- A **README with an architecture diagram and ADRs** (architecture decision records), plus one short technical write-up/blog post.

---

## 4. The Data Layer (the moat — make it the centerpiece)

**Why filings:** they're free, real, and genuinely messy — inconsistent HTML/XBRL, giant multi-hundred-page documents, footnotes, tables, boilerplate, and section structure that varies by filer. Taming that *is* the differentiated work.

**Primary sources (all free):**
- **SEC EDGAR official APIs** — `data.sec.gov` company facts & submissions; full-text search at `efts.sec.gov`; bulk financial-statement datasets. No key required (just a declared User-Agent; respect rate limits).
- **`edgartools`** (Python, MIT, `dgunning/edgartools`) — clean, well-typed access to 10-K / 10-Q / 8-K, XBRL-to-DataFrame, and text-section extraction. Best starting point for ingestion.
- *(Optional, secondary)* **Earnings-call transcripts** — harder to get free; some via paid APIs (sec-api.io, kscope) or existing HuggingFace transcript datasets. Treat as a v2 add-on; **start with filings only.**

**Pipeline design (this is the RBC story, modernized):**
- **Orchestrator:** Dagster (preferred for asset-based lineage and a clean local dev story) or Airflow (closer to RBC experience — pick in the build chat).
- **Stages:** scheduled discovery of new filings → download → parse (HTML/XBRL) → section extraction (MD&A, Risk Factors, financial statements) → cleaning/normalization → **chunking strategy** (structure-aware, not naive fixed-size) → embedding → upsert into vector store.
- **Data-quality checks:** schema/section presence validation, dedup (filings get re-filed/amended — handle 10-K/A), empty/garbled-extraction detection, embedding-count reconciliation. Log all of it (echoes RBC null/duplicate/schema validation).
- **Incrementality:** only ingest/re-embed new or amended filings; track watermark state.
- **Scope control:** start with **one sector or ~20–50 companies**, not all of EDGAR.

---

## 5. System Architecture

Data flow, end to end:

```
EDGAR (filings)
   → [Dagster pipeline: download → parse → section-extract → clean → chunk → embed]
   → Vector store (pgvector / Qdrant) + metadata store (Postgres)
   → Retrieval service (hybrid: BM25 + dense → rerank)
   → LLM answer synthesis (citation-grounded, source spans attached)
   → FastAPI backend  →  Next.js chat UI (inline citations) + /metrics eval page
        ↑
   Observability (Langfuse / Phoenix): traces, tokens, latency, cost
   Eval harness (Ragas + DeepEval) runs in CI + on a schedule against the labeled set
```

---

## 6. Tech Stack (biased toward target-company stacks)

- **Language/API:** Python, FastAPI (+ Pydantic).
- **Ingestion/orchestration:** Dagster or Airflow; `edgartools` for EDGAR.
- **Storage:** Postgres for metadata; **pgvector** for embeddings (simplest single-DB story; aligns with Databricks Lakebase's "Postgres for AI" direction) — or Qdrant/LanceDB if you want a dedicated vector DB.
- **Retrieval:** hybrid BM25 + dense; a **cross-encoder reranker** (or Cohere Rerank — ties to Cohere, a Toronto target).
- **Orchestration of the RAG flow:** LlamaIndex or LangGraph (LangGraph if you want the agentic option open for v2).
- **LLM:** any strong API model; keep it swappable behind an interface (model-neutrality is what Glean/Databricks ship).
- **Eval:** **Ragas** (context precision/recall, faithfulness, answer relevancy, synthetic test-set generation) for experimentation; **DeepEval** (pytest-style) wired into CI as a quality gate; optionally Promptfoo. Use a **strong, separate judge model** (not the generator).
- **Observability:** Langfuse or Arize Phoenix.
- **MCP (v2):** expose the corpus as an MCP server so it's callable as a tool — directly echoes Databricks/Glean/Ramp.
- **Deploy:** Docker; Fly.io or Render for cheap always-on hosting (AWS optional to flex the cert). **GitHub Actions** for CI/CD (Ryan's Jenkins/UrbanCode story, modernized).
- **Frontend:** Next.js / React.

---

## 7. The AI Subsystem (detail)

- **Hybrid retrieval** (sparse + dense) → **rerank** top-N → pass top-k to the LLM.
- **Citation-grounded generation:** every claim in the answer must point to a retrieved source span; if support is weak, the system says so rather than guessing (this "knows when not to answer" behavior is exactly Wealthsimple's "where AI should and should not take responsibility").
- **Metadata filters:** by company, form type, fiscal period.
- **Chunking is a first-class decision** (structure-aware; tables handled separately) — document the choice in an ADR; it's the single biggest lever on retrieval quality.

---

## 8. The Evaluation Harness (the differentiator — do not cut this)

This is what separates the portfolio from every "I built a RAG chatbot" repo. The production minimum, tracked weekly against a **versioned labeled question set**:

- **Retrieval:** recall@k (the highest-leverage metric — if the right chunk never enters the candidate set, generation can't recover), context precision/recall.
- **Generation:** faithfulness (does each claim trace to a retrieved chunk — production target ~90%), answer relevancy.
- **Citation accuracy:** do the cited sources actually support the claim (this is the UX users trust).
- **Operational:** freshness, latency, cost per query.

Workflow: use **Ragas** to bootstrap a golden set (synthetic generation) + hand-label a core set; run **DeepEval** in CI as a pass/fail quality gate so retrieval/chunking/model changes can't silently regress. Surface all numbers on the public `/metrics` page. (A ~200-question eval run costs roughly $1 with a small judge model — cheap.)

---

## 9. Observability & Production

- Trace every query: retrieved chunk IDs, rerank scores, prompt, tokens, latency, cost.
- Dashboard: query volume, p50/p95 latency, cost/day, faithfulness over time.
- CI/CD: lint + unit tests + DeepEval gate on PRs; scheduled re-eval; scheduled ingestion runs.

---

## 10. Phased Roadmap

- **MVP (≈2–3 weeks):** one sector / ~20 companies, basic hybrid RAG, citation-grounded answers, deployed to a live URL. *Ship this before anything else.*
- **v1 (+2–3 weeks):** the orchestrated incremental ingestion pipeline with data-quality checks + the full eval harness + public `/metrics` page + observability + CI eval gate.
- **v2 (stretch):** reranker upgrade, MCP server, multi-document comparison ("compare R&D spend across these 3 filings over 2 years"), earnings-call transcripts, multi-model routing.

---

## 11. Suggested Repo Structure

```
ledgerlens/
  ingestion/        # Dagster assets: download, parse, chunk, embed, quality checks
  retrieval/        # hybrid search + rerank
  api/              # FastAPI app, RAG orchestration, citation logic
  eval/             # Ragas + DeepEval suites, golden question set (versioned)
  web/              # Next.js chat UI + /metrics page
  observability/    # Langfuse/Phoenix wiring
  infra/            # Dockerfile, GitHub Actions, deploy config
  docs/             # architecture diagram, ADRs, write-up
  README.md
```

---

## 12. Résumé Bullets It Earns

- Built and deployed an end-to-end financial-document RAG assistant ingesting 10-K/10-Q filings via a scheduled Dagster pipeline (HTML/XBRL parsing, section extraction, schema validation, incremental embedding into pgvector), serving citation-grounded answers through a FastAPI/Next.js app on a live URL.
- Engineered a production evaluation harness (retrieval recall@k, faithfulness, citation accuracy) with Ragas/DeepEval wired into CI as a quality gate and a public metrics dashboard, catching retrieval regressions across embedding and chunking changes.
- Containerized and deployed with GitHub Actions CI/CD and Langfuse tracing for per-query cost, latency, and trace observability.

---

## 13. Decisions to Settle in the Build Chat

- Dagster vs. Airflow (lineage/dev-ergonomics vs. RBC familiarity).
- pgvector single-DB vs. dedicated vector DB (Qdrant/LanceDB).
- Sector/company scope for MVP (which ~20 filers).
- Chunking strategy (structure-aware boundaries; table handling).
- Which LLM + which judge model; model-swap interface.
- Hosting target (Fly.io/Render vs. AWS).

---

## 14. Risks & Scope Guardrails

- **Over-scoping is the #1 risk.** Ship the MVP at one sector before building the pipeline/eval layers. A live URL + eval numbers beats a sprawling unfinished repo.
- **Don't let it become a model project.** The headline is the data pipeline + eval, not the LLM.
- **Respect EDGAR rate limits** (declared User-Agent, throttling) in the ingestion pipeline.
- **Earnings transcripts are a v2 trap** — they're harder to source freely; don't block the MVP on them.
