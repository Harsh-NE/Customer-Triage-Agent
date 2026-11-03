"""Regression tests for the fixes that followed the project review (reports/PROJECT_EVALUATION_REPORT.md): draft validation, content-free
detection, provider timeouts, the held-out label review, a quoted error beating an uncovered word on the real store, and the API-level
behaviour of a malformed draft. The graph-level tests for the same changes are at the end of tests/test_integration.py."""

import json
import sys
import types
from pathlib import Path

import pytest

from triage import config
from triage.resolver import steps as S
from triage.resolver.guardrails import DOMAIN_TERMS, content_free
from triage.resolver.llm import FakeLLM

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- draft validation
def test_normalize_repairs_harmless_variations():
    d = S.normalize_draft({"steps": [{"text": "Authenticate", "evidence_ids": "E1"}], "diagnosis": None, "verification": None})
    assert d["status"] == "OK" and d["steps"][0]["evidence_ids"] == ["E1"] and d["diagnosis"] == "" and d["verification"] == ""
    assert S.normalize_draft({"status": "INSUFFICIENT_EVIDENCE"})["steps"] == []
    assert S.normalize_draft({"steps": None})["steps"] == []


@pytest.mark.parametrize("bad", [[1, 2], "text", None, {"steps": "just do it"}, {"steps": ["a", "b"]}, {"steps": [{"evidence_ids": ["E1"]}]},
                                 {"steps": [{"text": "x", "evidence_ids": {"a": 1}}]}], ids=["list", "string", "none", "steps-string", "steps-strings", "no-text", "ids-dict"])
def test_normalize_refuses_replies_that_would_make_the_steps_meaningless(bad):
    with pytest.raises(S.MalformedDraft):
        S.normalize_draft(bad)


class Scripted(FakeLLM):
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def complete_json(self, system, user, max_tokens=1200):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def sig_and_evidence():
    from triage.resolver.contracts import Evidence, ProblemSignature
    return ProblemSignature(raw_query="x"), [Evidence(evidence_id="E1", chunk_id="c", doc_id="d", tier="kb", text="Run `docker ps`", rerank_score=0.9)]


GOOD = {"status": "OK", "diagnosis": "d", "steps": [{"text": "Run `docker ps`", "evidence_ids": ["E1"]}], "verification": "v"}


def test_draft_step_retries_a_malformed_reply_once_and_marks_it():
    llm = Scripted([{"steps": "oops"}, GOOD])
    d = S.draft_resolution(llm, *sig_and_evidence(), [])
    assert llm.calls == 2 and d["retried"] is True and d["steps"][0]["text"] == "Run `docker ps`" and "malformed" not in d


def test_draft_step_gives_up_after_two_bad_replies_without_raising():
    llm = Scripted([[1], ValueError("LLM response was not valid JSON: 'Sure!'")])
    d = S.draft_resolution(llm, *sig_and_evidence(), [])
    assert llm.calls == 2 and d["status"] == "INSUFFICIENT_EVIDENCE" and d["steps"] == [] and d["retried"] is True
    assert "ValueError" in d["malformed"]                                          # the last failure is the one recorded


def test_a_good_first_reply_costs_one_call_and_is_not_marked_retried():
    llm = Scripted([GOOD])
    d = S.draft_resolution(llm, *sig_and_evidence(), [])
    assert llm.calls == 1 and "retried" not in d


@pytest.mark.parametrize("exc", [TimeoutError("read timed out"), ConnectionError("reset"), RuntimeError("503")])
def test_provider_failures_are_never_retried_by_the_draft_step(exc):
    llm = Scripted([exc, GOOD])
    with pytest.raises(type(exc)):
        S.draft_resolution(llm, *sig_and_evidence(), [])
    assert llm.calls == 1


def test_multi_draft_skips_malformed_samples():
    llm = Scripted([{"steps": "bad"}, GOOD, [1]])
    drafts = S.multi_draft_resolution(llm, *sig_and_evidence(), [], n_drafts=3)
    assert len(drafts) == 1 and drafts[0]["steps"][0]["confidence"] == "medium"


# ---------------------------------------------------------------- content-free detection
@pytest.mark.parametrize("text", ["help", "it doesn't work", "error", "please fix", "I don't know, nothing happens", "1\nnone of these fit"])
def test_generic_complaints_are_content_free(text):
    assert content_free(text)


@pytest.mark.parametrize("text", ["what is the weather in chennai", "my excel formula is broken", "asdf qwerty", "docker pull 429", "exit code 137",
                                  "image pulls are failing with toomanyrequests"])
def test_anything_that_says_what_is_wrong_is_not_content_free(text):
    assert not content_free(text)


def test_naming_the_product_is_not_describing_the_problem():
    assert not content_free("I have a problem with docker") and content_free("I have a problem with docker", DOMAIN_TERMS)
    assert content_free("docker is broken", DOMAIN_TERMS) and not content_free("docker pull fails with toomanyrequests", DOMAIN_TERMS)
    assert not content_free("Docker Hub pulls are failing with a 429 error", DOMAIN_TERMS)


# ---------------------------------------------------------------- provider timeouts
def fake_sdk(monkeypatch, module, class_name):
    seen = {}

    class Client:
        def __init__(self, **kw):
            seen.update(kw)

    mod = types.ModuleType(module)
    setattr(mod, class_name, Client)
    monkeypatch.setitem(sys.modules, module, mod)
    return seen


