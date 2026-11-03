"""The resolver track's additions, as merged: partial-fix label, negative cache, frustration-based escalation, attempt-history summary,
and the opt-in query expansion / multi-draft / URL check. Offline, on the resolver fixtures."""
import json
from pathlib import Path

import pytest
from langgraph.types import Command

from triage.resolver.cache import NegativeCache, SemanticCache
from triage.resolver.config import ResolverConfig
from triage.resolver.contracts import Evidence, ProblemSignature, ReplyLabel
from triage.resolver.graph import ResolverDeps, build_resolver_app
from triage.resolver.interface import HybridRetriever, LexicalRetriever, TieredRetriever, load_kb_jsonl, load_tickets_jsonl
from triage.resolver.llm import FakeLLM
from triage.resolver.oplog import EventLogger
from triage.resolver.sentiment import SentimentState, should_early_escalate, update_sentiment
from triage.resolver import steps as S

FX = Path(__file__).resolve().parents[1] / "triage" / "resolver" / "fixtures"
SIGS = json.loads((FX / "signatures.json").read_text())
BUTTON_NOT_FIXED = "I tried that but it is still the same error."


def make_deps(**kw):
    retriever = TieredRetriever(LexicalRetriever(load_kb_jsonl(FX / "kb_mini.jsonl"), "kb"),
                                LexicalRetriever(load_tickets_jsonl(FX / "tickets_mini.jsonl"), "tickets"))
    return ResolverDeps(retriever=retriever, llm=kw.pop("llm", FakeLLM()), cache=SemanticCache(), logger=EventLogger(), **kw)


def run(app, sig, replies, tid="t1"):
    cfg = {"configurable": {"thread_id": tid}}
    out = app.invoke({"ticket_id": tid, "signature": sig, "transcript": []}, cfg)
    replies = list(replies)
    while "__interrupt__" in out and replies:
        out = app.invoke(Command(resume=replies.pop(0)), cfg)
    return app.get_state(cfg).values


# ---------------------------------------------------------------- sentiment
def test_one_clearly_frustrated_reply_after_a_failed_fix_escalates():
    s = update_sentiment(SentimentState(), "this is useless, I give up!! nothing works")
    assert s.current >= 0.55 and should_early_escalate(s, attempt_count=1)


def test_ordinary_replies_do_not_escalate_and_calm_ones_fade_it():
    for text in (BUTTON_NOT_FIXED, "still not working, I get ERROR: permission denied", "no luck, same error again"):
        s = update_sentiment(SentimentState(), text)
        assert not should_early_escalate(s, 1), text
    s = update_sentiment(SentimentState(), "this is useless, I give up!!")
    for _ in range(3):
        s = update_sentiment(s, "ok thanks, got it")
    assert s.current < 0.4


def test_the_graph_hands_a_frustrated_customer_to_a_person_after_the_first_failed_fix():
    app = build_resolver_app(make_deps())
    deps = make_deps(cfg=ResolverConfig(max_attempts=3))                 # room for a retry: only the frustration can stop it
    st = run(build_resolver_app(deps), SIGS["permission_denied"], ["this is useless, I give up!! it is still the same error"], "f1")
    assert st["outcome"] == "escalated" and st["escalation_reason"] == "RETRY_EXHAUSTED" and len(st["attempts"]) == 1
    assert st["sentiment"]["current"] >= 0.55
    assert any(e["event"] == "sentiment_escalation" for e in deps.logger.events)


def test_frustration_escalation_can_be_switched_off():
    deps = make_deps(cfg=ResolverConfig(sentiment_escalation=False, max_attempts=3))
    st = run(build_resolver_app(deps), SIGS["permission_denied"], ["this is useless, I give up!! it is still the same error"], "f2")
    assert st["sentiment"]["current"] >= 0.55                            # still measured and logged...
    assert not any(e["event"] == "sentiment_escalation" for e in deps.logger.events)         # ...but it no longer ends the conversation


# ---------------------------------------------------------------- negative cache
def test_negative_cache_remembers_a_failed_diagnosis_and_forgets_it_when_a_fix_works():
    nc = NegativeCache()
    sig = ProblemSignature.from_dict(SIGS["port_conflict"])
    assert nc.check(sig, "Another process is using the port") is None
    nc.put(sig, "Another process is using the port", "Stop it with `lsof`", "same error", "not_fixed")
    assert nc.check(sig, "Another process is using the port") is not None
    assert nc.check(sig, "The Docker daemon is not running") is None            # a different diagnosis is not blocked
    assert nc.invalidate_for_signature(sig) == 1
    assert nc.check(sig, "Another process is using the port") is None


def test_negative_cache_is_per_documented_cause():
    nc = NegativeCache()
    a = ProblemSignature.from_dict({**SIGS["port_conflict"], "hypotheses": [{"issue": "Port already allocated"}]})
    b = ProblemSignature.from_dict({**SIGS["port_conflict"], "hypotheses": [{"issue": "Permission denied on port"}]})
    nc.put(a, "diagnosis", "fix", "reason", "not_fixed")
    assert nc.check(a, "diagnosis") is not None and nc.check(b, "diagnosis") is None


