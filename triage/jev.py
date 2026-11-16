"""jev.py -- a small client for the hosted Jev decision API (TypeSafe AI).

Jev answers a question about some text with a probability instead of generating text. Three question types:
  noul    yes/no            -> the probability of yes
  choice  one of N options  -> the chosen option and the probability of each
  score   ordered levels    -> a probability-weighted score

Written from the OpenAPI spec at https://api.typesafe.ai/openapi.json (POST /v1/systemone, Bearer key). NOT yet run against the
live service: there is no key yet. The pipeline does not call it yet either; USE_JEV only builds this client (see ResolverDeps.jev).
The key is read from TYPESAFE_API_KEY (environment or .env) and is never logged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests

from triage import config
from triage.pricing import cost_usd

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"


class JevError(RuntimeError):
    pass


@dataclass
class Decision:
    answer: Any             # noul: probability of yes | choice: the chosen option | score: the weighted score
    confidence: float       # 0..1. noul: how far the probability is from 0.5, scaled. choice / score: as reported by the API
    input_tokens: int
    latency_ms: float
    cost_usd: Optional[float]

    def to_event(self, node: str) -> dict:
        return {"node": node, "latency_ms": self.latency_ms, "input_tokens": self.input_tokens, "cost_usd": self.cost_usd}


class JevClient:
    def __init__(self, api_key: str, model: str = MODEL, post: Callable = requests.post, timeout: float = 10.0) -> None:
        self._key, self.model, self._post, self._timeout = api_key, model, post, timeout

    @classmethod
    def from_env(cls) -> Optional["JevClient"]:
        key = config.get_api_key("jev")
        return cls(key) if key else None

    def ask(self, state: Any, question: dict) -> Decision:
        body = {"model": self.model, "state": state, "questions": {"q": question}}
        start = time.perf_counter()
        r = self._post(URL, json=body, headers={"Authorization": f"Bearer {self._key}"}, timeout=self._timeout)
        latency = round((time.perf_counter() - start) * 1000, 2)
        if r.status_code != 200:
            raise JevError(f"Jev returned HTTP {r.status_code}")             # the body is not echoed: it may quote the request
        data = r.json()
        answer, tokens = data["answers"]["q"], int(data.get("usage", {}).get("input_tokens", 0))
        cost = cost_usd(self.model, {"input_tokens": tokens, "output_tokens": 0})
        if answer["type"] == "noul":
            p = float(answer["noul"])
            return Decision(p, round(abs(p - 0.5) * 2, 4), tokens, latency, cost)
        value = answer["choice"] if answer["type"] == "choice" else answer["score"]
        return Decision(value, float(answer["confidence"]), tokens, latency, cost)

    def noul(self, state: Any, instructions: str) -> Decision:
        return self.ask(state, {"type": "noul", "instructions": instructions})

    def choice(self, state: Any, instructions: str, options: dict[str, str]) -> Decision:
        return self.ask(state, {"type": "choice", "instructions": instructions, "criteria": options})

    def score(self, state: Any, instructions: str, levels: list[str]) -> Decision:
        return self.ask(state, {"type": "score", "instructions": instructions, "criteria": levels})
