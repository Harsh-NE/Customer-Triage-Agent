"""B4 — semantic cache keyed on the Problem Signature.

Lookup order:
  1. Exact tier    – hash of the canonical signature string
  2. Hard metadata gate – product_area, component, and (when both sides have them)
                     error strings / exit codes must match before similarity counts.
                     Stops "same words, different root cause" false hits.
  3. Semantic tier – cosine similarity on the signature embedding, graduated:
                     sim >= upper          -> HIT_SEMANTIC (reuse answer)
                     lower <= sim < upper  -> HIT_REDRAFT  (reuse evidence, re-draft)
                     sim < lower           -> MISS

Writes: only confirmed resolutions (customer said "resolved" or a human approved).
Invalidation: an entry dies when any of its evidence documents changed hash in
store_manifest.json (see invalidate_stale).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

from triage.config import CacheConfig
from triage.contracts import CacheStatus, ProblemSignature


# --------------------------------------------------------------------------- embedders
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Model-free char-n-gram hashing embedder. Good enough for tests and for a
    baseline; swap for SentenceTransformerEmbedder (same model as the KB) in real runs."""

    def __init__(self, dim: int = 512, n: int = 3):
        self.dim, self.n = dim, n

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            s = f" {t.lower()} "
            for i in range(len(s) - self.n + 1):
                h = int(hashlib.md5(s[i:i + self.n].encode()).hexdigest(), 16)
                v[h % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from sentence_transformers import SentenceTransformer  # lazy
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))           # inputs are unit-normalised


# --------------------------------------------------------------------------- entries
def _norm_err(e: str) -> str:
    return re.sub(r"\s+", " ", e.lower()).strip()


@dataclass
class CacheEntry:
    entry_id: str
    key_hash: str
    key_text: str
    product_area: Optional[str]
    component: Optional[str]
    error_strings: list[str]
    exit_codes: list[int]
    embedding: list[float]
    draft: dict[str, Any]
    evidence: list[dict[str, Any]]              # serialised Evidence (with doc_hash)
    confirmed_by: str                           # "customer" | "human"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    hits: int = 0
    valid: bool = True


@dataclass
class CacheLookup:
    status: CacheStatus
    entry: Optional[CacheEntry] = None
    similarity: float = 0.0
    rejected_by_gate: int = 0


class SemanticCache:
    def __init__(self, cfg: CacheConfig | None = None, embedder: Embedder | None = None,
                 path: Optional[str | Path] = None):
        self.cfg = cfg or CacheConfig()
        self.embedder = embedder or HashingEmbedder()
        self.path = Path(path) if path else None
        self.entries: list[CacheEntry] = []
        if self.path and self.path.exists():
            self.entries = [CacheEntry(**e) for e in json.loads(self.path.read_text())]

    # -- persistence
    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(e) for e in self.entries]))

    @staticmethod
    def key_hash(sig: ProblemSignature) -> str:
        return hashlib.sha256(sig.cache_key_text().encode()).hexdigest()[:20]

    # -- gate
    @staticmethod
    def metadata_gate(sig: ProblemSignature, e: CacheEntry) -> bool:
        if (sig.product_area or None) != (e.product_area or None):
            return False
        if (sig.component or None) != (e.component or None):
            return False
        if sig.error_strings and e.error_strings:
            if not {_norm_err(x) for x in sig.error_strings} & {_norm_err(x) for x in e.error_strings}:
                return False
        if sig.exit_codes and e.exit_codes and not set(sig.exit_codes) & set(e.exit_codes):
            return False
        return True

    # -- lookup
    def lookup(self, sig: ProblemSignature, upper: Optional[float] = None,
               lower: Optional[float] = None) -> CacheLookup:
        upper = self.cfg.upper if upper is None else upper
        lower = self.cfg.lower if lower is None else lower
        live = [e for e in self.entries if e.valid]
        if not live:
            return CacheLookup(CacheStatus.MISS)
        kh = self.key_hash(sig)
        for e in live:
            if e.key_hash == kh:
                e.hits += 1
                return CacheLookup(CacheStatus.HIT_EXACT, e, 1.0)
        candidates = [e for e in live if self.metadata_gate(sig, e)]
        rejected = len(live) - len(candidates)
        if not candidates:
            return CacheLookup(CacheStatus.MISS, rejected_by_gate=rejected)
        q = self.embedder.embed([sig.cache_key_text()])[0]
        best, sim = max(((e, cosine(q, e.embedding)) for e in candidates), key=lambda t: t[1])
        if sim >= upper:
            best.hits += 1
            return CacheLookup(CacheStatus.HIT_SEMANTIC, best, round(sim, 4), rejected)
        if sim >= lower:
            best.hits += 1
            return CacheLookup(CacheStatus.HIT_REDRAFT, best, round(sim, 4), rejected)
        return CacheLookup(CacheStatus.MISS, None, round(sim, 4), rejected)

    # -- write
    def put(self, sig: ProblemSignature, draft: dict[str, Any], evidence: list[dict[str, Any]],
            confirmed_by: Optional[str]) -> Optional[CacheEntry]:
        if self.cfg.require_confirmed and confirmed_by not in ("customer", "human"):
            return None
        kh = self.key_hash(sig)
        self.entries = [e for e in self.entries if e.key_hash != kh]   # newest wins
        entry = CacheEntry(
            entry_id=f"C-{uuid.uuid4().hex[:10]}", key_hash=kh, key_text=sig.cache_key_text(),
            product_area=sig.product_area, component=sig.component,
            error_strings=list(sig.error_strings), exit_codes=list(sig.exit_codes),
            embedding=self.embedder.embed([sig.cache_key_text()])[0],
            draft=draft, evidence=evidence, confirmed_by=confirmed_by or "unknown")
        self.entries.append(entry)
        self.save()
        return entry

    # -- invalidation
    def invalidate_stale(self, manifest: dict[str, Any]) -> int:
        """manifest = store_manifest.json, expects {"doc_hashes": {doc_id: hash}}."""
        current = manifest.get("doc_hashes", {})
        n = 0
        for e in self.entries:
            if not e.valid:
                continue
            for ev in e.evidence:
                if ev.get("tier") != "kb":
                    continue
                now = current.get(ev.get("doc_id"))
                if now is None or (ev.get("doc_hash") and now != ev["doc_hash"]):
                    e.valid = False
                    n += 1
                    break
        self.save()
        return n
