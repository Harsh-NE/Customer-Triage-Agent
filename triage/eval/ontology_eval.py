"""
ontology_eval.py -- does the ontology help retrieval find the right documented issue?

For every query the retriever returns candidate chunks (as the Clarifier sees them); chunks are grouped into KB issues, best
score first, and we record the rank of the first issue that matches a gold issue. Compared across ontology modes:
off | expand (alias terms in the BM25 query) | entities (extra ranked list from shared entities / known issues) | both.

Two query sets: `paraphrases.jsonl`, 42 customer-style queries written in DIFFERENT words from the docs (nicknames, aliases, error
strings), and the 20 gold scenarios of the Clarifier evaluation as a regression check. Both were written by the same author as the
ontology, so treat gains as an upper bound, and read losses as real.

    python -m triage.eval.ontology_eval                # writes reports/ontology_eval.{json,md}
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from triage.hybrid import HybridKBRetriever
from triage.issues import issue_key, issue_title
from triage.ontology.model import norm_title
from triage.sim.customer import load_scenarios

HERE = Path(__file__).resolve().parent
REPORT_DIR = HERE.parents[1] / "reports"
MODES = ("off", "expand", "entities", "both")
KS = (1, 3, 8)


def matches(candidate, gold: dict) -> bool:
    return gold["path"] in candidate.source_path and norm_title(gold["issue"]) in norm_title(issue_title(candidate))


def issue_rank(candidates, golds: list[dict]):
    """1-based rank of the first matching issue among the issues in score order, or None."""
    seen: list[str] = []
    for c in sorted(candidates, key=lambda c: -c.score):
        key = issue_key(c)
        if key not in seen:
            seen.append(key)
        if any(matches(c, g) for g in golds):
            return seen.index(key) + 1 if key in seen else None
    return None


def load_items() -> dict[str, list[dict]]:
    para = [json.loads(l) for l in (HERE / "paraphrases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    scen = [{"id": s.id, "query": s.opening, "gold": [{"path": s.gold["source_path_contains"], "issue": s.gold["issue_contains"]}]}
            for s in load_scenarios() if s.gold]
    return {"paraphrases": para, "scenario_openings": scen}


def evaluate(retriever, items: list[dict]) -> tuple[dict, dict[str, int | None]]:
    ranks = {it["id"]: issue_rank(retriever.search(it["query"], top_k=8), it["gold"]) for it in items}
    n = len(items)
    metrics = {f"recall@{k}": round(sum(1 for r in ranks.values() if r is not None and r <= k) / n, 3) for k in KS}
    metrics["mrr"] = round(sum(1 / r for r in ranks.values() if r) / n, 3)
    metrics["n"] = n
    return metrics, ranks


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare retrieval with and without the ontology.")
    ap.add_argument("--modes", nargs="*", default=list(MODES))
    ap.add_argument("--out-json", type=Path, default=REPORT_DIR / "ontology_eval.json")
    ap.add_argument("--out-md", type=Path, default=REPORT_DIR / "ontology_eval.md")
    args = ap.parse_args()

    sets = load_items()
    results: dict = {}
    per_query: dict = {name: {} for name in sets}
    base = HybridKBRetriever(ontology_mode="off")
    model = None
    for mode in args.modes:
        r = HybridKBRetriever(ontology_mode=mode, model=model) if model else base if mode == "off" else HybridKBRetriever(ontology_mode=mode)
        r._ensure()
        model = r._model                                  # one embedding model for every configuration
        results[mode] = {}
        for name, items in sets.items():
            metrics, ranks = evaluate(r, items)
            results[mode][name] = metrics
            per_query[name][mode] = ranks
        print(mode, {n: results[mode][n] for n in sets})

    lines = ["# Ontology ablation: does it help retrieval find the documented issue?", "",
             f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python -m triage.eval.ontology_eval`. Real KB, hybrid retriever, rank = position of the "
             "first correct issue among the issues returned (8 chunks plus siblings). Queries and ontology share an author: gains are an upper bound._", ""]
    for name, items in sets.items():
        lines += [f"## {name} (n={len(items)})", "", "| mode | recall@1 | recall@3 | recall@8 | MRR |", "|---|---|---|---|---|"]
        for mode in args.modes:
            m = results[mode][name]
            lines.append(f"| {mode} | {m['recall@1']} | {m['recall@3']} | {m['recall@8']} | {m['mrr']} |")
        if "off" in args.modes:
            for mode in [m for m in args.modes if m != "off"]:
                better = [(i, per_query[name]["off"][i], per_query[name][mode][i]) for i in per_query[name]["off"]
                          if (per_query[name][mode][i] or 99) < (per_query[name]["off"][i] or 99)]
                worse = [(i, per_query[name]["off"][i], per_query[name][mode][i]) for i in per_query[name]["off"]
                         if (per_query[name][mode][i] or 99) > (per_query[name]["off"][i] or 99)]
                lines += ["", f"`{mode}` vs `off`: improved {len(better)}, worsened {len(worse)}."
                          + (" Improved: " + ", ".join(f"{i} ({a}->{b})" for i, a, b in better) if better else "")
                          + (" Worsened: " + ", ".join(f"{i} ({a}->{b})" for i, a, b in worse) if worse else "")]
        lines.append("")
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args.out_json.write_text(json.dumps({"results": results, "ranks": per_query}, indent=2), encoding="utf-8")
    print(f"report: {args.out_md}")


if __name__ == "__main__":
    main()
