"""jev.py -- a client for Jev, a small decision model: it answers a question about some text with a probability instead of generating text.

Reached through OpenRouter's decisions endpoint (POST https://openrouter.ai/api/alpha/decisions, Bearer OPENROUTER_API_KEY), as described in
OpenRouter's Jev tutorial. Three question types:
  noul    yes/no            the criteria give a "true" and a "false" description; the answer is the probability of yes
  choice  one of N options  the chosen option and the probability of each
  score   ordered levels    a probability-weighted score

"~typesafe/jev-latest" follows the newest release; "typesafe/jev-1.13" pins one (set JEV_MODEL), which keeps a calibrated threshold meaningful.
Each response names the dated snapshot that answered; it is kept in Decision.model and logged. NOT yet run against the live service (no key yet).
The key is read from OPENROUTER_API_KEY (environment or .env) and is never logged.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests

from triage import config
from triage.pricing import cost_usd

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "~typesafe/jev-latest"


class JevError(RuntimeError):
    pass


@dataclass
class Decision:
    answer: Any             # noul: probability of yes | choice: the chosen option | score: the weighted score
    confidence: float       # 0..1. noul: how far the probability is from 0.5, scaled. choice / score: as reported by the API
    input_tokens: int
    latency_ms: float
    cost_usd: Optional[float]
    model: str = ""         # the dated snapshot that answered


class JevClient:
    def __init__(self, api_key: str, model: Optional[str] = None, post: Callable = requests.post, timeout: float = 15.0) -> None:
        self._key, self._post, self._timeout = api_key, post, timeout
        self.model = model or os.environ.get("JEV_MODEL") or MODEL

    @classmethod
    def from_env(cls) -> Optional["JevClient"]:
        key = config.get_api_key("jev")
        return cls(key) if key else None

    def ask(self, state: Any, question: dict) -> Decision:
        body = {"model": self.model, "state": state if isinstance(state, dict) else {"text": state}, "questions": {"q": question}}
        start = time.perf_counter()
        r = self._post(URL, json=body, headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}, timeout=self._timeout)
        latency = round((time.perf_counter() - start) * 1000, 2)
        if r.status_code != 200:
            raise JevError(f"Jev returned HTTP {r.status_code}")             # the body is not echoed: it may quote the request
        data = r.json()
        answer, usage = data["answers"]["q"], data.get("usage") or {}
        tokens = int(usage.get("input_tokens") or 0)
        cost = usage["cost"] if usage.get("cost") is not None else cost_usd(self.model, {"input_tokens": tokens, "output_tokens": 0})
        snapshot = data.get("model") or self.model
        if answer["type"] == "noul":
            p = float(answer["noul"])
            return Decision(p, round(abs(p - 0.5) * 2, 4), tokens, latency, cost, snapshot)
        value = answer["choice"] if answer["type"] == "choice" else answer["score"]
        return Decision(value, float(answer["confidence"]), tokens, latency, cost, snapshot)

    def noul(self, state: Any, instructions: str, yes: str, no: str) -> Decision:
        return self.ask(state, {"type": "noul", "instructions": instructions, "criteria": {"true": yes, "false": no}})

    def choice(self, state: Any, instructions: str, options: dict[str, str]) -> Decision:
        return self.ask(state, {"type": "choice", "instructions": instructions, "criteria": options})

    def score(self, state: Any, instructions: str, levels: list[str]) -> Decision:
        return self.ask(state, {"type": "score", "instructions": instructions, "criteria": levels})


class FakeJev:
    """Offline stand-in (JEV_BACKEND=fake): the probability of yes is the share of the problem's longer words found in the evidence.
    Free, deterministic, and enough to rehearse the whole cascade; it says nothing about how the real model behaves."""

    model = "fake-jev"

    def noul(self, state: dict, instructions: str, yes: str, no: str) -> Decision:
        words = lambda text: set(re.findall(r"[a-z0-9]{4,}", str(text).lower()))          # noqa: E731
        problem = words(state.get("customer_problem", ""))
        evidence = words(" ".join(f"{e.get('title', '')} {e.get('text', '')}" for e in state.get("evidence", [])))
        p = len(problem & evidence) / len(problem) if problem else 0.0
        return Decision(round(p, 4), round(abs(p - 0.5) * 2, 4), 0, 0.0, 0.0, self.model)
