"""
ticket_freshness_eval.py -- does the opt-in legacy-tooling penalty (TICKET_LEGACY_PENALTY) cut stale advice from ticket results?

There is no labelled set that says which ticket answers which question, so this CANNOT measure whether the tickets returned are
more correct. It measures a proxy that is honest about being one: across all the evaluation questions (29 scenarios, 42 paraphrases and the
65 held-out real questions), among the top five tickets returned,

  stale share     how many depend on tooling Docker has retired (docker-machine, boot2docker, Docker Toolbox, --link, ...) when the customer
                  did not mention it
  median age      of the tickets returned
  top-1 changed   how often the best ticket is a different one with the penalty on (a large number would mean it is not a light touch)

A lower stale share with few top-1 changes and no loss of relevance would justify the penalty; relevance still needs a person (look at the
`changed` examples written to the JSON). Free, offline.

    PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.ticket_freshness_eval
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

from triage.eval.ontology_eval import load_items
from triage.hybrid import LEGACY_TERMS, TicketRetriever
from triage.sim.customer import load_scenarios

HERE = Path(__file__).resolve().parent
REPORT_DIR = HERE.parents[1] / "reports"


def queries() -> list[str]:
    seen, out = set(), []
    for q in [s.opening for s in load_scenarios()] + [i["query"] for i in load_items()["paraphrases"]] + \
             [s.opening for s in load_scenarios(HERE / "heldout_scenarios.jsonl")]:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def stale(hit, query: str) -> bool:
    return not LEGACY_TERMS.search(query) and bool(LEGACY_TERMS.search(f"{hit.title} {hit.problem_excerpt} {hit.resolution}"))


def run(retriever, qs: list[str], penalty: float, k: int = 5) -> list[list]:
    os.environ["TICKET_LEGACY_PENALTY"] = str(penalty)
    try:
        return [retriever.search(q, top_k=k) for q in qs]
    finally:
        os.environ.pop("TICKET_LEGACY_PENALTY", None)


def summarize(qs: list[str], base: list[list], other: list[list]) -> dict:
    def stats(results):
        hits = [(q, h) for q, hs in zip(qs, results) for h in hs]
        return {"results": len(hits), "stale_share": round(sum(stale(h, q) for q, h in hits) / len(hits), 3) if hits else None,
                "median_age_years": round(statistics.median(getattr(h, "age_years", 0) or 0 for _, h in hits), 1) if hits else None}
    changed = [{"query": q[:90], "before": b[0].title[:80], "after": o[0].title[:80]} for q, b, o in zip(qs, base, other) if b and o and b[0].ticket_id != o[0].ticket_id]
    return {"queries": len(qs), "off": stats(base), "penalty_on": stats(other), "top1_changed": len(changed), "changed_examples": changed[:12]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Effect of the legacy-tooling ticket penalty (a proxy; see the docstring).")
    ap.add_argument("--penalty", type=float, default=0.5)
    ap.add_argument("--out", type=Path, default=REPORT_DIR / "regression" / "ticket_freshness_eval.json")
    args = ap.parse_args()
    qs = queries()
    retriever = TicketRetriever()
    started = time.time()
    base, other = run(retriever, qs, 1.0), run(retriever, qs, args.penalty)
    result = {"penalty": args.penalty, **summarize(qs, base, other), "seconds": round(time.time() - started)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "changed_examples"}, indent=1))
    for c in result["changed_examples"][:6]:
        print(f"  Q: {c['query']}\n     before: {c['before']}\n     after:  {c['after']}")


if __name__ == "__main__":
    main()
