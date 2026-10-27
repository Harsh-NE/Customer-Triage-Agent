"""The symptom list: customer-friendly wording per KB issue (looked up, written ahead of time by a model), the checks on that wording,
and the Clarifier question that lists what each of 3+ close causes looks like. Offline: fixed retrievers, a fake model."""

import importlib.util
import sys
from pathlib import Path

from triage.answers import match_option
from triage.clarifier import Clarifier, render_pick
from triage.config import ClarifierConfig
from triage.differential import apply_answers, rank_discriminators
from triage.sim.customer import RuleBasedCustomer, Scenario, classify_question
from triage.state import Candidate, ClarifierStatus, ExtractedFields, Hypothesis
from triage.symptoms import NONE_OPTION, SymptomBank, choose_symptoms

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("pipeline_12", ROOT / "scripts" / "12_symptoms.py")
gen = importlib.util.module_from_spec(spec)
sys.modules["pipeline_12"] = gen
spec.loader.exec_module(gen)

CFG = ClarifierConfig()
A, B, C, D = "p/a.md::Pulls stop", "p/b.md::Sign in rejected", "p/c.md::Window stays blank", "p/d.md::Disk is full"


def hyp(key, weight, issue):
    return Hypothesis(key, key, weight, weight, [key], {"issue": issue})


def bank():
    return SymptomBank({A: {"symptoms": ["Pulling an image stops with a 429 error"]}, B: {"symptoms": ["Nobody on the team can sign in"]},
                        C: {"symptoms": ["The Docker Desktop window stays blank"]}, D: {"symptoms": ["Builds stop because the disk is full"]}})


def four():
    return [hyp(A, 0.28, "Pulls stop"), hyp(B, 0.26, "Sign in rejected"), hyp(C, 0.24, "Window stays blank"), hyp(D, 0.22, "Disk is full")]


# ---------------- where the wording comes from ----------------
def test_stored_wording_comes_first_then_ontology_phrases_then_a_symptom_like_title():
    stored = SymptomBank({"x.md::Unable to connect": {"symptoms": ["docker commands answer with a daemon connection error"]}})
    assert stored.for_issue("x.md::Unable to connect") == ["Docker commands answer with a daemon connection error"]
    plain = SymptomBank({})
    assert plain.for_issue("x.md::Docker.app is damaged and can't be opened") == ["Docker.app is damaged and can't be opened"]
    assert plain.for_issue("x.md::Not enough seats") == []                       # a cause label, not something a customer sees
    assert plain.for_issue("x.md::Check for errors") == []                       # an instruction
    assert plain.for_issue("x.md::Overview") == []


def test_the_shipped_ontology_supplies_phrases_for_its_linked_issues():
    from triage.ontology import load_ontology
    linked = next(i for i in load_ontology().issues() if i.kb and i.symptoms)
    link = linked.kb[0]
    got = SymptomBank({}, load_ontology()).for_issue(f"content/{link.path}::{link.issue}")
    assert got and got[0][0].isupper()


# ---------------- choosing which wording to show ----------------
def test_one_distinct_symptom_per_cause_is_chosen_and_wording_that_fits_two_causes_is_dropped():
    chosen = choose_symptoms(four(), bank())
    assert [k for _, k in chosen] == [A, B, C, D] and chosen[0][0] == "Pulling an image stops with a 429 error"
    shared = SymptomBank({A: {"symptoms": ["Docker Desktop will not start"]}, B: {"symptoms": ["Docker Desktop will not start"]},
                          C: {"symptoms": ["The window stays blank"]}})
    assert choose_symptoms(four()[:3], shared) is None                     # A and B say the same thing: only C is left, which is not a list


def test_the_most_likely_cause_is_always_listed_and_a_list_without_it_is_never_offered():
    overlapping = SymptomBank({A: {"symptoms": ["Pulling an image stops with a 429 message"]}, B: {"symptoms": ["Pulling an image stops again and again"]},
                               C: {"symptoms": ["The Docker Desktop window stays blank"]}})
    got = choose_symptoms(four()[:3], overlapping)
    assert got[0][1] == A and [k for _, k in got] == [A, C]                           # the leader stays (its 429 differs); B's wording is too close to it
    same_as_leader = SymptomBank({A: {"symptoms": ["Pulling an image stops again"]}, B: {"symptoms": ["Pulling an image stops again"]}, C: {"symptoms": ["The window stays blank"]}})
    assert choose_symptoms(four()[:3], same_as_leader) is None                         # a leader whose wording fits another cause equally cannot be listed
    no_leader = SymptomBank({B: {"symptoms": ["Nobody on the team can sign in"]}, C: {"symptoms": ["The Docker Desktop window stays blank"]},
                             D: {"symptoms": ["Builds stop because the disk is full"]}})
    assert choose_symptoms(four(), no_leader) is None


