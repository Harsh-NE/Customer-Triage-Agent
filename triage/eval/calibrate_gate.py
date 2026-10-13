"""
calibrate_gate.py -- choose the confidence gate's thresholds from end-to-end results, and say how much the data can support.

The gate (triage/resolver/gate.py) decides, from the retrieved KB evidence and the signature, whether the Resolver may draft a
fix ("strong") or must go to tickets / an engineer. e2e_eval records exactly what the gate saw for every scenario, so any
GateConfig can be replayed offline: no LLM, no retrieval, seconds.

For each scenario that reached the gate, the question is: if the gate had let it through, would the TOP evidence have been the
documented fix? That gives, per config:
  correct_answers   gate strong AND top evidence is the gold issue
  wrong_answers     gate strong AND it is not (including out-of-scope scenarios, which have no right answer)
  coverage          correct_answers / scenarios with a gold fix
  wrong_rate        wrong_answers / answered, with a Wilson 95% upper bound (what zero observed errors can actually promise)

Selection: among ROBUST configs (still <= --max-wrong wrong answers with both thresholds one grid step looser) on the TUNING
file, the most correct answers; ties go to the middle of that plateau (its edge is where the next sample falls off).
With --test, the chosen config and
the current defaults are scored on a SECOND file that was not used for tuning: that, not the tuning score, is the number to trust.
Nothing is written into the Resolver's config; the recommended values are printed for you to adopt.

    python -m triage.eval.calibrate_gate --tune reports/e2e_eval_gemini.json                       # scenarios only
    python -m triage.eval.calibrate_gate --tune reports/e2e_eval_gemini.json reports/e2e_heldout_gemini.json   # pool both
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from dataclasses import replace
from pathlib import Path

from triage.resolver.config import GateConfig
from triage.resolver.contracts import Evidence, ProblemSignature
from triage.resolver.gate import assess

REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"
TOP_GRID = [round(0.30 + 0.05 * i, 2) for i in range(11)]           # 0.30 .. 0.80
CONF_GRID = [round(0.40 + 0.05 * i, 2) for i in range(10)]          # 0.40 .. 0.85


def wilson_upper(k: int, n: int, z: float = 1.96) -> float | None:
    """Upper end of the Wilson 95% interval for k errors in n answers. 0 errors in 20 still allows ~16%."""
    if n == 0:
        return None
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(min(1.0, (centre + margin) / (1 + z * z / n)), 3)


def first_kb_gate_input(row: dict) -> dict | None:
    return next((g for g in row.get("gate_inputs") or [] if g["tier"] == "kb" and g["evidence"]), None)


def gate_result(gate_input: dict, cfg: GateConfig):
    """Run the real gate on a recorded input."""
    ev = [Evidence(evidence_id=e["evidence_id"], chunk_id=e["evidence_id"], doc_id=e["doc_id"], tier=e["tier"], text="", url="",
                   rerank_score=e["rerank_score"], metadata={"component": e["component"], "topics": e["topics"]})
          for e in gate_input["evidence"]]
    sig = ProblemSignature(raw_query="", completeness=gate_input["completeness"],
                           clarifier={"p_top": gate_input["p_top"]} if gate_input["p_top"] is not None else {})
    return assess(ev, sig, cfg)


def replay(gate_input: dict, cfg: GateConfig) -> bool:
    """Would the gate have called this strong?"""
    return gate_result(gate_input, cfg).strong


def score(rows: list[dict], cfg: GateConfig) -> dict:
    gold_rows = [r for r in rows if r["has_gold"]]
    correct = wrong = other = 0
    for r in rows:
        g = first_kb_gate_input(r)
        if g is None or not replay(g, cfg):
            continue
        if r["has_gold"]:
            correct += bool(g["evidence"][0].get("gold"))
            wrong += not g["evidence"][0].get("gold")
        elif r["oos"] or r.get("kb_gap"):
            wrong += 1                                    # the KB has no answer to this: a fix drawn from it is wrong
        else:
            other += 1                                    # no label either way: reported, not counted as right or wrong
    answered = correct + wrong
    return {"correct_answers": correct, "wrong_answers": wrong, "answered_unlabelled": other,
            "coverage": round(correct / len(gold_rows), 3) if gold_rows else None,
            "wrong_rate": round(wrong / answered, 3) if answered else None, "wrong_rate_upper95": wilson_upper(wrong, answered),
            "n_gold": len(gold_rows), "n_no_kb_answer": sum(bool(r["oos"] or r.get("kb_gap")) for r in rows)}


def grid(base: GateConfig):
    for top, conf in itertools.product(TOP_GRID, CONF_GRID):
        yield replace(base, min_top_score=top, resolve_confidence=conf)


def choose(rows: list[dict], base: GateConfig, max_wrong: int = 0) -> tuple[GateConfig, dict]:
    """A config is only eligible if it is ROBUST: it still has <= max_wrong wrong answers when both thresholds are one grid
    step looser. A config that is safe only because it sits exactly on the last wrong answer is a fit to this sample."""
    step_top, step_conf = TOP_GRID[1] - TOP_GRID[0], CONF_GRID[1] - CONF_GRID[0]
    scored = [(cfg, score(rows, cfg)) for cfg in grid(base)]
    robust = [(c, s) for c, s in scored if s["wrong_answers"] <= max_wrong
              and score(rows, replace(c, min_top_score=c.min_top_score - step_top, resolve_confidence=c.resolve_confidence - step_conf))["wrong_answers"] <= max_wrong]
    ok = robust or [(c, s) for c, s in scored if s["wrong_answers"] <= max_wrong]
    if not ok:                                            # nothing is safe enough: take the fewest wrong answers, most conservative
        ok = [min(scored, key=lambda cs: (cs[1]["wrong_answers"], -cs[0].min_top_score, -cs[0].resolve_confidence))]
    best = max(s["correct_answers"] for _, s in ok)
    tied = [(c, s) for c, s in ok if s["correct_answers"] == best]
    tied.sort(key=lambda cs: (cs[0].min_top_score + cs[0].resolve_confidence, cs[0].min_top_score, cs[0].resolve_confidence))
    return tied[len(tied) // 2]                           # the middle of the plateau: the edge is where the next sample falls off


def separation(rows: list[dict], base: GateConfig) -> dict:
    """The gate's confidence for the top-1 evidence when it was right vs wrong. With little data this tells more than a threshold."""
    right, wrong = [], []
    for r in rows:
        g = first_kb_gate_input(r)
        if g is None or not (r["has_gold"] or r["oos"] or r.get("kb_gap")):
            continue
        res = gate_result(g, base)
        (right if r["has_gold"] and g["evidence"][0].get("gold") else wrong).append(round(res.confidence, 3))
    auc = None
    if right and wrong:
        auc = round(sum((a > b) + 0.5 * (a == b) for a in right for b in wrong) / (len(right) * len(wrong)), 3)
    return {"confidence_when_right": sorted(right), "confidence_when_wrong": sorted(wrong), "auc": auc}


