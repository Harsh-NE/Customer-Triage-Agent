"""
reflect.py -- A10: the redundant-question check (the Clarifier's "reflection" step).

The design verdict was: no separate Planner/Reflection agent -- reflection is a cheap STEP
inside the Clarifier. Before any question is sent, reflect_question() asks "should we really
ask this?" and blocks it when:

  already_known       the field is already filled in
  stated_earlier      the customer already told us (in an earlier message) -> fill it, don't ask
  asked_twice         we've asked about this feature twice and got nothing usable
  duplicate_wording   the text is (almost) identical to an earlier question

A feature asked ONCE and left unanswered may be asked again, rephrased (verdict.rephrase).
All checks are deterministic: reflection that costs an LLM call per question would defeat the
point of a "lighter" check. An LLM judge for borderline wording is a possible extension.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from triage.answers import value_in_text
from triage.context_session import SessionMemory
from triage.state import ExtractedFields, QuestionPlan
from triage.understand import is_vague_symptom

_TOKEN = re.compile(r"[a-z0-9]+")
MAX_ASKS_PER_FEATURE = 2
DUPLICATE_JACCARD = 0.8


@dataclass
class ReflectionVerdict:
    ask: bool
    reason: str                       # "ok" | already_known | stated_earlier | asked_twice | duplicate_wording
    filled_value: str | None = None   # set when the answer was recovered from earlier context
    rephrase: bool = False            # True = same feature asked before, reword it


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(_TOKEN.findall(a.lower())), set(_TOKEN.findall(b.lower()))
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def field_value(fields: ExtractedFields, feature: str):
    """The value if it is actually USABLE. 'it doesn't work' is stored as a symptom but tells
    us nothing, so it must not count as known (same rule as understand.detect_gaps)."""
    if feature == "error_message":
        return fields.error_messages              # text only; a bare code doesn't answer "which error?"
    if feature == "symptoms":
        specific = [s for s in fields.symptoms if not is_vague_symptom(s)]
        return specific or fields.error_messages or fields.error_codes
    return getattr(fields, feature, None)


def reflect_question(plan: QuestionPlan, session: SessionMemory) -> ReflectionVerdict:
    if field_value(session.fields, plan.feature):
        return ReflectionVerdict(False, "already_known")

    for turn in session.customer_turns():
        value = value_in_text(plan.feature, turn.text, plan.options)
        if value:
            return ReflectionVerdict(False, "stated_earlier", filled_value=value)

    previous = [q for q in session.questions if q.feature == plan.feature]
    if len(previous) >= MAX_ASKS_PER_FEATURE:
        return ReflectionVerdict(False, "asked_twice")

    if any(_jaccard(plan.text, q.text) >= DUPLICATE_JACCARD for q in session.questions):
        return ReflectionVerdict(False, "duplicate_wording", rephrase=bool(previous))

    return ReflectionVerdict(True, "ok", rephrase=bool(previous))
