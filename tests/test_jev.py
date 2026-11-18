"""jev client: the OpenRouter request shape, the three answer types, cost, and errors. A fake transport stands in for the network."""

import pytest

from triage import config
from triage.jev import MODEL, URL, FakeJev, JevClient, JevError

SNAPSHOT = "typesafe/jev-1.13-2026-10-01"


@pytest.fixture(autouse=True)
def no_pinned_model(monkeypatch):
    monkeypatch.delenv("JEV_MODEL", raising=False)


class Reply:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body


def client(answer, *, tokens=120, cost=0.000005, status=200):
    sent = {}

    def post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers)
        usage = {"input_tokens": tokens, "output_tokens": 4, **({"cost": cost} if cost is not None else {})}
        return Reply({"id": "gen-dec-1", "model": SNAPSHOT, "provider": "TypeSafe", "answers": {"q": answer}, "usage": usage}, status)

    return JevClient("secret-key", post=post), sent


def test_noul_sends_true_and_false_criteria_and_returns_the_probability():
    c, sent = client({"type": "noul", "noul": 0.9})
    d = c.noul({"customer_problem": "pull fails"}, "Is it about Docker Hub?", "yes text", "no text")
    assert (d.answer, d.confidence, d.input_tokens, d.cost_usd) == (0.9, 0.8, 120, 0.000005)
    assert d.model == SNAPSHOT                                            # the dated snapshot that answered, not the alias we asked for
    assert sent["url"] == URL == "https://openrouter.ai/api/alpha/decisions" and sent["headers"]["Authorization"] == "Bearer secret-key"
    assert sent["json"]["model"] == MODEL == "~typesafe/jev-latest" and sent["json"]["state"] == {"customer_problem": "pull fails"}
    assert sent["json"]["questions"]["q"] == {"type": "noul", "instructions": "Is it about Docker Hub?", "criteria": {"true": "yes text", "false": "no text"}}


def test_a_plain_text_state_is_wrapped_because_the_api_wants_an_object():
    c, sent = client({"type": "noul", "noul": 0.5})
    c.noul("just some text", "q", "y", "n")
    assert sent["json"]["state"] == {"text": "just some text"}


def test_a_pinned_model_is_used_when_set(monkeypatch):
    monkeypatch.setenv("JEV_MODEL", "typesafe/jev-1.13")
    c, sent = client({"type": "noul", "noul": 0.5})
    c.noul({}, "q", "y", "n")
    assert sent["json"]["model"] == "typesafe/jev-1.13"


def test_choice_and_score_pass_the_options_and_read_the_reported_confidence():
    c, sent = client({"type": "choice", "choice": "resolved", "confidence": 0.7, "probabilities": {"resolved": 0.7, "not_fixed": 0.3}})
    d = c.choice({"reply": "that worked"}, "What does the reply say?", {"resolved": "it is fixed", "not_fixed": "it is not"})
    assert (d.answer, d.confidence) == ("resolved", 0.7)
    assert sent["json"]["questions"]["q"]["criteria"] == {"resolved": "it is fixed", "not_fixed": "it is not"}
    c, sent = client({"type": "score", "score": 1.4, "confidence": 0.6, "legend": {}, "probabilities": {}})
    d = c.score({"evidence": "x"}, "How well does it support the answer?", ["not at all", "partly", "fully"])
    assert (d.answer, d.confidence) == (1.4, 0.6)
    assert sent["json"]["questions"]["q"]["criteria"] == ["not at all", "partly", "fully"]


def test_cost_comes_from_the_response_and_falls_back_to_the_price_table():
    c, _ = client({"type": "noul", "noul": 0.5}, cost=0.0000125)
    assert c.noul({}, "q", "y", "n").cost_usd == 0.0000125
    c, _ = client({"type": "noul", "noul": 0.5}, tokens=1_000_000, cost=None)
    assert c.noul({}, "q", "y", "n").cost_usd == pytest.approx(0.042)      # jev-latest in triage/pricing.json


def test_an_error_status_raises_without_echoing_the_body():
    c, _ = client({"type": "noul", "noul": 0.5}, status=401)
    with pytest.raises(JevError, match="401"):
        c.noul({}, "q", "y", "n")


def test_from_env_needs_a_key(monkeypatch):
    monkeypatch.setattr(config, "get_api_key", lambda provider: None)
    assert JevClient.from_env() is None
    monkeypatch.setattr(config, "get_api_key", lambda provider: "k" if provider == "jev" else None)
    assert isinstance(JevClient.from_env(), JevClient)
    assert config.PROVIDER_API_KEY_ENV["jev"] == "OPENROUTER_API_KEY"


def test_the_offline_stand_in_scores_word_overlap_and_is_deterministic():
    jev = FakeJev()
    state = {"customer_problem": "docker pull fails rate limit", "evidence": [{"title": "Pull rate limit", "text": "docker hub limits each pull"}]}
    assert jev.noul(state, "q", "y", "n").answer == jev.noul(state, "q", "y", "n").answer == 0.8       # 4 of the 5 longer words are in the evidence
    assert jev.noul({"customer_problem": "", "evidence": []}, "q", "y", "n").answer == 0.0
