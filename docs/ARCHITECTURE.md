# Architecture — Customer Support Agentic RAG System

Status legend: **[Built]** implemented and verified · **[Designed]** ideated and agreed on, not yet coded · **[Deferred]** intentionally postponed.

## 1. Problem & Approach

Addresses a common, company-agnostic support workflow: a customer describes a problem
in free text; the system should understand it, find grounded evidence for a resolution
in a curated knowledge base, attempt to resolve the issue conversationally, and
escalate to a human support engineer when it can't.

Two design principles run through every stage:
- **Evidence-first, never fabricated** — answers must be traceable to retrieved KB chunks; low-confidence evidence triggers escalation rather than a guess.
- **Soft signals, never hard filters** — metadata (product area, category) *boosts* ranking, it never excludes a candidate outright, because misclassification in the source data is expected.

## 2. Two-Tier Knowledge Model

- **Tier 1 — Curated Knowledge Base [Built]**: official product troubleshooting documentation (`MicrosoftDocs/SupportArticles-docs`, CC-BY-4.0 — see [DATA_SOURCES.md](DATA_SOURCES.md) for the licence and attribution this requires), processed into a hybrid-searchable index. A candidate Kaggle ticket dataset was rejected as synthetic — unrendered template placeholders, nonsensical resolutions, near-uniform random labels.
- **Tier 2 — Historical Resolved Tickets [Deferred]**: no real ticket dataset available yet. Planned to be added later via a summarization agent. A side effect of the Resolver design (§5) is that every successfully-resolved conversation is already a ready-made Tier-2 record (query + steps taken + confirmation it worked) — worth keeping in mind for when this tier is built.

## 3. Data Pipeline [Built] — M1–M6

Each stage reads the previous stage's output. `data/raw/` is never modified; every script writes only to `data/processed/`.

| # | Script | Responsibility | Result |
|---|--------|-----------------|--------|
| 01 | `scripts/01_profile.py` | Profiles the raw corpus (file counts, structure, front matter) | 8,055 files profiled |
| 02 | `scripts/02_filter.py` | Inclusion/exclusion manifest — drops templates, includes, landing pages, tiny stubs | 7,930 / 8,056 included |
| 03 | `scripts/03_clean.py` | Cleans Markdown, resolves `[!INCLUDE]` directives, normalizes callouts/HTML links/whitespace | — |
| 04 | `scripts/04_chunk.py` | Hierarchical chunking: Article → Section (H2) → Subsection (H3) → Chunk | 55,771 chunks from 7,930 docs |
| 05 | `scripts/05_metadata.py` | Enriches chunks: `product_area`, `component`, `category`/`subcategory` (parsed from `ms.custom: sap:` tags), `kb_number`, `error_codes` | `taxonomy.json`: 26 product areas |
| 06 | `scripts/06_store.py` | Builds the BM25 index and the Chroma vector store | 55,771 / 55,771 chunks embedded |
| 07 | `scripts/07_retrieve.py` | Hybrid retrieval: BM25 + vector, RRF fusion, metadata boosting, cross-encoder rerank | see §4 |
| 08 | `scripts/08_evaluate.py` | Recall@5 / Recall@10 benchmark over a 52-query hand-built set | see §4.4 |
| 09 | `scripts/09_understand.py` | LLM query understanding, missing-context detection, problem-signature normalization | see §5.1 |

### 3.1 Hierarchical chunking, in detail

Chunking follows the document's own structure rather than a fixed token window:
`Article → Section (H2) → Subsection (H3) → Chunk`. H1 is treated as the article title
(not a section level); H4+ headings fold into bold inline text rather than adding a
fourth tree level; fenced code blocks are treated as atomic units so a code sample is
never split mid-block. Each chunk record carries its full heading path and metadata,
so a fine-grained chunk always knows which section/article it belongs to.

Retrieval then uses **"index small, return whole"** (the parent/child retrieval
pattern): matching happens at the fine chunk level for precision, but results are
deduplicated and expanded to their full parent group (shared section, or whole
article) before being returned — so the caller gets complete, usable context rather
than an isolated fragment.

## 4. Retrieval Architecture [Built]

`scripts/07_retrieve.py::hybrid_search()` combines three signals in sequence:

```
query
  ├─→ BM25 search (sparse, keyword)   ─┐
  └─→ Vector search (dense, semantic) ─┼─→ Reciprocal Rank Fusion ─→ Metadata boost ─→ Cross-encoder rerank ─→ results
```

