"""
07_retrieve.py -- Query the BM25 and vector stores built by 06_store.py.

Retrieval works in two steps, kept as separate functions so 08_evaluate.py can reuse
them exactly (no re-implementation, no drift between what's tested and what's served):

  1. rank   -- BM25 or vector search over individual chunks (index SMALL: precise matching)
  2. expand -- each hit is mapped to its parent group (the whole Section, or whole Article
               if the section has no subsections) and merged with its siblings, deduping
               repeat hits from the same group. The agent gets the full Symptom+Cause+
               Resolution text, not a lone fragment (return WHOLE).

Usage:
    python scripts/07_retrieve.py
"""

from __future__ import annotations

import json
import os
import pickle
import re
from collections import Counter, defaultdict
from pathlib import Path

import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# chunks_metadata.jsonl, not chunks.jsonl: same fields, plus 05_metadata.py's
# product_area/component/category -- needed for the rank-boosting step below.
CHUNKS_PATH = PROJECT_ROOT / "data" / "processed" / "chunks_metadata.jsonl"

DEFAULTS = {
    "EMBEDDING_MODEL": "BAAI/bge-base-en-v1.5",
    "RERANKER_MODEL": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "VECTOR_DB_PATH": "data/processed/store/vector",
    "BM25_PATH": "data/processed/store/bm25",
}

TOKEN_RE = re.compile(r"\w+")

# BGE-family models are trained to expect this instruction prefixed onto the QUERY only
# (never onto the indexed passages) for asymmetric retrieval. Applied automatically below.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

DEFAULT_POOL = 50       # raw candidates each of BM25/vector fetches before fusion
RERANK_TOP_N = 20       # how many fused candidates the (slower) cross-encoder re-scores
RRF_K = 60              # standard reciprocal rank fusion constant
# Multiplicative, not additive: RRF scores across a 50-candidate pool only span about
# 0.008-0.033, so a flat bonus (e.g. +0.15) doesn't nudge close calls -- it dwarfs the
# entire natural score range and overrides real relevance outright. A 15% multiplier keeps
# the boost proportional: a strong candidate's lead stays a lead, only close calls flip.
METADATA_BOOST = 1.15
METADATA_BOOST_MIN_VOTES = 3  # require at least this many top candidates to agree first
                               # (raised from 2 -- reduces false consensus from one
                               # chunk-heavy article filling several pool slots by itself)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_dotenv_file(path: Path) -> dict:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def get_config() -> dict:
    dotenv_values = load_dotenv_file(PROJECT_ROOT / ".env")
    return {key: os.environ.get(key) or dotenv_values.get(key) or default
            for key, default in DEFAULTS.items()}


def collection_name_for_model(model_name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", model_name).strip("-").lower()
    return f"kb_chunks__{slug}"


# ---------------------------------------------------------------------------
# Chunk lookup + parent grouping ("index small, return whole")
# ---------------------------------------------------------------------------

def load_chunk_lookup(chunks_path: Path) -> dict:
    lookup = {}
    with chunks_path.open(encoding="utf-8") as f:
        for line in f:
            chunk = json.loads(line)
            lookup[chunk["chunk_id"]] = chunk
    return lookup


def parent_key_for(chunk: dict) -> str:
    """Group by the immediate parent in the Article->Section->Subsection tree: a shared
    H2 scenario for subsection leaves (keeps unrelated scenarios in the same article from
    being merged together), otherwise the whole article (the common flat Symptoms/Cause/
    Resolution pattern, where those are siblings directly under the article)."""
    if chunk.get("subsection_title"):
        return f"{chunk['source_path']}::{chunk['section_title']}"
    return chunk["source_path"]


def build_parent_index(chunk_lookup: dict) -> dict:
    """parent_key -> chunk_ids belonging to that group, in original document order
    (chunk_id's zero-padded sequence suffix sorts correctly)."""
    groups = defaultdict(list)
    for chunk_id, chunk in chunk_lookup.items():
        groups[parent_key_for(chunk)].append(chunk_id)
    for ids in groups.values():
        ids.sort()
    return groups


def expand_group(parent_key: str, chunk_lookup: dict, parent_index: dict) -> dict:
    chunk_ids = parent_index[parent_key]
    chunks = [chunk_lookup[cid] for cid in chunk_ids]
    parts = []
    for c in chunks:
        label = c["section_title"]
        if c["subsection_title"]:
            label += f" / {c['subsection_title']}"
        parts.append(f"[{label}]\n{c['text']}")
    return {
        "parent_key": parent_key,
        "source_path": chunks[0]["source_path"],
        "article_title": chunks[0]["article_title"],
        "chunk_ids": chunk_ids,
        "text": "\n\n".join(parts),
    }


def _collect_results(ranked: list[tuple[str, float]], k: int, chunk_lookup: dict,
                      parent_index: dict | None) -> list[dict]:
    """Turn a ranked (chunk_id, score) list into up to k result records.
    parent_index=None -> raw mode: no dedup, exactly the old chunk-level behavior.
    parent_index given -> expanded mode: dedupe by parent group, merge siblings in."""
    results = []
    seen_keys = set()
    for chunk_id, score in ranked:
        if len(results) >= k:
            break
        chunk = chunk_lookup.get(chunk_id)
        if chunk is None:
            continue
        if parent_index is None:
            results.append({"score": score, "source_path": chunk["source_path"],
                             "article_title": chunk["article_title"], "text": chunk["text"],
                             "chunk_ids": [chunk_id]})
            continue
        pk = parent_key_for(chunk)
        if pk in seen_keys:
            continue
        seen_keys.add(pk)
        results.append({"score": score, **expand_group(pk, chunk_lookup, parent_index)})
    return results


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

def load_bm25_index(bm25_path: Path) -> dict:
    with (bm25_path / "bm25_index.pkl").open("rb") as f:
        return pickle.load(f)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def bm25_rank(query: str, bm25_index: dict, pool: int = DEFAULT_POOL) -> list[tuple[str, float]]:
    bm25, chunk_ids = bm25_index["bm25"], bm25_index["chunk_ids"]
    scores = bm25.get_scores(tokenize(query))
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:pool]
    return [(chunk_ids[i], float(scores[i])) for i in order]


