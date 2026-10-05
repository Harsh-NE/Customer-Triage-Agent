"""
dialogue.py -- run one scenario end to end: simulated customer <-> Clarifier.

Also holds gold matching, because "is the right KB issue among the Clarifier's hypotheses?"
is the headline correctness question for both the eval and the unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from triage.clarifier import Clarifier
from triage.context_session import SessionMemory
from triage.differential import issue_title
from triage.reflect import field_value
from triage.sim.customer import LLMCustomer, RuleBasedCustomer, Scenario
from triage.state import ClarifierResult, ClarifierStatus, Hypothesis


def hypothesis_matches_gold(h: Hypothesis, gold: dict) -> bool:
    source, _, issue = h.key.partition("::")
    return (gold["source_path_contains"].lower() in source.lower()
            and gold["issue_contains"].lower() in issue.lower())


def gold_rank(result: ClarifierResult, gold: dict | None) -> int | None:
    """1-based rank of the gold issue in the signature's hypotheses (top 3 are kept), else None."""
    if not gold or not result.signature:
        return None
    for i, h in enumerate(result.signature.hypotheses, 1):
        if hypothesis_matches_gold(h, gold):
            return i
    return None


@dataclass
class DialogueResult:
    scenario: Scenario
    result: ClarifierResult
    session: SessionMemory
    transcript: list[tuple[str, str]] = field(default_factory=list)   # (role, text)
    questions: list[dict] = field(default_factory=list)               # feature, text, redundant, duplicate
    gold_rank: int | None = None
    stuck: bool = False                                               # hit max_turns while still asking
    first_result: ClarifierResult | None = None                       # the result for the OPENING message alone
    tool_calls: int = 0                                               # registry calls over the whole ticket

    @property
    def status(self) -> str:
        return "stuck" if self.stuck else self.result.status.value


def run_dialogue(clarifier: Clarifier, customer: RuleBasedCustomer | LLMCustomer, scenario: Scenario,
                 max_turns: int = 6) -> DialogueResult:
    session = clarifier.start(f"SIM-{scenario.id}")
    message = customer.opening()
    transcript: list[tuple[str, str]] = []
    questions: list[dict] = []
    first: ClarifierResult | None = None
    result: ClarifierResult | None = None
    seen_texts: set[str] = set()

    for _ in range(max_turns):
        transcript.append(("customer", message))
        result = clarifier.turn(session, message)
        first = first or result
        if result.status is not ClarifierStatus.ASK:
            break
        q = result.question
        # fields are post-merge for this turn, so "known" here means the Clarifier already had it
        questions.append({"feature": q.feature, "text": q.text,
                          "redundant": bool(field_value(session.fields, q.feature)),
                          "duplicate": q.text in seen_texts})
        seen_texts.add(q.text)
        transcript.append(("assistant", q.text))
        message = customer.reply(q.text)

    stuck = result.status is ClarifierStatus.ASK
    return DialogueResult(scenario, result, session, transcript, questions,
                          gold_rank(result, scenario.gold), stuck, first, len(clarifier.registry.log))
