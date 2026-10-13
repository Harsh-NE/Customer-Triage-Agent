"""
e2e_eval.py -- end-to-end evaluation of the integrated system (Clarifier -> Resolver) on the labelled scenarios.

Each scenario runs through the real joint graph on the real stores. The simulated customer (triage/sim) answers the
Clarifier's questions; when the Resolver sends a fix, an ORACLE reacts: "that worked" if the evidence the fix cites is the
scenario's gold KB issue, otherwise "still the same error". So this measures whether the system reaches the DOCUMENTED fix
and whether it ever sends a wrong one -- not the quality of an LLM's wording (the default FakeLLM only quotes the evidence).
Tickets have no gold label, so a fix drawn from tickets is always answered "still the same error" (conservative).

What the numbers can and cannot say: 29 same-author scenarios, a rule-based customer, gate thresholds that are B's starting
guesses. They show whether the pieces fit and where; they are not a quality estimate.

    python -m triage.eval.e2e_eval                       # all scenarios, FakeLLM, writes reports/e2e_eval*.{json,md}
    python -m triage.eval.e2e_eval --ids S05 S17 -v      # a few, with transcripts
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path

from langgraph.types import Command

from triage.clarifier import Clarifier
from triage.joint import build_default_deps, build_joint_graph
from triage.resolver.cache import SemanticCache
from triage.resolver.llm import get_llm
from triage.sim.customer import RuleBasedCustomer, Scenario, load_scenarios

REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"
GOOD, BAD = "that worked, thanks", "I tried that but it is still the same error"
_CITED = re.compile(r"\[(E\d+(?:, E\d+)*)\]")


class Recording:
    """Wraps the Resolver's retriever and remembers every call, so the oracle can see the evidence behind a fix."""

    def __init__(self, inner) -> None:
        self.inner, self.calls, self.gate_inputs = inner, [], []
        self.exclude: set[str] = set()          # ticket ids to hide from the ticket tier (a held-out question's own ticket)

    def retrieve(self, query, signature=None, k=10, tier="kb", exclude_chunk_ids=()):
        if tier == "tickets" and self.exclude:
            exclude_chunk_ids = [*exclude_chunk_ids, *self.exclude]
        result = self.inner.retrieve(query, signature, k=k, tier=tier, exclude_chunk_ids=exclude_chunk_ids)
        self.calls.append((tier, result))
        clar = (getattr(signature, "clarifier", None) or {})
        self.gate_inputs.append({            # all the confidence gate sees, so calibrate_gate can replay it with other thresholds
            "tier": tier, "completeness": getattr(signature, "completeness", 0.0), "p_top": clar.get("p_top"),
            "evidence": [{"evidence_id": e.evidence_id, "doc_id": e.doc_id, "tier": e.tier, "rerank_score": e.rerank_score,
                          "component": e.metadata.get("component"), "topics": list(e.metadata.get("topics") or []),
                          "issue": str(e.metadata.get("issue", ""))[:80]} for e in result]})
        return result


def is_gold(evidence, gold: dict) -> bool:
    page = evidence.doc_id.split("#")[0].lower()
    return (evidence.tier == "kb" and gold["source_path_contains"].lower() in page
            and gold["issue_contains"].lower() in str(evidence.metadata.get("issue", "")).lower())


def is_gold_row(row: dict, gold: dict) -> bool:
    """is_gold for a recorded gate-input row (a dict) instead of an Evidence object."""
    return (row["tier"] == "kb" and gold["source_path_contains"].lower() in row["doc_id"].split("#")[0].lower()
            and gold["issue_contains"].lower() in row["issue"].lower())


