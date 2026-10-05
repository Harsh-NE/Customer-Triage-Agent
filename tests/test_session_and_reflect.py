import pytest

from triage.config import ClarifierConfig
from triage.context_session import SessionMemory, approx_tokens
from triage.reflect import reflect_question
from triage.state import ExtractedFields, QuestionPlan


def _session(**fields):
    s = SessionMemory("T-test")
    for k, v in fields.items():
        setattr(s.fields, k, v)
    return s


# ---------------- session memory (A9) ----------------
def test_stored_turns_are_always_redacted_even_if_caller_forgot():
    s = SessionMemory("T")
    s.add_turn("customer", "my email is bob@example.com, password=hunter2")
    assert "bob@example.com" not in s.turns[0].text and "hunter2" not in s.turns[0].text
    assert s.redactions["email"] == 1 and s.redactions["secret"] == 1


def _long_session(n_turns=30):
    s = _session(product_area="docker-hub", symptoms=["pull fails"], platform="mac")
    for i in range(n_turns):
        s.add_turn("customer", f"message {i}: " + "docker pull is failing again and again. " * 12)
        s.add_turn("assistant", f"question {i}", feature="platform")
    return s


@pytest.mark.parametrize("budget", [60, 120, 300, 700, 2000])
def test_render_context_never_exceeds_token_budget(budget):
    ctx = _long_session().render_context(max_tokens=budget)
    assert approx_tokens(ctx) <= budget + 10                    # +10: the explicit truncation marker


def test_render_context_keeps_known_fields_and_condenses_old_turns():
    s = _long_session(8)
    s.record_question(QuestionPlan("platform", "which os?"), 3)
    ctx = s.render_context(max_tokens=700)
    assert '"product": "docker-hub"' in ctx and "platform(awaiting reply)" in ctx
    assert "C(earlier):" in ctx and "A(earlier): asked about platform" in ctx
    assert ctx.count("docker pull is failing") < 8 * 12         # older turns condensed, not replayed


def test_render_context_with_tiny_budget_still_returns_header_with_marker():
    ctx = _long_session().render_context(max_tokens=30)
    assert "KNOWN" in ctx or "truncated" in ctx


def test_retry_history_tracks_rejected_chunks_only_for_not_resolved():
    s = SessionMemory("T")
    s.record_attempt(["c1", "c2"], "not_resolved", "still broken, password=hunter2")
    s.record_attempt(["c3"], "partial")
    s.record_attempt(["c4"], "resolved")
    assert s.rejected_chunk_ids() == {"c1", "c2"}
    text = s.render_retry_context()
    assert "Attempt 1" in text and "not_resolved" in text and "hunter2" not in text
    assert "Do not repeat the rejected evidence" in text
    assert SessionMemory("T2").render_retry_context() == "No earlier attempts."


def test_open_question_lifecycle():
    s = SessionMemory("T")
    assert s.open_question is None
    s.record_question(QuestionPlan("platform", "which os?", ["mac"]), 1)
    assert s.open_question.feature == "platform" and s.questions_asked == 1
    s.mark_answered("mac")
    assert s.open_question is None and s.answered == {"platform": "mac"}


def test_session_json_round_trip_and_files(tmp_path):
    s = _long_session(3)
    s.record_attempt(["c1"], "not_resolved", "no")
    s.mark_answered("x")
    assert SessionMemory.from_json(s.to_json()) == s
    assert SessionMemory.load(s.save(tmp_path)) == s


def test_triage_record_marks_closed_only_when_outcome_is_final():
    s = SessionMemory("T")
    assert s.to_triage_record().closed_at is None
    assert s.to_triage_record(outcome="escalated").closed_at is not None


# ---------------- reflection (A10) ----------------
def test_blocks_question_when_field_already_known():
    v = reflect_question(QuestionPlan("platform", "which os?", ["windows"]), _session(platform="mac"))
    assert (v.ask, v.reason) == (False, "already_known")


def test_recovers_answer_stated_earlier_instead_of_asking():
    s = _session()                                   # extraction "missed" it: field empty, but the text says it
    s.add_turn("customer", "Docker Desktop won't start on my Windows laptop")
    v = reflect_question(QuestionPlan("platform", "which os?", ["windows", "mac"]), s)
    assert (v.ask, v.reason, v.filled_value) == (False, "stated_earlier", "windows")


def test_vague_symptom_does_not_count_as_known():
    s = _session(symptoms=["it doesn't work"])
    assert reflect_question(QuestionPlan("symptoms", "describe it"), s).ask is True
    s2 = _session(symptoms=["it doesn't work"], error_codes=["HTTP 429 response code"])
    assert reflect_question(QuestionPlan("symptoms", "describe it"), s2).reason == "already_known"


def test_rephrase_allowed_once_then_blocked_after_two_asks():
    s = _session()
    s.record_question(QuestionPlan("platform", "Which operating system are you running Docker on?"), 1)
    again = reflect_question(QuestionPlan("platform", "Just to narrow this down, is this on Windows or Mac?"), s)
    assert again.ask is True and again.rephrase is True
    s.record_question(QuestionPlan("platform", "Just to narrow this down, is this on Windows or Mac?"), 3)
    assert reflect_question(QuestionPlan("platform", "a third way to ask"), s).reason == "asked_twice"


def test_near_duplicate_wording_is_blocked():
    s = _session()
    s.record_question(QuestionPlan("issue", "Which of these sounds closest to your problem? 1. A 2. B"), 1)
    v = reflect_question(QuestionPlan("component", "Which of these sounds closest to your problem? 1. A 2. B"), s)
    assert (v.ask, v.reason) == (False, "duplicate_wording")


def test_context_config_defaults_are_sane():
    cfg = ClarifierConfig()
    assert cfg.context_token_budget > 0 and cfg.max_clarify_turns >= 1 and 0 < cfg.mismatch_penalty < 1