def bm25_search(query: str, k: int, bm25_index: dict, chunk_lookup: dict,
                 parent_index: dict | None = None, pool: int = DEFAULT_POOL) -> list[dict]:
    ranked = bm25_rank(query, bm25_index, pool)
    return _collect_results(ranked, k, chunk_lookup, parent_index)


# ---------------------------------------------------------------------------
# Vector
# ---------------------------------------------------------------------------

def get_chroma_collection(vector_db_path: Path, model_name: str):
    client = chromadb.PersistentClient(path=str(vector_db_path))
    return client.get_collection(name=collection_name_for_model(model_name))


def vector_rank(query: str, model: SentenceTransformer, model_name: str, collection,
                 pool: int = DEFAULT_POOL) -> list[tuple[str, float]]:
    query_text = BGE_QUERY_INSTRUCTION + query if "bge" in model_name.lower() else query
    query_embedding = model.encode([query_text]).tolist()
    found = collection.query(query_embeddings=query_embedding, n_results=pool)
    return list(zip(found["ids"][0], found["distances"][0]))


def vector_search(query: str, k: int, model: SentenceTransformer, model_name: str, collection,
                   chunk_lookup: dict, parent_index: dict | None = None,
                   pool: int = DEFAULT_POOL) -> list[dict]:
    ranked = vector_rank(query, model, model_name, collection, pool)
    return _collect_results(ranked, k, chunk_lookup, parent_index)


# ---------------------------------------------------------------------------
# Fusion, metadata rank-boosting, cross-encoder reranking
# ---------------------------------------------------------------------------

