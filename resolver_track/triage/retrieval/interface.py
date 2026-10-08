"""Retrieval interface (B-owned contract, called by the Resolver AND by A's
ambiguity check, A4).

Both members code against `Retriever`. Concrete implementations:
  * LexicalRetriever   – BM25 + metadata boost, no models. Used for fixtures, unit
                         tests, A's solo development, and as the Tier 2 ticket index
                         until embeddings are added.
  * PhaseAAdapter      – wraps the existing Phase A hybrid pipeline
                         (BM25 + vector -> RRF -> metadata boost -> cross-encoder).
  * TieredRetriever    – routes tier="kb" / tier="tickets" to the right backend.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol, runtime_checkable

from rank_bm25 import BM25Okapi

from triage.contracts import Evidence, ProblemSignature, Tier


@runtime_checkable
class Retriever(Protocol):
    def retrieve(self, query: str, signature: Optional[ProblemSignature] = None,
                 k: int = 10, tier: Tier = "kb",
                 exclude_chunk_ids: Iterable[str] = ()) -> list[Evidence]:
        """Return up to k Evidence objects, best first.

        Guarantees every implementation must keep:
          * evidence_id is "E1".."Ek" in rank order (what the Resolver cites)
          * rerank_score is normalised to 0..1 (the confidence gate depends on it)
          * chunks in exclude_chunk_ids are never returned (used for retries)
        """
        ...


# --------------------------------------------------------------------------- helpers
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.\-:/]*", re.I)
_STOP = set("a an the is are was were be to of and or in on for with my i it this that "
            "how do does can cannot can't not when after before from at as by".split())


def tokenize(text: str) -> list[str]:
    return [t.lower().strip(".:") for t in _TOKEN.findall(text or "")
            if t.lower() not in _STOP]


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _number(results: list[Evidence]) -> list[Evidence]:
    for i, ev in enumerate(results, 1):
        ev.evidence_id = f"E{i}"
    return results


# --------------------------------------------------------------------------- lexical
class LexicalRetriever:
    """BM25 over a list of documents with a signature metadata boost.

    docs: dicts with keys chunk_id, doc_id, text and optional url, source,
    parent_text, trust, metadata{product_area, component, topics}.
    """

    def __init__(self, docs: list[dict[str, Any]], tier: Tier = "kb",
                 metadata_boost: float = 0.15, trust_weight: float = 0.15):
        if not docs:
            raise ValueError("LexicalRetriever needs at least one document")
        self.docs = docs
        self.tier = tier
        self.metadata_boost = metadata_boost
        self.trust_weight = trust_weight
        self._tokens = [tokenize(d.get("text", "") + " " + (d.get("title") or "")) for d in docs]
        self.bm25 = BM25Okapi(self._tokens)

    def retrieve(self, query: str, signature: Optional[ProblemSignature] = None,
                 k: int = 10, tier: Tier = "kb",
                 exclude_chunk_ids: Iterable[str] = ()) -> list[Evidence]:
        q = tokenize(signature.search_text() if signature else query) or tokenize(query)
        if not q:
            return []
        excluded = set(exclude_chunk_ids)
        raw = self.bm25.get_scores(q)
        qset = set(q)
        scored = []
        for idx, s in enumerate(raw):
            d = self.docs[idx]
            if d["chunk_id"] in excluded:
                continue
            coverage = len(qset & set(self._tokens[idx])) / len(qset)
            if coverage == 0:
                continue
            s = max(float(s), 0.0)       # BM25 IDF can hit 0 on tiny corpora
            bm = s / (s + 6.0)                                   # squash to 0..1
            score = 0.5 * bm + 0.5 * coverage
            meta = d.get("metadata") or {}
            if signature:
                if signature.product_area and meta.get("product_area") == signature.product_area:
                    score += self.metadata_boost
                if signature.component and (meta.get("component") == signature.component
                                            or signature.component in (meta.get("topics") or [])):
                    score += self.metadata_boost
            if d.get("trust") is not None:
                score = (1 - self.trust_weight) * score + self.trust_weight * float(d["trust"])
            scored.append((min(score, 1.0), s, idx))
        scored.sort(key=lambda t: t[0], reverse=True)
        out = []
        for score, s, idx in scored[:k]:
            d = self.docs[idx]
            out.append(Evidence(
                evidence_id="", chunk_id=d["chunk_id"], doc_id=d.get("doc_id", d["chunk_id"]),
                tier=self.tier, text=d["text"], url=d.get("url", ""), source=d.get("source", ""),
                parent_text=d.get("parent_text"), trust=d.get("trust"),
                fused_score=float(s), rerank_score=round(float(score), 4),
                doc_hash=d.get("doc_hash") or _hash(d.get("parent_text") or d["text"]),
                metadata=d.get("metadata") or {}))
        return _number(out)


def load_kb_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_tickets_jsonl(path: str | Path, exclude_synthetic: bool = True,
                       min_trust: float = 0.0, exclude_overlaps_kb: bool = False,
                       holdout_ids: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Turn A's docker_tickets_vN.jsonl into retrievable documents.

    Use the JSONL, not the CSV (the v3 CSV has 82 corrupted rows).
    holdout_ids: ticket_ids reserved for the eval set — never index them.
    """
    holdout = set(holdout_ids)
    docs = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        if t.get("ticket_id") in holdout:
            continue
        if exclude_synthetic and str(t.get("is_synthetic")).lower() == "true":
            continue
        if exclude_overlaps_kb and str(t.get("overlaps_kb")).lower() == "true":
            continue
        trust = float(t.get("trust_score") or 0.0)
        if trust < min_trust or not t.get("resolution"):
            continue
        topics = t.get("topics") or []
        if isinstance(topics, str):
            try:
                topics = json.loads(topics)
            except json.JSONDecodeError:
                topics = [topics]
        title = t.get("title") or ""
        problem = t.get("problem") or ""
        docs.append({
            "chunk_id": t["ticket_id"], "doc_id": t["ticket_id"], "title": title,
            "text": f"{title}\n{problem}".strip(),
            "parent_text": f"PROBLEM: {problem}\n\nRESOLUTION: {t['resolution']}",
            "url": t.get("url", ""), "source": t.get("source_type") or t.get("source", ""),
            "trust": trust,
            "metadata": {"topics": topics, "license": t.get("license"),
                         "trust_tier": t.get("trust_tier")},
        })
    return docs


