"""
kb_filter_eval.py -- do the opt-in KB clean-ups (triage/hybrid.py `KB_FILTERS`) help retrieval?

  dedupe    of chunks whose text is identical (3% of the KB) only the best-scored one is returned
  archive   previous-version pages (7% of the KB) are dropped unless the query sounds like an old Docker
  notes     release notes (19% of the KB) are dropped unless the query is about a release, update or fix

Same measurements as the reranker experiment (reuses its harness): issue-level Recall@1/3/8 and MRR on the paraphrases, the scenario openings
and the held-out real questions (19 gold after the label review), queries improved / worsened versus no filter, and whether the top score still
separates answerable from unanswerable queries (the held-out 46 KB-gap questions). Retrieval only; free; no paid calls.

A filter is worth keeping only if it does not hurt the held-out set and helps somewhere. n is small, so read "improved / worsened", not the
percentages. None of the filters is on by default.

    PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.kb_filter_eval
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from triage.eval.rerank_eval import REPORT_DIR, load_sets, run_variant, summarize, write_markdown
from triage.hybrid import HybridKBRetriever

VARIANTS = [("off", []), ("dedupe", ["dedupe"]), ("archive", ["archive"]), ("notes", ["notes"]),
            ("dedupe+archive", ["dedupe", "archive"]), ("dedupe+archive+notes", ["dedupe", "archive", "notes"])]


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare KB retrieval with and without the opt-in filters.")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out-json", type=Path, default=REPORT_DIR / "regression" / "kb_filter_eval.json")
    ap.add_argument("--out-md", type=Path, default=REPORT_DIR / "regression" / "kb_filter_eval.md")
    args = ap.parse_args()

    answerable, unanswerable = load_sets()
    retriever = HybridKBRetriever(rerank_mode="off", kb_filters="")
    retriever._ensure()
    results = {}
    for name, filters in VARIANTS:
        retriever.set_filters(filters)
        started = time.time()
        results[name] = run_variant(retriever, answerable, unanswerable, args.limit)
        print(f"{name:22} done in {time.time() - started:4.0f}s", flush=True)
    report = summarize(results, answerable, unanswerable)
    write_markdown(args.out_md, report, args.limit, None, "KB filters: results", "python -m triage.eval.kb_filter_eval", "opt-in filters")
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps({"report": report, "ranks": {n: r["sets"] for n, r in results.items()}}, indent=1), encoding="utf-8")
    print(args.out_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
