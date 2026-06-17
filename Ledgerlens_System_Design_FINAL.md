# Ledgerlens — System Design & Tech-Stack Decisions (FINAL)

*Senior-engineer design, decisions locked. Companion to `01_Ledgerlens_Project_Outline.md`, `Project_Portfolio_Blueprint_Ryan_Jean.md`, and `Career_Blueprint_Ryan_Jean.md`.*
*Finalized June 2026. Every fast-moving choice (embeddings, reranker, LLMs, EDGAR tooling, eval frameworks) and all pricing verified against current sources this month.*

> **Status: decisions locked.** All forks from the design pass are resolved (see §6, "Locked Decisions"). The stack is optimized to run for roughly **$0–$10/month** at portfolio traffic without sacrificing the architecture. The only choice left fully to taste is the MVP corpus (tech vs. financials), which has no architectural impact (§5).

---

## 0. Design Principles (the lens every decision is judged against)

1. **Ship a live URL fast; the #1 failure mode is over-scoping.** Every stage has an MVP form and a v1 form, and we deliberately under-build the MVP.
2. **The data layer is the headline, not the LLM.** Tool choices that make the ingestion/retrieval pipeline *legible and demonstrable* win over choices that hide it behind a framework.
3. **Eval + observability are the senior differentiator.** First-class treatment, not bolted on at the end.
4. **Model-neutrality.** Embedder, reranker, and LLM all sit behind interfaces so they're swappable — a portfolio signal *and* protection against a frontier that moves monthly.
5. **Defensibility lives in the corpus + retrieval quality + measured faithfulness** — none of which a raw model call provides.
6. **Small ops surface, free-tier-first, spend-capped.** Solo builder economics: scale-to-zero infrastructure, free tiers wherever they don't compromise the product, hard spend caps on every paid provider. The dangerous money is always-on infra and an unguarded public endpoint — both are designed out below.

---

## 1. Reference Architecture

```
                          ┌────────────────────────────────────────────────┐
                          │  Orchestrator: Dagster                         │
                          │  (runs in GitHub Actions / locally —           │
                          │   NOT an always-on hosted daemon)              │
   SEC EDGAR  ──discover──▶  download → parse(HTML/XBRL) → section-extract│
   (edgartools)           │  → clean/normalize → structure-aware chunk     │
                          │  → embed (voyage-finance-2) → upsert           │
                          │  + data-quality checks, dedup, watermark       │
                          └───────────────┬────────────────────────────────┘
                                          ▼
                  ┌────────────────────────────────────────────┐
                  │  Neon Postgres (single DB, scale-to-zero)  │
                  │   • metadata (company, form, period, url)  │
                  │   • chunks + parents (text)                │
                  │   • pgvector (dense embeddings, HNSW)      │
                  │   • tsvector (sparse / BM25-style FTS)     │
                  └───────────────┬────────────────────────────┘
                                  ▼
   Retrieval service:  hybrid (FTS + dense) → RRF fuse → CPU cross-encoder rerank
                                  ▼                    (in-process, MiniLM/BGE — no API)
   Answer synthesis:  citation-grounded LLM (Claude Haiku 4.5, swappable → Sonnet 4.6)
                                  ▼
   FastAPI backend  ──────────────────────────────┐
                                  ▼                │
   Next.js chat UI (inline citations)  +  /metrics page (public)
                                  ▲                │
   Observability (Langfuse cloud free): per-query traces, tokens, latency, cost
   Eval harness (Ragas golden-set + DeepEval CI gate) on a versioned labeled set
```

Everything runs as: one FastAPI service (with the reranker in-process), one Neon Postgres, one Next.js app on Vercel, an orchestrator that fires in CI, and an eval/observability layer on free tiers.

---

## 2. Stage-by-Stage Stack Decisions

Each stage: realistic options, the analysis, the locked call, and the MVP-vs-later split.

### Stage 1 — Language & API Framework — **LOCKED: Python 3.12 + FastAPI + Pydantic v2**

