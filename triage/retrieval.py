"""
retrieval.py -- the Retrieval interface (Phase 0 contract) plus two stand-ins for Member A.

THE CONTRACT (Member B's retrieve.py must satisfy this to drop in unchanged):

    class Retriever(Protocol):
        def search(self, query: str, top_k: int = 8) -> list[Candidate]

  * returns chunk-level Candidates, best first: the top_k hits, optionally followed by SIBLING
    chunks of the same issue (so a small matching chunk arrives with its error-message chunk --
    "index small, return whole"). The Clarifier reads error text from siblings.
  * Candidate.score is normalised so that HIGHER IS BETTER and lies in (0, 1]
  * Candidate.metadata should carry: product_area, component, doc_kind, tags, error_signals
    (the fields scripts/05_metadata.py writes), and heading_path as the list on Candidate

Provided here, so the Clarifier is buildable and testable without waiting for B2:
  MockRetriever   in-memory keyword scorer over a tiny corpus -- tests / CI / offline eval
  ChromaRetriever vector-only search over the REAL Docker store -- live smoke tests and the
                  first offline eval baseline. NOT hybrid: no BM25, no rerank. B2's hybrid
                  retriever replaces it behind the same interface.
"""

from __future__ import annotations

import math
import re
from typing import Protocol

from triage import config
from triage.state import Candidate

_TOKEN = re.compile(r"\w+")
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class Retriever(Protocol):
    def search(self, query: str, top_k: int = 8) -> list[Candidate]: ...


class MockRetriever:
    """IDF-weighted query-term coverage over `corpus` (a list of dicts with chunk_id, text,
    source_path, article_title, heading_path, metadata). Deterministic and dependency-free."""

    def __init__(self, corpus: list[dict]) -> None:
        self._corpus = corpus
        self._tokens = [set(_TOKEN.findall((d["text"] + " " + " ".join(d.get("heading_path", []))).lower()))
                        for d in corpus]
        n = len(corpus)
        df: dict[str, int] = {}
        for toks in self._tokens:
            for t in toks:
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log((n + 1) / (c + 0.5)) + 1 for t, c in df.items()}
        self.queries: list[str] = []          # every query received, for assertions in tests

    def search(self, query: str, top_k: int = 8) -> list[Candidate]:
        self.queries.append(query)
        q = set(_TOKEN.findall(query.lower())) & set(self._idf)
        if not q:
            return []
        total = sum(self._idf[t] for t in q)
        scored = []
        for doc, toks in zip(self._corpus, self._tokens):
            covered = sum(self._idf[t] for t in q if t in toks)
            if covered:
                scored.append((covered / total, doc))
        scored.sort(key=lambda x: -x[0])
        return [Candidate(chunk_id=d["chunk_id"], text=d["text"], score=max(s, 1e-6),
                          source_path=d.get("source_path", ""), article_title=d.get("article_title", ""),
                          heading_path=list(d.get("heading_path", [])), metadata=dict(d.get("metadata", {})))
                for s, d in scored[:top_k]]


class ChromaRetriever:
    """Vector-only search over the Docker Chroma store built by scripts/06_store.py.
    Heavy imports and the embedding model load lazily on the first search.

    expand_siblings ("index small, return whole", as in scripts/07_retrieve.py): a vector hit is
    one small chunk, but the error message that distinguishes an issue usually sits in a SIBLING
    chunk of the same issue. Siblings of the SAME issue are appended at 0.9x the hit's score so
    the Clarifier can read them. They never outrank their hit, and release-notes/archive pages
    (hundreds of near-identical sections) are not expanded."""

    SIBLING_CAP = 8
    NO_EXPAND = {"release_notes", "archive"}

    def __init__(self, vector_db_path: str | None = None, model_name: str | None = None,
                 expand_siblings: bool = True, model=None) -> None:
        env = config.get_env()
        self._path = vector_db_path or str(config.PROJECT_ROOT / env["VECTOR_DB_PATH"])
        self._model_name = model_name or env["EMBEDDING_MODEL"]
        self._expand = expand_siblings
        self._model = model            # a SentenceTransformer shared with other retrievers, to load the model once
        self._collection = None

    def _ensure(self) -> None:
        if self._collection is not None:
            return
        import chromadb
        from sentence_transformers import SentenceTransformer
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", self._model_name).strip("-").lower()
        self._collection = chromadb.PersistentClient(path=self._path).get_collection(f"kb_chunks__{slug}")
        if self._model is None:
            try:   # prefer the local cache: no network round-trip, and a flaky connection can't fail a run
                self._model = SentenceTransformer(self._model_name, local_files_only=True)
            except Exception:  # noqa: BLE001 -- not cached yet: download once
                self._model = SentenceTransformer(self._model_name)

    @staticmethod
    def _to_candidate(cid: str, doc: str, meta: dict, score: float) -> Candidate:
        return Candidate(
            chunk_id=cid, text=doc, score=score,
            source_path=meta.get("rel_path", ""), article_title=meta.get("title", ""),
            heading_path=[p for p in meta.get("heading_path", "").split(" > ") if p],
            metadata=dict(meta))

    def search(self, query: str, top_k: int = 8) -> list[Candidate]:
        self._ensure()
        emb = self._model.encode([BGE_QUERY_INSTRUCTION + query]).tolist()
        res = self._collection.query(query_embeddings=emb, n_results=top_k)
        hits = [self._to_candidate(cid, doc, meta, 1.0 / (1.0 + float(dist)))
                for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0],
                                                res["metadatas"][0], res["distances"][0])]
        if not self._expand:
            return hits
        return sorted(hits + self._siblings(hits), key=lambda c: -c.score)

    def _siblings(self, hits: list[Candidate]) -> list[Candidate]:
        from triage.issues import issue_key
        seen_ids = {h.chunk_id for h in hits}
        done_groups: set[tuple[str, str]] = set()
        extra: list[Candidate] = []
        for hit in hits:
            group = (hit.source_path, str(hit.metadata.get("section", "")))
            if group in done_groups or hit.metadata.get("doc_kind") in self.NO_EXPAND:
                continue
            done_groups.add(group)
            got = self._collection.get(
                where={"$and": [{"rel_path": group[0]}, {"section": group[1]}]},
                include=["documents", "metadatas"])
            added = 0
            for cid, doc, meta in sorted(zip(got["ids"], got["documents"], got["metadatas"]), key=lambda t: t[0]):
                if cid in seen_ids or added >= self.SIBLING_CAP:
                    continue
                sibling = self._to_candidate(cid, doc, meta, hit.score * 0.9)
                if issue_key(sibling) == issue_key(hit):    # same ISSUE, not merely the same section
                    extra.append(sibling)
                    seen_ids.add(cid)
                    added += 1
        return extra