def run_scenario(app, rec: Recording, s: Scenario, verbose: bool = False, max_messages: int = 14) -> dict:
    first_input = len(rec.gate_inputs)
    rec.exclude = {s.hidden["source_ticket_id"]} if s.hidden.get("source_ticket_id") else set()
    tid = f"E2E-{s.id}"
    cfg = {"configurable": {"thread_id": tid}}
    customer = RuleBasedCustomer(s)
    out = app.invoke({"ticket_id": tid, "customer_message": customer.opening(), "transcript": []}, cfg)
    sent: list[dict] = []
    questions = 0
    for _ in range(max_messages):
        if "__interrupt__" not in out:
            break
        v = out["__interrupt__"][0].value
        if v["type"] == "clarifier_question":
            questions += 1
            reply = customer.reply(v["message"])
        else:
            tier, evidence = rec.calls[-1] if rec.calls else ("kb", [])
            cited = sorted({i for grp in _CITED.findall(v["message"]) for i in grp.split(", ")})
            good = bool(s.gold) and any(is_gold(e, s.gold) for e in evidence if e.evidence_id in cited)
            sent.append({"tier": tier, "cited": cited, "gold": good, "message": v["message"],
                         "sources": [e.metadata.get("issue", e.chunk_id)[:60] for e in evidence if e.evidence_id in cited],
                         "evidence": [{"evidence_id": e.evidence_id, "tier": e.tier, "url": e.url, "text": e.full_text[:2500]}
                                      for e in evidence if e.evidence_id in cited]})        # kept so the faithfulness judge can read what the fix was built from
            reply = GOOD if good else BAD
        if verbose:
            print(f"  [{v['type']}] {v['message'][:160]!r}\n  customer: {reply[:100]!r}")
        out = app.invoke(Command(resume=reply), cfg)
    st = app.get_state(cfg).values
    gate_inputs = [{**g, "evidence": [{**e, "gold": bool(s.gold) and is_gold_row(e, s.gold)} for e in g["evidence"]]}
                   for g in rec.gate_inputs[first_input:]]
    outcome = st.get("outcome") or ("in_progress" if "__interrupt__" in out else "unknown")
    return {"id": s.id, "opening": s.opening, "has_gold": bool(s.gold), "oos": bool(s.oos), "kb_gap": s.note.startswith("kb_gap"), "outcome": outcome,
            "escalation_reason": st.get("escalation_reason"), "questions": questions, "fixes_sent": sent,
            "first_gold": bool(sent and sent[0]["gold"]), "resolved_gold": outcome == "resolved" and any(f["gold"] for f in sent),
            "clarifier": (st.get("signature") or {}).get("clarifier", {}), "clarify_returns": st.get("clarify_returns", 0),
            "gate_inputs": gate_inputs, "gate_final": st.get("gate_detail"), "confidence": st.get("confidence")}