| Option | For | Against |
|---|---|---|
| **Python + FastAPI** | Async, Pydantic v2 validation, auto OpenAPI docs, lingua franca of every target's AI stack, your background | None material |
| Litestar | Faster, cleaner DI | Smaller ecosystem, no hiring signal |
| Flask / Django | Mature | Sync-first / heavyweight for a thin API |
| Node/TS | Co-locates with Next.js | Throws away the Python/ML ecosystem advantage |

Not a contest. FastAPI is what the targets use; typed request/response models double as your citation schema; async matters once you fan out to embed + rerank + LLM per query.

### Stage 2 — EDGAR Ingestion — **LOCKED: `edgartools` (+ raw `data.sec.gov` fallback)**

| Option | For | Against |
|---|---|---|
| **`edgartools`** (MIT) | Typed objects for 17+ form types, XBRL→DataFrame, **section extraction** (Item 1A, Item 7…), ships an MCP server (de-risks v2), no API key | Single maintainer — pin the version |
| Raw `data.sec.gov` | Zero deps, official | Weeks of hand-written HTML/XBRL parsing |
| `sec-api.io` | Clean JSON | Paid; external dependency the moat shouldn't rely on |

Section extraction is the reason — it hands you clean Item-level boundaries that the chunking strategy (Stage 5) is built on. Pin the version; the official APIs are the backstop. Its bundled MCP server makes the v2 MCP milestone nearly free. **Respect SEC rules:** declared User-Agent + throttling in the ingestion code, made visible in the repo.

### Stage 3 — Orchestration — **LOCKED: Dagster, executed in GitHub Actions / locally**

| Option | For | Against |
|---|---|---|
| **Dagster** | Asset-based lineage (filing→sections→chunks→embeddings is a tracked asset graph), great local dev + UI, killer README screenshot, native company/period partitions | Newer; not yet on your résumé (which is the point — it adds breadth) |
| Airflow | Direct RBC keyword match | Task-centric, hides lineage, heavier locally |
| Prefect | Lightest | Thinner "I built a data platform" signal |

**The strategic point:** you already have Airflow on your résumé from RBC, so building Ledgerlens on Dagster *adds* a tool while the Airflow experience is already demonstrated. The asset graph visualizes exactly the data-engineering sophistication you want seen.

**Cost lock:** Dagster runs as a **scheduled GitHub Actions job** (free CI minutes) or locally — **never** as an always-on hosted daemon or Dagster Cloud. A persistent orchestrator is a classic accidental $20–50/mo; we avoid it entirely. Dagster is designed to run triggered jobs, so this costs nothing and loses nothing.

**MVP shortcut:** the MVP ingests ~15–20 companies with a plain one-shot script. Graduate to the scheduled, incremental, lineage-tracked Dagster pipeline in v1.

### Stage 4 — Storage — **LOCKED: Neon Postgres + pgvector + FTS (single DB)**

| Option | For | Against |
|---|---|---|
| **Postgres + pgvector** | One store for metadata, chunk text, dense vectors (HNSW), *and* sparse FTS (tsvector) → **hybrid search in one DB**; SQL metadata filters (company/form/period); trivial ops | Not the fastest vector engine past ~1M vectors (irrelevant at your scale) |
| Qdrant | Best vector perf/filtering at scale | A second service to run; overkill here |
| Pinecone/Weaviate (managed) | Zero-ops vectors | Paid; splits data across two systems |

At 15–50 companies (tens of thousands of chunks), a dedicated vector DB solves a problem you don't have. Decisive wins: **hybrid retrieval inside one store** (FTS for lexical, pgvector for dense), **metadata filtering is just `WHERE`**, and one thing to deploy/back up. "Hybrid, metadata-filtered retrieval inside a single Postgres" is a cleaner data-engineering story than wiring a vector DB. Use an **HNSW** index; add `pgvectorscale` only if latency ever demands it.

