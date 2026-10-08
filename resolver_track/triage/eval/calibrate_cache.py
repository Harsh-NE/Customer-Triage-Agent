"""B4 — semantic-cache threshold calibration.

Input: JSONL of signature pairs {"a": {...}, "b": {...}, "same": true|false}
  same=true   -> paraphrases of the same problem (should HIT)
  same=false  -> hard negatives: similar wording, different cause (must MISS)

For each candidate threshold we insert `a` into a fresh cache, look up `b`, and
measure hit rate on positives and FALSE-HIT rate on negatives. Pick the lowest
threshold whose false-hit rate <= --max-false-hit (a wrong reused answer is worse
than a miss). Also reports how many negatives the metadata gate alone blocked.

    python -m triage.eval.calibrate_cache --pairs fixtures/cache_pairs.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from triage.cache import Embedder, HashingEmbedder, SemanticCache
from triage.config import CacheConfig
from triage.contracts import CacheStatus, ProblemSignature


def _sim_and_gate(pair: dict[str, Any], embedder: Embedder) -> tuple[float, bool]:
    a, b = ProblemSignature.from_dict(pair["a"]), ProblemSignature.from_dict(pair["b"])
    cache = SemanticCache(CacheConfig(upper=2.0, lower=-1.0, require_confirmed=False), embedder)
    entry = cache.put(a, {"steps": []}, [], confirmed_by="human")
    if cache.key_hash(a) == cache.key_hash(b):
        return 1.0, True
    passed = cache.metadata_gate(b, entry)
    sim = cache.lookup(b).similarity if passed else 0.0
    return sim, passed


def calibrate(pairs: list[dict[str, Any]], embedder: Embedder | None = None,
              max_false_hit: float = 0.0) -> dict[str, Any]:
    embedder = embedder or HashingEmbedder()
    scored = [(*_sim_and_gate(p, embedder), bool(p["same"])) for p in pairs]
    pos = [s for s in scored if s[2]]
    neg = [s for s in scored if not s[2]]
    sweep = []
    for t in [round(0.70 + 0.01 * i, 2) for i in range(31)]:
        hits = sum(gate and sim >= t for sim, gate, _ in pos)
        false_hits = sum(gate and sim >= t for sim, gate, _ in neg)
        sweep.append({"threshold": t,
                      "hit_rate": round(hits / len(pos), 4) if pos else None,
                      "false_hit_rate": round(false_hits / len(neg), 4) if neg else None})
    ok = [s for s in sweep if (s["false_hit_rate"] or 0) <= max_false_hit]
    chosen = min(ok, key=lambda s: s["threshold"]) if ok else None
    return {
        "n_pairs": len(pairs), "n_positive": len(pos), "n_negative": len(neg),
        "negatives_blocked_by_metadata_gate": sum(not gate for _, gate, _ in neg),
        "positive_similarities": sorted(round(s, 4) for s, g, _ in pos if g),
        "negative_similarities_past_gate": sorted(round(s, 4) for s, g, _ in neg if g),
        "max_false_hit": max_false_hit,
        "recommended_lower": chosen["threshold"] if chosen else None,
        "sweep": sweep,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="fixtures/cache_pairs.jsonl")
    ap.add_argument("--max-false-hit", type=float, default=0.0)
    ap.add_argument("--embedder", default="hashing", help="hashing | st:<model-name>")
    ap.add_argument("--out", default="reports/cache_calibration.json")
    a = ap.parse_args()
    emb: Embedder = HashingEmbedder()
    if a.embedder.startswith("st:"):
        from triage.cache import SentenceTransformerEmbedder
        emb = SentenceTransformerEmbedder(a.embedder[3:])
    pairs = [json.loads(l) for l in Path(a.pairs).read_text().splitlines() if l.strip()]
    rep = calibrate(pairs, emb, a.max_false_hit)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, indent=2))
    print({k: v for k, v in rep.items() if k != "sweep"})


if __name__ == "__main__":
    main()