1. **BM25** (`rank_bm25.BM25Okapi`) — keyword/sparse search over a `\w+`-tokenized corpus. Pool: top 50 candidates.
2. **Vector search** (ChromaDB, `BAAI/bge-base-en-v1.5` embeddings) — semantic/dense search. Queries are prefixed with the BGE instruction string (`"Represent this sentence for searching relevant passages: "`); passages are embedded as-is. Pool: top 50 candidates.
3. **Reciprocal Rank Fusion** — `score += 1/(k+rank)` per list, `k=60`. Combines by rank position rather than raw score, since BM25 and vector scores aren't on comparable scales.
4. **Metadata rank-boosting (soft)** — majority-vote `product_area` among the top candidates (min 3 votes agreeing); candidates matching that consensus get a `1.15×` multiplicative boost. Deliberately never a hard filter — RRF's natural score spread across a 50-candidate pool is only ~0.008–0.033, so this nudges close calls without ever excluding a candidate the primary signals disagree on.
5. **Cross-encoder rerank** — `cross-encoder/ms-marco-MiniLM-L-6-v2` re-scores only the top 20 fused candidates by reading query+passage jointly (unlike the independently-encoded bi-encoder embeddings used for the initial vector pass).

Both BM25 and vector stores are namespaced by embedding model (`collection_name_for_model()`) to prevent silent dimension collisions if the embedding model is ever changed.

### 4.4 Evaluation

`scripts/08_evaluate.py` measures Recall@5/@10 against 52 hand-built queries — 26
"distinctive" (rare-topic, low-competition) queries plus 26 across 7 deliberately
crowded clusters (near-duplicate sibling articles, e.g. `modern_authentication`,
`bitlocker_tpm`, `mfa`) chosen specifically to avoid an inflated baseline. An earlier,
easier query set scored an artificially high 0.97 for both methods; the crowded-cluster
set gives an honest, diagnostic signal:

| Method | Raw Recall | Expanded Recall |
|--------|-----------|------------------|
| BM25 | 0.88 | 0.92 |
| Vector | 0.92 | 0.94 |

Raw == expanded in every reported row, confirming chunking strategy is not implicated
in any observed retrieval failure. The two failure types found: (a) BM25 and vector
*agreeing* on a wrong result (`modern_authentication`, both methods scoring 0.50) — not
fixable by fusion alone, addressed by reranking; (b) *complementary* misses where the
two methods disagree — directly fixable by fusion. This distinction is what drove
implementing RRF fusion and cross-encoder reranking together. The hybrid (fused +
boosted + reranked) report has not yet been re-run since the metadata-boost scaling fix.

## 5. Understanding & Normalization [Built] — M6

`scripts/09_understand.py` turns a raw customer query into structured, actionable state, ahead of any retrieval:

- **Structured extraction** (LLM, provider-agnostic — see §5.2): `product_area`, `component`, `symptoms` (list), `category`, `severity` (Low/Medium/High/Critical — technical severity), `environment`, `frustration` (Low/Medium/High — customer's tone, judged separately from technical severity), `impact_scope` (Individual/Team/Organization/Unknown — blast radius, defaults to Unknown rather than guessing).
- **Deterministic missing-context detection** — checks whether required fields were actually extractable from the query.
- **Canonical problem-signature normalization** — a pipe-delimited string + `bge-base` embedding, built for a not-yet-implemented caching layer (M7). `frustration` and `impact_scope` are deliberately excluded from this signature: they describe the ticket *instance* (tone, blast radius), not the underlying technical problem, and including them would fragment cache hits for the same issue reported with different urgency or scope.

### 5.2 LLM provider abstraction

Dispatch-table pattern (`gemini` / `anthropic` / `openai`), each SDK lazily imported
only when selected. Configured entirely via `.env` (`LLM_PROVIDER`, `LLM_MODEL`,
provider-specific key resolved dynamically via `PROVIDER_API_KEY_ENV`). Default:
`gemini` / `gemini-3.5-flash-lite`. No LLM provider is hardcoded anywhere in the
pipeline — this abstraction is what the agent layer (§6) will also sit on top of.

## 6. Agent Architecture [Designed, not yet built] — M8

Two agents, each owning a distinct responsibility, communicating through a shared
"pause and wait for the human's next message" mechanic (needed by both, built once).

```
customer query
      │
      ▼
 ┌─────────────┐   context sufficient    ┌─────────────┐
 │  Clarifier  │ ───────────────────────▶ │  Resolver   │
 └─────────────┘                          └─────────────┘
      ▲  │ context missing                       │
      │  ▼                                        │
   [pause: ask customer]                   [pause: send answer,
      │                                      wait for reply]
      └──── customer replies ───────────────────  │
                                                    ▼
                                          assess_resolution
                                         ↙ resolved      ↘ not resolved
                                    close out         retry (≤ max_attempts)
                                                       or escalate
```

### 6.1 Clarifier

- Runs structured extraction (`09_understand.py::extract_fields()`) and deterministic missing-context detection (`detect_missing_context()`) on the raw query.
- If context is missing: generates the actual clarifying question to send the customer — new work, since today `detect_missing_context()` only flags *that* something's missing, not *what to ask*.
- Optionally runs a **narrow ambiguity check**: a lightweight retrieval call using whatever fields are already known, checking only whether the candidate pool's `product_area`/`category` consensus is still split (the same signal `07_retrieve.py` already computes for metadata boosting). If the pool already converges despite a missing field, skip asking about it — avoids forcing an unnecessary round-trip on the customer. This is deliberately not full retrieval: it exists to test ambiguity, not to fetch a final answer, and only runs with whatever partial signature is available.
- Pauses, waits for the customer's reply, re-extracts/merges, and loops until context is sufficient.
- Produces the normalized problem signature (`normalize_to_signature()`) as the handoff artifact to the Resolver.

### 6.2 Resolver

A conversational loop, not a single-shot answer:

- Retrieves evidence (`07_retrieve.py::hybrid_search()`) using the normalized signature.
- **Pre-send confidence check** — if evidence is too weak to answer at all, escalates immediately rather than sending a shaky answer.
- Formats retrieved resolution steps into a customer-facing message (evidence-first, grounded), sends it, and pauses for the customer's reply.
- **Assess-resolution check** — classifies the reply via structured LLM extraction (`resolved | not_resolved | partial | unclear`), same pattern as `severity`/`frustration` in `09_understand.py`, rather than a keyword heuristic, since "kind of works but X is still off" needs real understanding.
- **Retry policy** (agreed): up to `max_attempts` (default 3 total attempts, i.e. 2 retries), layered cheap-to-expensive — retry 1 falls back to the next-ranked chunk already in the pool (no new retrieval call); retry 2 re-runs retrieval with the query augmented by what the customer said didn't work.
- **Escalation payload**: full conversation transcript, extracted fields, normalized signature, every chunk tried across attempts, and (for the retry-exhausted case) the customer's own words on what didn't work — substantially better context for a human than fields alone.

These two gates (pre-send confidence check, post-reply resolution check) catch
different failure modes: weak evidence up front vs. a plausible-looking answer that
turned out wrong.

### 6.3 Orchestration choice

Control flow is planned as a **LangGraph state graph** rather than a free-roaming
tool-calling agent: fixed nodes/edges, with the LLM doing content work (extraction,
question generation, answer formatting, resolution classification) at specific,
narrow points while the graph — not the LLM — decides branching. This keeps the
confidence gates and retry limits genuinely deterministic (an LLM in a free ReAct loop
could talk itself past a gate meant to stop it), and each node already has a clean
boundary that becomes a multi-agent subgraph later without restructuring, in line with
the "start at 1–2 agents, split into multi-agent later" plan.

## 7. Considered and Rejected: GraphRAG

Evaluated whether GraphRAG (LLM-extracted entity graph + community
detection + hierarchical community summaries, enabling "global sensemaking" queries
that no single chunk can answer) should replace or augment the current retrieval
approach.

**Not adopted for Tier 1.** GraphRAG solves a different problem — corpus-wide
synthesis ("what are the recurring themes across everything") — than what triage
actually needs, which is entity-specific lookup for one customer's specific problem.
Our own eval data (§4.4) shows the real failure mode is *disambiguation between
near-duplicate articles*, which reranking and metadata boosting already target; it is
not a case of "the answer isn't in any single chunk." Adopting it now would mean an
LLM extraction pass over all 55,771 chunks plus new graph-construction and
community-summarization infrastructure, for a failure mode our evaluation doesn't show.

**Where it could fit later**: Tier 2 trend analysis ("what are the top recurring
issues this month across resolved tickets") is a genuine global-sensemaking question,
unlike single-ticket triage — worth reconsidering if/when Tier 2 is built.

## 8. Roadmap

| Milestone | Status |
|---|---|
| M1–M5: Data pipeline (profile → filter → clean → chunk → metadata) | Built |
| M6: Storage, hybrid retrieval, evaluation, understanding/normalization | Built |
| M7: Caching layer (keyed on the normalized problem signature) | Not started |
| M8: Grounded generation + agent orchestration (Clarifier + Resolver) | Designed |
| M9: Confidence-gated escalation | Partially designed (folded into Resolver, §6.2) |
| Tier 2: Historical resolved tickets + summarization agent | Deferred — no real dataset yet |

## 9. Configuration Reference

All configuration lives in `.env` (see [.env.example](../.env.example)); no model,
provider, or path is hardcoded in the pipeline.

| Variable | Default | Used by |
|---|---|---|
| `EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | 06, 07, 09 |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 07 |
| `VECTOR_DB_PATH` | `data/processed/store/vector` | 06, 07 |
| `BM25_PATH` | `data/processed/store/bm25` | 06, 07 |
| `EMBEDDING_BATCH_SIZE` | `64` | 06 |
| `LLM_PROVIDER` | `gemini` | 09 |
| `LLM_MODEL` | `gemini-3.5-flash-lite` | 09 |
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | — | 09 (set only the one matching `LLM_PROVIDER`) |