def test_fewer_than_two_usable_symptoms_means_no_list():
    neutral = [hyp(f"p/{n}.md::Topic {n}", 0.25, f"Topic {n}") for n in "abcd"]
    assert choose_symptoms(neutral, SymptomBank({"p/a.md::Topic a": {"symptoms": ["Pulling an image stops with a 429 error"]}})) is None
    assert choose_symptoms(four(), None) is None


# ---------------- the checks on model-written wording ----------------
def issue(title="Pulls stop", text="You have reached your pull rate limit. Docker Hub returns a 429 response when pulling."):
    return {"title": title, "text": text, "article": "Docker Hub"}


def test_generated_wording_must_be_short_grounded_and_a_symptom_not_a_fix_or_command():
    kept, rejected = gen.validate(["Pulling an image stops with a 429 error", "Pulling an image stops with a 429 error", "Restart Docker Desktop now",
                                   "Run `docker login` to authenticate", "Nothing", "The kubernetes cluster explodes at midnight daily",
                                   "Docker Hub returns a rate limit message"], issue())
    assert kept == ["Pulling an image stops with a 429 error", "Docker Hub returns a rate limit message"]
    assert {r["reason"] for r in rejected} == {"duplicate", "instruction", "code_or_link", "length", "not_grounded"}


def test_the_generator_groups_chunks_into_issues_and_skips_work_already_done(tmp_path):
    chunks = [{"chunk_id": "c1", "source_path": "p/a.md", "article_title": "Hub", "heading_path": ["Hub", "Pulls stop", "Error message"], "text": "You have reached your pull rate limit",
               "metadata": {"doc_kind": "troubleshooting"}},
              {"chunk_id": "c2", "source_path": "p/a.md", "article_title": "Hub", "heading_path": ["Hub", "Pulls stop", "Solution"], "text": "Authenticate to raise the limit",
               "metadata": {"doc_kind": "troubleshooting"}},
              {"chunk_id": "c3", "source_path": "p/z.md", "article_title": "Guide", "heading_path": ["Guide", "Intro"], "text": "How to", "metadata": {"doc_kind": "guide"}}]
    found = gen.issues_from_chunks(chunks, {"troubleshooting"})
    assert list(found) == ["p/a.md::Pulls stop"] and "Authenticate" in found["p/a.md::Pulls stop"]["text"]       # two chunks, one issue; the guide is ignored
    assert gen.FakeSymptomLLM().complete_json("", "PROBLEM TITLE: Docker.app is damaged and can't be opened\nPAGE: x")["symptoms"]


# ---------------- when the list is asked, and what the answer does ----------------
def features(hyps, exclude=(), symptoms=None):
    return [d.feature for d in rank_discriminators(hyps, ExtractedFields(), set(exclude), CFG, symptoms if symptoms is not None else bank())]


def test_three_or_more_close_causes_with_usable_symptoms_get_the_list_first():
    got = rank_discriminators(four(), ExtractedFields(), set(), CFG, bank())
    assert got[0].feature.startswith("pick:") and len(got[0].options) == 4 and got[0].detail["keys"] == [A, B, C, D]
    assert not any(f.startswith(("trait:", "confirm:")) for f in features(four()))          # replaces the per-cause yes/no
    assert "detail" not in features(four())


def test_one_or_two_close_causes_are_confirmed_not_listed_and_no_list_without_wording():
    assert not any(f.startswith("pick:") for f in features(four()[:2]))
    lopsided = [hyp(A, 0.55, "Pulls stop"), hyp(B, 0.15, "Sign in rejected"), hyp(C, 0.12, "Window stays blank")]
    assert not any(f.startswith("pick:") for f in features(lopsided))                         # only one cause is close to the leader
    assert not any(f.startswith("pick:") for f in features(four(), symptoms=SymptomBank({})))
    assert features(four(), symptoms=SymptomBank({}))[0] == "detail"                          # no wording: the open question, as before


def test_the_list_is_not_asked_twice():
    first = rank_discriminators(four(), ExtractedFields(), set(), CFG, bank())[0].feature
    assert not any(f.startswith("pick:") for f in features(four(), exclude={first}))


