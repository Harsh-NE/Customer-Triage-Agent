"""analytics.py -- dashboard numbers, each one a plain aggregate over stored rows (so every tile can be traced to data).

Definitions (shown to the UI in `definitions`, so nobody has to guess):
  resolution_rate  = resolved / (resolved + escalated)   -- active conversations are unfinished and declined requests are
                     out of scope, so neither counts for or against the agent
  agent_resolution_rate = resolved by the agent / the same denominator
  decline_rate     = declined / all finished conversations
  cost             = sum of per-call costs from triage/pricing.json; calls whose model has no price are COUNTED
                     (`unpriced_calls`) and excluded from the sum, never priced at zero silently
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Optional

from sqlalchemy import select

from triage.api.db import AgentEvent, Conversation, Message, utcnow

DEFINITIONS = {
    "resolution_rate": "resolved / (resolved + escalated); active and declined (out of scope) conversations are excluded",
    "agent_resolution_rate": "resolved by the agent alone / (resolved + escalated)",
    "decline_rate": "declined (out of scope) / finished conversations",
    "cost": "sum of per-call cost from triage/pricing.json; calls on models without a price are counted separately as unpriced",
    "verify_drop_rate": "fix steps removed by the citation/command check / steps drafted",
}


def _rate(n: float, d: float) -> Optional[float]:
    return round(n / d, 4) if d else None


def _since(days: int):
    return utcnow() - timedelta(days=days)


def _convs(s, days: int) -> list[Conversation]:
    return list(s.scalars(select(Conversation).where(Conversation.created_at >= _since(days))))


def _events(s, ids: list[str]) -> list[AgentEvent]:
    if not ids:
        return []
    out: list[AgentEvent] = []
    for i in range(0, len(ids), 500):           # stay under SQLite's bound-parameter limit
        out += list(s.scalars(select(AgentEvent).where(AgentEvent.conversation_id.in_(ids[i:i + 500]))))
    return out


def _cost_block(events: list[AgentEvent], convs: list[Conversation]) -> dict:
    calls = [e for e in events if e.event == "llm_call"]
    priced = [e for e in calls if e.cost_usd is not None]
    total = sum(e.cost_usd for e in priced)
    by_conv: dict[str, float] = defaultdict(float)
    for e in priced:
        by_conv[e.conversation_id] += e.cost_usd
    status = {c.id: c.status for c in convs}
    def avg(which: str):
        ids = [i for i in by_conv if status.get(i) == which]
        return round(sum(by_conv[i] for i in ids) / len(ids), 8) if ids else None
    return {"input_tokens": sum(e.input_tokens for e in calls), "output_tokens": sum(e.output_tokens for e in calls),
            "total_tokens": sum(e.input_tokens + e.output_tokens for e in calls), "llm_calls": len(calls),
            "unpriced_calls": len(calls) - len(priced), "total_cost_usd": round(total, 8),
            "avg_cost_per_conversation_usd": round(total / len(by_conv), 8) if by_conv else None,
            "avg_cost_resolved_usd": avg("resolved"), "avg_cost_escalated_usd": avg("escalated")}


def summary(s, days: int = 30) -> dict:
    convs = _convs(s, days)
    ids = [c.id for c in convs]
    events = _events(s, ids)
    by_status = Counter(c.status for c in convs)
    resolved, escalated = by_status["resolved"], by_status["escalated"]
    resolved_agent = sum(1 for c in convs if c.status == "resolved" and c.resolved_by == "agent")
    finished = resolved + escalated + by_status["declined"]
    closed_times = [(c.closed_at - c.created_at).total_seconds() for c in convs if c.status == "resolved" and c.closed_at]
    agent_times = [(c.closed_at - c.created_at).total_seconds() for c in convs if c.resolved_by == "agent" and c.closed_at]
    rated = [c.rating for c in convs if c.rating is not None]
    helpful = [c.helpful for c in convs if c.helpful is not None]

    questions = Counter(m.conversation_id for m in s.scalars(select(Message).where(Message.conversation_id.in_(ids), Message.kind == "question"))) if ids else Counter()
    lookups = [e for e in events if e.event == "cache_lookup"]
    hits = [e for e in lookups if str((e.data or {}).get("status", "")).startswith("hit")]
    verifies = [e for e in events if e.event == "verify"]
    kept = sum(int((e.data or {}).get("kept") or 0) for e in verifies)
    dropped = sum(len((e.data or {}).get("dropped") or []) for e in verifies)
    gates = [e for e in events if e.event == "gate"]
    reasons = Counter(c.escalation_reason for c in convs if c.status == "escalated" or (c.status == "resolved" and c.resolved_by == "engineer"))

    return {
        "window_days": days, "definitions": DEFINITIONS,
        "totals": {"conversations": len(convs), "active": by_status["active"], "resolved": resolved, "resolved_by_agent": resolved_agent,
                   "resolved_by_engineer": resolved - resolved_agent, "escalated_open": escalated, "declined": by_status["declined"]},
        "rates": {"resolution_rate": _rate(resolved, resolved + escalated), "agent_resolution_rate": _rate(resolved_agent, resolved + escalated),
                  "escalation_rate": _rate(escalated + (resolved - resolved_agent), resolved + escalated),
                  "decline_rate": _rate(by_status["declined"], finished)},
        "timing": {"avg_time_to_resolution_s": round(sum(closed_times) / len(closed_times), 1) if closed_times else None,
                   "avg_agent_resolution_s": round(sum(agent_times) / len(agent_times), 1) if agent_times else None},
        "feedback": {"avg_rating": round(sum(rated) / len(rated), 2) if rated else None, "ratings": len(rated),
                     "helpful_rate": _rate(sum(1 for h in helpful if h), len(helpful)), "helpful_votes": len(helpful)},
        "agent_behaviour": {"avg_questions_per_conversation": round(sum(questions.values()) / len(convs), 2) if convs else None,
                            "cache_lookups": len(lookups), "cache_hit_rate": _rate(len(hits), len(lookups)),
                            "verify_drop_rate": _rate(dropped, kept + dropped), "avg_gate_confidence":
                            round(sum(float((e.data or {}).get("confidence") or 0) for e in gates) / len(gates), 3) if gates else None},
        "escalation_reasons": dict(reasons), "cost": _cost_block(events, convs),
    }


def timeseries(s, days: int = 30) -> list[dict]:
    per_day: dict[str, Counter] = defaultdict(Counter)
    for c in _convs(s, days):
        per_day[c.created_at.date().isoformat()]["created"] += 1
        per_day[c.created_at.date().isoformat()][c.status] += 1
    return [{"date": d, **{k: per_day[d].get(k, 0) for k in ("created", "resolved", "escalated", "declined", "active")}} for d in sorted(per_day)]


def cost(s, days: int = 30) -> dict:
    convs = _convs(s, days)
    events = [e for e in _events(s, [c.id for c in convs]) if e.event == "llm_call"]
    by_model: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0})
    by_node: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0})
    by_day: dict[str, float] = defaultdict(float)
    for e in events:
        for bucket in (by_model[e.model or "unknown"], by_node[e.node or "unknown"]):
            bucket["calls"] += 1
            bucket["input_tokens"] += e.input_tokens
            bucket["output_tokens"] += e.output_tokens
            if e.cost_usd is None:
                bucket["unpriced_calls"] += 1
            else:
                bucket["cost_usd"] = round(bucket["cost_usd"] + e.cost_usd, 8)
        if e.cost_usd is not None:
            by_day[e.ts.date().isoformat()] += e.cost_usd
    return {"window_days": days, "overall": _cost_block(events, convs), "by_model": by_model, "by_node": by_node,
            "by_day": [{"date": d, "cost_usd": round(v, 8)} for d, v in sorted(by_day.items())]}
