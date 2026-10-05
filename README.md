# Customer-Triage-Agent

An evidence-first customer-support triage assistant for **Docker**. Given a customer's free-text problem, it asks only
the clarifying questions that actually separate the possible causes, finds grounded evidence in a curated knowledge base,
and (by design) attempts a resolution conversationally and escalates to a human when it cannot.

Two principles: **evidence-first, never fabricated** (answers trace to retrieved documentation; weak evidence escalates
instead of guessing) and **soft signals, never hard filters** (metadata re-weights candidates, it never excludes them).

## Status at a glance

| Area | State |
|---|---|
| Tier 1 knowledge base (`docker/docs`) — pipeline + vector/BM25 store | **Built**: 961 docs → 10,031 chunks |
| Clarifier agent (understanding, differential diagnosis, session memory, reflection, tools) | **Built, verified**: 152 tests, offline evaluation |
| Hybrid retrieval (BM25 + vector + RRF + rerank) | Built for the earlier corpus; **not yet adapted/run on Docker** |
| Resolver agent, semantic cache, escalation, router, integrated graph | Designed, not built |
| Tier 2 historical tickets (13,899 rows) | **Dataset only** — no code uses it yet |
| Live LLM runs | **Never executed** — everything verified so far is offline/free |

Numbers from the offline Clarifier evaluation (29 scenarios, vector-only retriever; small and same-author, so optimistic):
right issue ranked first **0.85**, confident-and-correct **0.94**, out-of-scope questions answered confidently **0 of 6**,
mean **1.34** questions per ticket. See [reports/clarifier_eval_report.md](reports/clarifier_eval_report.md) and its caveats.

## How it works

```
customer message → Clarifier ──READY / UNRESOLVED──▶ Resolver (designed) → answer, or escalate with context
                       ▲  │ ASK                          │
                       └──┘ reply            NeedClarification (shared question budget)
```

The Clarifier retrieves candidate causes, groups them into one hypothesis per KB issue, and either declares one cause
clearly ahead (and grounded in the customer's own words) or asks the single question that would eliminate the most
competing causes — a platform, the exact error text, or "which of these sounds like yours". An LLM is used for one thing by
default (field extraction); everything else is deterministic and auditable. Full detail:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/MEMBER_A_HANDBOOK.md](docs/MEMBER_A_HANDBOOK.md).

## Repository layout

```
scripts/      numbered data pipeline 01–09 (profile → filter → clean → chunk → metadata → store → retrieve → evaluate → understand)
triage/       the agent layer: state (shared contracts), understand, clarifier, differential, session memory, reflection,
              tools, retrieval interface, simulated customer (sim/), evaluation + guardrails (eval/), cli
tests/        152 tests (140 offline + 12 against the real store, auto-skipped if the store is absent)
notebooks/    Colab notebooks 01–09 that build the Tier 2 ticket dataset
reports/      generated evaluation report
docs/         ARCHITECTURE, MEMBER_A_HANDBOOK, DOCKER_KB_BUILD, DATA_SOURCES, DATASET_QUALITY_REPORT
data/         git-ignored: raw/ and processed/ (regenerable)
```

## Setup

```bash
python -m venv csvenv
csvenv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env           # then fill in only what you need
```

`requirements.txt` covers the pipeline, LangGraph, pytest, and `google-genai` (the default LLM provider). To use
`anthropic` or `openai`, set `LLM_PROVIDER` in `.env`, uncomment the matching line in `requirements.txt` and reinstall.

## Quick start

**1. Build the knowledge base** (about an hour of CPU for the embedding step; or run it on EC2 — see
[docs/DOCKER_KB_BUILD.md](docs/DOCKER_KB_BUILD.md)):

```bash
git clone --depth 1 https://github.com/docker/docs.git data/raw/docker-docs
python scripts/02_filter.py
python scripts/03_clean.py
python scripts/04_chunk.py
python scripts/05_metadata.py
python scripts/06_store.py
```

**2. Test and try the Clarifier** (free: heuristic extraction, no API key):

```bash
python -m pytest                                   # add `-m real_store -s` for only the real-store tests
python -m triage.cli chat -v                       # you play the customer
python -m triage.cli replay --id S02 -v            # replay a labeled scenario with a simulated customer
python -m triage.eval.clarifier_eval               # offline evaluation → reports/
python -m triage.eval.clarifier_eval --sweep       # threshold calibration grid (~2.5 min)
```