def llm_usage(events: Path, offset: int) -> dict:
    """Calls, tokens, USD (None when the model has no price) and latency of the LLM calls logged since `offset`."""
    if not events.exists():
        return {}
    with events.open("rb") as f:
        f.seek(offset)
        lines = f.read().decode("utf-8", "ignore").splitlines()
    calls = [e for e in map(json.loads, filter(None, lines)) if e.get("event") == "llm_call"]
    costs = [e.get("cost_usd") for e in calls]
    lat = sorted(e["latency_ms"] for e in calls if e.get("latency_ms") is not None)
    return {"llm_calls": len(calls), "input_tokens": sum(e.get("input_tokens") or 0 for e in calls),
            "output_tokens": sum(e.get("output_tokens") or 0 for e in calls),
            "cost_usd": round(sum(c for c in costs if c), 4) if costs and all(c is not None for c in costs) else None,
            "llm_latency_ms_p50": lat[len(lat) // 2] if lat else None, "llm_latency_ms_p95": lat[int(len(lat) * 0.95)] if lat else None}


def summarize(rows: list[dict]) -> dict:
    gold = [r for r in rows if r["has_gold"]]
    nogold = [r for r in rows if not r["has_gold"]]
    oos = [r for r in rows if r["oos"]]
    gapped = [r for r in rows if r.get("kb_gap")]
    rate = lambda n, d: round(n / d, 3) if d else None            # noqa: E731
    first_tiers = Counter(r["fixes_sent"][0]["tier"] for r in rows if r["fixes_sent"])
    return {
        "scenarios": len(rows), "with_gold": len(gold), "out_of_scope": len(oos), "no_gold_other": len(nogold) - len(oos),
        "gold_resolved_rate": rate(sum(r["resolved_gold"] for r in gold), len(gold)),
        "gold_first_attempt_rate": rate(sum(r["first_gold"] for r in gold), len(gold)),
        "gold_escalated_rate": rate(sum(r["outcome"] in ("escalated", "rejected") for r in gold), len(gold)),
        "wrong_fix_sent_rate_gold": rate(sum(bool(r["fixes_sent"]) and not r["fixes_sent"][0]["gold"] for r in gold), len(gold)),
        "oos_resolved_rate": rate(sum(r["outcome"] == "resolved" for r in oos), len(oos)),
        "oos_fix_sent_rate": rate(sum(bool(r["fixes_sent"]) for r in oos), len(oos)),
        "oos_escalated_or_rejected_rate": rate(sum(r["outcome"] in ("escalated", "rejected") for r in oos), len(oos)),
        "no_gold_other_fix_sent_rate": rate(sum(bool(r["fixes_sent"]) for r in nogold if not r["oos"]), len(nogold) - len(oos)),
        "kb_gap": sum(r.get("kb_gap", False) for r in rows),
        "kb_gap_kb_fix_sent_rate": rate(sum(any(f["tier"] == "kb" for f in r["fixes_sent"]) for r in gapped), len(gapped)),   # the KB has no answer: wrong by definition
        "kb_gap_any_fix_sent_rate": rate(sum(bool(r["fixes_sent"]) for r in gapped), len(gapped)),
        "first_fix_tier": dict(first_tiers), "mean_questions": round(sum(r["questions"] for r in rows) / len(rows), 2),
        "outcomes": dict(Counter(r["outcome"] for r in rows)),
    }


def write_report(path: Path, meta: dict, summary: dict, rows: list[dict]) -> None:
    lines = [f"# End-to-end evaluation (Clarifier -> Resolver)", "",
             f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python -m triage.eval.e2e_eval`._", "",
             "Real stores, simulated customer, oracle feedback (see the module docstring). 29 same-author scenarios and "
             "thresholds that are starting guesses: this shows how the pieces fit, not quality.", "", "```json",
             json.dumps({"meta": meta, "summary": summary}, indent=2), "```", "",
             "| id | opening | outcome | q | fixes sent (tier: gold?) | first fix cites |", "|---|---|---|---|---|---|"]
    for r in rows:
        fixes = ", ".join(f"{f['tier']}:{'yes' if f['gold'] else 'no'}" for f in r["fixes_sent"]) or "-"
        cites = (r["fixes_sent"][0]["sources"][0] if r["fixes_sent"] and r["fixes_sent"][0]["sources"] else "-")
        lines.append(f"| {r['id']} | {r['opening'][:48]} | {r['outcome']}{'/' + r['escalation_reason'] if r['escalation_reason'] else ''} "
                     f"| {r['questions']} | {fixes} | {cites} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="End-to-end evaluation of the joint Clarifier + Resolver graph.")
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--scenarios", type=Path, default=None, help="scenario file (default: the 29 in triage/eval/scenarios.jsonl)")
    ap.add_argument("--llm", default="fake", help="Resolver LLM: fake | gemini | anthropic | openai (default fake: offline, free)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--out-json", type=Path, default=REPORT_DIR / "e2e_eval.json")
    ap.add_argument("--out-md", type=Path, default=REPORT_DIR / "e2e_eval_report.md")
    args = ap.parse_args()

    scenarios = [s for s in load_scenarios(args.scenarios) if not args.ids or s.id in args.ids]
    started = time.time()
    events = Path(__file__).resolve().parents[2] / "data" / "processed" / "docker" / "resolver" / "e2e_events.jsonl"
    events_from = events.stat().st_size if events.exists() else 0
    llm = get_llm(args.llm)
    kb, deps = build_default_deps(llm, log_path=events)
    deps.cache = SemanticCache(embedder=deps.cache.embedder)          # fresh, in-memory: scenarios must not feed each other
    rec = Recording(deps.retriever)
    deps.retriever = rec
    app = build_joint_graph(Clarifier(None, kb), deps)
    rows = []
    for s in scenarios:
        deps.cache = SemanticCache(embedder=deps.cache.embedder)      # each scenario starts with an empty cache: they must be independent
        if args.verbose:
            print(f"=== {s.id}: {s.opening}")
        rows.append(run_scenario(app, rec, s, args.verbose))
        print(f"[{len(rows)}/{len(scenarios)}] {s.id}: {rows[-1]['outcome']}, {rows[-1]['questions']} questions, "
              f"{len(rows[-1]['fixes_sent'])} fix(es) sent, {time.time() - started:.0f}s elapsed", flush=True)
    summary = summarize(rows)
    meta = {"retriever": "hybrid", "resolver_llm": args.llm, "resolver_model": getattr(llm, "model", None), "seconds": round(time.time() - started, 1),
            "scenario_file": str(args.scenarios or "scenarios.jsonl"), **llm_usage(events, events_from)}
    write_report(args.out_md, meta, summary, rows)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"report: {args.out_md}")


if __name__ == "__main__":
    main()