def test_picked_symptoms_lift_their_causes_the_rest_of_the_list_sinks_and_none_lowers_all():
    feature = "pick:" + "||".join([A, B, C, D])

    def run(value):
        return {h.key: round(h.weight, 3) for h in apply_answers(four(), {feature: value}, CFG)}
    one, two, none = run("2"), run("1,3"), run("none")
    assert one[B] > 0.6 and one[A] < 0.1 and two[A] > 0.3 and two[C] > 0.3 and two[B] < 0.1
    assert max(none.values()) < 0.4 and min(none.values()) > 0.15 and run("unknown") == {A: 0.28, B: 0.26, C: 0.24, D: 0.22}


def test_the_reply_is_understood_as_numbers_ordinals_the_wording_itself_or_a_description():
    opts = ["Pulling an image stops with a 429 error", "Nobody on the team can sign in", NONE_OPTION]
    ask = lambda r: match_option("pick:a||b", r, opts)        # noqa: E731
    assert [ask("1"), ask("1 and 2"), ask("the second one"), ask("Nobody on the team can sign in"), ask(NONE_OPTION + "."), ask("not sure")] == \
           ["1", "1,2", "2", "2", "none", "unknown"]
    assert ask("it freezes on a white screen forever") == "none"      # a description of something else: none of the listed, and the text is evidence


# ---------------- the whole conversation ----------------
class Fixed:
    def __init__(self, cands):
        self.cands = cands

    def search(self, query, top_k=8):
        return [Candidate(c.chunk_id, c.text, c.score, c.source_path, c.article_title, c.heading_path, dict(c.metadata)) for c in self.cands]


OPENING = "images fail to pull, people cannot sign in and the window is blank since the update"


def pool():
    titles = [("a", "Pulls stop", 0.62), ("b", "Sign in rejected", 0.61), ("c", "Window stays blank", 0.60), ("d", "Disk is full", 0.59)]
    return Fixed([Candidate(f"{i}1", f"{t}. details", s, f"p/{i}.md", "Troubleshoot", ["Troubleshoot", t], {"doc_kind": "troubleshooting", "product_area": "desktop"})
                  for i, t, s in titles])


def test_a_picked_symptom_decides_the_cause_and_becomes_part_of_the_problem_description():
    cl = Clarifier(None, pool(), ClarifierConfig(min_grounding=0.0), symptoms=bank())
    s = cl.start()
    res = cl.turn(s, OPENING)
    assert res.status is ClarifierStatus.ASK and res.question.feature.startswith("pick:")
    assert res.question.text == render_pick(res.question.options[:-1]) and res.question.options[-1] == NONE_OPTION and "closest" not in res.question.text
    res = cl.turn(s, "Nobody on the team can sign in")
    assert res.status is ClarifierStatus.READY and "Sign in rejected" in res.signature.hypotheses[0].label
    assert "Nobody on the team can sign in" in s.fields.symptoms and res.questions_asked == 1


def test_none_of_these_with_a_description_keeps_the_text_as_evidence_and_moves_on():
    cl = Clarifier(None, pool(), ClarifierConfig(min_grounding=0.0), symptoms=bank())
    s = cl.start()
    cl.turn(s, OPENING)
    cl.turn(s, "when I run a container it just exits with code 137 straight away")          # typed instead of ticking anything
    assert any("137" in x for x in s.fields.symptoms + s.fields.error_codes + s.fields.error_messages)
    assert sum(1 for q in s.questions if q.feature.startswith("pick:")) == 1


def test_the_simulated_customer_recognises_their_own_symptom_or_describes_it():
    text = render_pick(["Pulling an image stops with a 429 error", "Nobody on the team can sign in"])
    assert classify_question(text)[0] == "pick" and len(classify_question(text)[1]) == 2
    sc = Scenario(id="X", opening="x", hidden={"symptom_detail": "nobody on the team can sign in with SSO", "error_text": None}, gold={"source_path_contains": "x", "issue_contains": "seats"})
    assert RuleBasedCustomer(sc).reply(text) in ("2", "Nobody on the team can sign in")
    other = Scenario(id="Y", opening="x", hidden={"symptom_detail": "the fan is loud"}, gold=None)
    assert RuleBasedCustomer(other).reply(text).startswith("None of these, let me describe it.")


def test_the_none_of_these_button_alone_is_not_stored_as_a_symptom_and_the_next_question_asks_for_detail():
    cl = Clarifier(None, pool(), ClarifierConfig(min_grounding=0.0), symptoms=bank())
    s = cl.start()
    cl.turn(s, OPENING)
    res = cl.turn(s, NONE_OPTION + ".")
    assert not any("none of these" in x.lower() for x in s.fields.symptoms)
    assert res.status is ClarifierStatus.ASK and res.question.feature in ("detail", "error_open")
