"""
clarifier_eval.py -- A6: evaluate the Clarifier on the labeled scenarios, offline and free by default.

Each scenario is replayed through a simulated customer (see sim/customer.py). Metrics:

  gap detection        precision / recall of HARD gaps on the opening message vs. labels
  extraction           product_area / platform accuracy and error-code recall on the opening
  outcomes             READY / UNRESOLVED / stuck rates, mean questions per ticket
  correctness          gold@1 / gold@3 (is the right KB issue the Clarifier's top hypothesis?),
                       READY precision, wrong-READY rate, out-of-scope false-READY rate
  question quality     deterministic rubric (single question, options present, sane length),
                       redundant-question rate, duplicate-question rate
  cost                 tool calls and (if an LLM is used) LLM calls per ticket
  guardrails           the checks in guardrails.py

Usage:
    python -m triage.eval.clarifier_eval                         # chroma retriever, heuristic extractor, free
    python -m triage.eval.clarifier_eval --retriever keyword     # crude keyword retriever over the real chunks
    python -m triage.eval.clarifier_eval --extractor llm         # uses .env LLM (costs API calls -- you run it)
    python -m triage.eval.clarifier_eval --sweep                 # threshold calibration grid
    python -m triage.eval.clarifier_eval --retriever-factory mypkg.mod:make_retriever   # plug in B's hybrid
"""

from __future__ import annotations

import argparse
import importlib
import itertools
import json
import statistics
import time
from dataclasses import replace
from pathlib import Path

from triage import config
from triage.clarifier import Clarifier
from triage.config import ClarifierConfig
from triage.eval.guardrails import run_guardrail_checks
from triage.retrieval import ChromaRetriever, MockRetriever, Retriever
from triage.sim.customer import LLMCustomer, RuleBasedCustomer, Scenario, load_scenarios
from triage.sim.dialogue import DialogueResult, run_dialogue
from triage.state import Candidate
from triage.understand import detect_gaps, extract, load_known_products

REPORT_DIR = config.PROJECT_ROOT / "reports"


class CachingRetriever:
    """Memoises search() so threshold sweeps don't re-embed identical queries."""

    def __init__(self, inner: Retriever) -> None:
        self._inner = inner
        self._cache: dict[tuple[str, int], list[Candidate]] = {}

    def search(self, query: str, top_k: int = 8) -> list[Candidate]:
        key = (query, top_k)
        if key not in self._cache:
            self._cache[key] = self._inner.search(query, top_k)
        return [replace(c, metadata=dict(c.metadata)) for c in self._cache[key]]


def keyword_retriever() -> MockRetriever:
    """Crude IDF keyword retriever over the REAL Docker chunks -- a deliberately different signal
    from vector search, useful for checking the Clarifier isn't tuned to one retriever's quirks."""
    path = config.PROJECT_ROOT / "data" / "processed" / "docker" / "chunks_metadata.jsonl"
    corpus = []
    for line in path.read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        meta = {k: (", ".join(v) if isinstance(v, list) else v) for k, v in c["metadata"].items()}
        corpus.append({"chunk_id": c["chunk_id"], "text": c["text"], "source_path": c["source_path"],
                       "article_title": c["article_title"], "heading_path": c["heading_path"], "metadata": meta})
    return MockRetriever(corpus)


def build_retriever(name: str, factory: str | None) -> Retriever:
    if factory:
        module, _, attr = factory.partition(":")
        return getattr(importlib.import_module(module), attr)()
    if name == "keyword":
        return keyword_retriever()
    if name == "chroma":
        return ChromaRetriever()
    from triage.hybrid import HybridKBRetriever
    return HybridKBRetriever()


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def run_all(retriever: Retriever, cfg: ClarifierConfig, scenarios: list[Scenario], llm=None,
            style: str = "mixed", customer_llm=None) -> list[DialogueResult]:
    known = load_known_products()
    results = []
    for s in scenarios:
        clarifier = Clarifier(llm, retriever, cfg, known_products=known)
        customer = LLMCustomer(s, customer_llm) if customer_llm else RuleBasedCustomer(s, style=style)
        results.append(run_dialogue(clarifier, customer, s))
    return results


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def question_quality(q: dict) -> dict:
    text = q["text"]
    menu = q["feature"] in ("issue", "error_message")
    lead = " ".join(l for l in text.splitlines() if l.strip() and not l.strip()[:2].rstrip(".").isdigit())
    return {
        "single_question": lead.count("?") <= 1,     # option titles may contain '?', the lead may not repeat it
        "options_present": (len([l for l in text.splitlines() if l.strip()[:2].rstrip(".").isdigit()]) >= 2) if menu else True,
        "length_ok": len(text) <= 600,
    }


