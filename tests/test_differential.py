import pytest

from triage.config import ClarifierConfig
from triage.differential import (ambiguity_check, apply_answers, apply_error_evidence, build_hypotheses, decide,
                                 lexical_grounding, rank_discriminators)
from triage.issues import issue_key, issue_title
from triage.retrieval import MockRetriever
from triage.state import Candidate, ExtractedFields, Hypothesis
from triage.tools import make_clarifier_registry

CFG = ClarifierConfig()


def _cand(cid, heading, score=0.7, path="a.md", text="x", **meta):
    return Candidate(cid, text, score, path, heading[0], heading, {"doc_kind": "troubleshooting", **meta})


def _h(key, weight, **features):
    return Hypothesis(key, key, weight, weight, [key], features)


# ---- clustering handles both heading layouts of the real KB -------------------------
def test_issue_title_when_issue_is_h2_and_fields_are_h3():
    c = _cand("1", ["Troubleshoot Docker Hub", "Too many requests (429 response code)", "Error message"])
    assert issue_title(c) == "Too many requests (429 response code)"


def test_issue_title_when_issue_is_h3_under_a_topic_group():
    c = _cand("1", ["Troubleshoot topics", "Topics for Windows", "Docker Desktop fails to start"])
    assert issue_title(c) == "Docker Desktop fails to start"


def test_error_message_and_solution_chunks_join_one_hypothesis_but_different_issues_do_not():
    cands = [_cand("a1", ["T", "Issue A", "Error message"], 0.8), _cand("a2", ["T", "Issue A", "Solution"], 0.7),
             _cand("b1", ["T", "Issue B", "Error message"], 0.6)]
    assert issue_key(cands[0]) == issue_key(cands[1]) != issue_key(cands[2])
    hyps = build_hypotheses(cands, CFG)
    assert len(hyps) == 2 and sorted(h.chunk_ids for h in hyps) == [["a1", "a2"], ["b1"]]
    assert sum(h.weight for h in hyps) == pytest.approx(1.0)


def test_release_notes_are_downweighted_and_overview_is_penalised():
    cands = [_cand("t", ["T", "Real issue", "Solution"], 0.70),
             _cand("r", ["Release notes", "Bug fixes"], 0.70, doc_kind="release_notes"),
             _cand("o", ["T2", "Overview"], 0.70)]
    w = {h.key.split("::")[1]: h.weight for h in build_hypotheses(cands, CFG)}
    assert w["Real issue"] > w["Bug fixes"] and w["Real issue"] > w["Overview"]


# ---- grounding ------------------------------------------------------------------------------
def test_lexical_grounding():
    chunks = [_cand("1", ["T", "Daemon"], text="Cannot connect to the Docker daemon. The daemon is not running.")]
    on_topic = ExtractedFields(symptoms=["can't connect to the daemon"])
    off_topic = ExtractedFields(symptoms=["netflix password reset"])
    assert lexical_grounding(on_topic, chunks) >= 0.5 and lexical_grounding(off_topic, chunks) == 0.0
    assert lexical_grounding(ExtractedFields(), chunks) == 1.0          # nothing to check -> do not penalise


# ---- decide -----------------------------------------------------------------------------------
def test_decide_clear_split_ungrounded_and_empty():
    clear = [_h("a", 0.8), _h("b", 0.2)]
    split = [_h("a", 0.4), _h("b", 0.35), _h("c", 0.25)]
    assert decide(clear, CFG).reason == "clear" and not decide(clear, CFG).ambiguous
    assert decide(split, CFG).reason == "split" and decide(split, CFG).ambiguous
    ungrounded = [_h("a", 0.9), _h("b", 0.1)]
    ungrounded[0].grounding = 0.0
    assert decide(ungrounded, CFG).reason == "ungrounded"
    assert decide([], CFG).reason == "no_candidates"


def test_decide_respects_thresholds_in_config():
    hyps = [_h("a", 0.6), _h("b", 0.4)]
    assert not decide(hyps, ClarifierConfig(ready_p_top=0.5, ready_margin=0.1)).ambiguous
    assert decide(hyps, ClarifierConfig(ready_p_top=0.5, ready_margin=0.3)).ambiguous


# ---- discriminating questions -----------------------------------------------------------------------
def test_platform_is_chosen_when_causes_split_by_platform():
    hyps = [_h("w", 0.5, platform="windows", issue="W"), _h("m", 0.5, platform="mac", issue="M")]
    ranked = rank_discriminators(hyps, ExtractedFields(), set(), CFG)
    assert ranked[0].feature == "platform" and set(ranked[0].options) == {"windows", "mac"}
    assert ranked[0].gain == pytest.approx(0.5)


