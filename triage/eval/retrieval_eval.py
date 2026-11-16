"""
retrieval_eval.py -- the retrieval numbers a paper needs, with intervals, and a small tuning sweep that cannot fool us.

Per question set (issue-level: did the documented KB issue come back, and at what rank):
  Recall@1/3/5/8, MRR, NDCG@1/3/5/8, each with a 95% bootstrap interval (triage/eval/text_metrics.py), and retrieval latency p50/p95.

Question sets (all answerable questions with a gold KB issue):
  paraphrases     42   written by us, one per documented issue (an upper bound: same author as the knowledge graph)
  scenarios       20   openings of the 29 hand-written scenarios that have a gold issue (also optimistic)
  gold_dev        15   real Stack Overflow questions, the dev split of gold v1 (the fair number, but small)
  gold_test        4   the test split; only run with --include-test, and only for the final comparison
  pooled          77   the three tuning sets together; this is what a variant has to beat

WHAT THIS MEASURES. One search on the customer's OPENING message, no Clarifier questions and no answers. The end-to-end figures in the other
reports (for example recall@8 78.9% on 19 real questions) come from the whole flow, which searches 7-9 times with what the customer added, so
they are higher. The two are different quantities; a paper must say which one it reports.

TUNING RULE (fixed before running, so a lucky variant cannot be picked afterwards): a variant is adopted only if, against the baseline, the
paired-bootstrap 95% interval of the mean reciprocal-rank difference on `pooled` excludes zero AND `gold_dev` does not get worse AND the
result is stated with its interval. With 15 real questions few variants can pass; that is the honest outcome, and it is why gold v2 is needed.

    PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.retrieval_eval                    # the baseline report
    PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.retrieval_eval --sweep            # baseline plus the variants below
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from triage.eval import text_metrics as tm
from triage.eval.gold_v1 import DEV, TEST, read_split
from triage.eval.ontology_eval import issue_rank, load_items
from triage.sim.customer import load_scenarios

HERE = Path(__file__).resolve().parent
REPORT_DIR = HERE.parents[1] / "reports"
TUNING_SETS = ("paraphrases", "scenarios", "gold_dev")

# name -> settings applied on top of the shipped defaults. Only knobs that exist in HybridKBRetriever.
BASELINE = {"name": "baseline"}
VARIANTS = [
    {"name": "dense x1.5", "VECTOR_WEIGHT": 1.5}, {"name": "dense x2", "VECTOR_WEIGHT": 2.0},
    {"name": "keyword x1.5", "LEXICAL_WEIGHT": 1.5}, {"name": "keyword x2", "LEXICAL_WEIGHT": 2.0},
    {"name": "rrf k=20", "RRF_K": 20}, {"name": "rrf k=100", "RRF_K": 100},
    {"name": "pool 20", "pool": 20}, {"name": "pool 50", "pool": 50},
    {"name": "no ontology", "mode": "off"}, {"name": "ontology expand only", "mode": "expand"}, {"name": "ontology entities only", "mode": "entities"},
    {"name": "entity list x2", "ENTITY_LIST_WEIGHT": 1.0}, {"name": "known issue x1", "KNOWN_ISSUE_WEIGHT": 1.0}, {"name": "known issue x3", "KNOWN_ISSUE_WEIGHT": 3.0},
]


def _gold_of(row: dict) -> list[dict]:
    return [{"path": row["gold"]["source_path_contains"], "issue": row["gold"]["issue_contains"]}]


def load_sets(include_test: bool = False) -> dict[str, list[dict]]:
    items = load_items()
    sets = {"paraphrases": items["paraphrases"], "scenarios": items["scenario_openings"],
            "gold_dev": [{"id": r["id"], "query": r["opening"], "gold": _gold_of(r)} for r in read_split(DEV) if r.get("gold")]}
    if include_test:
        sets["gold_test"] = [{"id": r["id"], "query": r["opening"], "gold": _gold_of(r)} for r in read_split(TEST) if r.get("gold")]
    return sets


def pooled(sets: dict) -> list[dict]:
    return [dict(item, id=f"{name}:{item['id']}") for name in TUNING_SETS if name in sets for item in sets[name]]


def configure(kb, variant: dict) -> dict:
    """Apply a variant to a loaded retriever; returns what to restore. Class-level weights are set on the instance so nothing leaks."""
    saved = {}
    for key in ("VECTOR_WEIGHT", "LEXICAL_WEIGHT", "RRF_K", "ENTITY_LIST_WEIGHT", "KNOWN_ISSUE_WEIGHT"):
        saved[key] = getattr(kb, key)
        if key in variant:
            setattr(kb, key, variant[key])
    saved["_pool"], saved["_mode"] = kb._pool, kb._mode
    if "pool" in variant:
        kb._pool = variant["pool"]
    if "mode" in variant:
        kb._mode = variant["mode"]
    return saved


def restore(kb, saved: dict) -> None:
    for key, value in saved.items():
        setattr(kb, key, value)


def run_sets(kb, sets: dict[str, list[dict]], prep=None) -> tuple[dict[str, dict], dict[str, list[float]]]:
    """(ranks per set per question id, search milliseconds per set)."""
    ranks: dict[str, dict] = {}
    times: dict[str, list[float]] = {}
    for name, items in sets.items():
        ranks[name], times[name] = {}, []
        for item in items:
            started = time.perf_counter()
            hits = kb.search(prep(item["query"]) if prep else item["query"], top_k=8)
            times[name].append((time.perf_counter() - started) * 1000)
            ranks[name][item["id"]] = issue_rank(hits, item["gold"])
    return ranks, times


def summarize(ranks: dict[str, dict], times: dict[str, list[float]], sets: dict) -> dict:
    out: dict = {}
    pool_ranks = {}
    for name in TUNING_SETS:
        if name in ranks:
            pool_ranks.update({f"{name}:{i}": r for i, r in ranks[name].items()})
    for name, rk in {**ranks, "pooled": pool_ranks}.items():
        row = tm.ranking_report(list(rk.values()))
        t = sorted(times[name]) if name in times else sorted(sum((times[n] for n in TUNING_SETS if n in times), []))
        row["search_ms"] = {"p50": round(t[len(t) // 2]), "p95": round(t[min(len(t) - 1, int(0.95 * len(t)))])} if t else {}
        out[name] = row
    return out


def compare_to_baseline(base_ranks: dict, ranks: dict) -> dict:
    """Paired-bootstrap difference in reciprocal rank (variant minus baseline) on the pooled tuning sets and on gold_dev alone."""
    def rr(r):
        return 1.0 / r if r else 0.0
    out = {}
    for label, names in (("pooled", TUNING_SETS), ("gold_dev", ("gold_dev",))):
        ids = [(n, i) for n in names if n in ranks for i in ranks[n]]
        a = [rr(ranks[n][i]) for n, i in ids]
        b = [rr(base_ranks[n][i]) for n, i in ids]
        res = tm.paired_bootstrap(a, b)
        out[label] = {"mean_rr_diff": round(res["mean_diff"], 4), "ci95": [round(res["ci"][0], 4), round(res["ci"][1], 4)], "n": res["n"],
                      "better": sum(x > y for x, y in zip(a, b)), "worse": sum(x < y for x, y in zip(a, b))}
    out["adopt"] = bool(out["pooled"]["ci95"][0] > 0 and out["gold_dev"]["mean_rr_diff"] >= 0)
    return out


def _fmt(m: dict) -> str:
    return f"{m['value']:.3f} ({m['ci95'][0]:.2f}-{m['ci95'][1]:.2f})"


def write_markdown(path: Path, results: list[dict], title: str) -> None:
    lines = [f"# {title}", "", f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python -m triage.eval.retrieval_eval`. Issue-level ranking of the gold KB issue, k=8, "
             "retrieval only on the opening message, no LLM. Value (95% bootstrap interval over questions)._", ""]
    base = results[0]
    for set_name in [s for s in base["summary"] if s != "pooled"] + ["pooled"]:
        lines += [f"## {set_name} (n={base['summary'][set_name]['n']})", "", "| variant | recall@1 | recall@3 | recall@8 | MRR | NDCG@3 | NDCG@8 | search ms p50 / p95 |", "|---|---|---|---|---|---|---|---|"]
        for res in results:
            s = res["summary"][set_name]
            ms = s.get("search_ms") or {}
            lines.append(f"| {res['name']} | {_fmt(s['recall@1'])} | {_fmt(s['recall@3'])} | {_fmt(s['recall@8'])} | {_fmt(s['mrr'])} | {_fmt(s['ndcg@3'])} | {_fmt(s['ndcg@8'])} | {ms.get('p50', '-')} / {ms.get('p95', '-')} |")
        lines.append("")
    if any("vs_baseline" in r for r in results):
        lines += ["## Variants against the baseline (reciprocal rank, paired)", "", "| variant | pooled diff (95% interval) | better / worse | gold_dev diff | better / worse | adopt? |", "|---|---|---|---|---|---|"]
        for res in results[1:]:
            v = res["vs_baseline"]
            lines.append(f"| {res['name']} | {v['pooled']['mean_rr_diff']:+.3f} ({v['pooled']['ci95'][0]:+.3f} to {v['pooled']['ci95'][1]:+.3f}) | {v['pooled']['better']} / {v['pooled']['worse']} | "
                         f"{v['gold_dev']['mean_rr_diff']:+.3f} | {v['gold_dev']['better']} / {v['gold_dev']['worse']} | {'**yes**' if v['adopt'] else 'no'} |")
        lines += ["", "Adopt rule (fixed before the run): the interval on `pooled` excludes zero on the positive side and `gold_dev` does not get worse."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Retrieval metrics with confidence intervals, and an optional tuning sweep.")
    ap.add_argument("--sweep", action="store_true", help="also run the variants and compare each with the baseline")
    ap.add_argument("--include-test", action="store_true", help="add the gold_test split (final comparison only)")
    ap.add_argument("--prep", choices=("raw", "pipeline"), default="raw", help="pipeline: strip_chatter + condense_logs + 800-character cap before searching")
    ap.add_argument("--out-json", type=Path, default=REPORT_DIR / "regression" / "retrieval_eval.json")
    ap.add_argument("--out-md", type=Path, default=REPORT_DIR / "regression" / "retrieval_eval.md")
    args = ap.parse_args()

    from triage.eval.perturb_eval import pipeline_prep
    from triage.hybrid import HybridKBRetriever
    kb = HybridKBRetriever(rerank_mode="off", kb_filters="")
    kb._ensure()
    sets = load_sets(args.include_test)
    prep = pipeline_prep if args.prep == "pipeline" else None
    results, base_ranks = [], None
    for variant in [BASELINE, *(VARIANTS if args.sweep else [])]:
        saved = configure(kb, variant)
        try:
            kb.entity_index() if kb._mode in ("entities", "both") else None
            ranks, times = run_sets(kb, sets, prep)
        finally:
            restore(kb, saved)
        res = {"name": variant["name"], "settings": {k: v for k, v in variant.items() if k != "name"}, "summary": summarize(ranks, times, sets), "ranks": ranks}
        if base_ranks is None:
            base_ranks = ranks
        else:
            res["vs_baseline"] = compare_to_baseline(base_ranks, ranks)
        results.append(res)
        print(f"{variant['name']:<26} pooled MRR {res['summary']['pooled']['mrr']['value']:.3f}  gold_dev MRR {res['summary']['gold_dev']['mrr']['value']:.3f}", flush=True)
    write_markdown(args.out_md, results, "Retrieval evaluation" + (" (sweep)" if args.sweep else ""))
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps({"prep": args.prep, "results": results}, indent=1), encoding="utf-8")
    print(f"wrote {args.out_md}")


if __name__ == "__main__":
    main()
