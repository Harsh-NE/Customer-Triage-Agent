# Architecture — Customer Support Agentic RAG System

Status legend: **[Built]** implemented and run · **[Built, verified]** implemented and covered by tests/evaluation ·
**[Dataset only]** data exists but no code uses it · **[Designed]** agreed on, not yet coded · **[Deferred]** intentionally postponed.

> **Target application: Docker.** The project started on a Microsoft support-article corpus and pivoted to Docker on
> 2026-09-24. Everything below describes the Docker system. Figures that came from the earlier corpus are kept only
> where they are labelled *Microsoft corpus* (the retrieval evaluation in §4.2), because they have **not** been re-run
> on Docker. Current agent-layer detail lives in [MEMBER_A_HANDBOOK.md](MEMBER_A_HANDBOOK.md); how the Docker KB is
> built lives in [DOCKER_KB_BUILD.md](DOCKER_KB_BUILD.md); the team plan (v2) is a separate PDF kept outside the repo.

## 1. Problem & Approach

A common, company-agnostic support workflow: a customer describes a problem in free text; the system should understand
it, find grounded evidence for a resolution in a curated knowledge base, attempt to resolve it conversationally, and
escalate to a human support engineer when it can't.

Two design principles run through every stage:
- **Evidence-first, never fabricated** — answers must be traceable to retrieved KB chunks; low-confidence evidence triggers escalation rather than a guess.
- **Soft signals, never hard filters** — metadata (product area, platform, answers the customer gave) *re-weights* candidates, it never excludes one outright, because misclassification in the source data is expected.

Rollout is staged by risk, so cost and trust are earned before autonomy increases: **(1)** retrieval-only (return the
matching passage, no generation) → **(2)** gated generation (draft only when groundedness and confidence gates pass)
→ **(3)** autonomous and self-improving (cache and KB grow from confirmed resolutions). The cheapest correct answer is a
cache hit; the system should always try cheap-and-safe before expensive-and-risky.

## 2. Two-Tier Knowledge Model

- **Tier 1 — Curated Knowledge Base [Built, verified]**: the `docker/docs` repository (Apache License 2.0 — repo
  `LICENSE`, checked 2026-10-05; `_vendor/` content is excluded). 1,434 Markdown files scanned → **961** included →
  **11,440 chunks** (token-capped, rebuilt 2026-10-07), embedded and stored. Composition by page type (`doc_kind`): docs 6,029 ·
  release notes 2,185 · guides 1,694 · archived versions 763 · reference 486 · **troubleshooting 187 · FAQ 96**. Only ~2.5% of
  the KB is troubleshooting/FAQ and ~26% is release notes or archive — the retrieval and clarification design accounts for this
  (page-type weights, §6.1).