**Hosting it on Neon** (see §7 Cost): true scale-to-zero free tier, pgvector supported, sub-second cold start. Idle = $0. (Bonus: Neon is now owned by Databricks, a target.) **Escape hatch:** if you ever cross ~1M vectors with latency pressure, lift the dense leg into Qdrant behind the same retrieval interface — design the seam now, build it later.

### Stage 5 — Chunking Strategy — **LOCKED: structure-aware + parent–child + table handling (write the ADR)**

The single biggest lever on retrieval quality. Filings are hundreds of pages with filer-varying structure; answers live in known sections (Item 1A Risk Factors, Item 7 MD&A, financial statements + footnotes). Naive fixed-size chunking shreds tables, splits claims from context, and *neutralizes reranker gains* (the cross-encoder ends up scoring ambiguous half-passages).

| Strategy | Verdict |
|---|---|
| Fixed-size | ❌ Baseline only; destroys tables, kills rerank uplift |
| Recursive character split | ⚠️ Better, structure-blind |
| **Structure-aware (section-based)** | ✅ Split on the filing's own Item boundaries (edgartools), then sub-chunk long sections at paragraph boundaries |
| **Parent–child** | ✅ Embed small precise child chunks for retrieval; pass the parent section to the LLM for context |
| **Tables handled separately** | ✅ Extract intact; store structured table + a short text linearization/summary so both are retrievable and citable |
| Semantic (embedding-boundary) | ⚠️ Defer — marginal vs. the above for structured filings |

**Locked approach:** sections first (edgartools Items) → sub-chunk long sections to ~300–500-token children → parent–child expansion at synthesis time → tables pulled out intact with a linearized text + one-line summary (this is where finance Q&A lives and where naive chunking fails hardest). **Every chunk carries provenance metadata** — company, CIK, form type, fiscal period, Item/section, accession number, source URL, char offsets. **This metadata is the citation system.** Document the choice + rejected alternatives as an ADR — one of your clearest IC→lead signals.

### Stage 6 — Embedding Model — **LOCKED: voyage-finance-2** (free at your scale)

| Option | Retrieval quality | Cost / ops | Fit |
|---|---|---|---|
| **`voyage-finance-2`** | Finance-domain SOTA; strong on tables + numerical reasoning; 32K context | **First 50M tokens free**, then $0.12/1M | **Built for exactly this corpus** |
| OpenAI `text-embedding-3-large` | Strong general; Matryoshka dims | API, cheap | Finance-blind |
| BGE-M3 (open) | Matches commercial APIs | Self-host **GPU** (ironically *more* expensive at low volume) | Solid; portability fallback only |

The one place an off-the-shelf default genuinely beats the obvious choice *for your data* — financial tables and numerical reasoning are exactly where general embedders fall down, and that's most of your hard queries. And it's **free for you**: your entire MVP + v1 ingestion lands well under Voyage's 50M-free-token allowance; embedding cost is negligible regardless (the generative call is the real expense). Self-hosting BGE-M3 would cost *more* (GPU), so the API is the cheap option here.

Keep it behind a swappable `Embedder` interface and **A/B it against `text-embedding-3-large` and BGE-M3 in your own harness, then publish the recall@k delta on /metrics** — that comparison is a stronger artifact than any single model pick. (Voyage is now part of MongoDB; API unaffected — clean interface protects you regardless.)

### Stage 7 — Retrieval & Reranking — **LOCKED: hybrid + RRF + in-process CPU cross-encoder**

The 2026 production-standard pattern:

1. **Sparse leg:** Postgres FTS (lexical — exact tickers, defined terms, line items).
2. **Dense leg:** pgvector ANN over `voyage-finance-2` embeddings (semantic).
3. **Fuse:** Reciprocal Rank Fusion, `score(d) = Σ 1/(k + rank_i(d))`, **k=60** (the robust default).
4. **Rerank:** cross-encoder over the fused top-50→100, down to top-k for the LLM.

**Reranker — locked to self-hosted CPU**, not Cohere:

