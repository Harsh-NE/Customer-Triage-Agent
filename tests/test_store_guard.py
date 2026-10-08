"""06_store.py must not build new chunks over an existing collection (Chroma add() skips existing ids)."""

import importlib.util
import sys
from pathlib import Path

import chromadb
import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("store06", ROOT / "scripts" / "06_store.py")
S = importlib.util.module_from_spec(_spec)
sys.modules["store06"] = S
_spec.loader.exec_module(S)

MODEL = "BAAI/bge-base-en-v1.5"


def _seed(path, n=2):
    col = chromadb.PersistentClient(path=str(path)).get_or_create_collection(S.collection_name_for_model(MODEL))
    col.add(ids=[f"old{i}" for i in range(n)], embeddings=[[0.1, 0.2]] * n, documents=["old"] * n)


def test_missing_store_is_fine(tmp_path):
    S.prepare_collection_for_build(MODEL, tmp_path / "nope", rebuild=False)


def test_existing_collection_is_refused_without_rebuild(tmp_path):
    _seed(tmp_path)
    with pytest.raises(SystemExit, match="--rebuild"):
        S.prepare_collection_for_build(MODEL, tmp_path, rebuild=False)
    assert chromadb.PersistentClient(path=str(tmp_path)).get_collection(S.collection_name_for_model(MODEL)).count() == 2


def test_rebuild_drops_the_old_collection(tmp_path):
    _seed(tmp_path)
    S.prepare_collection_for_build(MODEL, tmp_path, rebuild=True)
    client = chromadb.PersistentClient(path=str(tmp_path))
    assert S.collection_name_for_model(MODEL) not in [c.name for c in client.list_collections()]


def test_bm25_text_includes_the_heading_path():
    chunk = {"chunk_id": "c", "text": "failed to register layer", "heading_path": ["Troubleshooting", "`docker pull` errors"]}
    tokens = S.tokenize(S.bm25_text(chunk))
    assert "pull" in tokens and "troubleshooting" in tokens and "layer" in tokens
    assert S.bm25_text({"chunk_id": "c", "text": "x"}).strip() == "x"            # no heading_path: still works