def test_error_message_beats_issue_menu_for_a_near_duplicate_pair():
    hyps = [_h("a", 0.5, error_message="You have reached your pull rate limit", issue="Pull limit"),
            _h("b", 0.5, error_message="Too Many Requests", issue="Too many requests")]
    assert rank_discriminators(hyps, ExtractedFields(), set(), CFG)[0].feature == "error_message"


def test_issue_menu_is_the_fallback_and_never_offers_generic_titles():
    hyps = [_h("a", 0.4, issue="Alpha"), _h("b", 0.4, issue="Beta"), _h("c", 0.2, issue="Overview")]
    ranked = rank_discriminators(hyps, ExtractedFields(), set(), CFG)
    assert [d.feature for d in ranked] == ["issue"] and set(ranked[0].options) == {"Alpha", "Beta"}


def test_already_known_or_excluded_features_are_not_asked_and_low_gain_is_dropped():
    hyps = [_h("w", 0.5, platform="windows", issue="W"), _h("m", 0.5, platform="mac", issue="M")]
    assert "platform" not in [d.feature for d in rank_discriminators(hyps, ExtractedFields(platform="mac"), set(), CFG)]
    assert "platform" not in [d.feature for d in rank_discriminators(hyps, ExtractedFields(), {"platform"}, CFG)]
    lopsided = [_h("a", 0.97, platform="windows"), _h("b", 0.03, platform="mac")]
    assert rank_discriminators(lopsided, ExtractedFields(), set(), CFG) == []     # eliminates ~6%, not worth asking


def test_features_most_hypotheses_lack_score_low_automatically():
    hyps = [_h("a", 0.45, platform="windows"), _h("b", 0.45, platform="mac"), _h("c", 0.10)]   # c has no platform
    d = rank_discriminators(hyps, ExtractedFields(), set(), CFG)[0]
    assert d.gain < 0.5                       # unknown-valued hypotheses survive every answer


# ---- soft re-weighting ----------------------------------------------------------------------------------
def test_answers_penalise_but_never_remove_a_contradicting_hypothesis():
    hyps = apply_answers([_h("w", 0.5, platform="windows"), _h("m", 0.5, platform="mac")], {"platform": "windows"}, CFG)
    assert hyps[0].key == "w" and 0 < hyps[1].weight < 0.2
    assert sum(h.weight for h in hyps) == pytest.approx(1.0)


def test_unknown_answer_changes_nothing():
    hyps = apply_answers([_h("w", 0.5, platform="windows"), _h("m", 0.5, platform="mac")], {"platform": "unknown"}, CFG)
    assert [h.weight for h in hyps] == [0.5, 0.5]


def test_pasted_error_text_boosts_the_hypothesis_documenting_it():
    hyps = [_h("a", 0.5, error_message="You have reached your pull rate limit. You may increase the limit"),
            _h("b", 0.5, error_message="Too Many Requests")]
    out = apply_error_evidence(hyps, ["Too Many Requests"], CFG)
    assert out[0].key == "b" and out[0].weight > 0.7


def test_error_evidence_ignores_weak_overlap():
    hyps = [_h("a", 0.5, error_message="Cannot connect to the Docker daemon"), _h("b", 0.5)]
    assert [h.weight for h in apply_error_evidence(hyps, ["totally unrelated words here"], CFG)] == [0.5, 0.5]


# ---- the A4 entry point on the offline corpus ----------------------------------------------------------------
def test_ambiguity_check_runs_up_to_three_queries_and_respects_the_tool_budget(retriever):
    fields = ExtractedFields(product_area="docker-hub", symptoms=["pull fails"], error_messages=["Too Many Requests"])
    res = ambiguity_check(fields, make_clarifier_registry(retriever, 8, 3), {}, set(), CFG)
    assert len(res.queries) == 3 and res.queries[1].startswith("troubleshoot ")
    res1 = ambiguity_check(fields, make_clarifier_registry(MockRetriever([]), 8, 1), {}, set(), CFG)
    assert len(res1.queries) == 1 and res1.confidence.reason == "no_candidates"


