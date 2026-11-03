"""strip_chatter: greetings and pleas come off before extraction and before the Resolver's search text; real content never does."""

import pytest

from triage.understand import extract, strip_chatter


@pytest.mark.parametrize("text, expected", [
    ("hi, Docker Hub pulls are failing with a 429 error thanks in advance, been stuck on this for hours", "Docker Hub pulls are failing with a 429 error"),
    ("Hello, docker pull fails. Please help me!", "docker pull fails."),
    ("my container keeps restarting, any help appreciated", "my container keeps restarting"),
    ("Thank you so much, that fixed it", "that fixed it"),
])
def test_chatter_is_removed(text, expected):
    assert strip_chatter(text) == expected


@pytest.mark.parametrize("text", [
    "Docker Desktop is stuck on starting on Windows",      # 'stuck' alone is content
    "docker run -p 8080:80 nginx fails with: bind: address already in use",
    "high memory use in the highlight container",           # 'hi' inside words must not match
    "thanks", "hi", "please help",                          # only chatter: returned unchanged, never empty
    "",
])
def test_content_is_kept(text):
    assert strip_chatter(text) == text


def test_the_extractor_no_longer_puts_chatter_in_the_symptom():
    res = extract("hi, Docker Hub pulls are failing with a 429 error thanks in advance, been stuck on this for hours", None, ["docker hub"])
    blob = " ".join(res.fields.symptoms or []).lower() if hasattr(res.fields, "symptoms") else str(res.fields).lower()
    assert "thanks" not in blob and "stuck on this" not in blob and "429" in str(res.fields)
