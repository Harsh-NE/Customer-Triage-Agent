"""B6 — Resolver evaluation.

Runs every case in an eval JSONL through the Resolver with scripted customer
replies (until A5's simulated customer exists) and reports:

  outcome_accuracy        resolved / escalated / rejected / needs_clarification as expected
  false_resolve_rate      resolved when it should have escalated/rejected  (KEY SAFETY METRIC)
  escalation_precision    of escalations, how many were expected
  escalation_recall       of expected escalations, how many happened
  reason_accuracy         escalation reason code matches (where specified)
  evidence_hit_rate       expected doc among cited evidence (resolved cases)
  citation_validity       share of drafted steps that survived verification
  mean_attempts           fixes tried per ticket

Case format (one JSON per line):
  {"case_id": "C1", "signature": {...} | "<key in signatures.json>",
   "replies": ["still broken", "works now"], "expected_outcome": "resolved",
   "expected_reason": "LOW_EVIDENCE", "expected_doc": "docs/...#1"}

    python -m triage.eval.eval_resolver --cases fixtures/eval_cases.jsonl \
        --signatures fixtures/signatures.json --out reports/resolver_eval.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from langgraph.types import Command

from triage.resolver.graph import ResolverDeps, build_resolver_app


def run_case(app, case: dict[str, Any], signature: dict[str, Any]) -> dict[str, Any]:
    cfg = {"configurable": {"thread_id": case["case_id"]}}
    state = app.invoke({"ticket_id": case["case_id"], "signature": signature, "transcript": []}, cfg)
    replies = list(case.get("replies") or [])
    turns = 0
    while "__interrupt__" in state:
        reply = replies.pop(0) if replies else "it still doesn't work"
        state = app.invoke(Command(resume=reply), cfg)
        turns += 1
        if turns > 10:
            break
    return {**app.get_state(cfg).values, "_turns": turns}


def evaluate(deps: ResolverDeps, cases: list[dict[str, Any]],
             signatures: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    signatures = signatures or {}
    app = build_resolver_app(deps)
    rows = []
    for case in cases:
        sig = case["signature"]
        sig = signatures[sig] if isinstance(sig, str) else sig
        n_events = len(deps.logger.events)
        final = run_case(app, case, sig)
        verify_events = [e for e in deps.logger.events[n_events:] if e["event"] == "verify"]
        kept = sum(e["kept"] for e in verify_events)
        dropped = sum(len(e["dropped"]) for e in verify_events)
        cited_docs = set()
        for a in final.get("attempts") or []:
            cited_docs.update(a.get("chunk_ids") or [])
        rows.append({
            "case_id": case["case_id"],
            "expected_outcome": case.get("expected_outcome"),
            "outcome": final.get("outcome"),
            "expected_reason": case.get("expected_reason"),
            "reason": final.get("escalation_reason") if final.get("outcome") in ("escalated", "rejected") else None,
            "expected_doc": case.get("expected_doc"),
            "evidence_hit": (case.get("expected_doc") in cited_docs) if case.get("expected_doc") else None,
            "attempts": len(final.get("attempts") or []),
            "confidence": final.get("confidence"),
            "cache_status": final.get("cache_status"),
            "steps_kept": kept, "steps_dropped": dropped,
        })
    return {"metrics": metrics(rows), "cases": rows}


def _safe(n: float, d: float) -> Optional[float]:
    return round(n / d, 4) if d else None


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    correct = sum(r["outcome"] == r["expected_outcome"] for r in rows)
    should_not_resolve = [r for r in rows if r["expected_outcome"] in ("escalated", "rejected")]
    false_resolves = sum(r["outcome"] == "resolved" for r in should_not_resolve)
    escalated = [r for r in rows if r["outcome"] in ("escalated", "rejected")]
    expected_esc = [r for r in rows if r["expected_outcome"] in ("escalated", "rejected")]
    with_reason = [r for r in rows if r["expected_reason"]]
    with_doc = [r for r in rows if r["evidence_hit"] is not None]
    kept = sum(r["steps_kept"] for r in rows)
    dropped = sum(r["steps_dropped"] for r in rows)
    return {
        "n_cases": n,
        "outcome_accuracy": _safe(correct, n),
        "false_resolve_rate": _safe(false_resolves, len(should_not_resolve)),
        "escalation_precision": _safe(sum(r["expected_outcome"] in ("escalated", "rejected") for r in escalated), len(escalated)),
        "escalation_recall": _safe(sum(r["outcome"] in ("escalated", "rejected") for r in expected_esc), len(expected_esc)),
        "reason_accuracy": _safe(sum(r["reason"] == r["expected_reason"] for r in with_reason), len(with_reason)),
        "evidence_hit_rate": _safe(sum(r["evidence_hit"] for r in with_doc), len(with_doc)),
        "citation_validity": _safe(kept, kept + dropped),
        "mean_attempts": _safe(sum(r["attempts"] for r in rows), n),
    }


def main() -> None:
    from triage.cache import SemanticCache
    from triage.llm import get_llm
    from triage.oplog import EventLogger
    from triage.retrieval.interface import (LexicalRetriever, TieredRetriever, load_kb_jsonl,
                                            load_tickets_jsonl)
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="fixtures/eval_cases.jsonl")
    ap.add_argument("--signatures", default="fixtures/signatures.json")
    ap.add_argument("--kb", default="fixtures/kb_mini.jsonl")
    ap.add_argument("--tickets", default="fixtures/tickets_mini.jsonl")
    ap.add_argument("--llm", default=None, help="fake | anthropic | openai")
    ap.add_argument("--out", default="reports/resolver_eval.json")
    a = ap.parse_args()
    cases = [json.loads(l) for l in Path(a.cases).read_text().splitlines() if l.strip()]
    holdout = {c.get("expected_doc") for c in cases if str(c.get("expected_doc", "")).startswith("HOLDOUT")}
    deps = ResolverDeps(
        retriever=TieredRetriever(LexicalRetriever(load_kb_jsonl(a.kb), "kb"),
                                  LexicalRetriever(load_tickets_jsonl(a.tickets, holdout_ids=holdout), "tickets")),
        llm=get_llm(a.llm), cache=SemanticCache(), logger=EventLogger("logs/eval_events.jsonl"))
    sigs = json.loads(Path(a.signatures).read_text()) if Path(a.signatures).exists() else {}
    report = evaluate(deps, cases, sigs)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=2))
    print(json.dumps(report["metrics"], indent=2))
    for r in report["cases"]:
        flag = "OK " if r["outcome"] == r["expected_outcome"] else "XX "
        print(flag, r["case_id"], r["expected_outcome"], "->", r["outcome"], r["reason"] or "")


if __name__ == "__main__":
    main()