- **Tier 2 — Historical Resolved Tickets [Dataset only]**: `docker_tickets_v5_fixed.csv` — **13,899 rows, 28 columns**,
  built by the Colab notebooks in `notebooks/` (01–09). Sources: Stack Overflow accepted (6,352), GitHub maintainer-resolved
  (4,593), Stack Exchange accepted (763), Docker forum solved (752), synthetic LLM Q&A from Hugging Face (655, flagged
  `is_synthetic`), GitHub community-resolved (499), official docs FAQ entries (152, flagged `overlaps_kb`), HF Q&A
  unspecified (101), forum inferred-resolved (32, lowest trust). Trust tiers: high 8,573 · medium 4,506 · low 820.
  Quality audit: [DATASET_QUALITY_REPORT.md](DATASET_QUALITY_REPORT.md).
  Put the CSV in `data/raw/tickets/`. **`scripts/10_tickets.py` turns it into a separate store** (built 2026-10-08);
  **no retriever, router or Resolver reads that store yet.**

  **How tickets are processed (decided and built).** A ticket is one problem + one resolution, so the KB's heading-based
  chunker does not apply: **one vector per ticket**. The embedded text is `title` + up to 3 cleaned error lines + the head of
  `problem`, capped at **256 tokens** (45% of `title + problem` exceed the model's 512; at 500 tokens embedding ran ~0.6
  tickets/s on a laptop CPU vs ~3.6/s at 256, i.e. ~6 h vs ~1 h, and the symptom is in the head anyway; `--max-tokens`
  changes it). The **resolution is not embedded**: it is stored whole and trimmed when context is built.
  - **Separate store** (`data/processed/docker/store/tickets/`): Chroma collection `tickets__baai-bge-base-en-v1-5`, a BM25
    index over title + errors + the *full* problem (+ tags for non-GitHub sources), and `tickets.db` (SQLite, one row per
    ticket incl. non-indexed ones, lists as JSON). Same embedding model as the KB, so one query embedding serves both.
    Kept apart because the unit, trust, voice and licences differ and 13k ticket vectors would crowd 11k KB chunks.
  - **Indexed: 13,092.** Not indexed (kept in the docstore with `exclude_reason`): 655 `is_synthetic`, 152 `overlaps_kb`.
    Low-trust tickets (165 remain) are indexed and meant to be filtered at query time.
  - **Chroma metadata is flat scalars only:** `trust_tier`, `trust_score`, `resolution_kind`, `kind_guess`, `source`,
    `source_type`, `age_years` (-1 = unknown), `has_code`, `n_errors`, `has_exit_code`, `url`, `license`, and one boolean per
    topic (`topic_networking`, ...) because Chroma cannot filter on lists.
  - **`error_strings` is unreliable in the source CSV**: it holds any quoted span (paths, commands) and ~19% prose cut at
    apostrophes ("ve got going..."). The script keeps only multi-word, error-looking lines without first-person prose;
    ~3.2k indexed tickets keep a real error line. Exit codes and versions are stored, not embedded.
  - **Intended use (not built):** hard filters on `kind_guess`, trust floor and `is_synthetic`; ranking = RRF(vector, BM25) x
    trust x resolution-kind x recency, with large boosts for exact error-line / exit-code matches and a soft topic boost;
    KB passages stay the primary evidence, tickets are labelled community-sourced context with URL + licence (CC BY-SA needs
    attribution); tickets lead only when the KB is weak, with lower confidence.
  - **Verified so far:** counts and token caps (tests), and one smoke query ("container exits with code 137"): the top vector
    and BM25 hits are the right ticket, but vector search also returns exit codes 139/125 and a low-trust ticket, which is what
    the exact-match boost and trust floor are for. No recall/precision measurement exists.

A side effect of the Resolver design (§6.2): every successfully-resolved conversation is already a ready-made Tier-2
record (query + steps taken + confirmation it worked).

## 3. Data Pipeline [Built] — M1–M6

Each stage reads the previous stage's output; `data/raw/` is never modified. For Docker, scripts 01–06 read
`data/raw/docker-docs/` and write to `data/processed/docker/`.

| # | Script | Responsibility | Docker status |
|---|--------|-----------------|---------------|
| 01 | `scripts/01_profile.py` | Profiles the raw corpus | **Not adapted** — still reports `ms.topic`; harmless, not on the build path |
| 02 | `scripts/02_filter.py` | Inclusion manifest | **Adapted**: allowlist of `content/{manuals,reference,guides,get-started}`; "troubleshooting" read from the front-matter `tags` list. 961 included / 473 excluded |
| 03 | `scripts/03_clean.py` | Cleans Markdown, callouts, links, whitespace | **Adapted** (carries `tags`). `> [!NOTE]` callouts use the same syntax as before; `[!INCLUDE]` resolution is a no-op on Docker |
| 04 | `scripts/04_chunk.py` | Hierarchical chunking | **Adapted**, token-aware (metadata: `tags`, `is_troubleshooting`, `weight`). 11,440 chunks |
| 05 | `scripts/05_metadata.py` | Enrichment | **Rewritten**: `product_area`, `component`, `doc_kind`, `tags`, `error_signals`, `source_url`, `license` |
| 06 | `scripts/06_store.py` | BM25 index + Chroma vector store | **Adapted**: Docker store paths, richer Chroma metadata, `--metadata-only` refresh |
| 07 | `scripts/07_retrieve.py` | Hybrid retrieval | **Not yet adapted** — see §4.1 |
| 08 | `scripts/08_evaluate.py` | Recall@5/@10 benchmark | **Not yet adapted** — Microsoft query set and paths |
| 09 | `scripts/09_understand.py` | Query understanding | **Superseded** for Docker by `triage/understand.py` (§5) |

