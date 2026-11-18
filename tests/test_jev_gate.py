"""jev_gate: the cascade (arm C) in isolation, and wired into the Resolver graph. No network: a stub stands in for Jev."""

import json
from pathlib import Path

import pytest
from langgraph.types import Command  # noqa: F401  (the graph interrupts for the customer; the tests stop at the first interrupt)

from triage import config
from triage.jev import Decision
from triage.resolver.cache import SemanticCache
from triage.resolver.contracts import Evidence, ProblemSignature
from triage.resolver.graph import ResolverDeps, build_resolver_app
from triage.resolver.interface import LexicalRetriever, TieredRetriever, load_kb_jsonl, load_tickets_jsonl
from triage.resolver.jev_gate import QUESTION, JevGate, JevGateConfig, Verdict, build_jev_gate, build_state
from triage.resolver.llm import FakeLLM
from triage.resolver.oplog import EventLogger

FX = Path(__file__).resolve().parents[1] / "triage" / "resolver" / "fixtures"
SIGS = json.loads((FX / "signatures.json").read_text())


def evidence(n, text="Docker Hub limits how many pulls an account may make.\nAuthenticate to raise the limit.", issue="Pull rate limit"):
    return [Evidence(evidence_id=f"E{i}", chunk_id=f"c{i}", doc_id=f"d{i}", tier="kb", text=text, metadata={"issue": issue}) for i in range(1, n + 1)]


def signature():
    return ProblemSignature.from_dict({"raw_query": "docker pull fails", "error_strings": ["429 too many requests"], "completeness": 0.9})


class Client:
    """Stands in for Jev: answers `p`, or raises `error`."""

    def __init__(self, p=0.95, error=None):
        self.p, self.error, self.states = p, error, []

    def noul(self, state, instructions, yes, no):
        self.states.append((state, instructions))
        if self.error:
            raise self.error
        return Decision(self.p, abs(2 * self.p - 1), 300, 12.5, 0.00001, "typesafe/jev-1.13-2026-10-01")


def test_the_state_jev_reads_is_the_problem_and_a_few_shortened_evidence_items():
    state = build_state(signature(), evidence(8), items=2, chars=10)
    assert "docker pull fails" in state["customer_problem"] and "429 too many requests" in state["customer_problem"]
    assert [e["id"] for e in state["evidence"]] == ["E1", "E2"] and all(len(e["text"]) == 10 for e in state["evidence"])
    assert state["evidence"][0]["title"] == "Pull rate limit"                 # the documented issue's name, not the first line of text


def test_a_confident_yes_overrides_and_the_call_is_logged_with_its_cost_and_snapshot():
    log, client = EventLogger(), Client(0.95)
    verdict = JevGate(client, JevGateConfig(answer_above=0.9), log).second_opinion("T1", signature(), evidence(3))
    assert verdict == Verdict(0.95, True) and client.states[0][1] == QUESTION
    (event,) = log.of_type("jev_call")
    assert (event["ticket_id"], event["p"], event["override"], event["shadow"]) == ("T1", 0.95, True, False)
    assert (event["input_tokens"], event["cost_usd"], event["model"]) == (300, 0.00001, "typesafe/jev-1.13-2026-10-01")


def test_a_probability_below_the_bar_does_not_override():
    assert JevGate(Client(0.89), JevGateConfig(answer_above=0.9)).second_opinion("T", signature(), evidence(1)) == Verdict(0.89, False)


def test_shadow_mode_asks_and_logs_but_never_overrides():
    log = EventLogger()
    verdict = JevGate(Client(0.99), JevGateConfig(shadow=True), log).second_opinion("T", signature(), evidence(1))
    assert verdict.override is False and log.of_type("jev_call")[0]["shadow"] is True and log.of_type("jev_call")[0]["p"] == 0.99


def test_a_failed_call_leaves_the_rules_decision_and_is_logged_as_an_error():
    log = EventLogger()
    verdict = JevGate(Client(error=RuntimeError("HTTP 503")), logger=log).second_opinion("T", signature(), evidence(1))
    assert verdict.override is False and verdict.p is None and "RuntimeError: HTTP 503" in verdict.error
    assert log.of_type("jev_call")[0]["error"].startswith("RuntimeError") and "p" not in log.of_type("jev_call")[0]


def test_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("JEV_ANSWER_ABOVE", "0.75")
    monkeypatch.setenv("JEV_ITEMS", "3")
    monkeypatch.setenv("JEV_CHARS", "200")
    monkeypatch.setenv("JEV_MODE", "shadow")
    assert JevGateConfig.from_env() == JevGateConfig(answer_above=0.75, items=3, chars=200, shadow=True)


def test_building_the_cascade_stops_without_a_key_and_can_use_the_offline_stand_in(monkeypatch):
    monkeypatch.delenv("JEV_BACKEND", raising=False)
    monkeypatch.setattr(config, "get_api_key", lambda provider: None)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        build_jev_gate()
    monkeypatch.setenv("JEV_BACKEND", "fake")
    assert isinstance(build_jev_gate(), JevGate)


# ---------------------------------------------------------------- inside the Resolver graph
class Gate:
    """A stand-in for JevGate at the graph's seam."""

    def __init__(self, verdict):
        self.verdict, self.calls = verdict, 0

    def second_opinion(self, ticket_id, sig, evidence):
        self.calls += 1
        return self.verdict


def run_gate(signature_key, jev):
    kb = LexicalRetriever(load_kb_jsonl(FX / "kb_mini.jsonl"), "kb")
    tickets = LexicalRetriever(load_tickets_jsonl(FX / "tickets_mini.jsonl"), "tickets")
    log = EventLogger()
    app = build_resolver_app(ResolverDeps(retriever=TieredRetriever(kb, tickets), llm=FakeLLM(), cache=SemanticCache(), logger=log, jev=jev))
    app.invoke({"ticket_id": "t1", "signature": SIGS[signature_key], "transcript": []}, {"configurable": {"thread_id": "t1"}})
    return log.of_type("gate")[0]


def test_when_the_rules_refuse_a_confident_jev_turns_the_refusal_into_an_answer():
    assert run_gate("unknown_issue", None)["decision"] == "fallback"                  # without Jev the rules refuse and fall back to tickets
    jev = Gate(Verdict(0.95, True))
    gate = run_gate("unknown_issue", jev)
    assert jev.calls == 1 and gate["decision"] == "resolve" and gate["jev_p"] == 0.95


def test_when_jev_does_not_override_or_fails_the_rules_decision_stands():
    for verdict in (Verdict(0.4, False), Verdict(None, error="boom")):
        jev = Gate(verdict)
        gate = run_gate("unknown_issue", jev)
        assert jev.calls == 1 and gate["decision"] == "fallback"                      # consulted, but the rules' decision is unchanged


def test_a_gate_that_is_already_confident_is_not_second_guessed():
    jev = Gate(Verdict(0.0, False))
    assert run_gate("port_conflict", jev)["decision"] == "resolve" and jev.calls == 0
