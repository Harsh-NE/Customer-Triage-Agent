import pytest

from triage.clarifier import Clarifier, render_question
from triage.config import ClarifierConfig
from triage.retrieval import MockRetriever
from triage.state import ClarifierStatus, NeedClarification, validate_signature

HUB_PATH = "content/manuals/docker-hub/troubleshoot.md"


def _top(res):
    return res.signature.hypotheses[0].label


# ---------------- the main paths ----------------
def test_specific_report_is_ready_without_asking_and_the_signature_is_contract_valid(make_clarifier):
    cl = make_clarifier()
    s = cl.start("T-1")
    res = cl.turn(s, "docker pull fails with 'You have reached your pull rate limit' HTTP 429 on Docker Hub")
    assert res.status is ClarifierStatus.READY and res.question is None and res.questions_asked == 0
    assert "pull rate limit" in _top(res)
    assert validate_signature(res.signature) == []
    assert res.signature.canonical_string.startswith("docker-hub|")
    assert 1 <= len(res.signature.hypotheses) <= 3


def test_near_duplicate_issues_trigger_the_error_text_question_then_resolve(make_clarifier):
    cl = make_clarifier()
    s = cl.start()
    res = cl.turn(s, "docker pull on Docker Hub keeps failing with a 429")
    assert res.status is ClarifierStatus.ASK and res.question.feature == "error_message"
    assert len(res.question.options) == 2 and res.question.text.count("?") == 1
    res = cl.turn(s, "Too Many Requests")
    assert res.status is ClarifierStatus.READY and "Too many requests" in _top(res)
    assert res.questions_asked == 1


def test_numbered_reply_selects_the_option(make_clarifier):
    cl = make_clarifier()
    s = cl.start()
    q = cl.turn(s, "docker pull on Docker Hub keeps failing with a 429").question
    wanted = next(i for i, o in enumerate(q.options, 1) if "pull rate limit" in o)
    res = cl.turn(s, str(wanted))
    assert res.status is ClarifierStatus.READY and "pull rate limit" in _top(res)


def test_platform_split_asks_for_the_operating_system(make_clarifier):
    cl = make_clarifier()
    s = cl.start()
    res = cl.turn(s, "Docker Desktop will not start")
    assert res.status is ClarifierStatus.ASK and res.question.feature == "platform"
    res = cl.turn(s, "I'm on Windows")
    assert res.status is ClarifierStatus.READY and "anti-virus" in _top(res)
    assert s.fields.platform == "windows" and s.answered["platform"] == "windows"


def test_content_free_message_asks_for_symptoms_not_for_the_product(make_clarifier):
    cl = make_clarifier()
    res = cl.turn(cl.start(), "it doesn't work")
    assert res.status is ClarifierStatus.ASK and res.question.feature == "symptoms"
    assert "?" not in res.question.text or res.question.text.count("?") == 1


def test_product_is_inferred_from_the_cause_when_the_customer_never_names_it(make_clarifier):
    cl = make_clarifier()
    res = cl.turn(cl.start(), "pull fails: You have reached your pull rate limit")
    assert res.status is ClarifierStatus.READY
    assert res.meta.get("inferred") == {"product_area": "docker-hub"}
    assert res.signature.fields.product_area == "docker-hub"


# ---------------- budget, repetition, unknowns ----------------
def test_budget_exhaustion_returns_unresolved_with_signature_and_hypotheses(make_clarifier):
    cl = make_clarifier(cfg=ClarifierConfig(max_clarify_turns=1))
    s = cl.start()
    assert cl.turn(s, "docker pull on Docker Hub keeps failing with a 429").status is ClarifierStatus.ASK
    res = cl.turn(s, "no idea, sorry")                       # unhelpful; budget (1) is spent
    assert res.status is ClarifierStatus.UNRESOLVED and res.questions_asked == 1
    assert res.signature is not None and res.signature.confidence.ambiguous
    assert validate_signature(res.signature) == []


def test_questions_are_never_repeated_and_unknown_counts_as_answered(make_clarifier):
    cl = make_clarifier()
    s = cl.start()
    cl.turn(s, "Docker Desktop will not start")             # asks platform
    cl.turn(s, "not sure which one")                         # 'unknown'
    texts = [q.text for q in s.questions]
    assert len(texts) == len(set(texts)) and [q.feature for q in s.questions].count("platform") == 1
    assert s.answered.get("platform") == "unknown"


