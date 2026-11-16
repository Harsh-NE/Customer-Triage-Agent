"""jev client: request shape, the three answer types, cost, and errors. A fake transport stands in for the network."""

import pytest

from triage import config
from triage.jev import URL, JevClient, JevError


class Reply:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body


def client(answer, tokens=120, status=200):
    sent = {}

    def post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers)
        return Reply({"model": "jev-latest", "answers": {"q": answer}, "usage": {"input_tokens": tokens, "output_tokens": 0}}, status)

    return JevClient("secret-key", post=post), sent


def test_noul_returns_the_probability_and_a_confidence_scaled_from_it():
    c, sent = client({"type": "noul", "noul": 0.9})
    d = c.noul("docker pull gives 429", "Is this about Docker Hub?")
    assert (d.answer, d.confidence, d.input_tokens) == (0.9, 0.8, 120)
    assert sent["url"] == URL and sent["headers"] == {"Authorization": "Bearer secret-key"}
    assert sent["json"]["state"] == "docker pull gives 429"
    assert sent["json"]["questions"]["q"] == {"type": "noul", "instructions": "Is this about Docker Hub?"}


def test_choice_and_score_pass_the_options_and_read_the_reported_confidence():
    c, sent = client({"type": "choice", "choice": "resolved", "confidence": 0.7, "probabilities": {"resolved": 0.7, "not_fixed": 0.3}})
    d = c.choice("that worked", "What does the reply say?", {"resolved": "it is fixed", "not_fixed": "it is not"})
    assert (d.answer, d.confidence) == ("resolved", 0.7)
    assert sent["json"]["questions"]["q"]["criteria"] == {"resolved": "it is fixed", "not_fixed": "it is not"}
    c, sent = client({"type": "score", "score": 1.4, "confidence": 0.6, "legend": {}, "probabilities": {}})
    d = c.score("evidence", "How well does it support the answer?", ["not at all", "partly", "fully"])
    assert (d.answer, d.confidence) == (1.4, 0.6)
    assert sent["json"]["questions"]["q"]["criteria"] == ["not at all", "partly", "fully"]


def test_cost_comes_from_the_price_table():
    c, _ = client({"type": "noul", "noul": 0.5}, tokens=1_000_000)
    assert c.noul("x", "y").cost_usd == pytest.approx(0.042)


def test_an_error_status_raises_without_echoing_the_body():
    c, _ = client({"type": "noul", "noul": 0.5}, status=401)
    with pytest.raises(JevError, match="401"):
        c.noul("x", "y")


def test_from_env_needs_a_key(monkeypatch):
    monkeypatch.setattr(config, "get_api_key", lambda provider: None)
    assert JevClient.from_env() is None
    monkeypatch.setattr(config, "get_api_key", lambda provider: "k" if provider == "jev" else None)
    assert isinstance(JevClient.from_env(), JevClient)
