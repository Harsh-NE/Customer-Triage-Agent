"""telemetry.py -- one flat record per query (the raw log), and the cache, latency and cost summaries built from those records.

A record says which arm and phase it came from, what happened (outcome, questions, was the first fix right) and what it cost (model calls,
tokens, USD, milliseconds). The cost and cache fields come from the events logged while the case ran.

Definitions (they are also printed in the comparison table):
  cache hit rate     cases whose answer was served from the cache (exact or semantic match) / cases that consulted the cache
  cache precision    served answers whose first fix was the gold fix / served answers.  False-hit rate = 1 - precision.
                     A cache hit on a case with no documented answer counts as a false hit.
  end-to-end latency seconds from the customer's first message to the end of the case, as p50 / p95. (The simulated customer
                     replies instantly, so this is the system's own time.)
  cost savings       model calls, tokens and USD avoided: the cache's estimated share, and the difference from the baseline arm.
"""

from __future__ import annotations

import statistics

from triage.eval import agent_metrics as M
from triage.eval.e2e_eval import usage_of

SERVED = ("hit_exact", "hit_semantic")            # CacheStatus values that answer without drafting


def _sum_or_none(values):
    return None if any(v is None for v in values) else round(sum(values), 9)       # one Jev call costs about 0.00001 USD


def case_record(arm: str, phase: str, row: dict, events: list[dict], features: dict) -> dict:
    """The raw log line for one query. `events` are the events logged while this case ran."""
    lookups = [e for e in events if e["event"] == "cache_lookup"]
    status = lookups[0]["status"] if lookups else "none"
    first_fix = row["fixes_sent"][0] if row["fixes_sent"] else None
    llm, jev = usage_of(events), [e for e in events if e["event"] == "jev_call"]
    jev_p = next((e["p"] for e in jev if e.get("p") is not None), None)
    return {
        "arm": arm, "phase": phase, "features": features, "id": row["id"], "opening": row["opening"],
        "has_gold": row["has_gold"], "outcome": row["outcome"], "escalation_reason": row["escalation_reason"],
        "questions": row["questions"], "fixes_sent": len(row["fixes_sent"]), "first_fix_gold": bool(first_fix and first_fix["gold"]),
        "cache_status": status, "cache_similarity": lookups[0].get("similarity") if lookups else None,
        "cache_served": status in SERVED, "cache_served_correct": status in SERVED and bool(first_fix and first_fix["gold"]),
        "latency_s": row["total_s"], "first_fix_s": row.get("first_fix_s"),
        "retrieval_ms": [e["latency_ms"] for e in events if e["event"] == "retrieval"],
        "stage_ms": {e["stage"]: e["latency_ms"] for e in events if e["event"] == "stage_timing"},
        "llm_calls": llm["llm_calls"], "input_tokens": llm["input_tokens"], "output_tokens": llm["output_tokens"],
        "cost_usd": llm["cost_usd"],
        "jev_calls": len(jev), "jev_input_tokens": sum(e.get("input_tokens") or 0 for e in jev),
        "jev_cost_usd": _sum_or_none([e.get("cost_usd") for e in jev if not e.get("error")]) if jev else 0.0,
        "jev_p": jev_p, "jev_overrides": sum(bool(e.get("override")) for e in jev), "jev_errors": sum(bool(e.get("error")) for e in jev),
    }


def cache_summary(records: list[dict]) -> dict:
    lookups = [r for r in records if r["cache_status"] != "none"]
    served = [r for r in lookups if r["cache_served"]]
    right = sum(r["cache_served_correct"] for r in served)
    return {"cases_that_consulted_the_cache": len(lookups),
            "hit_rate": M.rate(len(served), len(lookups)),
            "redraft_rate": M.rate(sum(r["cache_status"] == "hit_redraft" for r in lookups), len(lookups)),
            "precision": M.rate(right, len(served)),
            "false_hit_rate": M.rate(len(served) - right, len(served))}


def latency_summary(records: list[dict]) -> dict:
    ms = lambda key: [r[key] * 1000 for r in records if r[key] is not None]           # noqa: E731
    by_phase = {p: M.dist([r["latency_s"] * 1000 for r in records if r["phase"] == p]) for p in sorted({r["phase"] for r in records})}
    # Like for like: a first ask that was searched and resolved, against a repeat that the cache answered. (Repeats that escalated or were
    # rejected never reach the cache, and comparing them with full resolutions measures the mix of cases, not the cache.)
    full = [r["latency_s"] for r in records if r["phase"] == "first_ask" and r["cache_status"] == "miss" and r["outcome"] == "resolved"]
    cached = [r["latency_s"] for r in records if r["phase"] == "repeat" and r["cache_served"]]
    return {"end_to_end_ms": M.dist(ms("latency_s")), "first_fix_ms": M.dist(ms("first_fix_s")),
            "retrieval_ms": M.dist([x for r in records for x in r["retrieval_ms"]]), "end_to_end_ms_by_phase": by_phase,
            "repeat_speedup": round(M.percentile(full, 0.5) / M.percentile(cached, 0.5), 2) if full and cached else None}


def cost_summary(records: list[dict]) -> dict:
    llm_cost = _sum_or_none([r["cost_usd"] for r in records if r["llm_calls"]])      # None when a called model has no price
    jev_cost = _sum_or_none([r["jev_cost_usd"] for r in records])
    return {"cases": len(records), "llm_calls": sum(r["llm_calls"] for r in records),
            "llm_errors": sum(r.get("llm_errors", 0) for r in records), "llm_retries": sum(r.get("llm_retries", 0) for r in records),
            "input_tokens": sum(r["input_tokens"] + r["jev_input_tokens"] for r in records),
            "output_tokens": sum(r["output_tokens"] for r in records), "jev_calls": sum(r["jev_calls"] for r in records),
            "jev_overrides": sum(r.get("jev_overrides", 0) for r in records), "jev_errors": sum(r.get("jev_errors", 0) for r in records),
            "cost_usd": None if llm_cost is None or jev_cost is None else round(llm_cost + jev_cost, 9)}


def cache_savings(records: list[dict]) -> dict:
    """What the cache avoided, estimated: a served case would have cost what the average case that drafted cost, minus what it did cost
    (the customer's reply is still classified, so a served case is not free)."""
    served = [r for r in records if r["cache_served"]]
    paid = [r for r in records if not r["cache_served"] and r["llm_calls"]]
    out = {"served_from_cache": len(served)}
    for key in ("llm_calls", "input_tokens", "output_tokens", "cost_usd"):
        paid_values = [r[key] for r in paid]
        served_values = [0 if r[key] is None and not r["llm_calls"] else r[key] for r in served]       # no call, no cost
        usable = paid_values and None not in paid_values + served_values
        out[f"avoided_{key}"] = (round(len(served) * (statistics.mean(paid_values) - (statistics.mean(served_values) if served_values else 0)), 6)
                                 if usable else None)
    return out


def versus(totals: dict, baseline: dict) -> dict:
    """Percent of the baseline arm's calls, tokens and USD that this arm avoided (negative: it used more)."""
    save = lambda key: (round(100 * (1 - totals[key] / baseline[key]), 1)          # noqa: E731
                        if totals.get(key) is not None and baseline.get(key) else None)
    return {f"{key}_saved_vs_baseline": save(key) for key in ("llm_calls", "input_tokens", "cost_usd")}
