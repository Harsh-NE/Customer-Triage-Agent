"""
rerank_eval.py -- does a cross-encoder rerank of the KB retriever's candidates help, and what does it cost?

The same retriever is run with the rerank off and in several variants (triage/rerank.py: "order" keeps the calibrated score scale,
"blend" mixes similarity and cross-encoder relevance; the pool is how many fused candidates the cross-encoder re-reads). Per variant:

  ranking      issue-level Recall@1/3/8 and MRR of the gold issue, as in ontology_eval, on three labelled sets:
               42 paraphrases and 20 scenario openings (same author as the ontology: an upper bound) and the 13 held-out real questions
               (draft labels, 7 reviewer-confirmed; see reports/regression/heldout_gold_review.md). Queries improved / worsened vs off.
  separation   how well the retriever's top score tells answerable from unanswerable queries (AUC, 0.5 = no better than chance):
               20 gold vs 9 no-gold scenarios, 13 gold vs 52 "KB gap" held-out questions. This is what the confidence gate relies on.
  cost         wall time per search with the cross-encoder cache cleared before each one (the Clarifier searches 7-9 times per ticket).

Retrieval only: no drafting model, no paid calls. What it cannot say: whether the Clarifier and the gate do better with the new scores
(run the end-to-end evaluation with RERANK set for that), and anything about quality beyond these small sets.

    PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python -m triage.eval.rerank_eval
    python -m triage.eval.rerank_eval --variants off blend0.5@20 --limit 10          # a quick look
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from triage.eval.ontology_eval import issue_rank, load_items
from triage.hybrid import HybridKBRetriever
from triage.sim.customer import load_scenarios

HERE = Path(__file__).resolve().parent
REPORT_DIR = HERE.parents[1] / "reports"
KS = (1, 3, 8)
# name, mode, pool, blend
VARIANTS = [("off", "off", None, None),
            ("order@20", "order", 20, None),
            ("blend0.3@20", "blend", 20, 0.3), ("blend0.5@20", "blend", 20, 0.5), ("blend0.7@20", "blend", 20, 0.7),
            ("cross-encoder-only@20", "blend", 20, 1.0),
            ("order@10", "order", 10, None), ("blend0.5@10", "blend", 10, 0.5)]


def gold_of(scenario) -> list[dict]:
    return [{"path": scenario.gold["source_path_contains"], "issue": scenario.gold["issue_contains"]}]


def load_sets() -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """(answerable sets with gold issues, unanswerable sets). Each item: {id, query, gold?, tag?}."""
    scen = load_scenarios()
    held = load_scenarios(HERE / "heldout_scenarios.jsonl")
    answerable = {
        "paraphrases": load_items()["paraphrases"],
        "scenario_openings": [{"id": s.id, "query": s.opening, "gold": gold_of(s)} for s in scen if s.gold],
        "heldout_gold": [{"id": s.id, "query": s.opening, "gold": gold_of(s),
                          "tag": "weak" if "weak" in s.note else "confirmed"} for s in held if s.gold]}
    unanswerable = {"scenarios_no_gold": [{"id": s.id, "query": s.opening} for s in scen if not s.gold],
                    "heldout_kb_gap": [{"id": s.id, "query": s.opening} for s in held if not s.gold]}
    return answerable, unanswerable


def auc(positive: list[float], negative: list[float]) -> float | None:
    """P(a random answerable query's top score beats a random unanswerable one's); ties count half."""
    if not positive or not negative:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positive for n in negative)
    return round(wins / (len(positive) * len(negative)), 3)


def run_variant(retriever, answerable: dict, unanswerable: dict, limit: int | None) -> dict:
    out: dict = {"sets": {}, "top": {}}

    def one(item):
        return retriever.search(item["query"], top_k=8)

    for name, items in answerable.items():
        ranks, tops = {}, []
        for item in items[:limit]:
            cands = one(item)
            ranks[item["id"]] = issue_rank(cands, item["gold"])
            tops.append(max((c.score for c in cands), default=0.0))
        out["sets"][name] = ranks
        out["top"][name] = tops
    for name, items in unanswerable.items():
        out["top"][name] = [max((c.score for c in one(item)), default=0.0) for item in items[:limit]]
    return out


def metrics(ranks: dict) -> dict:
    n = len(ranks)
    m = {f"recall@{k}": round(sum(1 for r in ranks.values() if r is not None and r <= k) / n, 3) for k in KS}
    m["mrr"] = round(sum(1 / r for r in ranks.values() if r) / n, 3)
    m["n"] = n
    return m


def subset(ranks: dict, items: list[dict], tag: str) -> dict:
    return {i["id"]: ranks[i["id"]] for i in items if i.get("tag") == tag and i["id"] in ranks}


def compare(base: dict, other: dict) -> tuple[int, int]:
    better = sum((other[i] or 99) < (base[i] or 99) for i in base)
    worse = sum((other[i] or 99) > (base[i] or 99) for i in base)
    return better, worse


LATENCY_CONFIGS = [("off", "off", None, None), ("rerank, pool 20", "blend", 20, 0.5), ("rerank, pool 10", "blend", 10, 0.5)]


def bench_latency(retriever, queries: list[str]) -> dict:
    """Milliseconds per search for each cost configuration. The model is loaded once beforehand, and the pair cache is cleared before
    every timed search so the cross-encoder really reads the passages each time (the sweep above reuses scores between variants)."""
    reranker = retriever._reranker
    retriever.set_rerank("blend", 20, 0.5)
    retriever.search(queries[0], top_k=8)                      # warm-up: loads the model
    out = {}
    for name, mode, pool, blend in LATENCY_CONFIGS:
        retriever.set_rerank(mode, pool, blend)
        times = []
        for q in queries:
            if reranker is not None:
                reranker._cache.clear()
            started = time.perf_counter()
            retriever.search(q, top_k=8)
            times.append((time.perf_counter() - started) * 1000)
        times.sort()
        out[name] = {"mean": round(statistics.mean(times)), "p50": round(times[len(times) // 2]), "p95": round(times[min(len(times) - 1, int(0.95 * len(times)))]), "searches": len(times)}
    return out


def summarize(results: dict, answerable: dict, unanswerable: dict) -> dict:
    base = results["off"]
    report: dict = {}
    for name, res in results.items():
        row: dict = {"ranking": {}, "separation": {}}
        for set_name, ranks in res["sets"].items():
            row["ranking"][set_name] = {**metrics(ranks), "vs_off": dict(zip(("improved", "worsened"), compare(base["sets"][set_name], ranks)))}
        confirmed = subset(res["sets"].get("heldout_gold", {}), answerable["heldout_gold"], "confirmed")
        if confirmed:
            row["ranking"]["heldout_confirmed_only"] = metrics(confirmed)
        top = res["top"]
        row["separation"] = {
            "scenarios_auc": auc(top.get("scenario_openings", []), top.get("scenarios_no_gold", [])),
            "heldout_auc": auc(top.get("heldout_gold", []), top.get("heldout_kb_gap", [])),
            "heldout_median_top_gold": round(statistics.median(top["heldout_gold"]), 3) if top.get("heldout_gold") else None,
            "heldout_median_top_kb_gap": round(statistics.median(top["heldout_kb_gap"]), 3) if top.get("heldout_kb_gap") else None}
        report[name] = row
    return report


def write_markdown(path: Path, report: dict, limit: int | None, latency: dict | None = None, title: str = "Reranker experiment: results",
                   command: str = "python -m triage.eval.rerank_eval", what: str = "cross-encoder `ms-marco-MiniLM-L-6-v2`") -> None:
    lines = [f"# {title}", "",
             f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `{command}`" + (f" (first {limit} items per set only)" if limit else "") + ". "
             f"Real KB, hybrid retriever, {what}. Retrieval only; see the module docstring for what this cannot say._", ""]
    for set_name in ("paraphrases", "scenario_openings", "heldout_gold", "heldout_confirmed_only"):
        first = next(iter(report.values()))["ranking"].get(set_name)
        if not first:
            continue
        lines += [f"## {set_name} (n={first['n']})", "", "| variant | recall@1 | recall@3 | recall@8 | MRR | improved / worsened vs off |", "|---|---|---|---|---|---|"]
        for name, row in report.items():
            m = row["ranking"][set_name]
            vs = m.get("vs_off")
            lines.append(f"| {name} | {m['recall@1']} | {m['recall@3']} | {m['recall@8']} | {m['mrr']} | {'-' if not vs else str(vs['improved']) + ' / ' + str(vs['worsened'])} |")
        lines.append("")
    lines += ["## Does the top score tell answerable from unanswerable? (what the gate relies on)", "",
              "| variant | scenarios AUC (20 vs 9) | held-out AUC (13 vs 52) | held-out median top score: gold / KB-gap |", "|---|---|---|---|"]
    for name, row in report.items():
        s = row["separation"]
        lines.append(f"| {name} | {s['scenarios_auc']} | {s['heldout_auc']} | {s['heldout_median_top_gold']} / {s['heldout_median_top_kb_gap']} |")
    lines += ["", "AUC 0.5 means no better than chance; 1.0 is perfect. The held-out \"KB gap\" labels are unverified drafts."]
    if latency:
        lines += ["", "## Cost per search (CPU, model already loaded, cross-encoder cache cleared before every search)", "",
                  "| configuration | mean ms | p50 ms | p95 ms | searches timed |", "|---|---|---|---|---|"]
        lines += [f"| {n} | {m['mean']} | {m['p50']} | {m['p95']} | {m['searches']} |" for n, m in latency.items()]
        lines += ["", "A ticket makes 7-9 Clarifier searches plus 1-2 Resolver retrievals, so multiply the per-search difference accordingly."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare KB retrieval with and without a cross-encoder rerank.")
    ap.add_argument("--variants", nargs="*", default=None, help="names to run (default all); 'off' is always included")
    ap.add_argument("--limit", type=int, default=None, help="only the first N items of each set (a quick look)")
    ap.add_argument("--out-json", type=Path, default=REPORT_DIR / "regression" / "rerank_eval.json")
    ap.add_argument("--out-md", type=Path, default=REPORT_DIR / "regression" / "rerank_eval.md")
    args = ap.parse_args()

    answerable, unanswerable = load_sets()
    chosen = [v for v in VARIANTS if v[0] == "off" or not args.variants or v[0] in args.variants]
    retriever = HybridKBRetriever(rerank_mode="off")
    retriever._ensure()
    results = {}
    for name, mode, pool, blend in chosen:
        retriever.set_rerank(mode, pool, blend)
        started = time.time()
        results[name] = run_variant(retriever, answerable, unanswerable, args.limit)
        print(f"{name:24} done in {time.time() - started:5.0f}s", flush=True)
    report = summarize(results, answerable, unanswerable)
    sample = [i["query"] for items in answerable.values() for i in items[:args.limit]][::3][:40]
    latency = bench_latency(retriever, sample) if len(chosen) > 1 else None
    write_markdown(args.out_md, report, args.limit, latency)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps({"report": report, "latency": latency, "ranks": {n: r["sets"] for n, r in results.items()}}, indent=1), encoding="utf-8")
    print(args.out_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
