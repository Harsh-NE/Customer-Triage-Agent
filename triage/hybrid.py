"""
hybrid.py -- the two retrievers the Resolver will use.

  HybridKBRetriever   Tier 1 (docs). Dense + BM25 over the KB, fused with reciprocal rank fusion (RRF). Satisfies the
                      Retriever protocol in triage/retrieval.py, so it drops into the Clarifier unchanged.
  TicketRetriever     Tier 2 (historical resolved tickets). Dense + BM25 over the ticket store from scripts/10_tickets.py,
                      then a re-rank that uses the structured fields: trust, resolution kind, recency, and exact
                      error-line / exit-code matches. Returns TicketHit (community evidence), not Candidate.

KB scoring, and why it is not the RRF score. The Clarifier's thresholds (softmax temperature, READY gates) were calibrated
on vector similarity, 1/(1+distance), roughly 0.5-0.8. RRF scores (0.01-0.03) are on another scale. So RRF only decides WHICH
chunks come back (recall: BM25 finds rare terms such as "rootless" or "429" that dense search misses) and every returned chunk
is scored by its vector similarity to the query, computed exactly even for chunks only BM25 found. Same scale as before,
better recall. BM25 therefore changes which issues are in the pool, not their weights.

Ticket scoring is different: tickets are ranked by us (fused rank x trust x resolution kind x recency x exact matches), so
the score is a ranking score in (0, 1], not a similarity.

No cross-encoder rerank yet: it is a ~80 MB extra model with an uncalibrated score; add it only if an evaluation shows the
fused order needs it.
"""

from __future__ import annotations

import json
import pickle
import re
import sqlite3
from pathlib import Path

from triage import config
from triage.answers import overlap_coefficient
from triage.retrieval import BGE_QUERY_INSTRUCTION, ChromaRetriever
from triage.state import Candidate, TicketHit

_TOKEN = re.compile(r"\w+")
RRF_K = 60


def tokenize(text: str) -> list[str]:
    """Same tokenisation as scripts/06_store.py and 10_tickets.py -- the BM25 indexes were built with it."""
    return _TOKEN.findall(text.lower())


