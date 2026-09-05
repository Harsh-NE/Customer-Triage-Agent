# Customer-Triage-Agent

An intelligent customer support triage and resolution assistant, built around a curated
knowledge base, hybrid retrieval, and (in progress) LLM-based query understanding and
agentic resolution. Given a technical support query, understand it, retrieve grounded evidence from a knowledge base, attempt a resolution conversationally, and escalate to a human engineer when automated resolution isn't possible.

## Architecture

The system is designed around a two-tier knowledge model:

- **Tier 1 — Curated Knowledge Base** (built): official product troubleshooting
  documentation, processed into a hybrid-searchable index. See
  [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) for the specific open-source corpus used,
  its licence, and sourcing rationale.
- **Tier 2 — Historical Resolved Tickets** (not yet started): deferred until a real ticket
  dataset is available; will be added via a summarization agent.

Retrieval combines **BM25 (sparse)** and **dense vector search**, fused with **Reciprocal
Rank Fusion**, softly boosted by metadata consensus, and reranked with a **cross-encoder** —
see [docs/customer_support_rag_overview.pptx](docs/customer_support_rag_overview.pptx) for
the full write-up of goals, workflow, and theory, and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full architecture document
(built pipeline, retrieval design, evaluation results, and the designed-but-not-yet-built
agent layer).

## Pipeline

Each stage reads the previous stage's output and writes only to `data/processed/`.
`data/raw/` is never modified.

| # | Script | Purpose |
|---|--------|---------|
| 01 | `scripts/01_profile.py` | Profiles the raw corpus (file counts, structure, front matter) |
| 02 | `scripts/02_filter.py` | Builds an inclusion/exclusion manifest (drops templates, stubs, landing pages) |
| 03 | `scripts/03_clean.py` | Cleans Markdown, resolves `[!INCLUDE]` directives, normalizes callouts |
| 04 | `scripts/04_chunk.py` | Hierarchical chunking (Article → Section → Subsection → Chunk) |
| 05 | `scripts/05_metadata.py` | Enriches chunks with `product_area`, `category`, `kb_number`, error codes, etc. |
| 06 | `scripts/06_store.py` | Builds the BM25 index and the Chroma vector store |
| 07 | `scripts/07_retrieve.py` | Hybrid retrieval: BM25 + vector, RRF fusion, metadata boosting, cross-encoder rerank |
| 08 | `scripts/08_evaluate.py` | Recall@5 / Recall@10 benchmark over a hand-built query set |
| 09 | `scripts/09_understand.py` | LLM-based query understanding, missing-context detection, problem-signature normalization |

Run them in order from the project root:

```bash
python scripts/01_profile.py
python scripts/02_filter.py
python scripts/03_clean.py
python scripts/04_chunk.py
python scripts/05_metadata.py
python scripts/06_store.py
python scripts/07_retrieve.py
python scripts/08_evaluate.py
python scripts/09_understand.py --query "your test query here"
```

## Setup

```bash
python -m venv csvenv
csvenv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env           # then fill in the values you need
```

`requirements.txt` installs the core pipeline dependencies plus `google-genai` (the
default LLM provider for `09_understand.py`). If you switch `LLM_PROVIDER` in `.env` to
`anthropic` or `openai`, uncomment the matching line in `requirements.txt` and reinstall.

### Environment variables (`.env`)

See [.env.example](.env.example) for the full, commented list. Key ones:

- `EMBEDDING_MODEL`, `RERANKER_MODEL` — local sentence-transformers models, no API key needed
- `VECTOR_DB_PATH`, `BM25_PATH` — where the indexes are written (under `data/processed/store/`)
- `LLM_PROVIDER`, `LLM_MODEL` — which LLM backs `09_understand.py` (`gemini` | `anthropic` | `openai`)
- `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — set only the one matching `LLM_PROVIDER`

**Never commit `.env`** — it's already excluded via `.gitignore`. Only `.env.example`
(with empty key values) is tracked.

## Data

`data/raw/` and `data/processed/` are excluded from version control (large, and fully
regenerable by running the pipeline above against the raw corpus). To reproduce:

1. Clone the source corpus into `data/raw/MicrosoftDocs-SupportArticles/` — see
   [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) for the exact source and license (CC-BY-4.0).
2. Run the pipeline scripts in order (above).

## Status

Milestones M1–M6 (data pipeline through query understanding/normalization) are implemented.
Caching (M7), grounded generation + agent orchestration (M8), and confidence-gated
escalation (M9) are not yet started. See the roadmap slide in
[docs/customer_support_rag_overview.pptx](docs/customer_support_rag_overview.pptx).