def gap_and_extraction_metrics(scenarios: list[Scenario], llm=None) -> dict:
    known = load_known_products()
    tp = fp = fn = 0
    acc = {"product_area": [0, 0], "platform": [0, 0]}
    code_recall = [0, 0]
    for s in scenarios:
        fields = extract(s.opening, llm, known).fields
        predicted = {g.field for g in detect_gaps(fields) if g.hard}
        expected = set(s.expected_hard_gaps)
        tp += len(predicted & expected)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        for key in ("product_area", "platform"):
            if key in s.opening_facts:
                acc[key][1] += 1
                acc[key][0] += getattr(fields, key) == s.opening_facts[key]
        for code in s.opening_facts.get("error_codes", []):
            code_recall[1] += 1
            code_recall[0] += code in fields.error_codes
    return {
        "gap_precision": _rate(tp, tp + fp), "gap_recall": _rate(tp, tp + fn),
        "product_area_accuracy_on_opening": _rate(*acc["product_area"]),
        "platform_accuracy_on_opening": _rate(*acc["platform"]),
        "error_code_recall_on_opening": _rate(*code_recall),
    }


def summarize(results: list[DialogueResult]) -> dict:
    gold = [r for r in results if r.scenario.gold]
    oos = [r for r in results if r.scenario.oos]
    ready = [r for r in gold if r.status == "ready"]
    questions = [q for r in results for q in r.questions]
    quality = [question_quality(q) for q in questions]

    def qrate(key: str) -> float | None:
        return _rate(sum(x[key] for x in quality), len(quality))

    return {
        "scenarios": len(results), "with_gold": len(gold), "out_of_scope": len(oos),
        "ready_rate": _rate(sum(r.status == "ready" for r in results), len(results)),
        "unresolved_rate": _rate(sum(r.status == "unresolved" for r in results), len(results)),
        "stuck_rate": _rate(sum(r.stuck for r in results), len(results)),
        "mean_questions_per_ticket": round(statistics.mean(r.result.questions_asked for r in results), 2),
        "gold_top1": _rate(sum(r.gold_rank == 1 for r in gold), len(gold)),
        "gold_top3": _rate(sum(r.gold_rank is not None for r in gold), len(gold)),
        "ready_precision": _rate(sum(r.gold_rank == 1 for r in ready), len(ready)),
        "wrong_ready_rate": _rate(sum(r.gold_rank != 1 for r in ready), len(gold)),
        "oos_false_ready_rate": _rate(sum(r.status == "ready" for r in oos), len(oos)),
        "redundant_question_rate": _rate(sum(q["redundant"] for q in questions), len(questions)),
        "duplicate_question_rate": _rate(sum(q["duplicate"] for q in questions), len(questions)),
        "question_single_question": qrate("single_question"),
        "question_options_present": qrate("options_present"),
        "question_length_ok": qrate("length_ok"),
        "mean_tool_calls_per_ticket": round(statistics.mean(r.tool_calls for r in results), 2),
    }


def sweep(retriever: Retriever, scenarios: list[Scenario], base: ClarifierConfig, llm=None) -> list[dict]:
    cached = CachingRetriever(retriever)
    rows = []
    for temp, p_top, margin, grounding in itertools.product(
            (0.03, 0.05, 0.08), (0.4, 0.5, 0.6), (0.15, 0.25, 0.35), (0.0, 0.34, 0.5)):
        cfg = replace(base, softmax_temperature=temp, ready_p_top=p_top, ready_margin=margin, min_grounding=grounding)
        results = run_all(cached, cfg, scenarios, llm)
        m = summarize(results)
        oos = [r for r in results if r.scenario.oos]
        rows.append({"temperature": temp, "ready_p_top": p_top, "ready_margin": margin, "min_grounding": grounding,
                     "gold_top1": m["gold_top1"], "ready_precision": m["ready_precision"],
                     "wrong_ready_rate": m["wrong_ready_rate"], "oos_false_ready_rate": m["oos_false_ready_rate"],
                     "mean_questions": m["mean_questions_per_ticket"],
                     "oos_mean_questions": round(statistics.mean(r.result.questions_asked for r in oos), 2) if oos else None,
                     "stuck_rate": m["stuck_rate"]})
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def first_top_score(r: DialogueResult) -> float | None:
    """Best retrieval score the FIRST time retrieval ran for this ticket (None if it never ran)."""
    for res in (r.first_result, r.result):
        if res is None:
            continue
        conf = res.meta.get("confidence") or (res.signature.confidence.__dict__ if res.signature else None)
        if conf and conf.get("top_score"):
            return round(conf["top_score"], 3)
    return None


def _md_table(rows: list[dict], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "|".join("---" for _ in cols) + "|\n"
    return head + "\n".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows)


