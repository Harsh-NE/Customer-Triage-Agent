"""jev_gate.py -- Jev as a second opinion on the confidence gate (ablation arm C).

The evaluation found the gate to be the largest loss: for 11 of 15 escalated answerable real questions the right page was already among the
retrieved results and the gate still declined. So when the rule-based gate REFUSES on the first documentation search, Jev is asked one yes/no
question: "does this evidence contain a fix that applies to this customer's problem?". If it says yes with probability >= `answer_above`, the
case goes on to drafting. Otherwise, and whenever Jev fails, the rules' decision stands. The drafting step, the verifier and the customer's
reply still run, so a wrong "yes" is caught only by them. A confident gate (the rules say answer) is never second-guessed.

    USE_JEV=1                    switch the cascade on (arm C)
    OPENROUTER_API_KEY=...       the key Jev is reached with (JEV_BACKEND=fake: an offline stand-in, no key)
    JEV_ANSWER_ABOVE=0.9         probability of yes needed to turn a refusal into an answer
    JEV_MODE=shadow              ask and log, but never change the decision (choose the threshold from the logs first, see triage.eval.jev_threshold)
    JEV_ITEMS=5  JEV_CHARS=500   how many evidence items Jev reads, and how many characters of each
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from triage.resolver.contracts import Evidence, ProblemSignature
from triage.resolver.oplog import NULL_LOGGER

QUESTION = "Does the documentation evidence contain a fix that applies to this customer's problem?"
YES = "The evidence describes the cause of this customer's problem and a fix that applies to it."
NO = "The evidence is about a different problem, is too general, or does not give a fix for this problem."


@dataclass
class JevGateConfig:
    answer_above: float = 0.9
    items: int = 5
    chars: int = 500
    shadow: bool = False

    @classmethod
    def from_env(cls) -> "JevGateConfig":
        e = os.environ
        return cls(answer_above=float(e.get("JEV_ANSWER_ABOVE", cls.answer_above)), items=int(e.get("JEV_ITEMS", cls.items)),
                   chars=int(e.get("JEV_CHARS", cls.chars)), shadow=e.get("JEV_MODE", "active").lower() == "shadow")


@dataclass
class Verdict:
    p: Optional[float]                  # Jev's probability of yes; None when the call failed
    override: bool = False              # True: turn the gate's refusal into an answer
    error: Optional[str] = None


def build_state(sig: ProblemSignature, evidence: list[Evidence], items: int, chars: int) -> dict[str, Any]:
    """What Jev reads: the customer's problem and the first few evidence items, each cut short."""
    problem = " ".join([sig.raw_query, *sig.error_strings])[:1200]
    shown = [{"id": e.evidence_id, "title": str(e.metadata.get("issue") or (e.text.splitlines() or [""])[0])[:120], "text": e.full_text[:chars]}
             for e in evidence[:items]]
    return {"customer_problem": problem, "evidence": shown}


class JevGate:
    def __init__(self, client, cfg: Optional[JevGateConfig] = None, logger=NULL_LOGGER) -> None:
        self.client, self.cfg, self.logger = client, cfg or JevGateConfig(), logger

    def second_opinion(self, ticket_id: Optional[str], sig: ProblemSignature, evidence: list[Evidence]) -> Verdict:
        state = build_state(sig, evidence, self.cfg.items, self.cfg.chars)
        try:
            d = self.client.noul(state, QUESTION, YES, NO)
        except Exception as error:  # noqa: BLE001 -- whatever went wrong, the rules' decision stands
            message = f"{type(error).__name__}: {str(error)[:200]}"
            self.logger.log("jev_call", ticket_id=ticket_id, node="gate", error=message)
            return Verdict(None, error=message)
        override = d.answer >= self.cfg.answer_above and not self.cfg.shadow
        self.logger.log("jev_call", ticket_id=ticket_id, node="gate", p=d.answer, override=override, shadow=self.cfg.shadow,
                        latency_ms=d.latency_ms, input_tokens=d.input_tokens, cost_usd=d.cost_usd, model=d.model)
        return Verdict(d.answer, override)


def build_jev_gate(logger=NULL_LOGGER) -> JevGate:
    """The cascade for USE_JEV=1. It never falls silent: without a key the run stops, because an arm C that quietly behaved like arm B is worse than none."""
    from triage.jev import FakeJev, JevClient
    client = FakeJev() if os.environ.get("JEV_BACKEND", "").lower() == "fake" else JevClient.from_env()
    if client is None:
        raise RuntimeError("USE_JEV is on but OPENROUTER_API_KEY is not set (environment or .env). Set JEV_BACKEND=fake for an offline rehearsal.")
    return JevGate(client, JevGateConfig.from_env(), logger)
