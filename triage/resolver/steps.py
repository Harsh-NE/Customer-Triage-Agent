"""The three LLM-facing pieces of the Resolver:
  draft_resolution()  – evidence-only structured draft
  verify_draft()      – deterministic citation / fabrication check (no LLM)
  classify_reply()    – label the customer's reply
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from triage.resolver.contracts import Evidence, ProblemSignature, ReplyLabel
from triage.resolver.llm import LLM

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


def _check_url_liveness(url: str, timeout: float = 3.0) -> bool:
    """HEAD request to check if a URL is alive. Returns True if reachable."""
    try:
        import urllib.request
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "DockerSupportBot/1.0")
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status < 400
    except Exception:
        return False


def verify_draft(draft: dict[str, Any], evidence: list[Evidence],
                 min_keep_ratio: float = 0.5,
                 check_urls: bool = True) -> VerifyResult:
    """Keep only steps whose citations exist and whose commands/URLs appear in the
    cited evidence. Optionally validates URLs via HEAD requests.
    Fails if fewer than min_keep_ratio of steps survive."""
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
        # URL liveness check: HEAD request on every cited URL
        if check_urls:
            urls_in_step = _URL.findall(text)
            dead_urls = [u for u in urls_in_step if not _check_url_liveness(u.rstrip(".,"))]
            if dead_urls:
                dropped.append({"step": text, "reason": "dead_url", "items": dead_urls})
                continue
        kept.append({"text": text, "evidence_ids": ids,
                     "confidence": step.get("confidence", "medium")})
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
- partial:   some steps worked but others failed or the problem is partially fixed
- not_fixed: they tried it and the problem remains (same or new error)
- new_info:  they add facts about their setup/problem without saying whether it worked
- off_topic: unrelated to the problem
Return JSON: {"label": "...", "rationale": "<short>", "working_steps": [1,2], "failed_steps": [3]}
(working_steps and failed_steps only required for "partial" label)"""


def classify_reply(llm: LLM, last_message: str, reply: str) -> ReplyLabel:
    user = f"ASSISTANT MESSAGE:\n{last_message}\n\nCUSTOMER REPLY:\n{reply}"
    try:
        label = llm.complete_json(CLASSIFY_SYSTEM, user, max_tokens=200).get("label", "")
        return ReplyLabel(label)
    except Exception:
        from triage.resolver.llm import FakeLLM          # deterministic fallback
        return ReplyLabel(FakeLLM._classify(user)["label"])


# --------------------------------------------------------------------------- query expansion
EXPAND_SYSTEM = """TASK: expand_queries
You are a search query expander for Docker customer support.
Given a problem signature, generate 2-3 diverse search queries that would find
relevant documentation or past tickets.

Rules:
- First query: use exact error strings/codes if available.
- Second query: rephrase the symptom in different terms.
- Third query (optional): focus on the component/product area with common solutions.
- Keep each query under 30 words.

Return JSON: {"queries": ["query1", "query2", ...]}"""


def expand_queries(llm: LLM, signature: ProblemSignature) -> list[str]:
    """LLM rewrites a problem signature into 2-3 diverse search queries."""
    user = f"PROBLEM SIGNATURE:\n{signature.to_dict()}"
    try:
        result = llm.complete_json(EXPAND_SYSTEM, user, max_tokens=300)
        queries = result.get("queries", [])
        if isinstance(queries, list) and queries:
            return [q for q in queries if isinstance(q, str) and q.strip()][:3]
    except Exception:
        pass
    # Fallback: use the signature's own search text
    return [signature.search_text()]


# --------------------------------------------------------------------------- multi-draft
MULTI_DRAFT_SYSTEM = """TASK: draft
You are the Resolver in a customer-support triage system for Docker.
Write a troubleshooting reply using ONLY the evidence passages provided.

Rules:
- Every step must cite at least one evidence id, e.g. ["E1"].
- Only use commands, flags, settings, versions and URLs that appear verbatim in the cited evidence.
  Put commands in backticks.
- Do not repeat fixes the customer already tried.
- If the evidence does not address the problem, return status "INSUFFICIENT_EVIDENCE" with no steps.
- 2 to 5 steps, short and concrete. No speculation beyond the evidence.
- For each step, include a "confidence" field: "high" (directly supported by evidence),
  "medium" (inferred from related evidence), or "low" (weak support).

Return JSON:
{"status": "OK" | "INSUFFICIENT_EVIDENCE",
 "diagnosis": "<one sentence likely cause, grounded in evidence>",
 "steps": [{"text": "<step>", "evidence_ids": ["E1"], "confidence": "high|medium|low"}],
 "verification": "<how the customer confirms it worked>"}"""


