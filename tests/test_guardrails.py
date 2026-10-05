"""The guardrail checks must pass on the real code AND fail when the protection is removed
(negative controls) -- otherwise a green result proves nothing."""

import pytest

from triage import context_session, reflect, understand
from triage.clarifier import Clarifier
from triage.eval import guardrails as G
from triage.tools import ToolRegistry


@pytest.fixture
def factory(retriever):
    return lambda llm=None: Clarifier(llm, retriever)


def test_all_guardrail_checks_pass(factory):
    results = G.run_guardrail_checks(factory)
    assert len(results) == 6
    failed = [r for r in results if not r.passed]
    assert not failed, [(r.name, r.detail) for r in failed]


def test_negative_control_pii_check_fails_without_redaction(factory, monkeypatch):
    monkeypatch.setattr(context_session, "redact_pii", lambda text: (text, {}))
    assert G.check_pii(factory).passed is False


def test_negative_control_vague_check_fails_if_vagueness_detection_is_broken(factory, monkeypatch):
    monkeypatch.setattr(understand, "is_vague_symptom", lambda s: False)
    monkeypatch.setattr(reflect, "is_vague_symptom", lambda s: False)
    assert G.check_vague_queries(factory).passed is False


def test_negative_control_hostile_llm_check_fails_if_product_validation_is_removed(factory, monkeypatch):
    monkeypatch.setattr(understand, "normalize_product", lambda value, known: str(value) if value else None)
    assert G.check_malicious_llm(factory).passed is False


def test_negative_control_tool_check_fails_if_the_registry_stops_enforcing(factory, monkeypatch):
    def unguarded(self, name, **kwargs):
        return self._tools[name].fn(**kwargs)
    monkeypatch.setattr(ToolRegistry, "call", unguarded)
    try:
        assert G.check_tool_budget(factory).passed is False
    except KeyError:                      # an unregistered name blowing up is also "not enforced"
        pass


def test_negative_control_llm_failure_check_fails_if_exceptions_propagate(factory, monkeypatch):
    def raising_extract(*args, **kwargs):
        raise RuntimeError("no fallback")
    monkeypatch.setattr(understand, "extract", raising_extract)
    from triage import clarifier
    monkeypatch.setattr(clarifier.U, "extract", raising_extract)
    assert G.check_llm_failure(factory).passed is False
