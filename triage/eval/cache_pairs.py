"""
cache_pairs.py -- build signature pairs for cache calibration from queries whose correct KB issue is known.

calibrate_cache.py needs pairs of problem signatures labelled "same problem" (should hit the cache) or "different problem"
(must miss). The hand-written fixture has 8. Here the labels come from the gold issues we already have:

  same       two different customer wordings whose gold KB issue is identical (paraphrases + scenario openings + held-out)
  different  wordings with different gold issues (the dangerous ones: similar words, different cause)

Each wording is run through the real Clarifier (heuristic extraction, real KB) to get the signature the Resolver would
actually cache on; a Clarifier that needs more information is answered "I'm not sure" until it gives up, so every query yields a
signature. The queries share authors with the ontology (except the held-out ones), so read the separation as optimistic.

    python -m triage.eval.cache_pairs                      # writes reports/cache_pairs_generated.jsonl
    python -m triage.eval.calibrate_cache --pairs reports/cache_pairs_generated.jsonl --embedder st:BAAI/bge-base-en-v1.5
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

from triage.clarifier import Clarifier
from triage.resolver.handoff import to_resolver_signature
from triage.state import ClarifierStatus

HERE = Path(__file__).resolve().parent
REPORT_DIR = HERE.parents[1] / "reports"


def labelled_queries() -> list[dict]:
    """[{id, query, gold: (path, issue)}] from the paraphrases, the scenarios and (if built) the held-out scenarios."""
    out = []
    for line in (HERE / "paraphrases.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out.append({"id": d["id"], "query": d["query"], "gold": (d["gold"][0]["path"], d["gold"][0]["issue"].lower())})
    for name in ("scenarios.jsonl", "heldout_scenarios.jsonl"):
        path = HERE / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            d = json.loads(line) if line.strip() else None
            if d and d.get("gold"):
                out.append({"id": d["id"], "query": d["opening"],
                            "gold": (d["gold"]["source_path_contains"], d["gold"]["issue_contains"].lower())})
    return out


def signature_for(clarifier: Clarifier, query: str, max_turns: int = 5) -> dict | None:
    session = clarifier.start()
    result = clarifier.turn(session, query)
    for _ in range(max_turns):
        if result.status is not ClarifierStatus.ASK:
            break
        result = clarifier.turn(session, "I'm not sure.")
    if result.signature is None:
        return None
    return to_resolver_signature(result, session).to_dict()


def build_pairs(items: list[dict], sigs: dict[str, dict]) -> list[dict]:
    pairs = []
    for a, b in itertools.combinations([i for i in items if i["id"] in sigs], 2):
        if a["query"] == b["query"]:
            continue
        pairs.append({"a": sigs[a["id"]], "b": sigs[b["id"]], "same": a["gold"] == b["gold"], "ids": [a["id"], b["id"]]})
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate labelled signature pairs for cache calibration.")
    ap.add_argument("--out", type=Path, default=REPORT_DIR / "cache_pairs_generated.jsonl")
    args = ap.parse_args()
    from triage.hybrid import HybridKBRetriever
    clarifier = Clarifier(None, HybridKBRetriever())
    items = labelled_queries()
    sigs = {}
    for it in items:
        sig = signature_for(clarifier, it["query"])
        if sig:
            sigs[it["id"]] = sig
    pairs = build_pairs(items, sigs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(json.dumps(p) for p in pairs) + "\n", encoding="utf-8")
    pos = sum(p["same"] for p in pairs)
    print(f"{len(items)} queries -> {len(sigs)} signatures -> {len(pairs)} pairs ({pos} same, {len(pairs) - pos} different) -> {args.out}")


if __name__ == "__main__":
    main()