| Option | Verdict |
|---|---|
| **`ms-marco-MiniLM-L-6-v2`** (CPU) | ✅ ~80MB, runs on a tiny instance, $0 marginal — **MVP + free-host default** |
| **`bge-reranker-base`** (CPU) | ✅ ~300–400MB, better quality, needs ~1GB RAM — use once the app host has the headroom |
| Cohere Rerank (API) | Top quality + Toronto tie, but ~$2/1k searches and its free tier is **non-production** — defer to an optional future A/B on a capped paid key |
| Zerank-2 | ❌ CC-BY-NC license blocks commercial use |

Self-hosting the cross-encoder *in the FastAPI process* removes the per-search cost and the licensing question, and needs no GPU and no extra service. **Constraint to respect:** the reranker model must fit the app host's RAM — MiniLM on a 512MB free instance, `bge-reranker-base` once you're on ~1GB+. Keep it behind a `Reranker` interface so Cohere stays a one-line swap if you ever want the quality bump. **Validate uplift first:** a reranker only helps when recall is high but precision is low — measure the NDCG@10 delta on your gold set and publish it on /metrics.

### Stage 8 — RAG Orchestration — **LOCKED: thin custom core (LangGraph in v2)**

| Option | For | Against |
|---|---|---|
| **Thin custom core** | You own retrieve→rerank→prompt→parse→cite; fully legible/debuggable; demonstrates you understand the internals; no framework churn | You write the glue (~a few hundred lines) |
| LlamaIndex | RAG-native, fast demo | Hides the pipeline; weaker depth signal |
| LangGraph | Right tool for *agentic* flow; Databricks Agent Bricks supports it | Overkill for single-shot RAG |

For single-shot citation-grounded RAG, the orchestration is small enough that a framework adds more opacity than value — and owning the loop signals more depth than gluing abstractions. Use **LlamaIndex selectively as a utility** (a parser/loader helper) if it saves real time, but don't let it own the pipeline. Adopt **LangGraph in v2** for the multi-document comparison feature ("compare R&D spend across these 3 filings over 2 years"), where its state machine pays for itself and the Databricks alignment lands. The write-up sentence — "started framework-light to keep retrieval debuggable, adopted LangGraph when the agentic comparison feature justified it" — is exactly the criterion-#7 leadership signal.

### Stage 9 — LLM (Generator + Judge) — **LOCKED: Haiku 4.5 default → Sonnet 4.6 if eval justifies; judge = different family**

**Generator** (faithful grounded synthesis + reliable citation formatting):

| Model | Price /1M (in/out) | Role |
|---|---|---|
| **Claude Haiku 4.5** | **$1 / $5** | **MVP default** — strong at extraction/summarization over provided context; ~$0.009 per answer |
| Claude Sonnet 4.6 | $3 / $15 | Upgrade target if the harness shows Haiku's faithfulness/citation accuracy isn't enough |
| GPT-5.x / Gemini 3.x | — | Alternatives behind the interface; GPT-5.x for guaranteed-JSON if needed |

**Start on Haiku 4.5**, behind a provider-neutral interface (a thin wrapper or **LiteLLM**), and let your own eval decide whether to upgrade to Sonnet 4.6 — a clean "I made a cost/quality call from my metrics" story. **Cost levers:** prompt caching (up to 90% off the static system prompt + citation schema), the Batch API (50% off) for the eval and any bulk synthesis, and a hard `max_tokens` cap on output.

**Judge** (eval harness): **a different model family from the generator** (e.g., Haiku/Sonnet generates, GPT-5.x or Gemini judges) — same-model judging creates correlated blind spots; decorrelating is cheap insurance reviewers respect. ~$1 per 200-question run.

**"Knows when not to answer"** (a headline product trait, and the Wealthsimple "where AI should/should not take responsibility" signal): (a) a retrieval-confidence floor — abstain rather than guess when fused/rerank scores are weak; (b) a post-generation faithfulness check that flags unsupported claims. Frame abstention as a feature, not a limitation.