def write_report(path: Path, meta: dict, gap_metrics: dict, summary: dict, results: list[DialogueResult],
                 guards, sweep_rows: list[dict] | None) -> None:
    per = []
    for r in results:
        top = r.result.signature.hypotheses[0].label if r.result.signature and r.result.signature.hypotheses else "-"
        per.append({"id": r.scenario.id, "opening": r.scenario.opening[:50], "status": r.status,
                    "q": r.result.questions_asked, "gold_rank": r.gold_rank if r.scenario.gold else "n/a",
                    "first_top_score": first_top_score(r), "top hypothesis": top[:55]})
    lines = [
        "# Clarifier evaluation report", "",
        f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python -m triage.eval.clarifier_eval`._", "",
        "## Run configuration", "", "```json", json.dumps(meta, indent=2), "```", "",
        "## Caveats (read before trusting any number)", "",
        f"- **{summary['scenarios']} scenarios, {summary['with_gold']} with gold labels.** Differences of one scenario are "
        f"{round(100 / max(summary['with_gold'], 1))} percentage points of gold@1. This is a smoke-level signal, not a benchmark.",
        "- Gold labels and the simulated customer's hidden facts were written by the same author, from the same KB pages: "
        "optimistic by construction, and the rule-based customer answers menus perfectly.",
        "- The retriever here is **vector-only** (or crude keyword). Member B's hybrid retriever should be plugged in via "
        "`--retriever-factory` and this report regenerated; thresholds were tuned against whatever retriever ran.",
        "", "## Gap detection and extraction (opening message only)", "", _md_table([gap_metrics], list(gap_metrics)), "",
        "## Dialogue outcomes", "", _md_table([summary], list(summary)), "",
        "## Per-scenario", "", _md_table(per, ["id", "opening", "status", "q", "gold_rank", "first_top_score", "top hypothesis"]), "",
        "## Guardrails", "", _md_table([{"check": g.name, "result": "PASS" if g.passed else "**FAIL**", "detail": g.detail}
                                         for g in guards], ["check", "result", "detail"]), ""]
    if sweep_rows:
        ranked = sorted(sweep_rows, key=lambda r: (-(r["ready_precision"] or 0), r["wrong_ready_rate"] or 1,
                                                    r["oos_false_ready_rate"] or 1, r["mean_questions"]))
        lines += ["## Threshold sweep (best 10 by READY precision, then wrong-READY, then questions)", "",
                  _md_table(ranked[:10], list(ranked[0])), "",
                  "Default config values were chosen from this table, preferring a setting that is "
                  "robust to its neighbours over the single highest cell (with ~20 gold scenarios, the top cell is noise).", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate the Clarifier on labeled scenarios.")
    ap.add_argument("--retriever", choices=["hybrid", "chroma", "keyword"], default="hybrid")
    ap.add_argument("--retriever-factory", default=None, help="module:function returning a Retriever (e.g. Member B's)")
    ap.add_argument("--extractor", choices=["heuristic", "llm"], default="heuristic")
    ap.add_argument("--customer", choices=["rule", "llm"], default="rule")
    ap.add_argument("--style", choices=["mixed", "number", "text"], default="mixed")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--out-json", type=Path, default=REPORT_DIR / "clarifier_eval.json")
    ap.add_argument("--out-md", type=Path, default=REPORT_DIR / "clarifier_eval_report.md")
    args = ap.parse_args()

    from triage.llm import ProviderLLM
    llm = ProviderLLM() if args.extractor == "llm" else None
    customer_llm = llm if args.customer == "llm" else None
    scenarios = load_scenarios()
    retriever = CachingRetriever(build_retriever(args.retriever, args.retriever_factory))
    cfg = ClarifierConfig()

    started = time.time()
    results = run_all(retriever, cfg, scenarios, llm, args.style, customer_llm)
    summary = summarize(results)
    gap_metrics = gap_and_extraction_metrics(scenarios, llm)
    guards = run_guardrail_checks(lambda l=None: Clarifier(l if l is not None else llm, retriever, cfg))
    sweep_rows = sweep(retriever, scenarios, cfg, llm) if args.sweep else None

    meta = {"retriever": args.retriever_factory or args.retriever, "extractor": args.extractor,
            "customer": args.customer, "style": args.style, "seconds": round(time.time() - started, 1),
            "llm_usage": llm.usage.as_dict() if llm else None,
            "config": {k: v for k, v in cfg.__dict__.items() if not isinstance(v, dict)}}
    write_report(args.out_md, meta, gap_metrics, summary, results, guards, sweep_rows)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps({"meta": meta, "gap_metrics": gap_metrics, "summary": summary,
                                         "sweep": sweep_rows}, indent=2), encoding="utf-8")
    print(json.dumps({"gap_metrics": gap_metrics, "summary": summary}, indent=2))
    print("guardrails:", {g.name: g.passed for g in guards})
    print(f"report: {args.out_md}")


if __name__ == "__main__":
    main()
