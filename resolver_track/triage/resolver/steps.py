"""The three LLM-facing pieces of the Resolver:
  draft_resolution()  – evidence-only structured draft
  verify_draft()      – deterministic citation / fabrication check (no LLM)
  classify_reply()    – label the customer's reply
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from triage.contracts import Evidence, ProblemSignature, ReplyLabel
from triage.llm import LLM

# --------------------------------------------------------------------------- draft
DRAFT_SYSTEM = """TASK: draft
You are the Resolver in a customer-support triage system for Docker.
Write a troubleshooting reply using ONLY the evidence passages provided.

Rules:
- Every step must cite at least one evidence id, e.g. ["E1"].
- Only use commands, flags, settings, versions and URLs that appear verbatim in the cited evidence.
  Put commands in backticks.
- Do not repeat fixes the customer already tried.
- If the evidence does not address the problem, return status "INSUFFICIENT_EVIDENCE" with no steps.
- 2 to 5 steps, short and concrete. No speculation beyond the evidence.

Return JSON:
{"status": "OK" | "INSUFFICIENT_EVIDENCE",
 "diagnosis": "<one sentence likely cause, grounded in evidence>",
 "steps": [{"text": "<step>", "evidence_ids": ["E1"]}],
 "verification": "<how the customer confirms it worked>"}"""


def format_evidence(evidence: list[Evidence], max_chars: int = 1800) -> str:
    blocks = []
    for ev in evidence:
        header = f"[{ev.evidence_id}] tier={ev.tier} source={ev.source or 'n/a'} url={ev.url or 'n/a'}"
        blocks.append(f"{header}\n{ev.full_text[:max_chars]}")
    return "\n".join(blocks)


def draft_resolution(llm: LLM, signature: ProblemSignature, evidence: list[Evidence],
                     tried_fixes: list[str], last_reply: Optional[str] = None) -> dict[str, Any]:
    user = (
        f"PROBLEM SIGNATURE:\n{signature.to_dict()}\n\n"
        f"ALREADY TRIED (do not repeat):\n{tried_fixes or 'nothing yet'}\n\n"
        f"CUSTOMER'S LAST REPLY:\n{last_reply or 'n/a'}\n\n"
        f"EVIDENCE:\n{format_evidence(evidence)}"
    )
    out = llm.complete_json(DRAFT_SYSTEM, user)
    out.setdefault("status", "OK")
    out.setdefault("steps", [])
    out.setdefault("diagnosis", "")
    out.setdefault("verification", "")
    return out


# --------------------------------------------------------------------------- verify
_BACKTICK = re.compile(r"`([^`]+)`")
_URL = re.compile(r"https?://[^\s)\]>\"']+")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


@dataclass
class VerifyResult:
    ok: bool
    steps: list[dict[str, Any]]
    dropped: list[dict[str, Any]] = field(default_factory=list)


def verify_draft(draft: dict[str, Any], evidence: list[Evidence],
                 min_keep_ratio: float = 0.5) -> VerifyResult:
    """Keep only steps whose citations exist and whose commands/URLs appear in the
    cited evidence. Fails if fewer than min_keep_ratio of steps survive."""
    if draft.get("status") != "OK":
        return VerifyResult(False, [], [{"reason": "insufficient_evidence"}])
    by_id = {e.evidence_id: _norm(e.full_text + " " + e.url) for e in evidence}
    kept, dropped = [], []
    for step in draft.get("steps", []):
        text = step.get("text", "")
        ids = [i for i in step.get("evidence_ids", []) if i in by_id]
        if not ids:
            dropped.append({"step": text, "reason": "no_valid_citation"})
            continue
        cited = " ".join(by_id[i] for i in ids)
        bad = [c for c in _BACKTICK.findall(text) if _norm(c) not in cited]
        bad += [u for u in _URL.findall(text) if _norm(u.rstrip(".,")) not in cited]
        if bad:
            dropped.append({"step": text, "reason": "unsupported_command_or_url", "items": bad})
            continue
        kept.append({"text": text, "evidence_ids": ids})
    total = len(draft.get("steps", []))
    ok = bool(kept) and (len(kept) / max(total, 1)) >= min_keep_ratio
    return VerifyResult(ok, kept, dropped)


def render_message(draft: dict[str, Any], steps: list[dict[str, Any]],
                   evidence: list[Evidence]) -> str:
    urls = {e.evidence_id: e.url for e in evidence}
    lines = []
    if draft.get("diagnosis"):
        lines.append(draft["diagnosis"])
        lines.append("")
    for i, s in enumerate(steps, 1):
        lines.append(f"{i}. {s['text']} [{', '.join(s['evidence_ids'])}]")
    if draft.get("verification"):
        lines.append("")
        lines.append(f"To confirm: {draft['verification']}")
    cited = sorted({i for s in steps for i in s["evidence_ids"]}, key=lambda x: int(x[1:]))
    if cited:
        lines.append("")
        lines.append("Sources: " + "; ".join(f"{i} {urls.get(i) or ''}".strip() for i in cited))
    lines.append("")
    lines.append("Did this resolve the issue?")
    return "\n".join(lines)


# --------------------------------------------------------------------------- classify
CLASSIFY_SYSTEM = """TASK: classify
Classify the customer's reply to a troubleshooting message.
Labels:
- resolved:  the problem is fixed
- not_fixed: they tried it and the problem remains (same or new error)
- new_info:  they add facts about their setup/problem without saying whether it worked
- off_topic: unrelated to the problem
Return JSON: {"label": "...", "rationale": "<short>"}"""


def classify_reply(llm: LLM, last_message: str, reply: str) -> ReplyLabel:
    user = f"ASSISTANT MESSAGE:\n{last_message}\n\nCUSTOMER REPLY:\n{reply}"
    try:
        label = llm.complete_json(CLASSIFY_SYSTEM, user, max_tokens=200).get("label", "")
        return ReplyLabel(label)
    except Exception:
        from triage.llm import FakeLLM          # deterministic fallback
        return ReplyLabel(FakeLLM._classify(user)["label"])