### Stage 10 — Evaluation Harness — **LOCKED: Ragas (golden set) + DeepEval (CI gate)** — do not cut

The standard 2026 split: **Ragas** for experimentation + **synthetic golden-set generation** + the four RAG metrics (faithfulness, answer relevancy, context precision, context recall); **DeepEval** wired into CI as the **pytest-native quality gate** so retrieval/chunking/model changes can't silently regress.

Metrics, in priority order (note the deliberate weighting):

1. **Retrieval recall@k** — *highest leverage.* If the right chunk never enters the candidate set, generation can't recover.
2. **Citation accuracy** — do the cited sources actually support the claim? The metric users feel.
3. **Faithfulness** (~90% target) — does each claim trace to a retrieved chunk.
4. **Context precision/recall, answer relevancy.**
5. **Operational:** freshness, latency, cost per query.

**Critical caveat baked in:** faithfulness measures grounding to *retrieved context, not truth* — a confidently-grounded answer over a stale/wrong chunk still scores high and is still wrong. No framework can tell correct context from wrong context. That's *why* recall@k and citation accuracy outrank faithfulness here, and why ingestion freshness/dedup/amendment-handling (10-K/A) is a **correctness** concern, not just hygiene.

**Workflow:** Ragas bootstraps a synthetic golden set → hand-label a core ~100–200 question subset → DeepEval runs the gate on every PR + on a schedule → all numbers surface on the public **/metrics** page. The versioned gold set lives in the repo as its own artifact. (Judge cost ~$0.001–0.003/case; a full run is ~$1.)

### Stage 11 — Observability — **LOCKED: Langfuse (cloud free tier)**

