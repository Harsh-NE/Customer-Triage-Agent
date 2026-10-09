"""
llm.py -- one tiny LLM interface for the whole agent layer.

    class LLM:  complete(prompt: str) -> str

ProviderLLM dispatches to gemini / anthropic / openai exactly like scripts/09_understand.py
(same env vars, same default: gemini-3.5-flash-lite, the free small-tier model the project
settled on). Each SDK is imported lazily, only when selected.

ScriptedLLM is the offline stand-in used by tests and CI: it replays canned responses or
calls a function, and records every prompt it was given. No network, no key, no cost.

Both count calls and characters so cost per ticket can be reported (cost optimisation
needs numbers) -- see `usage`.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Callable, Protocol

from triage import config


class LLM(Protocol):
    def complete(self, prompt: str) -> str: ...


class _Usage:
    def __init__(self) -> None:
        self.calls = 0
        self.prompt_chars = 0
        self.response_chars = 0

    def record(self, prompt: str, response: str) -> None:
        self.calls += 1
        self.prompt_chars += len(prompt)
        self.response_chars += len(response)

    def as_dict(self) -> dict:
        return {"calls": self.calls, "prompt_chars": self.prompt_chars,
                "response_chars": self.response_chars,
                "approx_tokens": (self.prompt_chars + self.response_chars) // 4}


_tls = threading.local()      # the provider call functions return text; usage rides here so their signatures stay unchanged


def _set_usage(input_tokens: int, output_tokens: int) -> None:
    _tls.usage = {"input_tokens": int(input_tokens or 0), "output_tokens": int(output_tokens or 0)}


def _call_gemini(prompt: str, model: str, api_key: str) -> str:
    import logging

    from google import genai
    logging.getLogger("google_genai.models").setLevel(logging.ERROR)    # silences the harmless "automatic function calling" notice
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=prompt)
    meta = getattr(response, "usage_metadata", None)
    if meta is not None:     # thinking tokens are billed as output tokens
        _set_usage(getattr(meta, "prompt_token_count", 0),
                   (getattr(meta, "candidates_token_count", 0) or 0) + (getattr(meta, "thoughts_token_count", 0) or 0))
    return response.text


def _call_anthropic(prompt: str, model: str, api_key: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(model=model, max_tokens=1024,
                                      messages=[{"role": "user", "content": prompt}])
    _set_usage(response.usage.input_tokens, response.usage.output_tokens)
    return response.content[0].text


def _call_openai(prompt: str, model: str, api_key: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}])
    if response.usage:
        _set_usage(response.usage.prompt_tokens, response.usage.completion_tokens)
    return response.choices[0].message.content


_DISPATCH = {"gemini": _call_gemini, "anthropic": _call_anthropic, "openai": _call_openai}


class ProviderLLM:
    def __init__(self, provider: str | None = None, model: str | None = None) -> None:
        env = config.get_env()
        self.provider = (provider or env["LLM_PROVIDER"]).lower()
        self.model = model or env["LLM_MODEL"]
        if self.provider not in _DISPATCH:
            raise ValueError(f"Unknown LLM_PROVIDER '{self.provider}'. Supported: {list(_DISPATCH)}")
        self._api_key = config.get_api_key(self.provider)
        if not self._api_key:
            raise RuntimeError(f"No API key for '{self.provider}'. Set "
                               f"{config.PROVIDER_API_KEY_ENV[self.provider]} in your .env.")
        self.usage = _Usage()
        self.last_usage: dict = {}       # {input_tokens, output_tokens[, estimated]} of the most recent call

    def complete(self, prompt: str) -> str:
        _tls.usage = None
        response = _DISPATCH[self.provider](prompt, self.model, self._api_key)
        self.usage.record(prompt, response)
        reported = getattr(_tls, "usage", None)
        # If a provider response carries no usage, fall back to ~4 characters per token and say so.
        self.last_usage = reported or {"input_tokens": len(prompt) // 4, "output_tokens": len(response) // 4, "estimated": True}
        return response


class ScriptedLLM:
    """Replays `responses` in order (last one repeats), or computes them via `fn(prompt)`."""

    def __init__(self, responses: list[str] | None = None, fn: Callable[[str], str] | None = None) -> None:
        self._responses = list(responses or [])
        self._fn = fn
        self._i = 0
        self.prompts: list[str] = []
        self.usage = _Usage()

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._fn is not None:
            response = self._fn(prompt)
        else:
            if not self._responses:
                raise RuntimeError("ScriptedLLM has no responses configured")
            response = self._responses[min(self._i, len(self._responses) - 1)]
            self._i += 1
        self.usage.record(prompt, response)
        return response


def parse_json(raw_text: str) -> dict:
    """Tolerates markdown fences and chatter around the JSON object."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"LLM response was not valid JSON: {raw_text[:200]!r}")