# --------------------------------------------------------------------------- Phase A
class PhaseAAdapter:
    """Wrap the existing Phase A retrieval so it satisfies `Retriever`.

    search_fn: your existing function, e.g. retrieve.py's `search(query, k, filters)`,
    returning a list of dicts. field_map translates its keys to Evidence fields.
    score_is_logit: cross-encoders often return raw logits; we squash with a sigmoid
    so the confidence gate always sees 0..1.
    """

    DEFAULT_MAP = {"chunk_id": "chunk_id", "doc_id": "doc_id", "text": "text",
                   "url": "url", "source": "source", "parent_text": "parent_text",
                   "fused_score": "rrf_score", "rerank_score": "rerank_score",
                   "doc_hash": "doc_hash", "metadata": "metadata"}

    def __init__(self, search_fn: Callable[..., list[dict[str, Any]]], tier: Tier = "kb",
                 field_map: Optional[dict[str, str]] = None, score_is_logit: bool = True):
        self.search_fn = search_fn
        self.tier = tier
        self.field_map = {**self.DEFAULT_MAP, **(field_map or {})}
        self.score_is_logit = score_is_logit

    def _filters(self, sig: Optional[ProblemSignature]) -> dict[str, Any]:
        if not sig:
            return {}
        return {k: v for k, v in {"product_area": sig.product_area,
                                  "component": sig.component}.items() if v}

    def retrieve(self, query: str, signature: Optional[ProblemSignature] = None,
                 k: int = 10, tier: Tier = "kb",
                 exclude_chunk_ids: Iterable[str] = ()) -> list[Evidence]:
        excluded = set(exclude_chunk_ids)
        q = signature.search_text() if signature else query
        rows = self.search_fn(q, k=k + len(excluded), filters=self._filters(signature))
        out = []
        m = self.field_map
        for r in rows:
            if r.get(m["chunk_id"]) in excluded:
                continue
            score = float(r.get(m["rerank_score"], 0.0))
            if self.score_is_logit:
                score = 1 / (1 + math.exp(-score))
            text = r.get(m["text"], "")
            out.append(Evidence(
                evidence_id="", chunk_id=str(r.get(m["chunk_id"])),
                doc_id=str(r.get(m["doc_id"], r.get(m["chunk_id"]))), tier=self.tier,
                text=text, url=r.get(m["url"], ""), source=r.get(m["source"], ""),
                parent_text=r.get(m["parent_text"]), fused_score=float(r.get(m["fused_score"], 0.0)),
                rerank_score=round(score, 4),
                doc_hash=r.get(m["doc_hash"]) or _hash(r.get(m["parent_text"]) or text),
                metadata=r.get(m["metadata"]) or {}))
            if len(out) == k:
                break
        return _number(out)


class TieredRetriever:
    """Single object the Resolver holds; routes by tier."""

    def __init__(self, kb: Retriever, tickets: Optional[Retriever] = None):
        self.kb = kb
        self.tickets = tickets

    def retrieve(self, query: str, signature: Optional[ProblemSignature] = None,
                 k: int = 10, tier: Tier = "kb",
                 exclude_chunk_ids: Iterable[str] = ()) -> list[Evidence]:
        backend = self.kb if tier == "kb" else self.tickets
        if backend is None:
            return []
        return backend.retrieve(query, signature, k=k, tier=tier,
                                exclude_chunk_ids=exclude_chunk_ids)