def cfg_summary(cfg: GateConfig) -> dict:
    return {"min_top_score": cfg.min_top_score, "resolve_confidence": cfg.resolve_confidence}


def main() -> None:
    ap = argparse.ArgumentParser(description="Calibrate the confidence gate on e2e_eval results.")
    ap.add_argument("--tune", type=Path, nargs="+", required=True, help="e2e_eval JSON file(s) used to choose thresholds (rows are pooled)")
    ap.add_argument("--test", type=Path, default=None, help="a different e2e_eval JSON used only to check them")
    ap.add_argument("--max-wrong", type=int, default=0, help="wrong answers allowed on the tuning file (default 0)")
    ap.add_argument("--out", type=Path, default=REPORT_DIR / "gate_calibration.json")
    args = ap.parse_args()

    tune_rows = [r for f in args.tune for r in json.loads(f.read_text(encoding="utf-8"))["rows"]]
    if not any(r.get("gate_inputs") for r in tune_rows):
        raise SystemExit("no gate_inputs in that report; re-run triage.eval.e2e_eval (this version records them)")
    base = GateConfig()
    chosen, chosen_tune = choose(tune_rows, base, args.max_wrong)
    report = {"defaults": cfg_summary(base), "recommended": cfg_summary(chosen),
              "tune": {"files": [str(f) for f in args.tune], "defaults": score(tune_rows, base), "recommended": chosen_tune,
                       "separation": separation(tune_rows, base)}}
    if args.test:
        test_rows = json.loads(args.test.read_text(encoding="utf-8"))["rows"]
        report["test"] = {"file": str(args.test), "defaults": score(test_rows, base), "recommended": score(test_rows, chosen),
                          "separation": separation(test_rows, base)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nto adopt: put {{\"gate\": {json.dumps(cfg_summary(chosen))}}} in a JSON file and set RESOLVER_CONFIG to its path "
          f"(only if the test numbers hold up). report: {args.out}")


if __name__ == "__main__":
    main()
