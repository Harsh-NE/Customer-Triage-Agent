"""The arithmetic of triage/eval/ocr_eval.py (edit distance, CER, WER, the key line). The OCR engine itself is covered by tests/test_ocr.py."""

import pytest

from triage.eval import ocr_eval as O


def test_edit_distance_hand_values():
    assert O.edit_distance("kitten", "sitting") == 3
    assert O.edit_distance("", "abc") == 3 and O.edit_distance("abc", "") == 3 and O.edit_distance("same", "same") == 0
    assert O.edit_distance(["a", "b"], ["a", "c"]) == 1                      # works on word lists too


def test_cer_and_wer_ignore_whitespace_layout():
    assert O.cer("permission denied", "permission   denied\n") == 0.0
    assert O.cer("permission denied", "permisson denied") == pytest.approx(1 / 17)
    assert O.wer("pull rate limit", "pull rate") == pytest.approx(1 / 3)
    assert O.cer("", "anything") == 0.0


def test_key_line_skips_commands_and_blank_lines():
    lines = ["$ docker pull nginx", "", "Error response from daemon: toomanyrequests", "more"]
    assert O.key_line(lines) == "Error response from daemon: toomanyrequests"
    assert O.key_line(["$ docker ps", "all fine"]) is None


def test_key_line_error_finds_the_line_even_when_other_lines_are_noisy():
    truth = "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
    read = "$ docker ps\nCannot connect to the Docker daemon at unix:///var/run/docker.sock\nrandom"
    assert O.key_line_error(truth, read) == 0.0
    assert O.key_line_error(truth, "nothing useful here at all") > 0.5
