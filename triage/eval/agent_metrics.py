"""
agent_metrics.py -- one script that measures the agent on the six headline metrics, the minor per-stage metrics, and whether the logs
carry what is needed to measure them in production.

HEADLINE (for experiments and slides)
  1 resolution          first-attempt correct-fix rate, fixed within the 2-attempt budget, pass^k over repeated runs
  2 faithfulness        share of claims in the sent fixes that their cited evidence supports (needs --judge; the judge is a model)
  3 retrieval           Recall@1/3/8 and MRR of the gold issue, context precision of what the drafter was given
  4 safe decisions      wrong-fix rate, escalation recall / precision (no-answer cases that were escalated), terminal-action accuracy
  5 customer effort     questions per case, redundant / "not sure" / zero-question rates, question-type mix
  6 cost and speed      cost per verified resolution, end-to-end and time-to-first-reply p50 / p95
MINOR  citation validity, source mix, ticket-fallback rate, gate top scores, cache / verifier / LLM-error counts from the event log,
       optional Clarifier gap / gold@k metrics (--clarifier) and ontology on/off retrieval (--ontology)
LOGS   --audit-db: are the fields listed in the plan present in agent_events, how complete are conversations, plus the online numbers
       (time to first reply, cost per conversation, ratings) from the app database.

How a run works: every scenario goes through the real Clarifier -> Resolver graph (triage.eval.e2e_eval) with the simulated customer
and an oracle that answers "that worked" only when the fix cites the scenario's gold KB issue. Scenarios without a gold issue
(out of scope, or the KB has no answer) are CORRECT only when the agent sends no KB-backed fix and escalates / declines. With
--repeats N the whole set runs N times, the customer phrasing seeded differently each time (and a hosted model adds its own
variation); pass^k is the chance that k independent runs of a scenario are ALL right.

What the numbers can and cannot say: same-author scenarios, a rule-based customer, an oracle. The held-out file (65 real questions)
has draft labels (verified=False): the report says how many are verified. With the default fake model, faithfulness and cost are not
measured and latency is retrieval-only.

    set PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 (so the Clarifier's tie-breaking is the same in every run)
    python -m triage.eval.agent_metrics                                   # 29 scenarios, fake model: offline, free
    python -m triage.eval.agent_metrics --scenarios triage/eval/heldout_scenarios.jsonl
    python -m triage.eval.agent_metrics --llm gemini --repeats 3 --judge gemini --clarifier --ontology
    python -m triage.eval.agent_metrics --from-report reports/e2e_eval.json            # recompute from a finished run
    python -m triage.eval.agent_metrics --audit-db data/processed/docker/app.db         # log completeness + online numbers only
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports"
EVENTS = ROOT / "data" / "processed" / "docker" / "resolver" / "e2e_events.jsonl"
APP_DB = ROOT / "data" / "processed" / "docker" / "app.db"
ENDED_WITHOUT_FIX = ("escalated", "rejected")
NOT_SURE = re.compile(r"(?i)\b(not sure|don'?t know|do not know|don'?t remember|no idea|unsure)\b")
ASKS_ABOUT = {"platform": "platform", "product_area": "product_area", "error_message": "error_codes", "error_open": "error_codes"}


# ---------------------------------------------------------------- small helpers

def rate(k: int, n: int) -> dict:
    return {"value": round(k / n, 3) if n else None, "k": k, "n": n}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, math.ceil(q * len(v)) - 1)], 2)


def dist(values: list[float]) -> dict:
    values = [x for x in values if x is not None]
    return {"p50": percentile(values, 0.5), "p95": percentile(values, 0.95), "mean": round(statistics.mean(values), 2) if values else None,
            "max": round(max(values), 2) if values else None, "n": len(values)}


def is_rate(d) -> bool:
    return isinstance(d, dict) and set(d) == {"value", "k", "n"}


def is_dist(d) -> bool:
    return isinstance(d, dict) and set(d) == {"p50", "p95", "mean", "max", "n"}


# ---------------------------------------------------------------- 1. resolution

def correct_end(r: dict) -> bool:
    """The right thing happened. With a gold issue: it was resolved by a fix that cites it. Without one (out of scope, or the KB has no
    answer): no KB-backed fix went out and the case ended escalated / declined (an out-of-scope case must get no fix at all)."""
    if r["has_gold"]:
        return bool(r["resolved_gold"])
    if any(f["tier"] == "kb" for f in r["fixes_sent"]) or (r["oos"] and r["fixes_sent"]):
        return False
    return r["outcome"] in ENDED_WITHOUT_FIX


def pass_hat_k(per_scenario: dict[str, list[bool]]) -> dict:
    """tau-bench pass^k: for a scenario with c right runs out of n, C(c,k)/C(n,k) is the chance that k runs drawn without replacement
    are all right; averaged over scenarios. pass^1 is the plain success rate."""
    n = min((len(v) for v in per_scenario.values()), default=0)
    return {f"pass^{k}": round(statistics.mean(math.comb(sum(v), k) / math.comb(len(v), k) for v in per_scenario.values()), 3)
            for k in range(1, n + 1)}


def resolution(runs: list[list[dict]]) -> dict:
    rows = [r for run in runs for r in run]
    gold = [r for r in rows if r["has_gold"]]
    resolved = [r for r in gold if r["resolved_gold"]]
    per: dict[str, list[bool]] = defaultdict(list)
    for run in runs:
        for r in run:
            per[r["id"]].append(correct_end(r))
    out = {
        "gold_first_attempt_correct": rate(sum(r["first_gold"] for r in gold), len(gold)),
        "gold_fixed_within_2_attempts": rate(sum(bool(r["resolved_gold"]) and any(f["gold"] for f in r["fixes_sent"][:2]) for r in gold), len(gold)),
        "gold_escalated_instead": rate(sum(r["outcome"] in ENDED_WITHOUT_FIX for r in gold), len(gold)),
        "attempts_per_resolved_gold": dist([len(r["fixes_sent"]) for r in resolved]),
        "correct_end_all_scenarios": rate(sum(correct_end(r) for r in rows), len(rows)),
        "outcomes": dict(Counter(r["outcome"] for r in rows)),
    }
    if len(runs) > 1:
        out["pass_hat_k"] = pass_hat_k(per)
        out["unstable_scenarios"] = sorted(i for i, v in per.items() if 0 < sum(v) < len(v))
    return out


# ---------------------------------------------------------------- 2. faithfulness

def faithfulness(rows: list[dict], judge_name: str, limit: int | None, self_check: bool) -> dict:
    from triage.eval import judge as J
    fixes = J.fixes_to_judge(rows)[:limit]
    if not fixes:
        return {"note": "no fix with message + evidence to judge"}
    if judge_name == "fake":
        llm = J._FakeJudge()
    else:
        from triage.resolver.llm import ClarifierProviderLLM
        llm = ClarifierProviderLLM(None if judge_name == "gemini" else judge_name, None)
    results = [J.judge_one(llm, f["problem"], f["message"], f["evidence"]) for f in fixes]
    out = {"judge": f"{judge_name}:{getattr(llm, 'model', '')}", "fixes_judged": len(fixes), **J.aggregate(results)}
    if self_check:
        out["negative_controls"] = J.self_check(llm, fixes)
    return out


# ---------------------------------------------------------------- 3. retrieval

def retrieval(rows: list[dict]) -> dict:
    """On the first KB retrieval of each gold scenario. Ranks are CHUNK positions (a gold issue spans several chunks)."""
    from triage.eval.calibrate_gate import first_kb_gate_input
    gold = [r for r in rows if r["has_gold"]]
    ranks, p5, ctx_prec, nothing = [], [], [], 0
    for r in gold:
        gi = first_kb_gate_input(r)
        if not gi:
            nothing += 1
            ranks.append(None)
            continue
        flags = [bool(e["gold"]) for e in gi["evidence"]]
        ranks.append(flags.index(True) + 1 if True in flags else None)
        p5.append(sum(flags[:5]) / len(flags[:5]))
        hits = [sum(flags[:i + 1]) / (i + 1) for i, f in enumerate(flags) if f]        # Ragas-style: precision at each relevant position
        ctx_prec.append(sum(hits) / len(hits) if hits else 0.0)
    n = len(gold)
    top = lambda kind: [first_kb_gate_input(r)["evidence"][0]["rerank_score"] for r in rows       # noqa: E731
                        if first_kb_gate_input(r) and (r["has_gold"] if kind == "gold" else not r["has_gold"])]
    return {"gold_scenarios": n, "no_kb_evidence": nothing,
            **{f"recall@{k}": rate(sum(1 for x in ranks if x and x <= k), n) for k in (1, 3, 8)},
            "mrr": round(sum(1 / x for x in ranks if x) / n, 3) if n else None,
            "precision@5": round(statistics.mean(p5), 3) if p5 else None,
            "context_precision": round(statistics.mean(ctx_prec), 3) if ctx_prec else None,
            "top_rerank_score_gold": dist(top("gold")), "top_rerank_score_no_gold": dist(top("other"))}


def ontology_ablation(scenarios, modes=("off", "both")) -> dict:
    from triage.eval import ontology_eval as O
    from triage.hybrid import HybridKBRetriever
    items = {"scenarios": [{"id": s.id, "query": s.opening, "gold": [{"path": s.gold["source_path_contains"], "issue": s.gold["issue_contains"]}]}
                           for s in scenarios if s.gold],
             "paraphrases": O.load_items()["paraphrases"]}
    out, model = {}, None
    for mode in modes:
        r = HybridKBRetriever(ontology_mode=mode, model=model) if model else HybridKBRetriever(ontology_mode=mode)
        r._ensure()
        model = r._model
        out[mode] = {name: O.evaluate(r, its)[0] for name, its in items.items() if its}
    return out


# ---------------------------------------------------------------- 4. safe decisions

def safe_decisions(rows: list[dict]) -> dict:
    """The no-answer cases are those with no gold issue (out of scope, or the KB has no documented fix): the agent should escalate or
    decline. Escalation recall = how many of them it did; precision = how many of its escalations were such cases."""
    gold = [r for r in rows if r["has_gold"]]
    nogold = [r for r in rows if not r["has_gold"]]
    stopped = [r for r in rows if r["outcome"] in ENDED_WITHOUT_FIX]
    wrong_gold = [r for r in gold if r["fixes_sent"] and not r["fixes_sent"][0]["gold"]]
    wrong_nogold = [r for r in nogold if any(f["tier"] == "kb" for f in r["fixes_sent"]) or (r["oos"] and r["fixes_sent"])]
    return {
        "wrong_fix_rate": rate(len(wrong_gold) + len(wrong_nogold), len(rows)),
        "wrong_first_fix_on_gold": rate(len(wrong_gold), len(gold)),
        "kb_fix_on_no_answer_cases": rate(len(wrong_nogold), len(nogold)),
        "escalation_recall": rate(sum(r in stopped for r in nogold), len(nogold)),
        "escalation_precision": rate(sum(not r["has_gold"] for r in stopped), len(stopped)),
        "unnecessary_escalation_rate": rate(sum(r in stopped for r in gold), len(gold)),
        "terminal_action_accuracy": rate(sum(correct_end(r) for r in rows), len(rows)),
        "escalation_reasons": dict(Counter(r["escalation_reason"] for r in stopped if r["escalation_reason"])),
        "note": "per-turn answer/ask/escalate accuracy needs a label for every turn; this is the end-of-case version",
    }


# ---------------------------------------------------------------- 5. customer effort

def question_kind(message: str) -> str:
    from triage.sim.customer import classify_question
    return classify_question(message)[0]


def effort(rows: list[dict]) -> dict:
    per_case = [len(r["asked"]) if "asked" in r else r["questions"] for r in rows]
    asked = [(r, a) for r in rows for a in r.get("asked", [])]
    repeated = redundant = 0
    for r in rows:
        seen: set[str] = set()
        for a in r.get("asked", []):
            kind = question_kind(a["message"])
            repeated += a["message"] in seen
            redundant += (ASKS_ABOUT.get(kind) in (r.get("opening_facts") or {})) and a["message"] not in seen
            seen.add(a["message"])
    clear = [r for r in rows if r.get("vagueness") == "low"]
    ready = [r for r in rows if r["has_gold"] and r["fixes_sent"]]
    return {
        "questions_per_case": dist(per_case),
        "questions_histogram": dict(sorted(Counter(per_case).items())),
        "zero_question_rate": rate(sum(q == 0 for q in per_case), len(rows)),
        "zero_question_rate_clear_openings": rate(sum(len(r.get("asked", [])) == 0 for r in clear), len(clear)),
        "redundant_question_rate": rate(redundant, len(asked)),
        "repeated_question_rate": rate(repeated, len(asked)),
        "not_sure_answer_rate": rate(sum(bool(NOT_SURE.search(a["reply"])) for _, a in asked), len(asked)),
        "question_type_mix": dict(Counter(question_kind(a["message"]) for _, a in asked)),
        "ready_precision_first_fix": rate(sum(r["first_gold"] for r in ready), len(ready)),
        "note": "redundant = asked for a fact the opening message already gave (scenario opening_facts)",
    }


# ---------------------------------------------------------------- 6. cost and speed

def cost_speed(rows: list[dict]) -> dict:
    usage = [r.get("usage") or {} for r in rows]
    costs = [u.get("cost_usd") for u in usage]
    priced = bool(costs) and all(c is not None for c in costs)
    total = round(sum(costs), 4) if priced else None
    resolved = sum(bool(r["resolved_gold"]) for r in rows)
    tokens = sum((u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) for u in usage)
    return {
        "total_cost_usd": total,
        "cost_per_case_usd": round(total / len(rows), 4) if priced and rows else None,
        "cost_per_verified_resolution_usd": round(total / resolved, 4) if priced and resolved else None,
        "tokens_per_verified_resolution": round(tokens / resolved) if resolved else None,
        "llm_calls_per_case": dist([u.get("llm_calls", 0) for u in usage]),
        "end_to_end_seconds": dist([r.get("total_s") for r in rows]),
        "time_to_first_reply_seconds": dist([r.get("first_reply_s") for r in rows]),
        "note": None if priced else "cost is null: the model is unpriced or no model was called (fake). Latency then covers retrieval and "
                                    "the Clarifier only. Add the model to triage/pricing.json to price it.",
    }


# ---------------------------------------------------------------- minor: drafting, sources, event log

def drafting(rows: list[dict]) -> dict:
    fixes = [(r, f) for r in rows for f in r["fixes_sent"]]
    shown = {r["id"]: {e["evidence_id"] for g in r["gate_inputs"] for e in g["evidence"]} for r in rows}
    valid = sum(bool(f["cited"]) and set(f["cited"]) <= shown[r["id"]] for r, f in fixes)
    firsts = Counter(r["fixes_sent"][0]["tier"] for r in rows if r["fixes_sent"])
    with_fix = [r for r in rows if r["fixes_sent"]]
    return {"fixes_sent": len(fixes), "citation_valid": rate(valid, len(fixes)),
            "first_fix_tier": dict(firsts),
            "ticket_fallback_rate": rate(sum(any(f["tier"] == "tickets" for f in r["fixes_sent"]) for r in with_fix), len(with_fix)),
            "cited_per_fix": dist([len(f["cited"]) for _, f in fixes])}


def read_events(path: Path, offset: int = 0) -> list[dict]:
    if not path.exists():
        return []
    with path.open("rb") as f:
        f.seek(offset)
        return [json.loads(l) for l in f.read().decode("utf-8", "ignore").splitlines() if l.strip()]


def ops_from_events(events: list[dict]) -> dict:
    by = defaultdict(list)
    for e in events:
        by[e.get("event")].append(e)
    llm = by["llm_call"]
    cache = Counter(e.get("status") for e in by["cache_lookup"])
    return {
        "events": dict(Counter(e.get("event") for e in events)),
        "llm_errors": rate(sum(bool(e.get("error")) or str(e.get("status", "ok")).startswith("error") for e in llm), len(llm)),
        "llm_latency_ms": dist([e.get("latency_ms") for e in llm]),
        "llm_calls_by_node": dict(Counter(e.get("node") for e in llm)),
        "cache_lookups": dict(cache), "cache_rejected_by_gate": sum(bool(e.get("rejected_by_gate")) for e in by["cache_lookup"]),
        "retrieval_tiers": dict(Counter(e.get("tier") for e in by["retrieval"])),
        "retrieval_latency_ms": dist([e.get("latency_ms") for e in by["retrieval"]]),
        "gate_decisions": dict(Counter(e.get("decision") for e in by["gate"])),
        "verifier_steps_dropped": sum(len(e.get("dropped") or []) if isinstance(e.get("dropped"), list) else int(e.get("dropped") or 0) for e in by["verify"]),
        "verifier_steps_kept": sum(len(e.get("kept") or []) if isinstance(e.get("kept"), list) else int(e.get("kept") or 0) for e in by["verify"]),
        "escalation_events": dict(Counter(e.get("reason") for e in by["escalation"])),
    }


# ---------------------------------------------------------------- optional: the Clarifier on its own

def clarifier_stage(scenarios) -> dict:
    from triage.config import ClarifierConfig
    from triage.eval import clarifier_eval as C
    retriever = C.CachingRetriever(C.build_retriever("hybrid", None))
    results = C.run_all(retriever, ClarifierConfig(), scenarios)
    return {"gap_and_extraction": C.gap_and_extraction_metrics(scenarios), "dialogue": C.summarize(results)}


# ---------------------------------------------------------------- logs: are the fields there, and the online numbers

REQUIRED = {"llm_call": ["model", "node", "latency_ms", "input_tokens", "output_tokens", "cost_usd", "status"],
            "retrieval": ["tier", "n", "top_score", "latency_ms"], "gate": ["decision", "confidence", "tier", "reasons"],
            "clarifier_turn": ["questions_asked", "reason", "status", "question_feature"], "cache_lookup": ["status", "similarity"],
            "verify": ["kept", "dropped"], "outcome": ["outcome", "attempts"], "escalation": ["reason", "priority"]}
WANTED = {"trace id on every event": ["trace_id"], "config / threshold version": ["config_version", "config_hash"],
          "KB / index / ontology version": ["kb_version", "index_version", "ontology_version"],
          "evidence ids shown to the drafter": ["evidence_ids", "evidence_ids_shown"], "evidence ids cited in the fix": ["cited_ids", "evidence_ids_cited"],
          "question wording": ["question_text", "question"], "customer answer, parsed": ["parsed_answer", "answer_parsed"],
          "per-stage latency": ["stage_latency_ms"], "limit-hit flags (3 questions, 2 attempts, timeout)": ["limit_hit", "budget_exceeded", "timeout"],
          "decision reason (answer / ask / escalate)": ["reasons", "reason"]}


def load_db_events(db: Path) -> list[dict]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    out = []
    for row in con.execute("SELECT * FROM agent_events ORDER BY id"):
        data = json.loads(row["data"]) if row["data"] else {}
        out.append({**data, "event": row["event"], "conversation_id": row["conversation_id"], "node": row["node"] or data.get("node"),
                    "model": row["model"] or data.get("model"), "latency_ms": row["latency_ms"] if row["latency_ms"] is not None else data.get("latency_ms"),
                    "input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"], "cost_usd": row["cost_usd"], "ts": row["ts"]})
    return out


def audit_events(events: list[dict]) -> dict:
    by = defaultdict(list)
    for e in events:
        by[e.get("event")].append(e)
    fields = {}
    for kind, names in REQUIRED.items():
        evs = by.get(kind, [])
        fields[kind] = {"events": len(evs), **{n: rate(sum(e.get(n) is not None for e in evs), len(evs)) for n in names}} if evs else {"events": 0}
    keys = {k for e in events for k in e}
    convs = defaultdict(set)
    for e in events:
        if e.get("conversation_id"):
            convs[e["conversation_id"]].add(e["event"])
    n = len(convs)
    llm = by.get("llm_call", [])
    return {
        "events": len(events), "conversations": n, "fields_present": fields,
        "unpriced_llm_calls": rate(sum(e.get("cost_usd") is None for e in llm), len(llm)),
        "conversation_has": {k: rate(sum(k in v for v in convs.values()), n) for k in ("clarifier_turn", "retrieval", "gate", "llm_call", "outcome")},
        "wanted_fields": {label: any(c in keys for c in cands) for label, cands in WANTED.items()},
        "not_logged": [label for label, cands in WANTED.items() if not any(c in keys for c in cands)],
    }


def online_from_db(db: Path) -> dict:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    convs = [dict(r) for r in con.execute("SELECT * FROM conversations")]
    first: dict[str, dict] = {}
    for m in con.execute("SELECT conversation_id, role, created_at FROM messages ORDER BY id"):
        d = first.setdefault(m["conversation_id"], {})
        d.setdefault("customer" if m["role"] == "customer" else "agent" if m["role"] == "agent" else "other", m["created_at"])
    from datetime import datetime
    parse = lambda s: datetime.fromisoformat(str(s).replace("Z", "+00:00"))          # noqa: E731
    wait = [(parse(d["agent"]) - parse(d["customer"])).total_seconds() for d in first.values() if "agent" in d and "customer" in d]
    cost: dict[str, float] = defaultdict(float)
    unpriced = set()
    for e in con.execute("SELECT conversation_id, cost_usd FROM agent_events WHERE event = 'llm_call'"):
        (cost.__setitem__(e["conversation_id"], cost[e["conversation_id"]] + e["cost_usd"]) if e["cost_usd"] is not None else unpriced.add(e["conversation_id"]))
    rated = [c["rating"] for c in convs if c.get("rating") is not None]
    helpful = [c for c in convs if c.get("helpful") is not None]
    return {"conversations": len(convs), "status": dict(Counter(c["status"] for c in convs)),
            "escalation_reasons": dict(Counter(c["escalation_reason"] for c in convs if c.get("escalation_reason"))),
            "time_to_first_agent_reply_seconds": dist(wait),
            "cost_per_conversation_usd": dist(list(cost.values())), "conversations_with_unpriced_calls": len(unpriced),
            "mean_rating": round(statistics.mean(rated), 2) if rated else None, "rated": len(rated),
            "helpful_rate": rate(sum(bool(c["helpful"]) for c in helpful), len(helpful)),
            "resolved_by": dict(Counter(c["resolved_by"] for c in convs if c.get("resolved_by")))}


# ---------------------------------------------------------------- running

def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT, timeout=10).stdout.strip() or None
    except Exception:  # noqa: BLE001 -- not a git checkout is fine
        return None


def run_all(scenarios, llm_name: str, repeats: int, verbose: bool) -> tuple[list[list[dict]], dict, list[dict]]:
    from triage.clarifier import Clarifier
    from triage.eval.e2e_eval import Recording, llm_usage, run_scenario
    from triage.joint import build_default_deps, build_joint_graph
    from triage.resolver.cache import SemanticCache
    from triage.resolver.llm import get_llm

    llm = get_llm(llm_name)
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    events_from = EVENTS.stat().st_size if EVENTS.exists() else 0
    kb, deps = build_default_deps(llm, log_path=EVENTS)
    rec = Recording(deps.retriever)
    deps.retriever = rec
    app = build_joint_graph(Clarifier(None, kb), deps)
    runs, started, total = [], time.time(), len(scenarios) * repeats
    for rep in range(repeats):
        rows = []
        for s in scenarios:
            deps.cache = SemanticCache(embedder=deps.cache.embedder)            # scenarios must not feed each other through the cache
            offset = EVENTS.stat().st_size if EVENTS.exists() else 0
            row = run_scenario(app, rec, s, verbose, customer_seed=rep if repeats > 1 else None)
            row["usage"] = llm_usage(EVENTS, offset)
            rows.append(row)
            print(f"[run {rep + 1}/{repeats}  {len(rows)}/{len(scenarios)}] {s.id}: {row['outcome']}, {row['questions']} q, "
                  f"{len(row['fixes_sent'])} fix, {row['total_s']}s ({time.time() - started:.0f}s elapsed of ~{total} cases)", flush=True)
        runs.append(rows)
    meta = {"resolver_llm": llm_name, "resolver_model": getattr(llm, "model", None), "seconds": round(time.time() - started, 1)}
    return runs, meta, read_events(EVENTS, events_from)


# ---------------------------------------------------------------- report

def flatten(prefix: str, value, out: list[tuple[str, object]]) -> None:
    if isinstance(value, dict) and not is_rate(value) and not is_dist(value) and value:
        for k, v in value.items():
            flatten(f"{prefix}.{k}" if prefix else k, v, out)
    else:
        out.append((prefix, value))


def show(v) -> str:
    if is_rate(v):
        return f"{v['value'] * 100:.1f}% ({v['k']}/{v['n']})" if v["value"] is not None else f"n/a (0 of {v['n']})"
    if is_dist(v):
        return f"p50 {v['p50']} / p95 {v['p95']} / mean {v['mean']} / max {v['max']} (n={v['n']})" if v["n"] else "n/a"
    return json.dumps(v, default=str) if isinstance(v, (dict, list)) else ("n/a" if v is None else str(v))


def write_markdown(path: Path, report: dict) -> None:
    lines = ["# Agent metrics", "", f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python -m triage.eval.agent_metrics`._", "",
             "```json", json.dumps(report["meta"], indent=2, default=str), "```", ""]
    titles = {"major": "Headline metrics", "minor": "Minor metrics by stage", "logs": "Log completeness (agent_events)", "online": "Online numbers (app database)"}
    for section, title in titles.items():
        if section not in report:
            continue
        lines += [f"## {title}", ""]
        for name, body in report[section].items():
            lines += [f"### {name}", "", "| metric | value |", "|---|---|"]
            flat: list[tuple[str, object]] = []
            flatten("", body, flat)
            lines += [f"| {k or name} | {show(v)} |" for k, v in flat] + [""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def headline(report: dict) -> list[str]:
    m = report.get("major", {})
    pick = lambda *p: _dig(m, p)          # noqa: E731
    items = [("1 first-attempt correct (gold)", pick("1_resolution", "gold_first_attempt_correct")),
             ("1 fixed within 2 attempts (gold)", pick("1_resolution", "gold_fixed_within_2_attempts")),
             ("2 fully supported fixes", pick("2_faithfulness", "fully_supported_rate")),
             ("3 recall@3 of gold issue", pick("3_retrieval", "recall@3")), ("3 MRR", pick("3_retrieval", "mrr")),
             ("4 wrong-fix rate", pick("4_safe_decisions", "wrong_fix_rate")), ("4 escalation recall", pick("4_safe_decisions", "escalation_recall")),
             ("4 escalation precision", pick("4_safe_decisions", "escalation_precision")),
             ("5 questions per case", pick("5_customer_effort", "questions_per_case")),
             ("6 cost per verified resolution (USD)", pick("6_cost_and_speed", "cost_per_verified_resolution_usd")),
             ("6 end-to-end seconds", pick("6_cost_and_speed", "end_to_end_seconds"))]
    return [f"  {label:<40} {show(v)}" for label, v in items]


def _dig(d, path):
    for p in path:
        d = d.get(p) if isinstance(d, dict) else None
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure the agent on the headline and minor metrics; audit the event log.")
    ap.add_argument("--scenarios", type=Path, default=None, help="scenario file (default: the 29 in triage/eval/scenarios.jsonl)")
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=None, help="only the first N scenarios (a quick look before a full run)")
    ap.add_argument("--llm", default="fake", help="Resolver model: fake | gemini | anthropic | openai (default fake: offline, free)")
    ap.add_argument("--repeats", type=int, default=1, help="run the whole set N times (customer phrasing seeded per run) for pass^k")
    ap.add_argument("--from-report", type=Path, nargs="*", default=None, help="e2e_eval / agent_metrics JSON file(s) to recompute from; each is one run")
    ap.add_argument("--judge", default=None, help="faithfulness judge: gemini | anthropic | openai | fake (costs model calls; omit to skip)")
    ap.add_argument("--judge-limit", type=int, default=None, help="judge at most N fixes (from the first run)")
    ap.add_argument("--self-check", action="store_true", help="also plant known faults and report whether the judge catches them")
    ap.add_argument("--clarifier", action="store_true", help="also the Clarifier's own gap / gold@k / READY-precision metrics (free)")
    ap.add_argument("--ontology", action="store_true", help="also gold-issue Recall@k / MRR with the ontology off vs on (free)")
    ap.add_argument("--audit-db", type=Path, nargs="?", const=APP_DB, default=None, help="audit agent_events in the app database (default path if none given)")
    ap.add_argument("--skip-run", action="store_true", help="do not run scenarios (use with --audit-db)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--out-json", type=Path, default=REPORT_DIR / "agent_metrics.json")
    ap.add_argument("--out-md", type=Path, default=REPORT_DIR / "agent_metrics.md")
    args = ap.parse_args()

    report: dict = {"meta": {"git_commit": git_commit(), "pythonhashseed": os.environ.get("PYTHONHASHSEED"), "date": time.strftime("%Y-%m-%d %H:%M"),
                             "env": {k: os.environ.get(k) for k in ("ONTOLOGY_MODE", "SYMPTOM_LIST", "SUPPLEMENTARY") if os.environ.get(k)}}}
    if os.environ.get("PYTHONHASHSEED") is None:
        print("note: PYTHONHASHSEED is not set; the Clarifier's tie-breaking then differs between runs. Set PYTHONHASHSEED=0 to compare configurations.")

    scenarios = []
    runs: list[list[dict]] = []
    if args.from_report:
        for p in args.from_report:
            data = json.loads(p.read_text(encoding="utf-8"))
            runs.append(data["rows"] if "rows" in data else data["runs"][0])
        report["meta"].update({"source": [str(p) for p in args.from_report]})
        ops = run_events = None
    elif not args.skip_run:
        from triage.sim.customer import load_scenarios
        scenarios = [s for s in load_scenarios(args.scenarios) if not args.ids or s.id in args.ids][:args.limit]
        runs, meta, events = run_all(scenarios, args.llm, max(1, args.repeats), args.verbose)
        run_events = events
        ops = ops_from_events(events)
        report["meta"].update(meta | {"scenario_file": str(args.scenarios or "scenarios.jsonl"), "scenarios": len(scenarios), "repeats": args.repeats,
                                      "unverified_labels": f"{sum('verified=False' in s.note for s in scenarios)} of {len(scenarios)}"})
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        (args.out_json.with_name(args.out_json.stem + "_rows.json")).write_text(json.dumps({"meta": report["meta"], "rows": runs[0], "runs": runs}, indent=1, default=str), encoding="utf-8")
    else:
        ops = run_events = None

    if runs:
        rows = [r for run in runs for r in run]
        report["major"] = {"1_resolution": resolution(runs), "3_retrieval": retrieval(rows), "4_safe_decisions": safe_decisions(rows),
                           "5_customer_effort": effort(rows), "6_cost_and_speed": cost_speed(rows)}
        report["minor"] = {"drafting_and_sources": drafting(rows)}
        if ops:
            report["minor"]["event_log_of_this_run"] = ops
        if args.judge:
            print(f"judging faithfulness with {args.judge} ...", flush=True)
            report["major"]["2_faithfulness"] = faithfulness(runs[0], args.judge, args.judge_limit, args.self_check)
        else:
            report["major"]["2_faithfulness"] = {"note": "not run: pass --judge gemini (the judge is a model call per sent fix)"}
        report["major"] = dict(sorted(report["major"].items()))
    if args.clarifier:
        from triage.sim.customer import load_scenarios
        print("running the Clarifier on its own ...", flush=True)
        report.setdefault("minor", {})["clarifier"] = clarifier_stage(scenarios or load_scenarios(args.scenarios))
    if args.ontology:
        from triage.sim.customer import load_scenarios
        print("retrieval with the ontology off vs on ...", flush=True)
        report.setdefault("minor", {})["ontology_off_vs_on"] = ontology_ablation(scenarios or load_scenarios(args.scenarios))
    if args.audit_db:
        if not args.audit_db.exists():
            raise SystemExit(f"no database at {args.audit_db}")
        report["logs"] = {"app_database": audit_events(load_db_events(args.audit_db))}
        if run_events:
            report["logs"]["this_run_jsonl"] = audit_events([{**e, "conversation_id": e.get("ticket_id")} for e in run_events])
        report["online"] = {"app_database": online_from_db(args.audit_db)}

    write_markdown(args.out_md, report)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if "major" in report:
        print("\nHEADLINE")
        print("\n".join(headline(report)))
    if "logs" in report:
        print("\nNOT LOGGED YET:", ", ".join(report["logs"]["app_database"]["not_logged"]) or "nothing missing")
    print(f"\nreport: {args.out_md}\njson:   {args.out_json}")


if __name__ == "__main__":
    main()