def multi_draft_resolution(llm: LLM, signature: ProblemSignature, evidence: list[Evidence],
                           tried_fixes: list[str], last_reply: Optional[str] = None,
                           n_drafts: int = 3) -> list[dict[str, Any]]:
    """Generate n_drafts at temperature > 0, each with step-level confidence."""
    user = (
        f"PROBLEM SIGNATURE:\n{signature.to_dict()}\n\n"
        f"ALREADY TRIED (do not repeat):\n{tried_fixes or 'nothing yet'}\n\n"
        f"CUSTOMER'S LAST REPLY:\n{last_reply or 'n/a'}\n\n"
        f"EVIDENCE:\n{format_evidence(evidence)}"
    )
    drafts = []
    for _ in range(n_drafts):
        try:
            out = llm.complete_json(MULTI_DRAFT_SYSTEM, user)
            out.setdefault("status", "OK")
            out.setdefault("steps", [])
            out.setdefault("diagnosis", "")
            out.setdefault("verification", "")
            # Ensure each step has a confidence field
            for step in out.get("steps", []):
                step.setdefault("confidence", "medium")
            drafts.append(out)
        except Exception:
            continue
    return drafts if drafts else [draft_resolution(llm, signature, evidence, tried_fixes, last_reply)]


def select_best_draft(drafts: list[dict[str, Any]], evidence: list[Evidence],
                      min_keep_ratio: float = 0.5) -> tuple[dict[str, Any], "VerifyResult"]:
    """Run verify on each draft, pick the one with the best pass rate.
    Ties broken by average step confidence score."""
    CONF_SCORE = {"high": 3, "medium": 2, "low": 1}
    best_draft = drafts[0]
    best_verify = verify_draft(drafts[0], evidence, min_keep_ratio)
    best_score = (-1, 0.0)  # (pass_rate, avg_confidence)

    for d in drafts:
        v = verify_draft(d, evidence, min_keep_ratio)
        total = len(d.get("steps", [])) or 1
        pass_rate = len(v.steps) / total
        avg_conf = sum(CONF_SCORE.get(s.get("confidence", "medium"), 2)
                       for s in d.get("steps", [])) / max(total, 1)
        score = (pass_rate, avg_conf)
        if score > best_score:
            best_score = score
            best_draft = d
            best_verify = v

    return best_draft, best_verify


# --------------------------------------------------------------------------- fix history summarization
def summarize_fix_history(attempts: list[dict[str, Any]]) -> str:
    """Summarize what each attempted fix revealed, not just what was tried.

    Instead of a flat list like ['Restart daemon', 'Clear cache'], produces:
    'Attempt 1: Restarted daemon → same 429 error, so not a local cache issue.
     Attempt 2: Cleared build cache → partial fix, networking still fails.'

    This gives the LLM better context for the next draft.
    """
    if not attempts:
        return "No previous attempts."
    lines = []
    for a in attempts:
        num = a.get("attempt_no", "?")
        diagnosis = a.get("diagnosis", "unknown cause")
        steps_text = "; ".join(s.get("text", "")[:80] for s in a.get("steps", []))
        reply = a.get("customer_reply", "")
        label = a.get("reply_label", "unknown")

        if label == "resolved":
            insight = "Fix worked."
        elif label == "partial":
            insight = f"Partial success. Customer said: {reply[:120]}"
        elif label == "not_fixed":
            # Extract what the failure revealed
            if reply:
                insight = f"Did not work. Customer reported: {reply[:120]}"
            else:
                insight = "Did not work (no details from customer)."
        elif label == "new_info":
            insight = f"Customer provided new info: {reply[:120]}"
        else:
            insight = f"Outcome: {label}. Reply: {(reply or 'none')[:80]}"

        lines.append(f"Attempt {num} ({diagnosis[:60]}): Tried [{steps_text[:100]}] → {insight}")

    return "\n".join(lines)
