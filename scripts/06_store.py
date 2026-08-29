"""
06_store.py -- Build the BM25 and vector indexes over chunks.jsonl.

Two independent stores are built from the same chunk stream:
  - BM25 (rank_bm25.BM25Okapi)   -> data/processed/store/bm25/
  - Vector (Chroma + SentenceTransformers) -> data/processed/store/vector/

They are built and persisted separately on purpose: either one can be swapped out
later (a different sparse index, a different embedding model/vector DB) without
touching the other. No retrieval/query API, hybrid ranking, or reranking here --
this script only builds and persists the two indexes.

Config is read from EMBEDDING_MODEL, VECTOR_DB_PATH, BM25_PATH, EMBEDDING_BATCH_SIZE,
in this order of precedence: real environment variable > .env file (if present) >
the defaults documented in .env.example.

Read-only against data/raw/ and chunks.jsonl. Writes only under data/processed/store/.

Usage:
    python scripts/06_store.py --input data/processed/chunks.jsonl
    python scripts/06_store.py --input data/processed/chunks.jsonl --limit 100
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import re
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "processed" / "chunks.jsonl"

DEFAULTS = {
    "EMBEDDING_MODEL": "BAAI/bge-base-en-v1.5",
    "VECTOR_DB_PATH": "data/processed/store/vector",
    "BM25_PATH": "data/processed/store/bm25",
    "EMBEDDING_BATCH_SIZE": "64",
}

TOKEN_RE = re.compile(r"\w+")


def collection_name_for_model(model_name: str) -> str:
    """Different embedding models produce incompatible, differently-sized vectors, so each
    gets its own Chroma collection in the same store -- switching models never collides
    with or overwrites a previous model's collection."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", model_name).strip("-").lower()
    return f"kb_chunks__{slug}"


# ---------------------------------------------------------------------------
# Config loading: real env > .env file > .env.example-documented defaults
# ---------------------------------------------------------------------------

def load_dotenv_file(path: Path) -> dict:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def get_config() -> dict:
    dotenv_values = load_dotenv_file(PROJECT_ROOT / ".env")
    config = {}
    for key, default in DEFAULTS.items():
        config[key] = os.environ.get(key) or dotenv_values.get(key) or default
    config["EMBEDDING_BATCH_SIZE"] = int(config["EMBEDDING_BATCH_SIZE"])
    return config


# ---------------------------------------------------------------------------
# Chunk loading (tolerant of malformed lines)
# ---------------------------------------------------------------------------

def load_chunks(input_path: Path, limit: int | None) -> tuple[list[dict], list[dict]]:
    valid: list[dict] = []
    errors: list[dict] = []

    with input_path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if limit is not None and len(valid) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append({"line": line_no, "error": f"invalid JSON: {exc}"})
                continue
            if not chunk.get("chunk_id") or not chunk.get("text"):
                errors.append({"line": line_no, "error": "missing chunk_id or text"})
                continue
            valid.append(chunk)

    return valid, errors


def article_id_from_rel_path(rel_path: str) -> str:
    stem = rel_path[:-3] if rel_path.endswith(".md") else rel_path
    return stem.replace("/", "__")


def chunk_metadata(chunk: dict) -> dict:
    """Sanitized for Chroma: all values must be str/int/float/bool, never None or a list."""
    md = chunk.get("metadata") or {}
    return {
        "chunk_id": chunk["chunk_id"],
        "article_id": article_id_from_rel_path(chunk.get("source_path", "")),
        "title": chunk.get("article_title") or "",
        "rel_path": chunk.get("source_path") or "",
        "section": chunk.get("section_title") or "",
        "subsection": chunk.get("subsection_title") or "",
        "heading_path": " > ".join(chunk.get("heading_path") or []),
        "ms_topic": md.get("ms_topic") or "",
    }


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

