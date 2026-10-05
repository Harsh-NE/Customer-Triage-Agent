"""
config.py -- environment loading and the Clarifier's tunable thresholds.

Env precedence matches scripts/06_store.py: real environment variable > .env file > default.
The thresholds in ClarifierConfig are ASSUMPTIONS, not measured optima -- they were set from
a threshold sweep over 29 labeled scenarios (see reports/clarifier_eval_report.md) -- a
SMALL sample, vector-only retriever, same author for labels and hidden facts -- and are meant to be
re-calibrated with `python -m triage.eval.clarifier_eval` whenever the retriever changes,
because retrieval scores from different retrievers are not on the same scale.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ENV_DEFAULTS = {
    "LLM_PROVIDER": "gemini",
    "LLM_MODEL": "gemini-3.5-flash-lite",
    "EMBEDDING_MODEL": "BAAI/bge-base-en-v1.5",
    "VECTOR_DB_PATH": "data/processed/docker/store/vector",
    "TAXONOMY_PATH": "data/processed/docker/taxonomy.json",
}

PROVIDER_API_KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _load_dotenv(path: Path) -> dict:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def get_env() -> dict:
    """Resolved settings. The API key is looked up lazily by llm.py and never printed or logged."""
    dotenv = _load_dotenv(PROJECT_ROOT / ".env")
    return {k: os.environ.get(k) or dotenv.get(k) or default for k, default in ENV_DEFAULTS.items()}


def get_api_key(provider: str) -> str | None:
    key_env = PROVIDER_API_KEY_ENV.get(provider.lower())
    if not key_env:
        return None
    return os.environ.get(key_env) or _load_dotenv(PROJECT_ROOT / ".env").get(key_env)


@dataclass
class ClarifierConfig:
    # --- turn budget -------------------------------------------------------------
    max_clarify_turns: int = 3          # max questions asked per ticket; shared with Resolver callbacks
    max_tool_calls_per_turn: int = 3    # guardrail on search_kb calls inside one Clarifier turn
    top_k: int = 8                      # candidates fetched per search

    # --- ambiguity decision (A4). Scores are Candidate.score in (0, 1], higher = better ---
    softmax_temperature: float = 0.08   # lower = a clear top hit dominates faster (and more wrong READYs)
    ready_p_top: float = 0.5            # top hypothesis must hold at least this much mass...
    ready_margin: float = 0.25          # ...and lead the runner-up by at least this much
    min_top_score: float = 0.0          # absolute score floor. DISABLED on purpose: with the vector retriever, junk and
                                        # genuine hits score alike (0.669 vs 0.669); min_grounding below does this job
    mismatch_penalty: float = 0.15      # weight multiplier for hypotheses contradicting a customer answer
    error_match_threshold: float = 0.6  # customer's pasted error vs a hypothesis's documented error text
    error_match_boost: float = 4.0      # weight multiplier at a perfect match (scaled by the match score)
    min_discriminator_gain: float = 0.15  # don't ask a question that eliminates less than this
    min_option_weight: float = 0.05     # a cause below this probability is never offered in a menu
    # How easily can a CUSTOMER answer a question about this feature? Ranking uses
    # gain * answerability, so a slightly less decisive but far easier question wins. `component`
    # is intentionally absent: it is an internal doc-path label ("troubleshoot-and-support")
    # a customer cannot answer. `issue` ("which of these sounds like yours?") is the universal
    # fallback -- always available, but the customer has to read and interpret doc titles.
    feature_answerability: dict = field(default_factory=lambda: {
        "platform": 1.0, "error_message": 0.9, "product_area": 0.8, "issue": 0.6})

    # --- retrieval weighting by page type. Release notes / archived versions are ~25% of the
    # KB and shouldn't compete equally with troubleshooting pages. A soft multiplier, never a filter.
    doc_kind_weight: dict = field(default_factory=lambda: {
        "troubleshooting": 1.0, "faq": 1.0, "docs": 0.9, "reference": 0.85,
        "guide": 0.85, "release_notes": 0.6, "archive": 0.4,
    })

    # Clusters titled "Overview" etc. are structural intro sections that match broad queries
    # and manufacture false confidence; they are weak evidence of any specific CAUSE.
    generic_title_weight: float = 0.5
    # Dense retrieval always returns SOMETHING, and its absolute scores don't separate junk from signal
    # (observed: an irrelevant hit scored the same as a correct one). So the top hypothesis must also be
    # lexically grounded: at least this share of the customer's content words appear in its text.
    min_grounding: float = 0.34

    # --- question phrasing -----------------------------------------------------
    llm_phrase_questions: bool = False  # True = +1 LLM call per question; default templates (cheaper, auditable)
    max_options_in_question: int = 4

    # --- context window discipline (A9) ------------------------------------------
    context_token_budget: int = 700     # approx tokens (chars/4) of session context given to the LLM
    keep_last_turns: int = 4