def test_unmatched_menu_reply_that_looks_like_an_error_is_kept_as_evidence():
    corpus = [{"chunk_id": f"x{i}", "text": f"{n} problem with widgets and gadgets", "source_path": "doc.md",
               "article_title": "Doc", "heading_path": ["Doc", n], "metadata": {"doc_kind": "troubleshooting", "product_area": "engine"}}
              for i, n in enumerate(["Alpha", "Beta"])]
    cl = Clarifier(None, MockRetriever(corpus))
    s = cl.start()
    res = cl.turn(s, "widgets and gadgets problem on docker engine")
    assert res.status is ClarifierStatus.ASK and res.question.feature == "issue"
    res = cl.turn(s, "Error: widget exploded 0x42")          # not a menu option, but error-shaped
    assert "Error: widget exploded 0x42" in s.fields.error_messages


def test_failed_menu_falls_back_to_asking_for_the_exact_error_once():
    corpus = [{"chunk_id": f"x{i}", "text": f"{n} problem with widgets and gadgets", "source_path": "doc.md",
               "article_title": "Doc", "heading_path": ["Doc", n], "metadata": {"doc_kind": "troubleshooting", "product_area": "engine"}}
              for i, n in enumerate(["Alpha", "Beta"])]
    cl = Clarifier(None, MockRetriever(corpus))
    s = cl.start()
    cl.turn(s, "widgets and gadgets problem on docker engine")                       # issue menu
    res = cl.turn(s, "none of these fit")
    assert res.status is ClarifierStatus.ASK and res.question.feature == "error_open" and not res.question.options
    assert res.meta.get("last_resort") is True
    res = cl.turn(s, "there is no error, it just fails")                              # nothing to add
    assert "error_open" in s.answered and s.answered["error_open"] == "unknown" and not s.fields.error_messages
    assert [q.feature for q in s.questions].count("error_open") == 1


def test_open_ended_error_reply_is_stored_verbatim():
    corpus = [{"chunk_id": "x0", "text": "Alpha problem with widgets", "source_path": "d.md", "article_title": "D",
               "heading_path": ["D", "Alpha"], "metadata": {"doc_kind": "troubleshooting", "product_area": "engine"}},
              {"chunk_id": "x1", "text": "Beta problem with widgets", "source_path": "d.md", "article_title": "D",
               "heading_path": ["D", "Beta"], "metadata": {"doc_kind": "troubleshooting", "product_area": "engine"}}]
    cl = Clarifier(None, MockRetriever(corpus))
    s = cl.start()
    cl.turn(s, "widgets problem on docker engine")
    cl.turn(s, "none of these fit")
    cl.turn(s, "it prints: fatal widget collapse (code 7)")
    assert any("fatal widget collapse" in m for m in s.fields.error_messages)


# ---------------- Resolver callback ----------------
def test_resolver_callback_asks_one_targeted_question_within_the_shared_budget(make_clarifier):
    cl = make_clarifier(cfg=ClarifierConfig(max_clarify_turns=2))
    s = cl.start()
    assert cl.turn(s, "docker pull fails with 'You have reached your pull rate limit' on Docker Hub").status is ClarifierStatus.READY
    res = cl.reenter(s, NeedClarification("platform", "evidence differs per OS"))
    assert res.status is ClarifierStatus.ASK and res.question.feature == "platform" and res.meta["callback"] == "platform"
    assert s.questions_asked == 1
    cl.turn(s, "macOS")
    again = cl.reenter(s, NeedClarification("platform"))
    assert again.status is ClarifierStatus.UNRESOLVED and again.reason.startswith("cannot_clarify")  # already known


def test_resolver_callback_respects_the_budget(make_clarifier):
    cl = make_clarifier(cfg=ClarifierConfig(max_clarify_turns=0))
    res = cl.reenter(cl.start(), NeedClarification("platform"))
    assert res.status is ClarifierStatus.UNRESOLVED and res.reason == "budget_exhausted"


# ---------------- tools / metadata ----------------
def test_result_meta_reports_this_turns_tool_calls_and_extraction_source(make_clarifier):
    cl = make_clarifier()
    s = cl.start()
    r1 = cl.turn(s, "docker pull fails with 'You have reached your pull rate limit' on Docker Hub")
    names = [c["tool"] for c in r1.meta["tool_calls"]]
    assert names.count("search_kb") == 3 and r1.meta["extraction_source"] == "heuristic"
    r2 = cl.turn(cl.start(), "it doesn't work")
    assert [c["tool"] for c in r2.meta["tool_calls"]] == ["ask_customer"]       # no search on a content-free message
    assert r1.meta["hypotheses"] and "p_top" in r1.meta["confidence"]


