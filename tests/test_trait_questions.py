"""The Clarifier no longer asks "which of these sounds closest to your problem?". To tell similar causes apart it asks a question about
the one condition that separates them (a "trait" yes/no), or for more detail when no cause stands out. Offline: fixed retrievers."""

import pytest

from triage.answers import NONE_OF_ABOVE, match_option
from triage.clarifier import Clarifier
from triage.config import ClarifierConfig
from triage.differential import apply_answers, rank_discriminators, trait_question
from triage.reflect import reflect_question
from triage.sim.customer import RuleBasedCustomer, Scenario, classify_question
from triage.state import Candidate, ClarifierStatus, ExtractedFields, Hypothesis, QuestionPlan

CFG = ClarifierConfig()
AV = "Docker Desktop fails to start when anti-virus software is installed"
VIRT = "Docker Desktop fails due to Virtualization not working"
CPU = "Incompatible CPU detected"


def hyp(key, weight, issue, **features):
    return Hypothesis(key, key, weight, weight, [key], {"issue": issue, **features})


# ---------------- generating the question from a cause's own title ----------------
def test_a_condition_in_the_title_becomes_a_natural_question():
    assert trait_question(AV, [VIRT, CPU]) == ("Does this happen when anti-virus software is installed?", 1.0)
    assert trait_question(VIRT, [AV])[0] == "Could this be related to Virtualization not working?"
    assert trait_question("Pulls fail after upgrading Docker Desktop", [CPU])[0] == "Did this start after upgrading Docker Desktop?"


def test_a_title_with_no_condition_is_confirmed_with_its_own_words():
    question, quality = trait_question("Docker.app is damaged and can't be opened", [CPU])
    assert question == 'Does this describe your problem: "Docker.app is damaged and can\'t be opened"?' and quality == 1.0


def test_nothing_is_asked_when_nothing_sets_the_cause_apart_or_the_title_is_generic():
    assert trait_question("Overview", [CPU]) is None                         # a structural heading, not a cause
    assert trait_question("`docker pull` errors", [CPU]) is None            # too little content to ask about
    assert trait_question(AV, [AV + " (older versions)"]) is None            # the other cause says the same thing


# ---------------- which question is asked ----------------
def features(hyps, exclude=()):
    return [d.feature for d in rank_discriminators(hyps, ExtractedFields(), set(exclude), CFG)]


def test_the_closest_issue_menu_is_never_among_the_default_questions():
    assert "issue" not in CFG.feature_answerability
    assert "issue" not in features([hyp("a", 0.4, AV), hyp("b", 0.4, VIRT), hyp("c", 0.2, CPU)])


def test_two_close_causes_get_a_question_about_the_leading_ones_condition():
    ranked = rank_discriminators([hyp("a", 0.5, AV), hyp("b", 0.45, VIRT)], ExtractedFields(), set(), CFG)
    trait = next(d for d in ranked if d.feature.startswith(("trait:", "confirm:")))
    assert trait.feature == "trait:a" and trait.options == ["Yes", "No", "Not sure"]
    assert trait.detail["question"] == "Does this happen when anti-virus software is installed?"


def test_a_concrete_error_text_or_platform_still_beats_a_yes_no():
    hyps = [hyp("a", 0.5, "Pull limit", error_message="You have reached your pull rate limit"),
            hyp("b", 0.5, "Too many requests", error_message="Too Many Requests")]
    assert features(hyps)[0] == "error_message"
    win = [hyp("w", 0.5, AV, platform="windows"), hyp("m", 0.5, VIRT, platform="mac")]
    assert features(win)[0] == "platform"


def test_many_flat_causes_get_a_request_for_detail_not_a_yes_no_per_cause():
    flat = [hyp(k, 0.15, t) for k, t in zip("abcdef", [AV, VIRT, CPU, "Docker.app is damaged and can't be opened", "Access denied on launch", "Windows containers fail"])]
    assert features(flat) == ["detail"]


def test_after_the_detail_is_in_a_yes_no_is_allowed_even_when_the_field_is_still_flat():
    flat = [hyp(k, 0.17, t) for k, t in zip("abcdef", [AV, VIRT, CPU, "Docker.app is damaged and can't be opened", "Access denied on launch", "Windows containers fail"])]
    assert features(flat, exclude={"detail"})[0].startswith(("trait:", "confirm:"))


def test_a_cause_that_was_already_asked_about_is_not_asked_about_again():
    hyps = [hyp("a", 0.5, AV), hyp("b", 0.45, VIRT)]
    again = [d.feature for d in rank_discriminators(hyps, ExtractedFields(), {"trait:a"}, CFG)]
    assert "trait:a" not in again and "trait:b" in again


# ---------------- what the answer does ----------------
def test_yes_lifts_the_cause_no_sinks_it_and_not_sure_changes_nothing():
    def run(value):
        hs = [hyp("a", 0.5, AV), hyp("b", 0.5, VIRT)]
        return {h.key: h.weight for h in apply_answers(hs, {"trait:a": value}, CFG)}
    assert 0.65 < run("yes")["a"] < 0.8 and run("no")["a"] < 0.2 and run("unknown") == {"a": 0.5, "b": 0.5}   # yes is moderate, no is firm


def test_yes_no_and_not_sure_are_understood_in_plain_language():
    ask = lambda r: match_option("trait:a", r, ["Yes", "No", "Not sure"])        # noqa: E731
    assert [ask(r) for r in ("Yes", "yeah, that's right", "No", "nope", "No, it happens with a VPN", "not sure", "I don't know")] == \
           ["yes", "yes", "no", "no", "no", "unknown", "unknown"] == ["yes", "yes", "no", "no", "no", NONE_OF_ABOVE, NONE_OF_ABOVE]
    assert ask("it fails at the login step") is None                              # a real answer in other words: read as new information instead