def reciprocal_rank_fusion(ranked_lists: list[list[tuple[str, float]]],
                            k: int = RRF_K) -> list[tuple[str, float]]:
    """Combine several ranked (chunk_id, score) lists into one, using each item's *rank
    position* rather than its raw score -- BM25 scores and vector distances aren't on
    comparable scales, so this sidesteps normalization entirely. A chunk that ranks well
    in either list scores well overall; a chunk both agree on scores best."""
    fused_scores: dict[str, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, (chunk_id, _) in enumerate(ranked, start=1):
            fused_scores[chunk_id] += 1.0 / (k + rank)
    return sorted(fused_scores.items(), key=lambda item: item[1], reverse=True)


def apply_metadata_boost(ranked: list[tuple[str, float]], chunk_lookup: dict,
                          top_n_for_vote: int = 10, boost: float = METADATA_BOOST,
                          min_votes: int = METADATA_BOOST_MIN_VOTES) -> list[tuple[str, float]]:
    """Soft nudge, not a filter: look at the product_area of the current top candidates: if
    several of them already agree, give other candidates that share that product_area a
    proportional score multiplier. Never removes or excludes anything -- a strong candidate
    from a 'wrong' area still wins if its underlying score is high enough, and the boost is
    scaled to each candidate's own score rather than a flat amount, so it can't dwarf the
    real ranking signal the way an additive bonus does. A wrong majority vote just fails to
    help (no penalty), rather than a hard filter that can hide the right answer outright
    behind a misclassified category."""
    def area_of(chunk_id: str) -> str | None:
        chunk = chunk_lookup.get(chunk_id)
        return chunk.get("metadata", {}).get("product_area") if chunk else None

    top_areas = [area_of(cid) for cid, _ in ranked[:top_n_for_vote]]
    top_areas = [a for a in top_areas if a]
    if not top_areas:
        return ranked

    dominant, votes = Counter(top_areas).most_common(1)[0]
    if votes < min_votes:
        return ranked

    boosted = [(cid, score * boost if area_of(cid) == dominant else score) for cid, score in ranked]
    return sorted(boosted, key=lambda item: item[1], reverse=True)


def load_cross_encoder(model_name: str) -> CrossEncoder:
    return CrossEncoder(model_name)


def rerank(query: str, ranked: list[tuple[str, float]], chunk_lookup: dict,
           cross_encoder: CrossEncoder, top_n: int = RERANK_TOP_N) -> list[tuple[str, float]]:
    """Re-score only the top_n candidates (the expensive step) with a cross-encoder, which
    reads the query and each candidate's text together rather than comparing separately-
    computed vectors -- much better at telling apart near-duplicate articles. Everything
    beyond top_n keeps its original fused order as a fallback tail."""
    shortlist = [(cid, score) for cid, score in ranked[:top_n] if cid in chunk_lookup]
    if not shortlist:
        return ranked

    pairs = [(query, chunk_lookup[cid]["text"]) for cid, _ in shortlist]
    ce_scores = cross_encoder.predict(pairs)
    reranked_head = sorted(zip((cid for cid, _ in shortlist), ce_scores),
                            key=lambda item: item[1], reverse=True)
    remainder = ranked[top_n:]
    return [(cid, float(score)) for cid, score in reranked_head] + remainder


def hybrid_rank(query: str, bm25_index: dict, model: SentenceTransformer, model_name: str,
                 collection, chunk_lookup: dict, cross_encoder: CrossEncoder,
                 pool: int = DEFAULT_POOL) -> list[tuple[str, float]]:
    """The full pipeline: BM25 + vector -> fuse -> metadata boost -> cross-encoder rerank."""
    bm25_ranked = bm25_rank(query, bm25_index, pool)
    vec_ranked = vector_rank(query, model, model_name, collection, pool)
    fused = reciprocal_rank_fusion([bm25_ranked, vec_ranked])
    boosted = apply_metadata_boost(fused, chunk_lookup)
    return rerank(query, boosted, chunk_lookup, cross_encoder)


def hybrid_search(query: str, k: int, bm25_index: dict, model: SentenceTransformer, model_name: str,
                   collection, chunk_lookup: dict, cross_encoder: CrossEncoder,
                   parent_index: dict | None = None, pool: int = DEFAULT_POOL) -> list[dict]:
    ranked = hybrid_rank(query, bm25_index, model, model_name, collection, chunk_lookup,
                          cross_encoder, pool)
    return _collect_results(ranked, k, chunk_lookup, parent_index)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def print_result(query: str, method: str, result: dict) -> None:
    print(f"\n=== {method} search ===")
    print(f"Customer query: \"{query}\"\n")
    print(f"Score/dist   : {result['score']:.4f}")
    print(f"Article      : {result['article_title']}")
    print(f"Source       : {result['source_path']}")
    print(f"Merged from  : {len(result['chunk_ids'])} chunk(s) -> {result['chunk_ids']}")
    print(f"Text         : {result['text'][:600]}")


def main() -> None:
    config = get_config()
    bm25_path = PROJECT_ROOT / config["BM25_PATH"]
    vector_db_path = PROJECT_ROOT / config["VECTOR_DB_PATH"]

    print("Loading chunk lookup + parent index ...")
    chunk_lookup = load_chunk_lookup(CHUNKS_PATH)
    parent_index = build_parent_index(chunk_lookup)

    print("Loading BM25 index ...")
    bm25_index = load_bm25_index(bm25_path)

    print(f"Loading embedding model: {config['EMBEDDING_MODEL']} ...")
    model = SentenceTransformer(config["EMBEDDING_MODEL"])
    collection = get_chroma_collection(vector_db_path, config["EMBEDDING_MODEL"])

    print(f"Loading reranker model: {config['RERANKER_MODEL']} ...")
    cross_encoder = load_cross_encoder(config["RERANKER_MODEL"])

    bm25_query = "Outlook doesn't connect when using modern authentication"
    results = bm25_search(bm25_query, k=1, bm25_index=bm25_index, chunk_lookup=chunk_lookup,
                           parent_index=parent_index)
    if results:
        print_result(bm25_query, "BM25 (keyword, expanded)", results[0])

    vector_query = "My laptop's drive encryption won't turn on, something about the security chip being locked out"
    results = vector_search(vector_query, k=1, model=model, model_name=config["EMBEDDING_MODEL"],
                             collection=collection, chunk_lookup=chunk_lookup, parent_index=parent_index)
    if results:
        print_result(vector_query, "Vector (semantic, expanded)", results[0])

    # This one previously failed BOTH BM25 and vector search independently (see
    # 08_evaluate.py's modern_authentication cluster) -- fusion+boost+rerank is meant
    # to be the fix for exactly this case.
    hybrid_query = "Outlook keeps prompting for a password over and over ever since modern authentication was turned on"
    results = hybrid_search(hybrid_query, k=1, bm25_index=bm25_index, model=model,
                             model_name=config["EMBEDDING_MODEL"], collection=collection,
                             chunk_lookup=chunk_lookup, cross_encoder=cross_encoder,
                             parent_index=parent_index)
    if results:
        print_result(hybrid_query, "Hybrid (fusion + metadata boost + rerank)", results[0])

    print()


if __name__ == "__main__":
    main()