def rrf_fuse(ranked_lists: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal rank fusion: score(id) = sum over lists of 1 / (k + rank), rank starting at 1."""
    fused: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank)
    return fused


def bm25_top(bm25, ids: list[str], query: str, pool: int) -> list[str]:
    """Ids of the `pool` best BM25 matches (positive scores only), best first."""
    tokens = tokenize(query)
    if not tokens:
        return []
    scores = bm25.get_scores(tokens)
    order = sorted(range(len(scores)), key=lambda i: -scores[i])[:pool]
    return [ids[i] for i in order if scores[i] > 0]


def _sq_distance(a, b) -> float:
    return float(sum((x - y) ** 2 for x, y in zip(a, b)))


def _load_bm25(path: Path, id_key: str):
    with (path / "bm25_index.pkl").open("rb") as f:
        data = pickle.load(f)
    return data["bm25"], data[id_key]


# ---------------------------------------------------------------------------
# Tier 1: hybrid KB retriever
# ---------------------------------------------------------------------------

class HybridKBRetriever(ChromaRetriever):
    """Dense + BM25 + RRF over the KB, then the same sibling expansion as ChromaRetriever."""

    def __init__(self, bm25_path: str | None = None, pool: int = 30, **kwargs) -> None:
        super().__init__(**kwargs)
        self._bm25_path = Path(bm25_path or config.PROJECT_ROOT / config.get_env()["BM25_PATH"])
        self._pool = pool
        self._bm25 = None
        self._bm25_ids: list[str] = []

    def search(self, query: str, top_k: int = 8) -> list[Candidate]:
        self._ensure()
        if self._bm25 is None:
            self._bm25, self._bm25_ids = _load_bm25(self._bm25_path, "chunk_ids")

        q_emb = self._model.encode([BGE_QUERY_INSTRUCTION + query])[0].tolist()
        res = self._collection.query(query_embeddings=[q_emb], n_results=self._pool,
                                     include=["documents", "metadatas", "distances"])
        by_id: dict[str, Candidate] = {
            cid: self._to_candidate(cid, doc, meta, 1.0 / (1.0 + float(dist)))
            for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0])}
        vector_ranked = list(res["ids"][0])
        lexical_ranked = bm25_top(self._bm25, self._bm25_ids, query, self._pool)

        chosen = [cid for cid, _ in sorted(rrf_fuse([vector_ranked, lexical_ranked]).items(), key=lambda kv: -kv[1])][:top_k]

        lexical_only = [cid for cid in chosen if cid not in by_id]       # found by BM25 but not by dense search
        if lexical_only:
            got = self._collection.get(ids=lexical_only, include=["documents", "metadatas", "embeddings"])
            for cid, doc, meta, emb in zip(got["ids"], got["documents"], got["metadatas"], got["embeddings"]):
                by_id[cid] = self._to_candidate(cid, doc, meta, 1.0 / (1.0 + _sq_distance(q_emb, emb)))

        hits = sorted((by_id[cid] for cid in chosen), key=lambda c: -c.score)
        if not self._expand:
            return hits
        return sorted(hits + self._siblings(hits), key=lambda c: -c.score)


# ---------------------------------------------------------------------------
# Tier 2: ticket retriever
# ---------------------------------------------------------------------------

TRUST_ORDER = {"low": 0, "medium": 1, "high": 2}
# How much we believe the answer was validated. (llm_generated rows are not indexed at all.)
RESOLUTION_KIND_WEIGHT = {
    "accepted_answer": 1.0, "maintainer_comment": 1.0, "official_answer": 1.0, "forum_accepted_answer": 0.95,
    "forum_op_confirmed_reply": 0.9, "community_comment": 0.85, "curated_answer": 0.8,
}
EXIT_CODE_BOOST = 1.5          # the ticket mentions the exit code the customer reported
EXIT_CODE_MISMATCH = 0.85      # the ticket is about other exit codes only
ERROR_LINE_BOOST = 1.4         # a ticket error line closely matches the customer's words
ERROR_LINE_MIN_OVERLAP = 0.6
TOPIC_BOOST = 1.1              # soft: shares a topic with what the Clarifier inferred
_EXIT_CODE_RE = re.compile(r"(?i)\b(?:exit(?:ed)?(?:\s+with)?(?:\s+(?:status|code))?|code|status)\s*[:=]?\s*(\d{1,3})\b")

_ROW_COLUMNS = ("ticket_id, title, problem, resolution, source, source_type, trust_tier, trust_score, resolution_kind, "
                "kind_guess, age_years, topics, errors_clean, exit_codes, docker_versions, url, license")


def query_exit_codes(query: str) -> set[str]:
    """Exit codes the customer mentions ('exit code 137', 'exited with code 1'); HTTP codes like 429 are > 255 and ignored."""
    return {m for m in _EXIT_CODE_RE.findall(query) if int(m) <= 255}


def recency_factor(age_years: float | None) -> float:
    """Docker changes: a 9-year-old fix is weaker evidence than a 2-year-old one. Mild, floored, unknown age = 0.9."""
    if age_years is None:
        return 0.9
    return max(0.6, 1.0 - 0.04 * max(0.0, age_years - 3.0))


def score_ticket(row: dict, base: float, query: str, codes: set[str], topics: set[str]) -> tuple[float, list[str]]:
    """base in (0, 1] is the fused retrieval rank; the structured fields adjust it. Returns (score, reasons)."""
    reasons: list[str] = []
    score = base * (0.6 + 0.4 * (row["trust_score"] or 0.0))
    score *= RESOLUTION_KIND_WEIGHT.get(row["resolution_kind"], 0.85)
    score *= recency_factor(row["age_years"])
    ticket_codes = set(row["exit_codes"]) | query_exit_codes(row["title"])      # the column is sparse; titles often say it
    if codes and ticket_codes:
        if codes & ticket_codes:
            score *= EXIT_CODE_BOOST
            reasons.append("exit_code:" + ",".join(sorted(codes & ticket_codes)))
        else:
            score *= EXIT_CODE_MISMATCH
    if any(overlap_coefficient(query, line) >= ERROR_LINE_MIN_OVERLAP for line in row["errors_clean"]):
        score *= ERROR_LINE_BOOST
        reasons.append("error_line")
    shared = topics & set(row["topics"])
    if shared:
        score *= TOPIC_BOOST
        reasons.append("topic:" + ",".join(sorted(shared)))
    return score, reasons


def rank_tickets(rows: list[dict], fused: dict[str, float], query: str, top_k: int, *, topics: set[str] | None = None,
                 kind: str | None = None, min_trust: str = "medium", codes: set[str] | None = None,
                 exclude_ids: set[str] = frozenset()) -> list[tuple[dict, float, list[str]]]:
    """Pure ranking over fetched rows (no I/O, unit-testable). Hard filters: kind, exclude_ids, duplicate URLs.
    Trust floor is soft: tickets below `min_trust` only fill the list when too few eligible ones exist."""
    codes = query_exit_codes(query) if codes is None else codes
    best = 2.0 / (RRF_K + 1)                           # a document ranked first by both lists
    scored = []
    for row in rows:
        if row["ticket_id"] in exclude_ids or (kind and row["kind_guess"] != kind):
            continue
        s, why = score_ticket(row, fused.get(row["ticket_id"], 0.0) / best, query, codes, topics or set())
        scored.append((row, s, why))
    scored.sort(key=lambda t: -t[1])

    seen_urls: set[str] = set()
    eligible, fallback = [], []
    floor = TRUST_ORDER[min_trust]
    for row, s, why in scored:
        if row["url"] and row["url"] in seen_urls:
            continue
        seen_urls.add(row["url"])
        (eligible if TRUST_ORDER.get(row["trust_tier"], 0) >= floor else fallback).append((row, s, why))
    out = (eligible + fallback)[:top_k]
    peak = max((s for _, s, _ in out), default=1.0)
    return [(row, s / peak if peak > 1.0 else s, why) for row, s, why in out]      # keep scores within (0, 1]


class TicketRetriever:
    """Hybrid search over the ticket store (Chroma + BM25 + SQLite docstore built by scripts/10_tickets.py)."""

    def __init__(self, store_root: str | None = None, model_name: str | None = None, model=None, pool: int = 30) -> None:
        env = config.get_env()
        self._root = Path(store_root or config.PROJECT_ROOT / env["TICKETS_STORE_PATH"])
        self._model_name = model_name or env["EMBEDDING_MODEL"]
        self._model = model
        self._pool = pool
        self._collection = None
        self._bm25 = None
        self._ids: list[str] = []
        self._db: sqlite3.Connection | None = None

    def _ensure(self) -> None:
        if self._collection is not None:
            return
        import chromadb
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", self._model_name).strip("-").lower()
        self._collection = chromadb.PersistentClient(path=str(self._root / "vector")).get_collection(f"tickets__{slug}")
        self._bm25, self._ids = _load_bm25(self._root / "bm25", "ticket_ids")
        self._db = sqlite3.connect(self._root / "tickets.db", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            try:
                self._model = SentenceTransformer(self._model_name, local_files_only=True)
            except Exception:  # noqa: BLE001 -- not cached yet: download once
                self._model = SentenceTransformer(self._model_name)

    def _rows(self, ids: list[str]) -> list[dict]:
        marks = ",".join("?" * len(ids))
        out = []
        for r in self._db.execute(f"SELECT {_ROW_COLUMNS} FROM tickets WHERE ticket_id IN ({marks})", ids):
            row = dict(r)
            for col in ("topics", "exit_codes", "docker_versions"):
                row[col] = json.loads(row[col] or "[]")
            row["errors_clean"] = json.loads(row.pop("errors_clean") or "[]")
            out.append(row)
        return out

    def search(self, query: str, top_k: int = 5, *, topics: list[str] | None = None, kind: str | None = None,
               min_trust: str = "medium", exit_codes: list[str] | None = None,
               exclude_ids: set[str] = frozenset()) -> list[TicketHit]:
        self._ensure()
        q_emb = self._model.encode([BGE_QUERY_INSTRUCTION + query]).tolist()
        vector_ranked = self._collection.query(query_embeddings=q_emb, n_results=self._pool)["ids"][0]
        lexical_ranked = bm25_top(self._bm25, self._ids, query, self._pool)
        fused = rrf_fuse([vector_ranked, lexical_ranked])
        rows = self._rows(list(fused))
        codes = query_exit_codes(query) | set(exit_codes or [])
        ranked = rank_tickets(rows, fused, query, top_k, topics=set(topics or []), kind=kind, min_trust=min_trust,
                              codes=codes, exclude_ids=set(exclude_ids))
        hits = []
        for row, score, why in ranked:
            via = [name for name, lst in (("vector", vector_ranked), ("bm25", lexical_ranked)) if row["ticket_id"] in lst]
            hits.append(TicketHit(
                ticket_id=row["ticket_id"], title=row["title"], problem_excerpt=(row["problem"] or "")[:400],
                resolution=row["resolution"] or "", score=round(score, 4), url=row["url"], license=row["license"],
                source=row["source"], source_type=row["source_type"], trust_tier=row["trust_tier"],
                trust_score=row["trust_score"] or 0.0, resolution_kind=row["resolution_kind"],
                kind_guess=row["kind_guess"], age_years=row["age_years"], topics=row["topics"],
                error_lines=row["errors_clean"], exit_codes=row["exit_codes"], docker_versions=row["docker_versions"],
                matched=via + why))
        return hits


def render_ticket_card(hit: TicketHit, max_words: int = 180) -> str:
    """Compact, labelled context block for an LLM. Always says it is community-sourced and carries the citation +
    licence (the CC BY-SA sources require attribution). The resolution is cut at a word boundary."""
    words = hit.resolution.split()
    fix = " ".join(words[:max_words]) + (" ..." if len(words) > max_words else "")
    age = f", {hit.age_years:.0f} years old" if hit.age_years is not None else ""
    return (f"[Community ticket - not official documentation | {hit.source}, trust {hit.trust_tier}{age}]\n"
            f"Problem: {hit.title}\n"
            f"Reported fix: {fix}\n"
            f"Source: {hit.url} ({hit.license})")