def test_an_earlier_no_in_free_text_does_not_answer_a_yes_no_about_a_cause():
    from triage.context_session import SessionMemory
    s = SessionMemory("t")
    s.add_turn("customer", "no error message, it just never starts")
    verdict = reflect_question(QuestionPlan("trait:a", "Does this happen when anti-virus software is installed?\n(yes, no, or not sure)", ["Yes", "No", "Not sure"]), s)
    assert verdict.ask and verdict.filled_value is None


# ---------------- the whole conversation ----------------
def cand(cid, title, score):
    return Candidate(cid, f"{title}. details", score, f"{cid}.md", "Troubleshoot topics", ["Troubleshoot topics", title], {"doc_kind": "troubleshooting", "product_area": "desktop"})


class Fixed:
    def __init__(self, cands):
        self.cands = cands

    def search(self, query, top_k=8):
        return [Candidate(c.chunk_id, c.text, c.score, c.source_path, c.article_title, c.heading_path, dict(c.metadata)) for c in self.cands]


def pair():
    return Fixed([cand("av", AV, 0.62), cand("virt", VIRT, 0.60)])


def test_a_confirming_yes_resolves_and_a_no_hands_the_win_to_the_other_cause():
    for answer in ("yes", "no"):
        cl = Clarifier(None, pair())
        s = cl.start()
        res = cl.turn(s, "Docker Desktop will not start")
        assert res.status is ClarifierStatus.ASK and res.question.feature.startswith(("trait:", "confirm:"))
        asked_about = "anti-virus" if "anti-virus" in res.question.text else "Virtualization"       # whichever cause currently leads
        other = "Virtualization" if asked_about == "anti-virus" else "anti-virus"
        res = cl.turn(s, answer)
        assert res.status is ClarifierStatus.READY and (asked_about if answer == "yes" else other) in res.signature.hypotheses[0].label
        assert [x.lower() for x in s.fields.symptoms] == ["docker desktop will not start"]          # the bare yes / no is not stored as a symptom
        assert res.questions_asked == 1


def test_not_sure_does_not_move_the_decision_and_the_same_question_is_not_repeated():
    cl = Clarifier(None, pair())
    s = cl.start()
    cl.turn(s, "Docker Desktop will not start")
    res = cl.turn(s, "not sure")
    texts = [q.text for q in s.questions]
    assert len(texts) == len(set(texts))
    assert res.status is ClarifierStatus.UNRESOLVED or (res.question and res.question.feature != s.questions[0].feature)


def test_the_question_is_one_short_sentence_with_three_options_and_never_a_list_of_titles():
    cl = Clarifier(None, pair())
    res = cl.turn(cl.start(), "Docker Desktop will not start")
    assert res.question.options == ["Yes", "No", "Not sure"] and res.question.text.count("?") == 1
    assert "closest" not in res.question.text.lower() and not any(l.strip()[:2].rstrip(".").isdigit() for l in res.question.text.splitlines())


# ---------------- the simulated customer answers like someone who knows their own situation ----------------
def scenario(gold):
    return Scenario(id="X1", opening="Docker Desktop will not start", hidden={}, gold={"source_path_contains": "x", "issue_contains": gold})


def test_the_simulated_customer_says_yes_to_the_real_cause_and_no_to_another():
    ask = "Does this happen when anti-virus software is installed?\n(yes, no, or not sure)"
    assert classify_question(ask)[0] == "trait"
    assert RuleBasedCustomer(scenario("anti-virus software is installed")).reply(ask).startswith("Yes")
    assert RuleBasedCustomer(scenario("Incompatible CPU detected")).reply(ask).startswith("No")
    assert RuleBasedCustomer(Scenario(id="X2", opening="help", hidden={})).reply(ask) == "I'm not sure."


def test_the_detail_question_is_answered_with_the_customers_own_description():
    q = "Could you give me a bit more detail about what happens when it fails, such as which step breaks and what any message or screen says?"
    assert classify_question(q)[0] == "symptoms"


def test_a_yes_to_the_cause_in_its_own_words_is_strong_and_a_yes_to_one_condition_is_moderate():
    def lifted(kind):
        hs = [hyp("a", 0.4, AV), hyp("b", 0.6, VIRT)]
        return {h.key: h.weight for h in apply_answers(hs, {f"{kind}:a": "yes"}, CFG)}["a"]
    assert lifted("confirm") > 0.8 > lifted("trait") > 0.5
    assert trait_question("Docker.app is damaged and can't be opened", [CPU])[0].startswith("Does this describe")     # that form is the "confirm" kind


def test_saying_there_is_no_error_text_answers_the_question_without_becoming_a_symptom():
    cl = Clarifier(None, Fixed([cand("x1", "Alpha widget failure in engine", 0.6), cand("x2", "Beta widget failure in engine", 0.6)]))
    s = cl.start()
    cl.turn(s, "widgets fail in the engine")
    s.questions.append(__import__("triage.state", fromlist=["QuestionRecord"]).QuestionRecord(turn_idx=1, feature="error_open", text="Could you copy the exact error message you see?", options=[])) \
        if False else None
    from triage.state import QuestionPlan
    s.record_question(QuestionPlan("error_open", "Could you copy the exact error message you see, including any error code?", []), s.add_turn("assistant", "q", feature="error_open").idx)
    cl.turn(s, "There's no error text, it just fails.")
    assert not any("no error text" in x.lower() for x in s.fields.symptoms)