Live-LLM variants (`--extractor llm`, `--customer llm`) make API calls and have **never been run** by the authors of this
code; run them yourself and check `extraction_source` in the output for any `heuristic_fallback`.

## The data pipeline

Each stage reads the previous stage's output; `data/raw/` is never modified.

| # | Script | Purpose | Docker status |
|---|--------|---------|---------------|
| 01 | `01_profile.py` | Profile the raw corpus | not adapted (reports `ms.topic`) |
| 02 | `02_filter.py` | Inclusion manifest (allowlist of content dirs; "troubleshooting" from the `tags` front matter) | adapted |
| 03 | `03_clean.py` | Clean Markdown, callouts, links | adapted |
| 04 | `04_chunk.py` | Hierarchical chunking (Article → Section → Subsection → Chunk) | adapted |
| 05 | `05_metadata.py` | `product_area`, `component`, `doc_kind`, `tags`, `error_signals`, `source_url`, `license` | rewritten |
| 06 | `06_store.py` | BM25 index + Chroma vector store (`--metadata-only` refreshes metadata without re-embedding) | adapted |
| 07 | `07_retrieve.py` | Hybrid retrieval: BM25 + vector, RRF, soft metadata boost, cross-encoder rerank | **not yet adapted** — still reads the earlier corpus's chunk file |
| 08 | `08_evaluate.py` | Recall@5/@10 benchmark | **not yet adapted** |
| 09 | `09_understand.py` | Query understanding | **superseded** by `triage/understand.py` |

## Tier 2: historical resolved tickets (not yet used)

`notebooks/01–09` (run in Colab) collect and clean ~13.9k resolved Docker problems from Stack Overflow and other Stack
Exchange sites, GitHub issues, the Docker community forum, official FAQ entries, and two Hugging Face datasets, with
PII masking, trust scoring, de-duplication and topic classification. The corrected output is `docker_tickets_v5_fixed.csv`
(13,899 rows; 655 synthetic rows are flagged). Audit: [docs/DATASET_QUALITY_REPORT.md](docs/DATASET_QUALITY_REPORT.md).
**The files are not in this repository and no code reads them.** Integrating them is the next data task.

## Configuration

See [.env.example](.env.example). Key variables: `EMBEDDING_MODEL`, `RERANKER_MODEL` (local models, no key needed);
`VECTOR_DB_PATH`, `BM25_PATH` (default `data/processed/docker/store/...`); `LLM_PROVIDER`, `LLM_MODEL`; and exactly one of
`GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`. Agent-layer thresholds are in `triage/config.py`.

**Never commit `.env`, `*.pem` or `*.key`** — all are git-ignored. Treat any API key that has been printed into a terminal or
shared transcript as exposed and rotate it.

## Team and ownership

Two-person split by agent, not by layer (plan: Team Workplan v2). **Member A** — understanding and the Clarifier
(this README's agent layer; hand-over document: [docs/MEMBER_A_HANDBOOK.md](docs/MEMBER_A_HANDBOOK.md)). **Member B** —
Tier 1 data, hybrid retrieval, memory/cache, and the Resolver. The contract between them is `triage/state.py`
(`SCHEMA_VERSION`), and the Retriever interface in `triage/retrieval.py`.

## Documentation index

| Document | What it covers |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full architecture, status of each part, known gaps |
| [docs/MEMBER_A_HANDBOOK.md](docs/MEMBER_A_HANDBOOK.md) | Clarifier hand-over: contracts, assumptions, what is and is not verified, integration guide |
| [docs/DOCKER_KB_BUILD.md](docs/DOCKER_KB_BUILD.md) | Building and verifying the Docker KB, including the EC2 batch runbook and pitfalls |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) | Where data comes from, licences (opens with the current Docker sources) |
| [docs/DATASET_QUALITY_REPORT.md](docs/DATASET_QUALITY_REPORT.md) | Audit of the Tier 2 ticket dataset |
| `docs/customer_support_rag_overview.pptx` | Original write-up — **predates the Docker pivot and the agent layer** |

## Known gaps

No live LLM run; no hybrid-retriever run on Docker; Resolver, cache, router and the integrated graph not built; Tier 2
not integrated; the pre-pivot slide deck is out of date; the adapted scripts and `triage/` are not yet committed.