Open-source LLM observability with strong cost + latency + trace UX that maps directly onto the /metrics + "cost per query" requirements. Use the **cloud free tier** (covers a portfolio's trace volume — no self-hosted container to pay for); self-host only if you later prefer it. Trace every query: retrieved chunk IDs, rerank scores, prompt, tokens, latency, cost. Arize Phoenix is the equally-good OTel-native alternative.

### Stage 12 — Deployment & CI/CD — **LOCKED: Neon + Vercel + GitHub Actions; app host warm (~$5–7) or free (cold)**

| Component | Choice | Cost |
|---|---|---|
| Database | **Neon** (Postgres + pgvector, scale-to-zero, free tier) | **$0** |
| Frontend | **Vercel Hobby** (native Next.js) | **$0** |
| CI / ingestion / eval gate | **GitHub Actions** (free minutes) | **$0** |
| App / API host | **Render free** (cold starts) *or* **Fly.io / Render paid** (warm) | $0 *or* ~$5–7 |

GitHub Actions is your Jenkins/UrbanCode story modernized: lint + unit tests + the **DeepEval gate** on every PR, plus scheduled re-eval and incremental ingestion. **AWS** is deliberately *not* the host — it taxes iteration and budget for a solo MVP; earn the cloud signal cheaply instead via an ADR describing the AWS deployment (RDS+pgvector, ECS/Fargate, S3 for raw filings) or the cloud cert. See §7 for the warm-vs-cold tradeoff.

### Stage 13 — Frontend — **LOCKED: Next.js (App Router)**

Chat UI with **inline, clickable citations** (each linking to source filing + section) + a public **/metrics** page rendering eval numbers and cost/latency/faithfulness-over-time. The product surface is what makes this *visible* — the difference between "a RAG repo" and "a live thing you can use." Two routes (chat + metrics) is plenty for v1. (Streamlit is faster but reads as a demo, not a product.)

---

## 3. Consolidated Stack (final)

| Layer | Locked choice | Swappable? | Cost |
|---|---|---|---|
| Language / API | Python 3.12 + FastAPI + Pydantic v2 | — | $0 |
| EDGAR access | `edgartools` (+ raw `data.sec.gov` fallback) | Yes (`FilingSource`) | $0 |
| Orchestration | Dagster, run in GitHub Actions / locally | — | $0 |
| Storage | Neon Postgres + pgvector + FTS (single DB) | dense leg → Qdrant later | $0 (free tier) |
| Chunking | Structure-aware + parent–child + table handling | — | $0 |
| Embeddings | `voyage-finance-2` (50M free, then $0.12/1M) | Yes (`Embedder`) | ~$0 |
| Retrieval | Hybrid FTS + dense, RRF (k=60) | — | $0 |
| Reranker | In-process CPU cross-encoder: MiniLM (free host) → `bge-reranker-base` (≥1GB) | Yes (`Reranker`) | $0 |
| RAG orchestration | Thin custom core (LangGraph in v2) | — | $0 |
| Generator LLM | Claude Haiku 4.5 (→ Sonnet 4.6 if eval justifies) via LiteLLM | Yes | ~$1–3/mo |
| Judge LLM | Different family (GPT-5.x / Gemini), eval-only | Yes | ~$1–4/mo |
| Eval | Ragas (golden set) + DeepEval (CI gate) | — | judge cost only |
| Observability | Langfuse (cloud free tier) | — | $0 |
| Deploy / CI | Docker + Neon + Vercel + GitHub Actions; app host free/warm | — | $0–7/mo |
| Frontend | Next.js (chat + /metrics) | — | $0 |

---

## 4. MVP Scope (the one remaining taste call)

**Corpus:** the only decision with no architectural impact, left to your preference.

| Option | For | Against |
|---|---|---|
| **~15–20 large-cap tech/software** *(recommended default)* | Relatable demo questions, more uniform filings, fastest path to good retrieval | Less domain-leverage narrative |
| Financial-sector filings | Plays the RBC domain card directly | Bank 10-Ks are the longest/most complex — higher MVP risk |
| Split (~12 tech + ~5 financials) | Both angles | Slightly more ingestion variety to handle |

**Recommended default: ~15–20 large-cap tech/software for the MVP, then expand to / pivot toward financial-sector filings in v1** to play the domain card in the narrative ("extended the corpus to bank filings, leveraging my RBC domain knowledge of financial reporting"). Ship-speed and demo-ability win at MVP; the fintech story lands at v1. Flip to financials-now if you'd rather lead with domain leverage — no other decision changes.

**MVP retrieval shape:** include hybrid + RRF from the start (cheap, robust on exact-term queries); use MiniLM rerank at MVP and validate its uplift before considering anything heavier. **Citation grounding is in from day one** — it's the product's entire trust premise.

---

## 5. Cost & Operations

The architecture was already cheap; these are the operational choices and guardrails that keep it that way.

### Realistic monthly cost

| Item | Cost |
|---|---|
| Database (Neon free, scale-to-zero) | **$0** |
| Embeddings (voyage-finance-2, 50M free) | **$0** |
| Reranker (in-process CPU) | **$0** |
| Frontend (Vercel Hobby) | **$0** |
| Orchestration / CI / eval gate (GitHub Actions free minutes) | **$0** |
| Observability (Langfuse cloud free) | **$0** |
| LLM generation (Haiku 4.5, ~$0.009/answer; ~100–300 queries/mo) | **~$1–3** |
| Eval judge runs (different family, weekly) | **~$1–4** |
| App host (optional, to keep it warm) | **$0 (cold) or ~$5–7 (warm)** |
| **Total** | **~$0–3 fully free / ~$7–12 with a warm app + Sonnet** |

The LLM is the only thing that scales with traffic, and at portfolio volumes it's single-digit dollars. Embeddings, reranker, DB, frontend, and orchestration are fixed at $0.

### Cost-control checklist (the "no surprise bill" guardrails, in priority order)

1. **Hard spend caps + billing alerts on every paid provider** (Anthropic console usage limit; Voyage). Cap Anthropic at, say, $15/mo and the worst case is bounded no matter what.
2. **Rate-limit the public endpoint** — per-IP and a global per-day query cap in FastAPI. Stops a bot from running up the LLM bill.
3. **Gate the demo lightly** — shared passphrase, simple captcha, or "request access" — keeps crawlers out without hurting the recruiter experience.
4. **Cache answers** for identical queries (cheap; also speeds the demo).
5. **Cap LLM `max_tokens`** so no single call runs away.
6. **Prompt caching** on the static system prompt + schema (up to 90% off cached input).
7. **Incremental embedding only** (watermark new/amended filings) — keeps you inside Voyage's free 50M.
8. **Scale-to-zero infra** (Neon; Render free / Fly auto-stop); ingestion + eval in CI, never on a persistent worker.

### The one tradeoff worth ~$5–7/month

Free app hosting means cold starts: Render's free tier spins down after ~15 min idle, and the first request then takes 30–60s — a bad first impression on a link a recruiter clicks once. Neon's DB cold start is sub-second, so the app tier is the bottleneck. **Recommendation:** keep DB, embeddings, reranker, frontend, and orchestration at $0, and spend the single ~$5–7/month to keep just the *app* warm (Render paid or a small always-on Fly machine). For the artifact whose whole job is to impress, that's the one place the money is worth it. Going fully $0 (accept the cold start, maybe with a "waking up…" UI message) is a legitimate choice too.

---

## 6. Locked Decisions (summary)

1. **Orchestrator:** Dagster, run in GitHub Actions / locally (no hosted daemon).
2. **Storage:** Neon Postgres + pgvector + FTS, single DB, scale-to-zero free tier.
3. **Embeddings:** `voyage-finance-2` (free at your scale), swappable; publish an in-harness A/B.
4. **Reranker:** in-process CPU cross-encoder — MiniLM (free host) → `bge-reranker-base` (≥1GB); Cohere deferred to an optional capped A/B.
5. **RAG orchestration:** thin custom core; LangGraph in v2.
6. **Generator:** Claude Haiku 4.5 via LiteLLM, upgrade to Sonnet 4.6 only if the harness justifies it; prompt caching + output cap.
7. **Judge:** different model family, eval-only.
8. **Eval:** Ragas golden set + DeepEval CI gate; weight recall@k + citation accuracy above faithfulness.
9. **Observability:** Langfuse cloud free tier.
10. **Hosting:** Neon + Vercel + GitHub Actions ($0); app host warm at ~$5–7 (recommended) or free with cold starts.
11. **MVP corpus:** ~15–20 large-cap tech/software (default) → financials in v1. *(Only open-to-taste item; no architectural impact.)*

---

## 7. Build Order (maps to the outline's phasing)

**MVP (≈2–3 weeks):** ~15–20 tech filings ingested by a one-shot script → structure-aware chunking → `voyage-finance-2` embeddings into Neon/pgvector → hybrid FTS+dense+RRF retrieval → in-process MiniLM rerank → Claude Haiku 4.5 citation-grounded answers via LiteLLM → minimal Next.js chat UI with inline citations on Vercel → deployed to a live URL. Langfuse tracing + spend caps + rate limiting on from the start.

**v1 (+2–3 weeks):** Dagster incremental pipeline in GitHub Actions (discovery → parse → clean → chunk → embed → upsert) with data-quality checks, dedup, 10-K/A amendment handling, and watermarking → full Ragas + DeepEval harness on a versioned gold set → public /metrics page (recall@k, citation accuracy, faithfulness, latency, cost, *plus* your embedding/reranker A/B) → GitHub Actions eval gate → upgrade reranker to `bge-reranker-base` and decide Haiku-vs-Sonnet from the numbers → README with architecture diagram + ADRs + one technical write-up.

**v2 (stretch):** LangGraph multi-document comparison agent, MCP server (edgartools' bundled one shortens this), earnings-call transcripts, financial-sector corpus expansion, multi-model routing, optional Cohere reranker A/B on a capped key.

---

*Next session: build the MVP ingestion + chunking module first — chunking quality gates everything downstream. (Confirm the MVP corpus choice in §6.11 when we start.)*