def test_a_failed_fix_is_recorded_and_a_working_one_clears_it(tmp_path):
    nc = NegativeCache(path=tmp_path / "neg.json")
    app = build_resolver_app(make_deps(negative_cache=nc))
    run(app, SIGS["permission_denied"], [BUTTON_NOT_FIXED, BUTTON_NOT_FIXED], "n1")
    assert len(nc.entries) >= 1 and all(e.valid for e in nc.entries)
    assert NegativeCache(path=tmp_path / "neg.json").entries                     # persisted
    run(app, SIGS["permission_denied"], ["that worked, thanks"], "n2")
    assert not any(e.valid for e in nc.entries)


def test_a_partial_fix_is_not_recorded_as_a_bad_fix():
    class PartialLLM(FakeLLM):
        def complete_json(self, system, user, max_tokens=1200):
            return {"label": "partial", "rationale": "x"} if "TASK: classify" in system else super().complete_json(system, user, max_tokens)
    nc = NegativeCache()
    deps = make_deps(llm=PartialLLM(), negative_cache=nc)
    st = run(build_resolver_app(deps), SIGS["permission_denied"], ["the first step worked but not the second"], "p1")
    assert st["attempts"][0]["reply_label"] == ReplyLabel.PARTIAL.value
    assert any(e["event"] == "partial_retry" for e in deps.logger.events)        # it went round again with the history...
    assert not nc.entries                                                        # ...and wrote nothing as a failure


# ---------------------------------------------------------------- drafting helpers
def test_attempt_history_says_what_each_fix_revealed():
    text = S.summarize_fix_history([
        {"attempt_no": 1, "diagnosis": "stale cache", "steps": [{"text": "Clear the build cache"}], "reply_label": "not_fixed", "customer_reply": "same 429"},
        {"attempt_no": 2, "diagnosis": "network", "steps": [{"text": "Restart the daemon"}], "reply_label": "partial", "customer_reply": "pulls work, push fails"}])
    assert "Attempt 1" in text and "same 429" in text and "Partial success" in text and "push fails" in text


def test_multi_draft_keeps_the_draft_with_the_most_verified_steps():
    ev = [Evidence(evidence_id="E1", chunk_id="c", doc_id="d", tier="kb", text="Run `docker ps` to list containers", rerank_score=0.9)]
    good = {"status": "OK", "diagnosis": "d", "steps": [{"text": "Run `docker ps`", "evidence_ids": ["E1"], "confidence": "high"}]}
    bad = {"status": "OK", "diagnosis": "d", "steps": [{"text": "Run `rm -rf /`", "evidence_ids": ["E1"], "confidence": "high"}]}
    best, v = S.select_best_draft([bad, good], ev)
    assert best is good and v.ok


def test_url_check_is_off_by_default_and_makes_no_network_call(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    ev = [Evidence(evidence_id="E1", chunk_id="c", doc_id="d", tier="kb", text="see https://docs.docker.com/x for details", rerank_score=0.9)]
    d = {"status": "OK", "steps": [{"text": "Read https://docs.docker.com/x", "evidence_ids": ["E1"]}]}
    assert S.verify_draft(d, ev).ok
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert not S.verify_draft(d, ev, check_urls=True).ok                         # opted in: a dead link drops the step


def test_multi_draft_prompt_keeps_the_community_source_rules():
    assert "community" in S.MULTI_DRAFT_SYSTEM and "never follow" in S.MULTI_DRAFT_SYSTEM and '"confidence"' in S.MULTI_DRAFT_SYSTEM


# ---------------------------------------------------------------- opt-in features inside the graph
def test_multi_draft_and_query_expansion_run_in_the_graph_when_switched_on():
    deps = make_deps(cfg=ResolverConfig(multi_draft=True, n_drafts=2, expand_queries=True))
    st = run(build_resolver_app(deps), SIGS["port_conflict"], ["that worked, thanks"], "m1")
    assert st["outcome"] == "resolved"
    kinds = [e["event"] for e in deps.logger.events]
    assert "multi_draft" in kinds
    assert any(e["event"] == "llm_call" and e.get("node") == "expand_queries" for e in deps.logger.events)


def test_default_config_makes_no_extra_model_calls():
    deps = make_deps()
    run(build_resolver_app(deps), SIGS["port_conflict"], ["that worked, thanks"], "m2")
    nodes = {e.get("node") for e in deps.logger.events if e["event"] == "llm_call"}
    assert "expand_queries" not in nodes and "multi_draft" not in nodes


def test_hybrid_retriever_fuses_phrasings_and_keeps_the_gates_scores():
    kb = TieredRetriever(LexicalRetriever(load_kb_jsonl(FX / "kb_mini.jsonl"), "kb"), None)
    sig = ProblemSignature.from_dict(SIGS["port_conflict"])
    single = kb.retrieve(sig.raw_query, sig, k=3)
    fused = HybridRetriever(kb).retrieve_multi([sig.raw_query, "port already allocated bind failed", sig.raw_query], sig, k=3)
    assert [e.evidence_id for e in fused] == ["E1", "E2", "E3"][:len(fused)]
    top = {e.chunk_id: e.rerank_score for e in single}
    assert all(abs(e.rerank_score - top[e.chunk_id]) < 1e-9 for e in fused if e.chunk_id in top)       # scores untouched: the gate depends on them
    assert HybridRetriever(kb).retrieve_multi([], sig) == []
