"""condense_logs: routine log lines go, the customer's words and error lines stay, short pasted errors are untouched."""

import pytest

from triage import understand as U
from triage.eval.perturb_eval import perturb

Q = "docker pull fails with 'toomanyrequests: You have reached your pull rate limit' on my laptop"
LOG = "\n".join(f"2026-03-02T10:00:0{i}Z INFO [app] step {i} ok" for i in range(8))


def test_the_perturbation_noise_is_removed_and_the_question_kept():
    noisy = perturb(Q, "log_noise")
    assert len(noisy) > 1000
    assert U.condense_logs(noisy) == Q


def test_error_lines_inside_a_log_are_kept_and_routine_ones_dropped():
    text = f"My container exits.\n{LOG}\n2026-03-02T10:00:09Z ERROR [db] connection refused to db:5432\n{LOG}"
    out = U.condense_logs(text)
    assert "My container exits." in out and "connection refused to db:5432" in out
    assert "step 3 ok" not in out


def test_at_most_a_few_error_lines_survive_and_duplicates_collapse():
    errors = "\n".join(f"2026-03-02T10:01:{i:02d}Z ERROR [db] failed to connect (attempt {i})" for i in range(20))
    out = U.condense_logs(f"help\n{errors}\n{LOG}")
    assert out.count("ERROR") == U.LOG_KEEP_LINES
    same = "\n".join(["2026-03-02T10:01:00Z ERROR [db] connection refused"] * 10 + [LOG])
    assert U.condense_logs("help\n" + same).count("connection refused") == 1


@pytest.mark.parametrize("text", [
    "ERROR: Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?",
    "docker: Error response from daemon: Conflict. The container name is already in use.\nSee 'docker run --help'.",
    "my build is slow",
    "",
])
def test_short_messages_and_pasted_errors_are_unchanged(text):
    assert U.condense_logs(text) == text


def test_a_few_log_lines_are_not_a_log():
    few = "It fails.\n" + "\n".join(f"2026-03-02T10:00:0{i}Z INFO [app] step {i} ok" for i in range(3))
    assert U.condense_logs(few) == few


def test_a_message_that_is_mostly_prose_is_unchanged_even_with_log_lines():
    prose = "\n".join(f"line {i} of my long explanation about what happens when I run the build" for i in range(20))
    text = prose + "\n" + LOG
    assert U.condense_logs(text) == text            # 8 log lines of 28 is under half


def test_never_empty_when_everything_is_routine_log():
    assert U.condense_logs(LOG).strip() != ""


def test_extract_uses_it_so_the_symptom_is_not_log_noise():
    fields = U.extract(perturb(Q, "log_noise"), None, []).fields
    assert all("heartbeat" not in s and "evicted" not in s for s in fields.symptoms)