def test_question_templates_have_one_question_mark_and_a_distinct_rephrase():
    for feature, options in (("platform", ["windows", "mac"]), ("symptoms", []), ("product_area", ["desktop", "engine"]),
                             ("error_message", ["A", "B"]), ("issue", ["A", "B"]), ("error_message", []),
                             ("component", ["pulls", "builds"]), ("component", [])):
        v0, v1 = render_question(feature, options, 0), render_question(feature, options, 1)
        assert v0 != v1
        lead = lambda t: " ".join(l for l in t.splitlines() if not l.strip()[:2].rstrip(".").isdigit())
        assert lead(v0).count("?") <= 1 and lead(v1).count("?") <= 1


# ---------------- LangGraph wiring ----------------
def test_langgraph_graph_matches_the_plain_call(make_clarifier):
    pytest.importorskip("langgraph")
    msgs = ["docker pull on Docker Hub keeps failing with a 429", "Too Many Requests"]
    plain_cl, graph_cl = make_clarifier(), make_clarifier()
    s1, s2 = plain_cl.start("A"), graph_cl.start("A")
    graph = graph_cl.build_graph()
    for m in msgs:
        r_plain = plain_cl.turn(s1, m)
        r_graph = graph.invoke({"session": s2, "customer_message": m})["result"]
        assert r_graph.status == r_plain.status
        assert (r_graph.question.text if r_graph.question else None) == (r_plain.question.text if r_plain.question else None)
        assert (r_graph.signature.canonical_string if r_graph.signature else None) == \
               (r_plain.signature.canonical_string if r_plain.signature else None)


def test_graph_takes_the_gap_branch_for_vague_input(make_clarifier):
    pytest.importorskip("langgraph")
    cl = make_clarifier()
    out = cl.build_graph().invoke({"session": cl.start(), "customer_message": "help"})
    assert out["result"].status is ClarifierStatus.ASK and out["result"].question.feature == "symptoms"


def test_as_node_plugs_into_an_outer_graph_state(make_clarifier):
    cl = make_clarifier()
    node = cl.as_node()
    out = node({"session": cl.start(), "customer_message": "it doesn't work"})
    assert out["clarifier_result"].status is ClarifierStatus.ASK


# ---------------- S17 regression: do not answer confidently while ignoring the customer's distinguishing word ----------------
class _FixedRetriever:
    def __init__(self, cands):
        self.cands = cands

    def search(self, query, top_k=8):
        return list(self.cands)


def _s17_pool():
    from triage.state import Candidate

    def c(cid, issue, score, text):
        return Candidate(cid, text, score, "content/x.md", "Docs", ["Docs", issue], {"doc_kind": "troubleshooting"})
    return [c("lead", "Troubleshooting failed pulls", 0.70, "docker pull fails: the registry is unreachable"),
            c("o1", "Rootless mode", 0.55, "rootless mode user namespaces"),
            c("o2", "Rootless networking", 0.54, "rootless networking slirp4netns"),
            c("o3", "Daemon socket", 0.53, "daemon socket permission"),
            c("o4", "Disk space", 0.52, "disk space full")]


def test_leader_missing_the_customers_distinguishing_word_triggers_a_question_then_is_waived():
    cl = Clarifier(None, _FixedRetriever(_s17_pool()))
    s = cl.start()
    res = cl.turn(s, "docker pull fails for me on rootless Docker")
    assert res.status is ClarifierStatus.ASK and res.question.feature == "issue"
    assert res.meta["confidence"]["reason"] == "uncovered_term" and res.meta["uncovered_terms"] == ["rootless"]
    res = cl.turn(s, "1")                          # the customer picks the leader: the doubt must not veto READY again
    assert res.status is ClarifierStatus.READY and res.reason == "clear" and "failed pulls" in _top(res)


def test_without_the_rare_term_check_the_same_pool_is_answered_confidently_with_no_question():
    # negative control: this is the S17 failure -- confident READY on an issue that never mentions "rootless"
    cl = Clarifier(None, _FixedRetriever(_s17_pool()), ClarifierConfig(rare_term_max_share=0.0))
    res = cl.turn(cl.start(), "docker pull fails for me on rootless Docker")
    assert res.status is ClarifierStatus.READY and res.questions_asked == 0 and "failed pulls" in _top(res)


def test_uncovered_term_with_nothing_to_ask_keeps_the_leader_but_says_so():
    pool = _s17_pool()[:1] + [p for p in _s17_pool()[1:]]
    for p in pool[1:]:
        p.score = 0.05                              # others are implausible: no question can separate anything
    cl = Clarifier(None, _FixedRetriever(pool))
    s = cl.start()
    res = cl.turn(s, "docker pull fails for me on rootless Docker, error: 'pull access denied for registry'")
    assert res.status is ClarifierStatus.READY and res.questions_asked == 0
    assert res.reason == "clear_with_uncovered_term" and res.meta["uncovered_terms"] == ["rootless"]
