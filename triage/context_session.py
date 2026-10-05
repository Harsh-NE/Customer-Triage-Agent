"""
context_session.py -- A9: session (working) memory + the retry-history tracker.

Working memory is per-ticket state, archived into the Triage Record on close. Two jobs:

  1. CONTEXT DISCIPLINE -- render_context() gives an LLM a compact structured summary under a
     hard token budget instead of replaying the raw transcript: known fields and what's been
     asked/answered always survive; recent turns stay verbatim; older turns are condensed.
  2. RETRY HISTORY -- record_attempt()/rejected_chunk_ids() let the Resolver see what was
     already tried and rejected, so a retry never repeats a draft the customer said failed.

Deliberately deterministic: no LLM summarisation. The summary must be cheap, reproducible and
auditable; "approx tokens" is chars/4, which is good enough for budgeting (not billing).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from triage.config import ClarifierConfig
from triage.state import (AttemptRecord, ExtractedFields, ProblemSignature, QuestionPlan, QuestionRecord,
                          TriageRecord, TurnRecord, from_dict, to_dict)
from triage.understand import merge_fields, redact_pii


def approx_tokens(text: str) -> int:
    return len(text) // 4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _first_sentence(text: str, limit: int) -> str:
    text = " ".join(text.split())
    for end in (". ", "? ", "! "):
        i = text.find(end)
        if 0 < i < limit:
            return text[: i + 1]
    return text[:limit] + ("..." if len(text) > limit else "")


@dataclass
class SessionMemory:
    ticket_id: str
    created_at: str = field(default_factory=_now)
    turns: list[TurnRecord] = field(default_factory=list)
    fields: ExtractedFields = field(default_factory=ExtractedFields)
    field_sources: dict[str, int] = field(default_factory=dict)   # field name -> turn that last changed it
    questions: list[QuestionRecord] = field(default_factory=list)
    answered: dict[str, str] = field(default_factory=dict)        # feature -> answer value
    attempts: list[AttemptRecord] = field(default_factory=list)
    redactions: dict[str, int] = field(default_factory=dict)

    # -- turns -------------------------------------------------------------
    def add_turn(self, role: str, text: str, **meta) -> TurnRecord:
        """Stored text is ALWAYS redacted here, regardless of what the caller did."""
        clean, counts = redact_pii(text)
        for kind, n in counts.items():
            self.redactions[kind] = self.redactions.get(kind, 0) + n
        turn = TurnRecord(idx=len(self.turns), role=role, text=clean, meta=meta)
        self.turns.append(turn)
        return turn

    def customer_turns(self) -> list[TurnRecord]:
        return [t for t in self.turns if t.role == "customer"]

    # -- fields ------------------------------------------------------------
    def apply_extraction(self, new: ExtractedFields, turn_idx: int) -> list[str]:
        self.fields, changed = merge_fields(self.fields, new)
        for name in changed:
            self.field_sources[name] = turn_idx
        return changed

    # -- questions ---------------------------------------------------------
    @property
    def open_question(self) -> QuestionRecord | None:
        return next((q for q in reversed(self.questions) if not q.answered), None)

    @property
    def questions_asked(self) -> int:
        return len(self.questions)

    def asked_features(self) -> set[str]:
        return {q.feature for q in self.questions}

    def record_question(self, plan: QuestionPlan, turn_idx: int) -> QuestionRecord:
        record = QuestionRecord(turn_idx=turn_idx, feature=plan.feature, text=plan.text, options=list(plan.options))
        self.questions.append(record)
        return record

    def mark_answered(self, value: str) -> None:
        q = self.open_question
        if q is not None:
            q.answered, q.answer_value = True, value
            self.answered[q.feature] = value

    # -- retry history (Resolver) -------------------------------------------
    def record_attempt(self, chunk_ids: list[str], outcome: str = "", feedback: str = "") -> AttemptRecord:
        record = AttemptRecord(attempt=len(self.attempts) + 1, chunk_ids_tried=list(chunk_ids),
                               outcome=outcome, customer_feedback=redact_pii(feedback)[0])
        self.attempts.append(record)
        return record

    def rejected_chunk_ids(self) -> set[str]:
        """Chunks from attempts the customer said did NOT work. 'partial' is not rejected: it
        helped, and may be combined with the next-ranked chunk."""
        return {cid for a in self.attempts if a.outcome == "not_resolved" for cid in a.chunk_ids_tried}

    def render_retry_context(self, max_feedback_chars: int = 200) -> str:
        if not self.attempts:
            return "No earlier attempts."
        lines = []
        for a in self.attempts:
            said = f' Customer said: "{a.customer_feedback[:max_feedback_chars]}"' if a.customer_feedback else ""
            lines.append(f"Attempt {a.attempt}: tried {', '.join(a.chunk_ids_tried) or 'n/a'} -> "
                         f"{a.outcome or 'no outcome yet'}.{said}")
        lines.append("Do not repeat the rejected evidence above.")
        return "\n".join(lines)

    # -- compaction ----------------------------------------------------------
    def _head(self) -> str:
        f = self.fields
        known = {k: v for k, v in {
            "product": f.product_area, "component": f.component, "platform": f.platform,
            "symptoms": f.symptoms, "errors": f.error_messages[:2] + f.error_codes,
            "versions": f.versions or None}.items() if v}
        asked = [f"{q.feature}={q.answer_value}" if q.answered else f"{q.feature}(awaiting reply)"
                 for q in self.questions]
        parts = [f"KNOWN: {json.dumps(known, ensure_ascii=False)}"]
        if asked:
            parts.append("ASKED: " + ", ".join(asked))
        return "\n".join(parts)

    def _conversation(self, keep_last: int, recent_chars: int) -> str:
        lines = []
        cutoff = max(len(self.turns) - keep_last, 0)
        for t in self.turns:
            who = "C" if t.role == "customer" else "A"
            if t.idx >= cutoff:
                lines.append(f"{who}: {t.text[:recent_chars]}")
            elif t.role == "customer":
                lines.append(f"{who}(earlier): {_first_sentence(t.text, 160)}")
            else:
                lines.append(f"{who}(earlier): asked about {t.meta.get('feature', 'something')}")
        return "\n".join(lines)

    def render_context(self, max_tokens: int | None = None, cfg: ClarifierConfig | None = None) -> str:
        """Compact structured summary within `max_tokens`. The KNOWN/ASKED header is never
        dropped; the conversation is shrunk progressively (fewer verbatim turns, shorter turns),
        then hard-truncated with an explicit marker, so the cap always holds."""
        cfg = cfg or ClarifierConfig()
        budget_chars = (max_tokens or cfg.context_token_budget) * 4
        head = self._head()
        if len(head) >= budget_chars:
            return head[: budget_chars - 20] + "\n[context truncated]"
        for keep, chars in ((cfg.keep_last_turns, 400), (2, 250), (1, 160)):
            text = head + "\nCONVERSATION:\n" + self._conversation(keep, chars)
            if len(text) <= budget_chars:
                return text
        convo = self._conversation(1, 160)
        room = budget_chars - len(head) - len("\nCONVERSATION:\n") - len("\n[context truncated]")
        return head + "\nCONVERSATION:\n" + convo[-max(room, 0):] + "\n[context truncated]"

    # -- persistence / archive ---------------------------------------------------
    def to_triage_record(self, outcome: str = "in_progress", signature: ProblemSignature | None = None,
                         evidence_chunk_ids: list[str] | None = None,
                         tool_calls: list[dict] | None = None) -> TriageRecord:
        return TriageRecord(
            ticket_id=self.ticket_id, created_at=self.created_at, transcript=list(self.turns),
            fields=self.fields, signature=signature, questions=list(self.questions),
            evidence_chunk_ids=list(evidence_chunk_ids or []), attempts=list(self.attempts),
            outcome=outcome, closed_at=None if outcome == "in_progress" else _now(),
            tool_calls=list(tool_calls or []))

    def to_json(self) -> str:
        return json.dumps(to_dict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "SessionMemory":
        return from_dict(cls, json.loads(raw))

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.ticket_id}.json"
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "SessionMemory":
        return cls.from_json(path.read_text(encoding="utf-8"))
