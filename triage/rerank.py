"""
rerank.py -- an OPTIONAL cross-encoder rerank of the KB retriever's fused candidates. An experiment: off unless RERANK is set.

Why it exists. On the 13 held-out real questions the right issue is in the top 8 for 85% but ranked first for only 31%
(reports/PROJECT_EVALUATION_REPORT.md, F-01): the fused order is the weak point, which is what a cross-encoder reads the query and
each passage TOGETHER to fix. Whether it pays off, and what it costs, is measured by `python -m triage.eval.rerank_eval`
(reports/RERANK_EXPERIMENT.md); nothing is switched on by default.

What it changes, and what it must not. The Clarifier's thresholds and the Resolver's gate were calibrated on the retriever's vector
similarity, 0.5-0.8 (see triage/hybrid.py). A cross-encoder emits logits (-12..+4), so its output is squashed with a sigmoid to a 0..1
relevance and combined with that similarity in one of two ways:

  order   the cross-encoder decides which candidates are returned and in what ORDER, but the SCORES stay on the calibrated scale: the
          same set of similarity values is handed out best-first. Thresholds keep their meaning; a chunk may carry a score that is not
          its own similarity.
  blend   score = (1 - w) x similarity + w x relevance. The ranking uses both signals; the scale moves (a clear match goes toward 1, a
          non-match toward 0), so thresholds tuned on the old scale need re-checking.

Cost: the model is about 80 MB and reads up to 512 tokens per passage, roughly 1 s for 20 passages on a CPU, per search.
It never raises: if the model cannot load or fails, the original order is returned.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import replace
from typing import Optional, Sequence

from triage.state import Candidate

log = logging.getLogger(__name__)

MODES = ("off", "order", "blend")
DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEFAULT_POOL = 20            # fused candidates the cross-encoder re-reads
DEFAULT_BLEND = 0.5
MAX_CHARS = 1800             # about 450 tokens; the model reads 512 including the query


def sigmoid(x: float) -> float:
    x = max(-60.0, min(60.0, float(x)))
    return 1.0 / (1.0 + math.exp(-x))


def candidate_text(c: Candidate) -> str:
    """What the cross-encoder reads for a chunk: its last two headings (the issue it belongs to) then the chunk text."""
    heading = " > ".join(c.heading_path[-2:]) if c.heading_path else c.article_title
    return f"{heading}. {c.text}"[:MAX_CHARS]


class CrossEncoderReranker:
    """Lazy sentence-transformers CrossEncoder with a cache, so a variant sweep re-reads each (query, passage) pair only once."""

    def __init__(self, model_name: Optional[str] = None, model=None, cache_size: int = 20000) -> None:
        self.model_name = model_name or os.environ.get("RERANKER_MODEL") or DEFAULT_MODEL
        self._model = model
        self._cache: dict[tuple[str, str], float] = {}
        self._cache_size = cache_size

    def _ensure(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name, max_length=512)
        return self._model

    def relevance(self, query: str, texts: Sequence[str]) -> list[float]:
        """0..1 relevance of each text to the query (sigmoid of the model's logit)."""
        todo = [t for t in dict.fromkeys(texts) if (query, t) not in self._cache]
        if todo:
            logits = self._ensure().predict([(query, t) for t in todo])
            if len(self._cache) + len(todo) > self._cache_size:
                self._cache.clear()
            for t, logit in zip(todo, logits):
                self._cache[(query, t)] = sigmoid(logit)
        return [self._cache[(query, t)] for t in texts]


def rerank_candidates(cands: list[Candidate], relevance: Sequence[float], mode: str, blend: float, top_k: int) -> list[Candidate]:
    """The `top_k` best of `cands` under `mode`, best first, each with its vector similarity and relevance kept in metadata.
    Pure: no model, so it is tested without one."""
    if mode not in MODES:
        raise ValueError(f"rerank mode must be one of {MODES}, got '{mode}'")
    if mode == "off" or not cands:
        return list(cands)[:top_k]
    tagged = [replace(c, metadata={**c.metadata, "vector_score": c.score, "ce_score": round(float(r), 4)}) for c, r in zip(cands, relevance)]
    if mode == "order":
        order = sorted(range(len(tagged)), key=lambda i: -relevance[i])
        scale = sorted((c.score for c in cands), reverse=True)              # the calibrated scores, handed out best-first
        out = [replace(tagged[i], score=scale[rank]) for rank, i in enumerate(order)]
    else:
        w = min(max(float(blend), 0.0), 1.0)
        out = [replace(t, score=(1.0 - w) * c.score + w * float(r)) for t, c, r in zip(tagged, cands, relevance)]
        out.sort(key=lambda c: -c.score)
    return out[:top_k]


def settings_from_env() -> tuple[str, int, float]:
    """(mode, pool, blend) from RERANK=off|order|blend, RERANK_POOL, RERANK_BLEND. Default: off."""
    mode = os.environ.get("RERANK", "off").lower()
    if mode not in MODES:
        raise ValueError(f"RERANK must be one of {MODES}, got '{mode}'")
    return mode, int(os.environ.get("RERANK_POOL", DEFAULT_POOL)), float(os.environ.get("RERANK_BLEND", DEFAULT_BLEND))
