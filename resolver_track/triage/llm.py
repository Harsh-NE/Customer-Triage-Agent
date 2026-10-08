"""Pluggable LLM layer. The Resolver only ever calls `LLM.complete_json`.

  * AnthropicLLM      – Claude via the anthropic SDK (ANTHROPIC_API_KEY)
  * OpenAICompatLLM   – any OpenAI-compatible endpoint (OpenAI, Groq, Ollama, vLLM…)
  * FakeLLM           – deterministic, offline; used by tests and solo development

Swap with get_llm("anthropic" | "openai" | "fake") or the LLM_PROVIDER env var.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol


class LLM(Protocol):
    name: str

    def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> dict[str, Any]:
        ...


def parse_json(text: str) -> dict[str, Any]:
    """Tolerant JSON extraction: strips ``` fences and leading prose."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"LLM did not return JSON: {text[:200]!r}")
    return json.loads(cleaned[start:end + 1])


class AnthropicLLM:
    def __init__(self, model: str | None = None, temperature: float = 0.0):
        import anthropic  # lazy import so tests don't need the SDK
        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("RESOLVER_MODEL", "claude-sonnet-5")
        self.temperature = temperature
        self.name = f"anthropic:{self.model}"
        self.last_usage: dict[str, int] = {}

    def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> dict[str, Any]:
        msg = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=self.temperature,
            system=system + "\nRespond with a single JSON object and nothing else.",
            messages=[{"role": "user", "content": user}])
        self.last_usage = {"input_tokens": msg.usage.input_tokens,
                           "output_tokens": msg.usage.output_tokens}
        return parse_json("".join(b.text for b in msg.content if b.type == "text"))


class OpenAICompatLLM:
    def __init__(self, model: str | None = None, base_url: str | None = None,
                 temperature: float = 0.0):
        from openai import OpenAI  # lazy import
        self.client = OpenAI(base_url=base_url or os.getenv("OPENAI_BASE_URL"))
        self.model = model or os.getenv("RESOLVER_MODEL", "gpt-4o-mini")
        self.temperature = temperature
        self.name = f"openai:{self.model}"
        self.last_usage: dict[str, int] = {}

    def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> dict[str, Any]:
        r = self.client.chat.completions.create(
            model=self.model, temperature=self.temperature, max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        if r.usage:
            self.last_usage = {"input_tokens": r.usage.prompt_tokens,
                               "output_tokens": r.usage.completion_tokens}
        return parse_json(r.choices[0].message.content or "")


class FakeLLM:
    """Offline stand-in. Recognises which prompt it got from a TASK: tag.

    - TASK: draft    -> builds steps from sentences of the top evidence passages,
                        citing them; returns INSUFFICIENT_EVIDENCE if none given.
    - TASK: classify -> keyword classifier over the customer reply.
    """
    name = "fake"
    last_usage: dict[str, int] = {}

    def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> dict[str, Any]:
        if "TASK: classify" in system:
            return self._classify(user)
        if "TASK: draft" in system:
            return self._draft(user)
        raise ValueError("FakeLLM: unknown task")

    @staticmethod
    def _classify(user: str) -> dict[str, Any]:
        reply = user.split("CUSTOMER REPLY:", 1)[-1].lower()
        if re.search(r"\b(still|didn'?t|did not|no luck|same error|not work|doesn'?t work|failed)\b", reply):
            label = "not_fixed"
        elif re.search(r"\b(works|worked|fixed|solved|resolved|thanks|thank you)\b", reply):
            label = "resolved"
        elif re.search(r"\b(also|actually|forgot|version|windows|mac|linux|error code)\b", reply):
            label = "new_info"
        else:
            label = "off_topic"
        return {"label": label, "rationale": "keyword heuristic"}

    @staticmethod
    def _draft(user: str) -> dict[str, Any]:
        blocks = re.findall(r"\[(E\d+)\][^\n]*\n(.*?)(?=\n\[E\d+\]|\Z)", user, flags=re.S)
        if not blocks:
            return {"status": "INSUFFICIENT_EVIDENCE", "diagnosis": "", "steps": []}
        steps = []
        for eid, body in blocks[:2]:
            if "RESOLUTION:" in body:              # Tier 2 ticket: cite the fix, not the problem
                body = body.split("RESOLUTION:", 1)[1]
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body.strip()) if len(s.strip()) > 20]
            for s in sentences[:2]:
                steps.append({"text": s, "evidence_ids": [eid]})
        first = blocks[0][1].replace("PROBLEM:", "").strip().split(".")[0]
        return {"status": "OK", "diagnosis": f"Likely cause: {first[:160]}.",
                "steps": steps[:4],
                "verification": "Re-run the failing command and confirm the error is gone."}


def get_llm(provider: str | None = None) -> LLM:
    provider = (provider or os.getenv("LLM_PROVIDER", "fake")).lower()
    if provider == "anthropic":
        return AnthropicLLM()
    if provider in ("openai", "groq", "ollama"):
        return OpenAICompatLLM()
    return FakeLLM()