def build_bm25_index(chunks: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    chunk_ids = [c["chunk_id"] for c in chunks]
    tokenized_corpus = [tokenize(c["text"]) for c in chunks]
    bm25 = BM25Okapi(tokenized_corpus)

    with (out_dir / "bm25_index.pkl").open("wb") as f:
        pickle.dump({"bm25": bm25, "chunk_ids": chunk_ids}, f)

    (out_dir / "chunk_ids.json").write_text(json.dumps(chunk_ids, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------------

def build_vector_store(chunks: list[dict], model_name: str, batch_size: int,
                        vector_db_path: Path) -> tuple[int, list[dict], int]:
    vector_db_path.mkdir(parents=True, exist_ok=True)
    errors: list[dict] = []

    print(f"Loading embedding model: {model_name} ...")
    model = SentenceTransformer(model_name)
    embedding_dim = model.get_sentence_embedding_dimension()

    client = chromadb.PersistentClient(path=str(vector_db_path))
    collection = client.get_or_create_collection(name=collection_name_for_model(model_name))

    embedded = 0
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        texts = [c["text"] for c in batch]
        try:
            embeddings = model.encode(texts, show_progress_bar=False).tolist()
            collection.add(
                ids=[c["chunk_id"] for c in batch],
                embeddings=embeddings,
                documents=texts,
                metadatas=[chunk_metadata(c) for c in batch],
            )
            embedded += len(batch)
        except Exception as exc:  # noqa: BLE001 -- keep the run going past a bad batch
            errors.append({"batch_start": start, "batch_size": len(batch), "error": str(exc)})
            print(f"  [error] batch starting at {start}: {exc}")

        print(f"  embedded {min(start + batch_size, len(chunks))}/{len(chunks)}")

    return embedded, errors, embedding_dim


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BM25 and vector indexes over chunks.jsonl.")
    parser.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT,
                         help=f"chunks.jsonl from 04_chunk.py (default: {DEFAULT_INPUT})")
    parser.add_argument("--limit", "-n", type=int, default=None,
                         help="Only process the first N valid chunks (smoke test)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path: Path = args.input.resolve()
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path} (run 04_chunk.py first)")

    config = get_config()
    vector_db_path = PROJECT_ROOT / config["VECTOR_DB_PATH"]
    bm25_path = PROJECT_ROOT / config["BM25_PATH"]
    store_root = PROJECT_ROOT / "data" / "processed" / "store"
    store_root.mkdir(parents=True, exist_ok=True)

    print(f"Loading chunks from {input_path} (limit={args.limit}) ...")
    chunks, load_errors = load_chunks(input_path, args.limit)
    print(f"Loaded {len(chunks)} valid chunks, {len(load_errors)} malformed/skipped.")

    if not chunks:
        raise SystemExit("No valid chunks to store.")

    print("Building BM25 index ...")
    build_bm25_index(chunks, bm25_path)

    print("Building vector store ...")
    embedded_count, embed_errors, embedding_dim = build_vector_store(
        chunks, config["EMBEDDING_MODEL"], config["EMBEDDING_BATCH_SIZE"], vector_db_path
    )

    all_errors = load_errors + embed_errors
    status = "success" if not all_errors else ("partial" if embedded_count > 0 else "failed")

    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_path),
        "limit_applied": args.limit,
        "chunk_count": len(chunks),
        "chunks_embedded": embedded_count,
        "embedding_model": config["EMBEDDING_MODEL"],
        "embedding_dimension": embedding_dim,
        "embedding_batch_size": config["EMBEDDING_BATCH_SIZE"],
        "vector_db_path": str(vector_db_path),
        "vector_collection": collection_name_for_model(config["EMBEDDING_MODEL"]),
        "bm25_path": str(bm25_path),
        "errors": all_errors,
        "status": status,
    }
    manifest_path = store_root / "store_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print()
    print("=== Store summary ===")
    print(f"Chunks loaded      : {len(chunks)}")
    print(f"Chunks embedded    : {embedded_count}")
    print(f"Malformed skipped  : {len(load_errors)}")
    print(f"Embedding errors   : {len(embed_errors)}")
    print(f"Embedding model    : {config['EMBEDDING_MODEL']} (dim={embedding_dim})")
    print(f"BM25 index         : {bm25_path}")
    print(f"Vector store       : {vector_db_path}")
    print(f"Status             : {status}")
    print(f"Manifest written to: {manifest_path}")


if __name__ == "__main__":
    main()
