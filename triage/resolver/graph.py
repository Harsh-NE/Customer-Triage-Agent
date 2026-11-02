"""B3 — the Resolver agent as a LangGraph subgraph.

    guard ─┬─ reject / hard-escalate ───────────────────────────────► escalate
           ├─ signature too incomplete ─────────────────────────────► to_clarifier
           └─► cache_lookup ─┬─ hit (exact / semantic) ──► verify
                             ├─ hit (redraft) ───────────► draft
                             └─ miss ─► retrieve(kb) ─► gate
    gate ─┬─ strong ─► draft ─► verify ─┬─ ok ─► send ─► await_reply ─► classify
          ├─ weak, tier=kb ─► retrieve(tickets) ─► gate     └─ fail ─► fallback / escalate
          └─ weak, tier=tickets ─► escalate
    classify ─┬─ resolved ─► close_resolved (write cache)
              ├─ not_fixed ─► retry (exclude tried evidence) or escalate RETRY_EXHAUSTED
              ├─ new_info ─► to_clarifier
              └─ off_topic ─► nudge ─► await_reply   (once), then escalate

MERGE CONTRACT (J1):
  * Reads  state["signature"] (dict form of ProblemSignature) — written by A's Clarifier.
  * Writes every B-owned key in TriageState plus state["next"]:
        "clarifier" -> parent graph should route to A's Clarifier, then back here
        "end"       -> conversation finished (resolved / escalated / rejected)
  * Customer turns use langgraph.types.interrupt(); the parent resumes with
    Command(resume="<customer text>"). A's Clarifier must use the same convention.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from triage.resolver.cache import NegativeCache, SemanticCache
from triage.resolver.feedback import ABMetrics, FeedbackCollector, TraceLogger
from triage.resolver.config import ResolverConfig
from triage.resolver.contracts import (CacheStatus, EscalationReason, Evidence, GateDecision, Outcome,
                              ProblemSignature, ReplyLabel, TriageRecord, TriageState)
from triage.resolver.escalate import build_payload, customer_message
from triage.resolver.sentiment import SentimentState, should_early_escalate, update_sentiment
from triage.resolver.guardrails import check_input, hard_escalation
from triage.resolver.llm import LLM, FakeLLM
from triage.resolver.oplog import NULL_LOGGER, EventLogger, estimate_cost
from triage.resolver.gate import assess
from triage.resolver.steps import (classify_reply, draft_resolution, expand_queries,
                                    multi_draft_resolution, render_message, select_best_draft,
                                    summarize_fix_history, verify_draft)
from triage.resolver.retrieval import HybridRetriever, Retriever


@dataclass
class ResolverDeps:
    retriever: Retriever
    llm: LLM = field(default_factory=FakeLLM)
    cache: Optional[SemanticCache] = None
    negative_cache: Optional[NegativeCache] = None
    feedback: Optional[FeedbackCollector] = None
    tracer: Optional[TraceLogger] = None
    ab_metrics: Optional[ABMetrics] = None
    logger: EventLogger = NULL_LOGGER
    cfg: ResolverConfig = field(default_factory=ResolverConfig)


def _sig(state: TriageState) -> ProblemSignature:
    return ProblemSignature.from_dict(state["signature"])


def _evs(state: TriageState) -> list[Evidence]:
    return [Evidence.from_dict(e) for e in state.get("evidence") or []]


def build_resolver_graph(deps: ResolverDeps) -> StateGraph:
    cfg, log = deps.cfg, deps.logger

    def _llm_logged(node: str, state: TriageState, fn, *args):
        with log.timed("llm_call", ticket_id=state.get("ticket_id"), node=node,
                       model=getattr(deps.llm, "name", "unknown")) as ev:
            out = fn(*args)
            usage = getattr(deps.llm, "last_usage", {}) or {}
            ev.update(usage)
            ev["cost_usd"] = estimate_cost(getattr(deps.llm, "model", "default"), usage)
        return out

    # ------------------------------------------------------------------ nodes
    def guard(state: TriageState) -> dict[str, Any]:
        sig = _sig(state)
        text = state.get("customer_message") or sig.raw_query
        g = check_input(text, sig)
        if not g.allowed:
            log.log("guardrail", ticket_id=state.get("ticket_id"), result="blocked", detail=g.detail)
            return {"escalation_reason": g.reason.value, "gate_decision": GateDecision.ESCALATE.value,
                    "gate_detail": {"guardrail": g.detail}, "outcome": Outcome.REJECTED.value}
        hard = hard_escalation(sig)
        if hard:
            log.log("guardrail", ticket_id=state.get("ticket_id"), result="hard_escalation",
                    detail=hard.value)
            return {"escalation_reason": hard.value, "gate_decision": GateDecision.ESCALATE.value}
        if (sig.completeness < cfg.gate.min_completeness
                and state.get("clarify_returns", 0) < cfg.max_clarify_returns
                and not state.get("attempts")):
            return {"gate_decision": GateDecision.CLARIFY.value}
        return {"gate_decision": "", "escalation_reason": None, "tier": "kb",
                "outcome": Outcome.IN_PROGRESS.value}

    def route_guard(state: TriageState) -> str:
        if state.get("gate_decision") == GateDecision.ESCALATE.value:
            return "escalate"
        if state.get("gate_decision") == GateDecision.CLARIFY.value:
            return "to_clarifier"
        # Start trace for this ticket
        if deps.tracer is not None:
            deps.tracer.start(state.get("ticket_id", "unknown"))
            deps.tracer.add_span(state.get("ticket_id", "unknown"), "guard")
        return "cache_lookup"

    def cache_lookup(state: TriageState) -> dict[str, Any]:
        if deps.cache is None or state.get("attempts"):
            return {"cache_status": CacheStatus.BYPASSED.value, "cache_entry_id": None}
        res = deps.cache.lookup(_sig(state))
        log.log("cache_lookup", ticket_id=state.get("ticket_id"), status=res.status.value,
                similarity=res.similarity, rejected_by_gate=res.rejected_by_gate)
        upd: dict[str, Any] = {"cache_status": res.status.value,
                               "cache_entry_id": res.entry.entry_id if res.entry else None}
        if res.entry and res.status != CacheStatus.MISS:
            upd["evidence"] = res.entry.evidence
            upd["tier"] = res.entry.evidence[0]["tier"] if res.entry.evidence else "kb"
            if res.status in (CacheStatus.HIT_EXACT, CacheStatus.HIT_SEMANTIC):
                upd["draft"] = res.entry.draft
                upd["confidence"] = 1.0 if res.status == CacheStatus.HIT_EXACT else res.similarity
        return upd

    def route_cache(state: TriageState) -> str:
        st = state.get("cache_status")
        if st in (CacheStatus.HIT_EXACT.value, CacheStatus.HIT_SEMANTIC.value):
            return "verify"
        if st == CacheStatus.HIT_REDRAFT.value:
            return "draft"
        return "retrieve"

    def retrieve(state: TriageState) -> dict[str, Any]:
        sig, tier = _sig(state), state.get("tier") or "kb"
        excluded = state.get("tried_evidence_ids") or []
        with log.timed("retrieval", ticket_id=state.get("ticket_id"), tier=tier) as ev:
            # Query expansion: LLM rewrites signature into 2-3 search queries
            queries = _llm_logged("expand_queries", state, expand_queries, deps.llm, sig)
            ev["queries"] = queries
            # Hybrid retrieve: run all queries, fuse via RRF
            hybrid = HybridRetriever(deps.retriever)
            results = hybrid.retrieve_multi(queries, sig, k=cfg.k, tier=tier,
                                            exclude_chunk_ids=excluded)
            ev["n"] = len(results)
            ev["top_score"] = results[0].rerank_score if results else None
        return {"evidence": [e.to_dict() for e in results]}

    def gate(state: TriageState) -> dict[str, Any]:
        sig, evs = _sig(state), _evs(state)
        g = assess(evs, sig, cfg.gate)
        tier = state.get("tier") or "kb"
        if g.strong:
            decision = GateDecision.RESOLVE
        elif tier == "kb" and cfg.use_ticket_fallback:
            decision = GateDecision.FALLBACK
        else:
            decision = GateDecision.ESCALATE
        log.log("gate", ticket_id=state.get("ticket_id"), tier=tier, decision=decision.value,
                **g.to_dict())
        upd: dict[str, Any] = {"confidence": g.confidence, "gate_decision": decision.value,
                               "gate_detail": {**g.to_dict(), "tier": tier}}
        if decision == GateDecision.FALLBACK:
            upd["tier"] = "tickets"
        if decision == GateDecision.ESCALATE:
            upd["escalation_reason"] = (EscalationReason.RETRY_EXHAUSTED if state.get("attempts")
                                        else EscalationReason.LOW_EVIDENCE).value
        return upd

    def route_gate(state: TriageState) -> str:
        return {GateDecision.RESOLVE.value: "draft", GateDecision.FALLBACK.value: "retrieve"}.get(
            state.get("gate_decision"), "escalate")

    def draft(state: TriageState) -> dict[str, Any]:
        sig, evs = _sig(state), _evs(state)
        attempts = state.get("attempts") or []
        # Smart retry: summarize what each fix revealed instead of flat list
        if attempts:
            tried = [summarize_fix_history(attempts)]
        # Negative cache: filter out known-bad diagnoses
        neg_skipped = []
        if deps.negative_cache is not None:
            sig = _sig(state)
            for ev in evidence:
                diag = ev.text[:200] if hasattr(ev, "text") else ""
                hit = deps.negative_cache.check(sig, diag)
                if hit:
                    neg_skipped.append(hit.entry_id)
            if neg_skipped:
                log.log("neg_cache_skip", ticket_id=state.get("ticket_id"),
                        skipped=len(neg_skipped))
        else:
            tried = []
        last_reply = (attempts or [{}])[-1].get("customer_reply")
        # Multi-draft: generate 3 drafts, pick the one with the best verify pass rate
        drafts = _llm_logged("multi_draft", state, multi_draft_resolution,
                             deps.llm, sig, evs, tried, last_reply, cfg.n_drafts)
        best, best_verify = select_best_draft(drafts, evs)
        log.log("multi_draft", ticket_id=state.get("ticket_id"),
                n_drafts=len(drafts), best_pass_rate=len(best_verify.steps) / max(len(best.get("steps", [])), 1))
        return {"draft": best}

    def verify(state: TriageState) -> dict[str, Any]:
        evs = _evs(state)
        v = verify_draft(state.get("draft") or {}, evs)
        log.log("verify", ticket_id=state.get("ticket_id"), ok=v.ok, kept=len(v.steps),
                dropped=v.dropped)
        d = dict(state.get("draft") or {})
        d["steps"] = v.steps
        upd: dict[str, Any] = {"draft": d, "gate_decision": "verified" if v.ok else "verify_failed"}
        if not v.ok:
            if (state.get("tier") or "kb") == "kb" and cfg.use_ticket_fallback:
                upd["tier"] = "tickets"
            else:
                upd["escalation_reason"] = (EscalationReason.RETRY_EXHAUSTED if state.get("attempts")
                                            else EscalationReason.VERIFICATION_FAILED).value
        return upd

    def route_verify(state: TriageState) -> str:
        if state.get("gate_decision") == "verified":
            return "send"
        return "escalate" if state.get("escalation_reason") else "retrieve"

    def send(state: TriageState) -> dict[str, Any]:
        d, evs = state["draft"], _evs(state)
        msg = render_message(d, d["steps"], evs)
        cited = sorted({i for s in d["steps"] for i in s["evidence_ids"]})
        by_id = {e.evidence_id: e for e in evs}
        attempts = list(state.get("attempts") or [])
        attempts.append({"attempt_no": len(attempts) + 1, "diagnosis": d.get("diagnosis", ""),
                         "steps": d["steps"], "evidence_ids": cited,
                         "chunk_ids": [by_id[i].chunk_id for i in cited if i in by_id],
                         "tier": state.get("tier") or "kb", "customer_reply": None,
                         "reply_label": None})
        tried = list(state.get("tried_evidence_ids") or [])
        tried += [by_id[i].chunk_id for i in cited if i in by_id and by_id[i].chunk_id not in tried]
        transcript = list(state.get("transcript") or []) + [{"role": "assistant", "content": msg}]
        return {"attempts": attempts, "tried_evidence_ids": tried, "transcript": transcript,
                "last_assistant_message": msg}

    def await_reply(state: TriageState) -> dict[str, Any]:
        # Nothing before interrupt() may have side effects: the node re-runs on resume.
        reply = interrupt({"type": "resolver_message", "ticket_id": state.get("ticket_id"),
                           "message": state.get("last_assistant_message", "")})
        transcript = list(state.get("transcript") or []) + [{"role": "user", "content": str(reply)}]
        return {"customer_message": str(reply), "transcript": transcript}

    def classify(state: TriageState) -> dict[str, Any]:
        reply = state.get("customer_message", "")
        label = _llm_logged("classify", state, classify_reply, deps.llm,
                            state.get("last_assistant_message", ""), reply)
        attempts = [dict(a) for a in state.get("attempts") or []]
        if attempts and attempts[-1].get("customer_reply") is None:
            attempts[-1]["customer_reply"] = reply
            attempts[-1]["reply_label"] = label.value
        # Sentiment tracking
        sentiment = update_sentiment(
            SentimentState.from_dict(state.get("sentiment")), reply)
        log.log("sentiment", ticket_id=state.get("ticket_id"),
                turn_score=sentiment.scores[-1] if sentiment.scores else 0,
                current=sentiment.current)
        return {"reply_label": label.value, "attempts": attempts,
                "sentiment": sentiment.to_dict()}

    def route_classify(state: TriageState) -> str:
        label = state.get("reply_label")
        if label == ReplyLabel.RESOLVED.value:
            return "close_resolved"
        if label == ReplyLabel.NEW_INFO.value and state.get("clarify_returns", 0) < cfg.max_clarify_returns:
            return "to_clarifier"
        if label == ReplyLabel.OFF_TOPIC.value:
            return "nudge" if state.get("off_topic_count", 0) < 1 else "escalate_off_topic"
        # Partial: some steps worked, re-draft only the failed ones
        if label == ReplyLabel.PARTIAL.value:
            n_attempts = len(state.get("attempts") or [])
            if n_attempts < cfg.max_attempts:
                return "prepare_partial_retry"
            return "escalate_retry"
        # Sentiment-gated early escalation
        sentiment = SentimentState.from_dict(state.get("sentiment"))
        n_attempts = len(state.get("attempts") or [])
        if should_early_escalate(sentiment, n_attempts):
            log.log("sentiment_escalation", ticket_id=state.get("ticket_id"),
                    frustration=sentiment.current, attempts=n_attempts)
            return "escalate_retry"
        if n_attempts < cfg.max_attempts:
            return "prepare_retry"
        return "escalate_retry"

    def prepare_retry(state: TriageState) -> dict[str, Any]:
        # Write negative cache entry for the failed attempt
        if deps.negative_cache is not None:
            last = (state.get("attempts") or [{}])[-1]
            deps.negative_cache.put(
                _sig(state),
                diagnosis=last.get("diagnosis", ""),
                fix_summary=last.get("fix_snippet", ""),
                failure_reason=last.get("customer_reply", "not resolved"),
                reply_label=last.get("reply_label", "not_resolved"))
        return {"tier": "kb", "draft": None, "gate_decision": ""}

    def prepare_partial_retry(state: TriageState) -> dict[str, Any]:
        """For partial success: keep working steps, re-draft only failed ones."""
        log.log("partial_retry", ticket_id=state.get("ticket_id"))
        return {"tier": "kb", "draft": None, "gate_decision": ""}

    def nudge(state: TriageState) -> dict[str, Any]:
        msg = ("I want to make sure we fix your Docker issue. Did the steps above solve it, "
               "or are you still seeing the problem?")
        transcript = list(state.get("transcript") or []) + [{"role": "assistant", "content": msg}]
        return {"transcript": transcript, "last_assistant_message": msg,
                "off_topic_count": state.get("off_topic_count", 0) + 1}

    def set_reason(reason: EscalationReason):
        """NOTE: trace finalization added below in the returned closure."""
        def _node(state: TriageState) -> dict[str, Any]:
            return {"escalation_reason": reason.value}
        return _node

    def close_resolved(state: TriageState) -> dict[str, Any]:
        if deps.cache is not None and state.get("cache_status") not in (
                CacheStatus.HIT_EXACT.value, CacheStatus.HIT_SEMANTIC.value):
            last = (state.get("attempts") or [{}])[-1]
            cited = set(last.get("evidence_ids") or [])
            evidence = [e for e in state.get("evidence") or [] if e["evidence_id"] in cited]
            deps.cache.put(_sig(state), state.get("draft") or {}, evidence, confirmed_by="customer")
            # Invalidate negative cache entries for this now-resolved problem
            if deps.negative_cache is not None:
                deps.negative_cache.invalidate_for_signature(_sig(state))
        # Trace: finalize
        if deps.tracer is not None:
            deps.tracer.finalize(
                state.get("ticket_id", "unknown"), outcome="resolved",
                cache_status=state.get("cache_status", ""),
                evidence_count=len(state.get("evidence") or []),
                attempts=len(state.get("attempts") or []))
        # A/B metrics
        if deps.ab_metrics is not None:
            deps.ab_metrics.record(
                ticket_id=state.get("ticket_id", "unknown"),
                resolved=True,
                attempts=len(state.get("attempts") or []),
                latency_ms=0.0)  # filled by caller if needed
        msg = "Glad that fixed it. I've recorded the solution so similar issues get resolved faster."
        transcript = list(state.get("transcript") or []) + [{"role": "assistant", "content": msg}]
        log.log("outcome", ticket_id=state.get("ticket_id"), outcome="resolved",
                attempts=len(state.get("attempts") or []))
        return {"outcome": Outcome.RESOLVED.value, "next": "end", "transcript": transcript}

    def to_clarifier(state: TriageState) -> dict[str, Any]:
        log.log("handoff", ticket_id=state.get("ticket_id"), to="clarifier")
        return {"outcome": Outcome.NEEDS_CLARIFICATION.value, "next": "clarifier",
                "clarify_returns": state.get("clarify_returns", 0) + 1}

    def escalate(state: TriageState) -> dict[str, Any]:
        reason = EscalationReason(state.get("escalation_reason") or EscalationReason.LOW_EVIDENCE.value)
        payload = build_payload(state, reason, detail=str(state.get("gate_detail") or ""))
        transcript = list(state.get("transcript") or []) + [
            {"role": "assistant", "content": customer_message(reason)}]
        outcome = (Outcome.REJECTED.value if state.get("outcome") == Outcome.REJECTED.value
                   else Outcome.ESCALATED.value)
        log.log("escalation", ticket_id=state.get("ticket_id"), reason=reason.value,
                priority=payload["priority"])
        return {"escalation_payload": payload, "outcome": outcome, "next": "end",
                "transcript": transcript}

    # ------------------------------------------------------------------ wiring
    g = StateGraph(TriageState)
    for name, fn in [("guard", guard), ("cache_lookup", cache_lookup), ("retrieve", retrieve),
                     ("gate", gate), ("draft", draft), ("verify", verify), ("send", send),
                     ("await_reply", await_reply), ("classify", classify),
                     ("prepare_retry", prepare_retry), ("prepare_partial_retry", prepare_partial_retry),
                     ("nudge", nudge),
                     ("escalate_retry", set_reason(EscalationReason.RETRY_EXHAUSTED)),
                     ("escalate_off_topic", set_reason(EscalationReason.OUT_OF_SCOPE)),
                     ("close_resolved", close_resolved), ("to_clarifier", to_clarifier),
                     ("escalate", escalate)]:
        g.add_node(name, fn)

    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", route_guard, ["escalate", "to_clarifier", "cache_lookup"])
    g.add_conditional_edges("cache_lookup", route_cache, ["verify", "draft", "retrieve"])
    g.add_edge("retrieve", "gate")
    g.add_conditional_edges("gate", route_gate, ["draft", "retrieve", "escalate"])
    g.add_edge("draft", "verify")
    g.add_conditional_edges("verify", route_verify, ["send", "retrieve", "escalate"])
    g.add_edge("send", "await_reply")
    g.add_edge("await_reply", "classify")
    g.add_conditional_edges("classify", route_classify,
                            ["close_resolved", "to_clarifier", "nudge", "escalate_off_topic",
                             "prepare_retry", "prepare_partial_retry", "escalate_retry"])
    g.add_edge("prepare_retry", "retrieve")
    g.add_edge("prepare_partial_retry", "retrieve")
    g.add_edge("nudge", "await_reply")
    g.add_edge("escalate_retry", "escalate")
    g.add_edge("escalate_off_topic", "escalate")
    for terminal in ("close_resolved", "to_clarifier", "escalate"):
        g.add_edge(terminal, END)
    return g


def build_resolver_app(deps: ResolverDeps, checkpointer=None):
    """Standalone compiled Resolver (solo development / tests). In J1 use
    build_resolver_graph(deps).compile() as a node inside the parent graph instead."""
    return build_resolver_graph(deps).compile(checkpointer=checkpointer or MemorySaver())


def to_triage_record(state: dict[str, Any]) -> TriageRecord:
    """Project graph state onto the shared TriageRecord (A7 schema)."""
    return TriageRecord(
        ticket_id=state.get("ticket_id") or TriageRecord().ticket_id,
        signature=state.get("signature"), transcript=state.get("transcript") or [],
        evidence_used=state.get("evidence") or [], attempts=state.get("attempts") or [],
        confidence=state.get("confidence"), gate_decision=state.get("gate_decision"),
        cache_status=state.get("cache_status") or CacheStatus.MISS.value,
        escalation_reason=state.get("escalation_reason"),
        escalation_payload=state.get("escalation_payload"),
        outcome=state.get("outcome") or Outcome.IN_PROGRESS.value)