### 3.1 Filtering

`docker/docs` is a full Hugo site repository, not a flat docs tree, so filtering is an **allowlist** of content
directories rather than an excludelist of noise. Excluded: `_vendor/` (267 vendored files), `layouts/`, `content/includes/`
(Hugo partials), repo root files, and 116 files under 20 words.

### 3.2 Hierarchical chunking

Chunking follows the document's own structure: `Article → Section (H2) → Subsection (H3) → Chunk`. H1 is the article
title; H4+ fold into bold inline text; fenced code blocks stay whole whenever they fit; each chunk carries its full heading path.

**The real KB is inconsistent about heading depth**, and this matters downstream. `docker-hub/troubleshoot.md` makes the
*issue* an H2 with "Error message / Possible causes / Solution" as H3 — so each of those becomes its own chunk. The Desktop
`topics.md` makes the issue an H3 under a platform group with those fields as H4 — so they fold into **one** chunk. The
chunks are left as produced; the agent layer handles both by treating those field-like sub-headings as belonging to their
parent issue (`triage/issues.py`).

**Token-aware length cap.** `bge-base-en-v1.5` reads at most **512 tokens**; anything beyond is silently dropped from the
embedding. The first build capped by *words* (400), which does not bound tokens: **1,098 of 10,031 chunks (10.9%) exceeded
512 tokens** (median 140, p95 727, max 9,590), so vector search only saw their first 512 tokens. `04_chunk.py` now counts
with the embedding model's own fast tokenizer (`--max-tokens`, default 500; `--tokenizer` overrides the model name) and
splits an oversized leaf at the most natural boundary that fits: paragraph → line → sentence → exact token-offset window.
A fenced code block that must be split is re-wrapped in its opener on every part, so each chunk stays valid Markdown (the
opener's language tag/attributes therefore repeat). Text is sliced from the original, never decoded from ids. The script
exits non-zero if any chunk is over the limit.
Measured on the real corpus (2026-10-06): 961 docs → **11,440 chunks**, tokens median 148 / p95 485 / max 500, **0 over 500**.
Compared with the old chunks, every document keeps all its text (ignoring repeated fence openers, table-delimiter runs and
whitespace), and one doc recovers a paragraph the old chunker had dropped. **Status: fixed and the store rebuilt**
(2026-10-07: 11,440 chunks embedded, no errors). Effect on the Clarifier eval (29 scenarios): gold-first unchanged at 0.85;
READY precision 0.94 → 0.89 and wrong-READY 1 → 2 of 20, the new one being S17 ("docker pull fails
on rootless Docker"): a generic Docker Hub "Troubleshooting failed pulls" section won with no question asked even though the
customer's "rootless" is not covered by it. Cause: overall grounding only checks word overlap. **Fixed 2026-10-08 by the
rare-term check (§6.1)**; the eval is back to 0.94 / 0.05.

Retrieval is meant to use **"index small, return whole"**: match at the fine chunk level, then expand to the parent group.

### 3.3 Metadata and its known sparsity

`product_area` = first path segment under `content/manuals/` (`engine`, `desktop`, `docker-hub`, …); for `guides`,
`reference`, `get-started` the section name is used. `doc_kind` ∈ {troubleshooting, faq, release_notes, archive, guide,
reference, docs}. **`error_signals` (HTTP/response and exit codes) is sparse — only 14 chunks carry one**, because Docker
docs have no consistent structured error-code convention (unlike the earlier corpus's hex codes). The verbatim error text
in the chunk body, not this field, is the reliable signal.

History worth knowing: the first Docker adaptation of `05_metadata.py` mislabelled ~1,941 `guides`/`reference` chunks as
`product_area="content"` and leaked file names (`retired.md`) into the label. Fixed 2026-10-05; the local store was
patched with `06_store.py --metadata-only` (no re-embedding). **Any copy built before then (e.g. on S3) still has the old labels.**

## 4. Retrieval Architecture

### 4.1 Hybrid retrieval [Built: `triage/hybrid.py`; the original `scripts/07_retrieve.py` is still not adapted]

Two retrievers, both in `triage/hybrid.py`, both lazily loading the stores and able to share one embedding model
(`TicketRetriever(model=kb._model)`):

**`HybridKBRetriever`** (Tier 1; satisfies the `Retriever` protocol, so it replaced the vector-only `ChromaRetriever` as the
default of the CLI and the eval; `--retriever chroma` still selects the old one). Dense top-30 and BM25 top-30 are fused with
RRF; the `top_k` best fused chunks are returned, then siblings of the same issue are appended exactly as before.
*Scoring is deliberately not the RRF score*: the Clarifier's thresholds were calibrated on vector similarity
(`1/(1+distance)`, ~0.5-0.8) and RRF values (0.01-0.03) are on another scale, so every returned chunk, including ones only BM25
found, is scored by its exact vector similarity. BM25 therefore changes *which* issues are in the pool (recall for rare terms
such as "rootless" or "429"), not their weights. No metadata boost and no cross-encoder rerank yet (the rerank model's score is
uncalibrated; add it only if an evaluation shows the fused order needs it).

**Headings are indexed in BM25.** A chunk's text does not contain its own heading, which is the issue's name
("`docker pull` errors"). `06_store.py` now indexes `heading_path + text` (rebuild just BM25 in seconds with
`python scripts/06_store.py --bm25-only`). Measured on the 29 scenarios: hybrid with text-only BM25 lost a gold issue (SCIM) and
left READY at 0.55; with headings gold-first returned to 0.85. **The dense side still embeds text only**, so putting the heading
path into the embedded text is the obvious next experiment (needs the ~1 h re-embedding).

| Clarifier eval (29 scenarios) | vector only | hybrid (headings in BM25) |
|---|---|---|
| right issue ranked first | 0.85 | 0.85 |
| READY precision / wrong-READY | 0.94 / 0.05 (S07) | **1.00 / 0.00** |
| READY rate | 0.62 | 0.59 |
| questions per ticket | 1.45 | 1.52 |
| out-of-scope false-READY | 0/6 | 0/6 |

Hybrid trades a little speed (0.07 more questions per ticket) for safety, and fixes the last known wrong-READY (S07). Same caveat as
every number here: 29 same-author scenarios. S17 ("rootless") is still unresolved: the gold issue sits under the heading
"`docker pull` errors" in a long page and does not reach the top results with either retriever.

**`TicketRetriever`** (Tier 2). Dense and BM25 top-30 over the ticket store, RRF, then a re-rank in `rank_tickets()` (pure, unit
tested): fused rank x trust (0.6 + 0.4 x trust_score) x resolution-kind weight x recency (mild, floored at 0.6, unknown age 0.9)
x exact matches (exit code in the query that the ticket also has: x1.5; ticket has only other codes: x0.85; a ticket error line
overlapping the query by >= 0.6: x1.4; shared inferred topic: x1.1). Hard filters: `kind`, `exclude_ids` (for evaluation) and
one result per URL. The trust floor is soft: tickets below `min_trust` (default `medium`) only fill the list when too few eligible
ones exist. Returns `TicketHit` (`triage/state.py`), whose `matched` field explains the ranking; `render_ticket_card()` turns a
hit into a labelled "community ticket, not official documentation" block with URL and licence for an LLM. Exit codes are read from the query
text ("exit code 137"); HTTP codes (> 255) are ignored. Verified by unit tests and spot checks only; there is **no recall or
precision measurement** for ticket retrieval.

**Original design (`scripts/07_retrieve.py`)** - kept for reference; still reads the earlier corpus's chunk file:

`scripts/07_retrieve.py::hybrid_search()` combines three signals in sequence:

```
query
  ├─→ BM25 search (sparse, keyword)   ─┐
  └─→ Vector search (dense, semantic) ─┼─→ Reciprocal Rank Fusion ─→ Metadata boost ─→ Cross-encoder rerank ─→ results
```

1. **BM25** (`rank_bm25.BM25Okapi`) — keyword search over a `\w+`-tokenized corpus. Pool: top 50.
2. **Vector search** (ChromaDB, `BAAI/bge-base-en-v1.5`, 768-dim) — queries are prefixed with the BGE instruction string; passages are embedded as-is. Pool: top 50.
3. **Reciprocal Rank Fusion** — `score += 1/(k+rank)`, `k=60`; combines by rank because BM25 and vector scores aren't comparable.
4. **Metadata rank-boosting (soft)** — majority-vote `product_area` among the top candidates (min 3 votes) gets a `1.15×` boost; never a hard filter.
5. **Cross-encoder rerank** — `cross-encoder/ms-marco-MiniLM-L-6-v2` re-scores only the top 20 fused candidates.

Both stores are namespaced by embedding model (`kb_chunks__<model-slug>`) to prevent silent dimension collisions.

**Status:** `07_retrieve.py` and `08_evaluate.py` still hardcode `CHUNKS_PATH = data/processed/chunks_metadata.jsonl` (the
earlier corpus's chunk file) while `.env` now points the vector and BM25 stores at `data/processed/docker/`. That mixes a
Docker index with a non-Docker chunk lookup. **I have not run it in that state**, so the failure mode is unconfirmed; the
first step of adapting retrieval is to point `CHUNKS_PATH` at the Docker chunks.

The agent layer does **not** use `07_retrieve.py` today. It talks to a `Retriever` interface
(`search(query, top_k) -> list[Candidate]`, scores normalised to (0, 1]) and ships a vector-only stand-in
(`ChromaRetriever`) so it could be built and measured before the hybrid retriever was adapted. See
[MEMBER_A_HANDBOOK.md §4.4](MEMBER_A_HANDBOOK.md) for the contract the hybrid retriever must satisfy.

### 4.2 Evaluation — *Microsoft corpus, not re-run on Docker*

`scripts/08_evaluate.py` measured Recall@5/@10 on 52 hand-built queries (26 distinctive + 26 across 7 deliberately
crowded clusters of near-duplicate articles; an earlier, easier set scored an inflated 0.97):

| Method | Raw Recall | Expanded Recall |
|--------|-----------|------------------|
| BM25 | 0.88 | 0.92 |
| Vector | 0.92 | 0.94 |

Failure types found: BM25 and vector *agreeing* on a wrong result (fixed only by reranking) vs *complementary* misses
(fixed by fusion) — which is why RRF and the cross-encoder were both implemented. The fused+boosted+reranked report was never
re-run after the metadata-boost scaling fix, and **no Docker retrieval benchmark exists yet**. Observed on Docker:
vector search is weak on numbers ("429") and rare terms ("rootless"), which a BM25 half should help.

## 5. Understanding & Normalization [Built, verified] — `triage/understand.py`

Turns raw customer text into the shared `ExtractedFields` contract. It supersedes `scripts/09_understand.py` for Docker.

- **Extraction**: an LLM judges meaning (product, component, symptoms, platform, severity, frustration, impact scope);
  **regex extracts everything that must be verbatim** — error codes, error messages, versions. A deterministic
  **heuristic extractor** is the default (free, repeatable) and the automatic fallback when an LLM call fails or returns bad JSON.
- **Normalization**: product is mapped to the KB taxonomy through a hand-written alias table (43 phrases → 14 products);
  an unknown product becomes `None`, never an invented label. Platform is detected from the text (WSL counts as Windows).
- **Missing-context detection**: only `symptoms` is a *hard* gap. `product_area` is *soft* — retrieval runs first and infers it
  when the candidate pool agrees; it is asked about only if the candidate causes span several products.
- **PII redaction** on every stored message: emails, API/AWS/GitHub/Docker tokens, JWTs, bearer tokens, `password=`-style
  assignments. IP addresses are kept (they are diagnostic in Docker errors).
- **Signature**: `canonical_string = product|component|symptoms` (the cache key). `frustration`, `impact_scope`, platform and
  versions are excluded from the key — tone and blast radius describe the ticket, not the problem.

### 5.1 LLM provider abstraction

One-method interface (`complete(prompt) -> str`) over a dispatch table (`gemini` / `anthropic` / `openai`), SDKs imported
lazily, configured via `.env` (`LLM_PROVIDER`, `LLM_MODEL`; default `gemini` / `gemini-3.5-flash-lite`). `ScriptedLLM` replays
canned responses for tests. **No live LLM call has been made against this code**; the default model name is unverified.

## 6. Agent Architecture — M8

Two LLM agents plus a deterministic router; control flow is a graph, not a free-roaming agent.

```
customer message
      │
      ▼        Clarifier [Built, verified]                                Resolver [Designed]
 ┌──────────────────────────────┐   READY / UNRESOLVED   ┌───────────────────────────────┐
 │ ingest → understand →        │ ──── ProblemSignature ─▶│ retrieve → confidence gate →  │
 │ {ask_gap | diagnose → decide}│ ◀── NeedClarification ──│ draft → classify reply →      │
 └──────────────────────────────┘     (shared budget)     │ retry (≤ max_attempts)/escalate│
      ▲  │ ASK                                            └───────────────────────────────┘
      └──┘ customer replies
```

### 6.1 Clarifier [Built, verified] — `triage/clarifier.py`

One invocation per customer message (stateless apart from `SessionMemory`). Statuses: **ASK** (a question is pending),
**READY** (confident signature), **UNRESOLVED** (budget spent / nothing left to ask / no evidence — the signature and a
ranked differential are still attached so the Resolver or a human can use them).

**Differential diagnosis** (`triage/differential.py`) — the core of the Clarifier. A symptom like "pull fails with 429"
matches several KB issues; instead of a generic "give more detail", the Clarifier:
1. retrieves (three queries merged by best score: everything known; the same prefixed with `troubleshoot`; the customer's verbatim error) and groups chunks into **hypotheses**, one per KB *issue*;
2. weights them: `softmax(score × page-type weight × generic-title weight / T)`; release notes ×0.6, archive ×0.4, "Overview" sections ×0.5; a pasted error that matches a hypothesis's documented error text boosts it (up to ×4);
3. decides **READY** only if `p_top ≥ 0.5`, `margin ≥ 0.25`, the top hypothesis is *lexically grounded* (≥ 34% of the customer's content words appear in its text) **and** it covers every *discriminating* customer term (below) — dense retrieval always returns something and its absolute scores do not separate junk from signal, so this check is what stops confident answers to out-of-scope questions;
4. otherwise ranks questions by *expected elimination × answerability* (platform 1.0, error text 0.9, product 0.8, "which of these sounds like yours" 0.6; `component` is never asked — it is an internal doc-path label); only plausible causes (≥ 5%) appear in a menu;
   **Rare-term check (`uncovered_term`).** Overall grounding can pass while the one word that matters is missing: "docker pull fails on *rootless* Docker" matched a generic pull page on 2 of 3 words. A customer word (function words ignored, crude stemming) is *discriminating* when it appears in at least one but at most 70% of the retrieved issues (`rare_term_max_share`; "rootless" was in 6 of 10, "pull" in all 10) and the pool has ≥ 4 issues. If the leader lacks such a word the decision is `uncovered_term` (ambiguous): the Clarifier asks the usual question (usually the issue menu). It is a trigger for *one* clarification, not a veto: once the customer has answered anything it is waived; and if there is nothing to ask the leader is still returned as READY with reason `clear_with_uncovered_term` and `meta["uncovered_terms"]` so the Resolver can hedge. `Hypothesis.missing_terms` carries the words (added with a default; no schema version bump). Measured on the 29 scenarios: S17 now ends unresolved after 2 questions instead of a wrong READY, S06 asks 1 extra question (still correct), nothing else changes; 0.34–0.7 behave the same, and 0.9 would also turn the other known wrong-READY (S07) into a question. The 0.7 default is a judgement from a small same-author eval, not a calibrated value.
5. re-weights **softly** after an answer (contradicting hypotheses ×0.15, never removed) and decides again; if nothing separates the causes it asks for the exact error text once.

**Reflection is a step, not an agent** (`triage/reflect.py`): before sending a question it checks the field isn't already known,
the customer hasn't already stated it, it hasn't been asked twice, and the wording isn't a duplicate. A planning agent was
considered and rejected — the step sequence is fixed, so the graph *is* the plan.

**Memory and context** (`triage/context_session.py`): working memory per ticket (fields, questions, answers, attempts);
`render_context(max_tokens)` gives an LLM a compact summary under a hard budget instead of replaying the transcript;
`record_attempt` / `rejected_chunk_ids` / `render_retry_context` let the Resolver see what was already tried and rejected.

**Tools** (`triage/tools.py`): a registry with an allowlist, per-turn budgets and a call log. `search_kb` (≤ 3/turn) and
`ask_customer` (1/turn, terminal). *Calls are issued by deterministic code, not by an LLM emitting function calls*; the
registry is the seam where that would plug in.

**Communication**: a one-way structured hand-off (`ProblemSignature`), plus one typed callback — `NeedClarification` — that
lets the Resolver ask the Clarifier one more targeted question, counted against the same 3-question budget.

**LangGraph**: `Clarifier.build_graph()` wires the same stages as nodes (a test asserts it behaves identically to the plain
call); `Clarifier.as_node()` is the plug-in point for the integrated graph.

### 6.2 Resolver [Designed]

A conversational loop, not a single-shot answer:

- Retrieves evidence using the normalized signature.
- **Pre-send gates**: a groundedness check (does every claim in the draft trace to retrieved evidence) and a confidence check; if evidence is too weak, escalate rather than send a shaky answer.
- Formats retrieved steps into a customer-facing message (evidence-first), sends it, and waits.
- **Assess-resolution check** — classifies the reply (`resolved | not_resolved | partial | unclear`) with structured LLM extraction, not a keyword heuristic.
- **Retry policy**: up to `max_attempts` (default 3), cheap-to-expensive — retry 1 uses the next-ranked chunk already in the pool; retry 2 re-retrieves with the query augmented by what the customer said didn't work. Rejected chunks are never repeated.
- **Escalation payload**: transcript, extracted fields, signature, every chunk tried, the customer's own words on what didn't work, and the Clarifier's ranked differential.
- **Semantic cache** keyed on `canonical_string`: signature-keyed, hard metadata gate (platform/version), graduated similarity threshold, two tiers (full answer / retrieval-only), populated only from confirmed resolutions. See the open questions in the handbook (§11): `component` is almost always `?`, and `embedding` is `None` unless an embedder is supplied.

### 6.3 Orchestration

A **LangGraph state graph** with fixed nodes and edges: the LLM does content work (extraction, optional question wording,
answer drafting, reply classification) at narrow points while the graph decides branching. A deterministic **router**
(dispatch by product/component; not an LLM) is the extension point for future specialist agents, each implementing one
interface (consume signature + context; emit draft + confidence or `NeedClarification`). Start with two agents; split later.

### 6.4 Shared contracts

All defined in `triage/state.py` (`SCHEMA_VERSION = "1.0.0"`): `ExtractedFields`, `Candidate`, `Hypothesis`,
`ProblemSignature`, `ClarifierResult`, `QuestionPlan`, `NeedClarification`, `TriageRecord` (+ turn/question/attempt
records), with a JSON round-trip and `validate_signature()` for each side's tests.

## 7. Evaluation & Testing [Built for the Clarifier]

- **213 tests** (`python -m pytest`): contracts, extractors, redaction, merging, session compaction under hard token caps,
  reflection rules, clustering for both heading layouts, discriminator ranking, full turns on an offline demo corpus,
  LangGraph ≡ plain call, the simulator, the 06_store rebuild guard and heading-aware BM25 (4), the token-aware chunker (16), the ticket pipeline (15), the two retrievers (17: fusion, ticket ranking, card
  rendering, and both retrievers on the real stores), and 12 tests against the **real** Docker store. Tests that need the
  cached tokenizer, the built store or the ticket CSV skip themselves when absent.
- **Guardrail checks** (`triage/eval/guardrails.py`): vague input must ask for symptoms; prompt-injection text is data; a
  hostile LLM response cannot corrupt fields or run tools; PII never reaches storage; the tool registry enforces its
  allowlist and budgets; an LLM failure degrades to heuristic extraction. Each has a **negative control** — break the
  protection and the check must fail.
- **Offline evaluation** (`python -m triage.eval.clarifier_eval`, ~50 s, free): 29 labeled scenarios authored from real KB
  entries, replayed through a simulated customer. Latest: right issue ranked first **0.85** (17/20), with the default hybrid retriever: READY precision **1.00**,
  wrong-READY **0.00**, out-of-scope false-READY **0/6**, mean **1.52** questions (vector-only: 0.94 / 0.05 / 1.45), 0 redundant/duplicate questions.
  Report: [`reports/clarifier_eval_report.md`](../reports/clarifier_eval_report.md).
- **Read these numbers with care**: 29 scenarios; labels, hidden facts and wording share one author; the simulated customer
  answers menus perfectly; the retriever was vector-only. Thresholds come from a sweep over this same small set.

## 8. Considered and Rejected: GraphRAG

Evaluated whether GraphRAG (LLM-extracted entity graph + community summaries for "global sensemaking") should replace or
augment retrieval. **Not adopted for Tier 1**: it solves corpus-wide synthesis, whereas triage needs entity-specific lookup,
and the observed failure mode is *disambiguation between near-duplicate articles* (the two HTTP-429 entries; six SSO error
entries), which reranking, metadata weighting and the Clarifier's differential already target. It would require an LLM pass over
every chunk plus new graph infrastructure. **Could fit later** for Tier-2 trend analysis ("top recurring issues this month").

## 9. Roadmap

| Milestone | Status |
|---|---|
| M1–M5: Data pipeline (filter → clean → chunk → metadata) on Docker | Built |
| M6: Storage (BM25 + Chroma, 11,440 chunks), query understanding | Built (understanding in `triage/`) |
| Hybrid KB retrieval (`HybridKBRetriever`) | **Built**, default for the Clarifier; evaluated through the Clarifier eval only |
| Docker retrieval benchmark (Recall@k, `08_evaluate.py`) | Not adapted; no direct retrieval benchmark on Docker |
| M8a: Clarifier (extraction, differential diagnosis, reflection, session memory, tools) | **Built, verified** |
| M8b: Resolver (grounded generation, groundedness + confidence gates, retry, escalation) | Designed |
| M7: Semantic cache keyed on the problem signature | Designed |
| Router + integrated LangGraph; end-to-end simulated-customer evaluation | Not started |
| Tier 2: ticket store (clean, embed, docstore, BM25) | **Built** (`scripts/10_tickets.py`, 13,092 tickets) |
| Tier 2: ticket retriever (`TicketRetriever`) | **Built**, spot-checked only |
| KB+ticket routing, ticket use by the Resolver | Designed (§2), not built |
| Self-improving loop (promote confirmed fixes, grow eval set) | Designed |
| Human-in-the-loop review / feedback flagging | Designed |
| Version-notes feed, live status/incident feed, book-derived content | Brainstormed only — **not** in the design |

## 10. Configuration Reference

All configuration lives in `.env` (see [.env.example](../.env.example)); no model, provider or path is hardcoded in the
pipeline scripts. Agent-layer thresholds live in `triage/config.py::ClarifierConfig`.

| Variable | Default | Used by |
|---|---|---|
| `EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | 06, 07, `triage/` |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 07 |
| `VECTOR_DB_PATH` | `data/processed/docker/store/vector` | 06, 07, `triage/` |
| `BM25_PATH` | `data/processed/docker/store/bm25` | 06, 07 |
| `TAXONOMY_PATH` | `data/processed/docker/taxonomy.json` | `triage/` (optional) |
| `EMBEDDING_BATCH_SIZE` | `64` | 06 |
| `LLM_PROVIDER` / `LLM_MODEL` | `gemini` / `gemini-3.5-flash-lite` | 09, `triage/` |
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | — | set only the one matching `LLM_PROVIDER`; never commit `.env` |

## 11. Known gaps

- `docs/customer_support_rag_overview.pptx` predates the Docker pivot and the agent layer; it is not updated.
- Scripts 01, 07, 08 are not adapted to Docker (§3, §4.1). 09 is superseded.
- No live LLM run, no hybrid-retriever run, no Tier-2 integration, no Docker retrieval benchmark.
- `TicketRetriever` exists but no router or Resolver calls it yet. Ticket retrieval quality is unmeasured beyond unit tests and spot checks. The CSV's `error_strings` column is noisy (prose fragments, quoted paths/commands); `10_tickets.py` filters it
  down to ~3.2k tickets with real error lines.
- Clarifier: the rare-term check (§6.1) is lexical, so a customer's paraphrase of what the docs call something else can cost one extra question (S06); its 0.7 threshold is not calibrated on a large set.
- Clarifier thresholds are from a small same-author sweep and should be re-calibrated when the retriever changes.
