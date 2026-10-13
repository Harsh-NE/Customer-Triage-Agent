"""handoff.py -- the A <-> B seam: Clarifier output -> Resolver signature, and the Clarifier as a node of the joint graph.

Why a translation layer at all. The two members wrote their contracts from the same workplan but independently:
A's ProblemSignature (triage/state.py) is a differential diagnosis (fields + ranked KB-issue hypotheses + a confidence),
B's (resolver/contracts.py) is a flat query description (error strings, exit codes, severity, completeness). Neither is
changed; `to_resolver_signature` maps A's onto B's and passes the differential through in B's two optional fields
(`hypotheses`, `clarifier`), which is what lets the Resolver start from the issue the Clarifier already found.

`completeness` is B's gate input ("is the signature specific enough to retrieve on?"). A has no such number; A has a
verdict. READY -> 0.5 + 0.5 x p_top (0.75..1.0). UNRESOLVED (question budget spent, still ambiguous) -> exactly 0.5: it is
not sent back to the Clarifier (B's bounce rule is `< 0.5`; asking again would only repeat), but contributes little to the
confidence gate, so the Resolver needs strong evidence of its own or it escalates.

The Clarifier node asks the customer through LangGraph `interrupt()` (B's convention). A node re-runs from its top when the
graph resumes, so nothing with side effects may run before the interrupt: the node performs ONE Clarifier turn per
execution, and when that turn needs an answer it stores the question in state (`clarifier_pending`) and the graph routes
back to the node, which then interrupts first and processes the reply after.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from langgraph.types import interrupt

from triage import understand as U
from triage.clarifier import Clarifier
from triage.context_session import SessionMemory
from triage.resolver.contracts import ProblemSignature, Severity, TriageState
from triage.resolver.guardrails import DOMAIN_TERMS, INJECTION, SECRET_REQUEST
from triage.resolver.oplog import NULL_LOGGER, estimate_cost
from triage.resolver.scope import classify_scope
from triage.state import ClarifierResult, ClarifierStatus
from triage.state import ProblemSignature as ClarifierSignature

_EXIT_CODE = re.compile(r"(?i)\bexit(?:ed)?(?:\s+with)?(?:\s+(?:status|code))?\s*[:=]?\s*(\d{1,3})\b")
_SEVERITY = {s.value: s for s in Severity}
UNRESOLVED_COMPLETENESS = 0.5
NO_SYMPTOM_COMPLETENESS = 0.3        # the Clarifier gave up and the customer never described a problem ("help", "docker")
CLARIFIER_EXHAUSTED = 99             # clarify_returns value meaning "the Clarifier has nothing more to ask"


# Obvious out-of-scope requests should be declined at once: no clarifying questions, no engineer handoff. Two signals, both
# deliberately narrow because a wrong "out of scope" turns away a real customer: the customer says it is not Docker, or
# names a well-known non-Docker service while using no Docker vocabulary at all ("my netflix container fails" is in scope).
NOT_DOCKER = re.compile(r"(?i)\b(?:not|isn'?t|is not|nothing to do with|unrelated to|no relation to)\s+(?:about\s+|with\s+|a\s+)?docker\b")
FOREIGN_SERVICE = re.compile(
    r"(?i)\b(netflix|spotify|youtube|instagram|facebook|whatsapp|tiktok|snapchat|twitter|gmail|outlook|hotmail|icloud|paypal|venmo|"
    r"hulu|disney\+?|playstation|xbox|steam|roblox|minecraft|fortnite|zoom|photoshop|excel|powerpoint|uber|tinder)\b")


def clearly_out_of_scope(customer_text: str) -> bool:
    if NOT_DOCKER.search(customer_text):
        return True
    return bool(FOREIGN_SERVICE.search(customer_text)) and not DOMAIN_TERMS.search(customer_text)


def completeness_of(result: ClarifierResult) -> float:
    if result.status is ClarifierStatus.READY and result.signature:
        return round(0.5 + 0.5 * min(max(result.signature.confidence.p_top, 0.0), 1.0), 3)
    if result.signature and any(g.hard for g in U.detect_gaps(result.signature.fields)):
        return NO_SYMPTOM_COMPLETENESS
    return UNRESOLVED_COMPLETENESS


def _hypothesis_dicts(sig: ClarifierSignature, limit: int = 3) -> list[dict[str, Any]]:
    return [{"label": h.label, "issue": h.features.get("issue", ""), "weight": round(h.weight, 4),
             "chunk_ids": list(h.chunk_ids), "grounding": h.grounding, "missing_terms": list(h.missing_terms)}
            for h in sig.hypotheses[:limit]]


def to_resolver_signature(result: ClarifierResult, session: SessionMemory) -> ProblemSignature:
    """A's READY/UNRESOLVED result -> B's ProblemSignature (see the module docstring for the mapping rules)."""
    sig = result.signature
    if sig is None:
        raise ValueError("a READY/UNRESOLVED ClarifierResult always carries a signature")
    f = sig.fields
    customer_text = "\n".join(t.text for t in session.customer_turns()).strip()     # already PII-redacted
    codes: list[int] = []
    for text in [*f.error_codes, *f.error_messages]:
        for m in _EXIT_CODE.findall(text):
            if int(m) <= 255 and int(m) not in codes:
                codes.append(int(m))
    inferred = (result.meta.get("inferred") or {}).get("product_area")
    environment = {k: v for k, v in {"os": f.platform, "detail": f.environment}.items() if v}
    top = _hypothesis_dicts(sig)
    return ProblemSignature(
        raw_query=customer_text or sig.nl_text,
        product_area=f.product_area or inferred, component=f.component,
        symptom="; ".join(f.symptoms)[:240] or None,
        error_strings=list(dict.fromkeys([*f.error_messages, *f.error_codes])),
        exit_codes=codes, versions=dict(f.versions), environment=environment,
        severity=_SEVERITY.get(str(f.severity).lower(), Severity.MEDIUM),
        missing_fields=[g.field for g in U.detect_gaps(f)],
        completeness=completeness_of(result), clarify_turns=result.questions_asked,
        hypotheses=top, entities=[dict(e) for e in sig.entities],
        clarifier={"status": result.status.value, "reason": result.reason, "p_top": round(sig.confidence.p_top, 4),
                   "margin": round(sig.confidence.margin, 4), "uncovered_terms": list(result.meta.get("uncovered_terms") or []),
                   "questions_asked": result.questions_asked, "canonical_string": sig.canonical_string})


def make_clarifier_node(clarifier: Clarifier, scope_llm: Any = None, logger: Any = None) -> Callable[[TriageState], dict[str, Any]]:
    """The Clarifier as a node of B's joint graph (replaces B's `stub_clarifier`). State in: `customer_message`
    (+ `clarifier_session`, `clarifier_pending`). State out: `signature` once READY/UNRESOLVED, else `clarifier_pending`.
    `scope_llm` (a Resolver-style LLM with complete_json) enables the one-call scope classifier on the FIRST message."""
    log = logger or NULL_LOGGER

    def node(state: TriageState) -> dict[str, Any]:
        raw = state.get("clarifier_session")
        session = SessionMemory.from_json(raw) if raw else clarifier.start(state.get("ticket_id"))
        transcript = list(state.get("transcript") or [])
        pending = state.get("clarifier_pending") or ""

        if pending:                                          # we are mid-conversation: show the question, wait, then process
            reply = str(interrupt({"type": "clarifier_question", "ticket_id": state.get("ticket_id"), "message": pending,
                                   "options": list(state.get("clarifier_options") or []),
                                   "feature": state.get("clarifier_feature") or ""}))
            transcript += [{"role": "assistant", "content": pending}, {"role": "user", "content": reply}]
            message = reply
        else:
            message = state.get("customer_message", "")
            if not transcript or transcript[-1] != {"role": "user", "content": message}:
                transcript.append({"role": "user", "content": message})

        if INJECTION.search(message) or SECRET_REQUEST.search(message):
            # Hostile text is not worth a clarifying question. Hand a minimal signature straight to B's guard, which
            # rejects it (prompt_injection / secret_request) and builds the escalation record in one place.
            sig = ProblemSignature(raw_query=message, completeness=1.0, clarifier={"status": "blocked_before_clarifier"})
            return {"transcript": transcript, "customer_message": message, "clarifier_pending": "", "next": "",
                    "signature": sig.to_dict()}

        everything_said = "\n".join([t.text for t in session.customer_turns()] + [message])
        decline: dict[str, Any] | None = {"source": "rule"} if clearly_out_of_scope(everything_said) else None
        if decline is None and scope_llm is not None and not raw and not pending:     # first message of the ticket only
            with log.timed("llm_call", ticket_id=state.get("ticket_id"), node="scope") as ev:
                verdict = classify_scope(scope_llm, message)
                usage = dict(getattr(scope_llm, "last_usage", None) or {})
                ev.update({"scope": verdict.scope, "confidence": verdict.confidence, "error": verdict.error, **usage,
                           "model": getattr(scope_llm, "model", None),
                           "cost_usd": estimate_cost(getattr(scope_llm, "model", ""), usage)})
            if verdict.decline:
                decline = {"source": "llm", "reason": verdict.reason, "confidence": verdict.confidence}
        if decline is not None:
            sig = ProblemSignature(raw_query=message, completeness=1.0, clarifier={"status": "out_of_scope", "scope": decline})
            return {"transcript": transcript, "customer_message": message, "clarifier_pending": "", "next": "",
                    "clarifier_session": session.to_json(), "signature": sig.to_dict()}

        result = clarifier.turn(session, message)
        log.log("clarifier_turn", ticket_id=state.get("ticket_id"), status=result.status.value, reason=result.reason,
                questions_asked=result.questions_asked, confidence=result.meta.get("confidence"),
                hypotheses=result.meta.get("hypotheses"), uncovered_terms=result.meta.get("uncovered_terms"),
                tool_calls=[c.get("tool") for c in result.meta.get("tool_calls", [])],
                extraction_source=result.meta.get("extraction_source"),
                question_feature=result.question.feature if result.question else None)
        update: dict[str, Any] = {"clarifier_session": session.to_json(), "transcript": transcript,
                                  "customer_message": message}
        if result.status is ClarifierStatus.ASK:
            return {**update, "clarifier_pending": result.question.text, "clarifier_options": list(result.question.options),
                    "clarifier_feature": result.question.feature}
        sig = to_resolver_signature(result, session)
        update.update({"clarifier_pending": "", "clarifier_options": [], "clarifier_feature": "", "next": "",
                       "signature": sig.to_dict()})
        if sig.completeness < UNRESOLVED_COMPLETENESS:
            # Bouncing back would only repeat questions the Clarifier already spent its budget on; B's guard escalates
            # with CLARIFY_LOOP_EXHAUSTED instead of guessing a fix for an unspecified problem.
            update["clarify_returns"] = CLARIFIER_EXHAUSTED
        return update

    return node
