"""The perturbations used by the robustness evaluation: deterministic, each does what it says, and the summary arithmetic. Offline."""

import re

import pytest

from triage.eval import perturb_eval as P

Q = "docker pull fails with toomanyrequests: You have reached your pull rate limit on registry-1.docker.io port 443"


def test_every_perturbation_is_deterministic_and_seed_dependent():
    for kind in P.KINDS:
        assert P.perturb(Q, kind, 0) == P.perturb(Q, kind, 0)
    assert P.perturb(Q * 3, "typos", 0) != P.perturb(Q * 3, "typos", 1)                  # another seed, other typos


def test_unknown_kinds_are_refused():
    with pytest.raises(ValueError):
        P.perturb(Q, "banana")


def test_typos_swap_letters_but_never_touch_digits_symbols_or_the_length():
    long_text = " ".join([Q] * 6)
    out = P.perturb(long_text, "typos", 0)
    assert out != long_text and len(out) == len(long_text) and sorted(out) == sorted(long_text)       # only the order of letters changed
    for original, changed in zip(long_text.split(), out.split()):
        if not P.PLAIN_WORD.match(original):
            assert original == changed                                                    # registry-1.docker.io, 443, toomanyrequests: ... untouched
    assert "443" in out and "registry-1.docker.io" in out


def test_case_changes_and_chatter_keep_the_original_words():
    assert P.perturb(Q, "shouting") == Q.upper() and P.perturb(Q, "lowercase") == Q.lower()
    chat = P.perturb(Q, "chatter")
    assert chat.startswith("hi, ") and Q.strip() in chat and chat.endswith("for hours")


def test_log_noise_appends_unrelated_lines_without_changing_the_question():
    out = P.perturb(Q, "log_noise")
    assert out.startswith(Q) and 1000 < len(out) - len(Q) < 1400
    assert not re.search(r"(?i)docker|pull|rate limit", out[len(Q):])                      # the noise says nothing about the problem


def test_two_issues_appends_a_non_docker_question():
    out = P.perturb(Q, "two_issues")
    assert out.startswith(Q) and out[len(Q):].strip().startswith("Also,") and not re.search(r"(?i)docker", out[len(Q):])


def test_the_sets_have_gold_labels_that_resolve_and_enough_items():
    items = P.answerable_items()
    assert len(items) == 42 + 20 + 19 and all(i["gold"] and i["query"] for i in items)
    assert {i["set"] for i in items} == {"scenario", "heldout", "paraphrase"} and len({(i["set"], i["id"]) for i in items}) == len(items)


def test_summary_counts_improved_and_worsened_against_the_original():
    results = {"original": {"ranks": {"a": 1, "b": 3, "c": None}, "clarifier": [{"ready": True, "top1_right": True, "gold_in_top3": True}]},
               "typos": {"ranks": {"a": 2, "b": 1, "c": None}, "clarifier": [{"ready": False, "top1_right": True, "gold_in_top3": True}]}}
    rep = P.summarize(results)
    assert rep["typos"]["retrieval"]["improved"] == 1 and rep["typos"]["retrieval"]["worsened"] == 1
    assert rep["original"]["retrieval"]["recall@1"] == pytest.approx(1 / 3, abs=1e-3) and rep["typos"]["clarifier"] == {
        "n": 1, "ready": 0, "ready_and_top1_right": 0, "top1_right": 1, "gold_in_top3": 1}
