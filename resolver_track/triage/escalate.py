"""B5 — human handoff payload.

The engineer should never need to re-ask the customer anything the system already
learned: signature, transcript, evidence consulted, fixes tried + replies, the
confidence breakdown and a machine-readable reason code.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from triage.contracts import EscalationReason
from triage.guardrails import mask_pii

PRIORITY = {
    EscalationReason.SECURITY_OR_DATA_LOSS: "P1",
    EscalationReason.CRITICAL_SEVERITY: "P1",
    EscalationReason.RETRY_EXHAUSTED: "P2",
    EscalationReason.VERIFICATION_FAILED: "P3",
    EscalationReason.LOW_EVIDENCE: "P3",
    EscalationReason.CLARIFY_LOOP_EXHAUSTED: "P3",
    EscalationReason.OUT_OF_SCOPE: "P4",
}

CUSTOMER_MESSAGE = {
    EscalationReason.OUT_OF_SCOPE:
        "I can only help with Docker-related technical issues, so I've passed this to the support team.",
    EscalationReason.SECURITY_OR_DATA_LOSS:
        "Because this may involve security or data loss, I've escalated it to an engineer right away. "
        "Please avoid further changes to the affected system until they contact you.",
}
DEFAULT_CUSTOMER_MESSAGE = ("I've passed your issue to a support engineer along with everything "
                            "we've tried so far, so you won't need to repeat yourself.")


def build_payload(state: dict[str, Any], reason: EscalationReason, detail: str = "") -> dict[str, Any]:
    sig = state.get("signature") or {}
    attempts = state.get("attempts") or []
    evidence = state.get("evidence") or []
    payload = {
        "ticket_id": state.get("ticket_id"),
        "escalated_at": datetime.now(timezone.utc).isoformat(),
        "reason_code": reason.value,
        "priority": PRIORITY.get(reason, "P3"),
        "detail": detail,
        "signature": sig,
        "confidence": state.get("confidence"),
        "gate": state.get("gate_detail"),
        "cache_status": state.get("cache_status"),
        "attempts": [{"attempt_no": a.get("attempt_no"), "tier": a.get("tier"),
                      "steps": [s.get("text") for s in a.get("steps", [])],
                      "customer_reply": mask_pii(a.get("customer_reply") or ""),
                      "reply_label": a.get("reply_label")} for a in attempts],
        "evidence_consulted": [{"id": e.get("evidence_id"), "tier": e.get("tier"),
                                "url": e.get("url"), "score": e.get("rerank_score")}
                               for e in evidence[:5]],
        "transcript": [{"role": t["role"], "content": mask_pii(t["content"])}
                       for t in state.get("transcript") or []],
        "suggested_next_checks": _suggest(reason, sig),
    }
    payload["summary_md"] = summary_markdown(payload)
    return payload


def _suggest(reason: EscalationReason, sig: dict[str, Any]) -> list[str]:
    if reason == EscalationReason.LOW_EVIDENCE:
        return ["No KB article or past ticket matched confidently — check for a new/undocumented issue.",
                "If resolved, add the fix to Tier 2 so the system can handle it next time."]
    if reason == EscalationReason.RETRY_EXHAUSTED:
        return ["All suggested fixes failed — review the attempts above before proposing new steps.",
                "Collect daemon logs / `docker info` output if not in the transcript."]
    if reason == EscalationReason.SECURITY_OR_DATA_LOSS:
        return ["Treat as security/data-loss incident; follow the incident runbook."]
    missing = sig.get("missing_fields") or []
    return [f"Ask for: {', '.join(missing)}"] if missing else []


def summary_markdown(p: dict[str, Any]) -> str:
    sig = p["signature"] or {}
    lines = [
        f"### Escalation {p['ticket_id']} — {p['reason_code']} ({p['priority']})",
        f"**Problem:** {sig.get('symptom') or sig.get('raw_query', '')}",
        f"**Product / component:** {sig.get('product_area')} / {sig.get('component')}",
        f"**Errors:** {', '.join(sig.get('error_strings') or []) or 'none captured'}",
        f"**Confidence:** {p['confidence']}",
        f"**Fixes tried:** {len(p['attempts'])}",
    ]
    for a in p["attempts"]:
        lines.append(f"- Attempt {a['attempt_no']} ({a['tier']}): {a['reply_label']} — “{a['customer_reply'][:120]}”")
    if p["suggested_next_checks"]:
        lines.append("**Next checks:** " + " ".join(p["suggested_next_checks"]))
    return "\n".join(lines)


def customer_message(reason: EscalationReason) -> str:
    return CUSTOMER_MESSAGE.get(reason, DEFAULT_CUSTOMER_MESSAGE)