def test_ambiguity_check_separates_the_demo_429_pair(retriever):
    fields = ExtractedFields(product_area="docker-hub", symptoms=["docker pull fails with a 429"],
                             error_codes=["HTTP 429 response code"])
    res = ambiguity_check(fields, make_clarifier_registry(retriever, 8, 3), {}, set(), CFG)
    labels = " ".join(h.label for h in res.hypotheses[:2])
    assert "pull rate limit" in labels and "Too many requests" in labels
    assert res.discriminators and res.discriminators[0].feature == "error_message"


# ---- rare-term grounding: a leader that lacks the one word that tells the issues apart ------------------------------
from triage.differential import rare_pool_terms, waive_uncovered_terms, AmbiguityResult  # noqa: E402


def _pool(leader_text, other_texts, leader_score=0.7, other_score=0.55):
    cands = [_cand("lead", ["T", "Issue lead"], leader_score, text=leader_text)]
    cands += [_cand(f"o{i}", ["T", f"Issue {i}"], other_score - 0.01 * i, text=t) for i, t in enumerate(other_texts)]
    return cands


ROOTLESS_FIELDS = ExtractedFields(symptoms=["docker pull fails for me on rootless Docker"])
OTHERS = ["rootless mode user namespaces", "rootless networking slirp4netns", "daemon socket permission", "disk space full"]


def test_leader_missing_a_discriminating_customer_term_is_flagged_and_not_clear():
    hyps = build_hypotheses(_pool("docker pull fails: registry unreachable", OTHERS), CFG, ROOTLESS_FIELDS)
    lead = next(h for h in hyps if h.chunk_ids == ["lead"])
    assert lead.missing_terms == ["rootless"] and hyps[0] is lead
    assert decide(hyps, CFG).reason == "uncovered_term" and decide(hyps, CFG).ambiguous
    assert decide(build_hypotheses(_pool("docker pull fails: registry unreachable", OTHERS), CFG), CFG).reason == "clear"  # no fields -> no check


def test_leader_that_covers_the_term_is_not_flagged():
    hyps = build_hypotheses(_pool("rootless docker pull fails", OTHERS), CFG, ROOTLESS_FIELDS)
    assert hyps[0].missing_terms == [] and decide(hyps, CFG).reason == "clear"


def test_terms_present_in_every_issue_or_in_none_are_not_discriminating():
    hays = ["docker pull rootless", "docker pull", "docker pull", "docker pull"]
    f = ExtractedFields(symptoms=["docker pull fails on rootless with zzzunknown"])
    assert set(rare_pool_terms(f, hays, CFG)) == {"rootless"}          # 'pull' is in all four, 'zzzunknown' in none


def test_function_words_and_stems_are_handled():
    f = ExtractedFields(symptoms=["they pulls images from our private registry"])
    hays = ["pull image registry", "pull image", "registry", "private tokens"]
    assert "from" not in rare_pool_terms(f, hays, CFG) and "they" not in rare_pool_terms(f, hays, CFG)
    hyps = build_hypotheses([_cand("a", ["T", "A"], 0.7, text="pull image"), _cand("b", ["T", "B"], 0.55, text="private x"),
                             _cand("c", ["T", "C"], 0.54, text="y"), _cand("d", ["T", "D"], 0.53, text="z")], CFG, f)
    assert "pulls" not in hyps[0].missing_terms and "images" not in hyps[0].missing_terms   # 'pull'/'image' found via stems


def test_rule_is_off_for_small_pools_and_when_disabled():
    cands = _pool("docker pull fails", ["rootless mode"])                   # 2 issues: 'rare' is meaningless
    assert build_hypotheses(cands, CFG, ROOTLESS_FIELDS)[0].missing_terms == []
    off = ClarifierConfig(rare_term_max_share=0.0)
    hyps = build_hypotheses(_pool("docker pull fails", OTHERS), off, ROOTLESS_FIELDS)
    assert hyps[0].missing_terms == [] and decide(hyps, off).reason == "clear"


def test_waiving_the_doubt_restores_the_ordinary_decision():
    hyps = build_hypotheses(_pool("docker pull fails: registry unreachable", OTHERS), CFG, ROOTLESS_FIELDS)
    amb = AmbiguityResult(hyps, decide(hyps, CFG), [])
    assert amb.confidence.reason == "uncovered_term"
    waived = waive_uncovered_terms(amb, CFG)
    assert waived.confidence.reason == "clear" and all(h.missing_terms == [] for h in waived.hypotheses)
    other = AmbiguityResult(hyps, decide([_h("a", 0.5), _h("b", 0.5)], CFG), [])
    assert waive_uncovered_terms(other, CFG).confidence.reason == "split"       # only this doubt is waived