def test_anthropic_and_openai_clients_get_a_timeout_and_a_retry_cap(monkeypatch):
    from triage import llm
    assert llm.PROVIDER_TIMEOUT_S == llm.GEMINI_TIMEOUT_S == 90 and llm.PROVIDER_MAX_RETRIES == 1
    seen = fake_sdk(monkeypatch, "anthropic", "Anthropic")
    with pytest.raises(AttributeError):                     # the fake client has no .messages: only the constructor arguments matter here
        llm._call_anthropic("hi", "m", "k")
    assert seen == {"api_key": "k", "timeout": 90, "max_retries": 1}
    seen = fake_sdk(monkeypatch, "openai", "OpenAI")
    with pytest.raises(AttributeError):
        llm._call_openai("hi", "m", "k")
    assert seen == {"api_key": "k", "timeout": 90, "max_retries": 1}


def test_the_resolvers_direct_anthropic_and_openai_wrappers_get_them_too(monkeypatch):
    from triage.resolver import llm as rl
    seen = fake_sdk(monkeypatch, "anthropic", "Anthropic")
    rl.AnthropicLLM()
    assert seen == {"timeout": 90, "max_retries": 1}
    seen = fake_sdk(monkeypatch, "openai", "OpenAI")
    rl.OpenAICompatLLM(base_url="http://localhost:1/v1")
    assert seen == {"base_url": "http://localhost:1/v1", "timeout": 90, "max_retries": 1}


def test_gemini_keeps_its_timeout(monkeypatch):
    from triage import llm
    captured = {}

    class Opts:
        def __init__(self, timeout):
            captured["timeout"] = timeout

    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")
    types_mod.HttpOptions = Opts

    class Client:
        def __init__(self, **kw):
            pass

        class models:
            @staticmethod
            def generate_content(**kw):
                return types.SimpleNamespace(text="ok", usage_metadata=None)

    genai.Client, genai.types = Client, types_mod
    google.genai = genai
    for name, mod in (("google", google), ("google.genai", genai), ("google.genai.types", types_mod)):
        monkeypatch.setitem(sys.modules, name, mod)
    assert llm._call_gemini("hi", "m", "k") == "ok" and captured["timeout"] == 90 * 1000


# ---------------------------------------------------------------- held-out label review
def test_the_heldout_labels_all_carry_an_honest_review_status():
    rows = [json.loads(line) for line in (ROOT / "triage" / "eval" / "heldout_scenarios.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    gold = [r for r in rows if r["gold"]]
    gaps = [r for r in rows if r["note"].startswith("kb_gap")]
    assert len(gold) == 19 and len(gaps) == 46 and len(rows) == 65
    assert sum("verified=reviewer-confirmed" in r["note"] or "verified=reviewer-relabelled-confirmed" in r["note"] for r in gold) == 11
    assert sum("verified=reviewer-weak" in r["note"] or "verified=reviewer-relabelled-weak" in r["note"] for r in gold) == 8
    assert all("verified=reviewer-confirmed-gap" in r["note"] for r in gaps)
    assert not any("verified=True" in r["note"] or "verified=False" in r["note"] for r in rows)       # reviewed by a model, not by a person; none left unreviewed


# ---------------------------------------------------------------- real store: the exact message that triggered the Clarifier fix
STORE = config.PROJECT_ROOT / config.get_env()["VECTOR_DB_PATH"]


@pytest.mark.real_store
@pytest.mark.skipif(not (STORE / "chroma.sqlite3").exists(), reason="Docker vector store not built locally")
def test_a_quoted_documented_error_plus_a_descriptive_sentence_needs_no_question():
    from triage.clarifier import Clarifier
    from triage.hybrid import HybridKBRetriever
    from triage.state import ClarifierStatus
    try:
        kb = HybridKBRetriever()
        kb.search("docker", top_k=1)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"stores unavailable: {exc}")
    quoted = "Error response from daemon: toomanyrequests: You have reached your pull rate limit."
    for message in (f"Getting this error in while pulling nginx server\n\n{quoted}",
                    f"Getting this error in while pulling nginx server\n\n$ docker pull nginx\n{quoted}"):
        cl = Clarifier(None, kb)
        res = cl.turn(cl.start("T-nginx"), message)
        assert res.status is ClarifierStatus.READY and res.questions_asked == 0, (res.reason, message)
        assert "pull rate limit" in res.signature.hypotheses[0].label.lower()
        assert "server" in (res.meta.get("uncovered_terms") or [])                          # the doubt is still passed to the Resolver


# ---------------------------------------------------------------- the knowledge graph's one wrong "undocumented" claim
def test_the_socket_permission_issue_links_to_the_section_that_documents_it():
    from triage.ontology import load_ontology
    node = load_ontology().by_id["issue-socket-permission"]
    assert [(l.path, l.issue) for l in node.kb] == [("engine/install/linux-postinstall.md", "Manage Docker as a non-root user")]
    undocumented = sorted(e.id for e in load_ontology().issues() if not e.kb)
    assert undocumented == ["issue-compose-v1-not-found", "issue-exec-format-error", "issue-no-space", "issue-pull-access-denied"]
