"""triage/ticket_ingest.py on a small REAL store built in a temp folder (Chroma + SQLite with the real columns + BM25 + manifest) and a fake embedder.
The real 13,092-ticket store is never touched."""

import json
import re
import sqlite3
from contextlib import closing

import chromadb
import numpy as np
import pytest

from triage import ticket_ingest as T
from triage import writeback as W
from triage.hybrid import TicketRetriever

COLLECTION = "tickets__fake"
COLUMNS = ["ticket_id", "source_id", "source", "source_type", "trust_tier", "trust_score", "trust_reasons", "is_synthetic", "overlaps_kb", "license",
           "url", "created_at", "age_years", "title", "problem", "resolution", "resolution_kind", "problem_score", "resolution_score", "kind_guess",
           "topics", "tags", "docker_versions", "error_strings", "exit_codes", "has_code", "problem_words", "resolution_words", "indexed",
           "exclude_reason", "errors_clean", "embed_text"]
SQL_TYPES = {**dict.fromkeys(["trust_score", "age_years", "problem_score", "resolution_score", "problem_words", "resolution_words"], "REAL"),
             **dict.fromkeys(["is_synthetic", "overlaps_kb", "has_code", "indexed"], "INTEGER")}          # as in the real store
OLD = [("T-old1", "container exits with code 137 out of memory", "My container is killed with exit code 137 when the build runs", "Raise the memory limit in Docker Desktop resources."),
       ("T-old2", "bind mount permission denied on linux volume", "Permission denied when a bind mounted folder is written from the container", "Fix the owner of the host folder with chown.")]
PROBLEM = "docker pull keeps failing on my laptop with a toomanyrequests error after a few pulls in the same hour"
FIX = ("Sign in with docker login so pulls count against your account limit, then retry the pull. "
       "If you share an office network, wait for the hourly window to reset or use a registry mirror.")


class HashModel:
    """Bag-of-words hashing into 64 dimensions, normalised: the same words give the same vector, different words give far-apart vectors."""

    def encode(self, texts):
        out = np.zeros((len(texts), 64))
        for i, text in enumerate(texts):
            for word in set(re.findall(r"[a-z0-9]+", text.lower())):
                out[i, hash(word) % 64] += 1.0
            out[i] /= max(np.linalg.norm(out[i]), 1e-9)
        return out


class Counter:
    def count(self, text):
        return len(text.split())


def hard_split(text, counter, n):
    return [" ".join(text.split()[:n])]


def candidate(title="docker pull rate limit error", problem=PROBLEM, fix=FIX, kind="customer_confirmed", **kw):
    return W.make_candidate(kind, title, problem, fix, **kw)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "evaluation_questions", lambda: [])
    root = tmp_path / "tickets"
    (root / "bm25").mkdir(parents=True)
    tickets = T.load_script("10_tickets.py")
    model = HashModel()
    with closing(sqlite3.connect(root / "tickets.db")) as db, db:
        db.execute(f"CREATE TABLE tickets ({', '.join(f'{c} {SQL_TYPES.get(c, 'TEXT')}' for c in COLUMNS)})")
        for tid, title, problem, resolution in OLD:
            row = {"ticket_id": tid, "source": "stackoverflow", "title": title, "problem": problem, "resolution": resolution, "tags": "[]", "errors_clean": "[]",
                   "indexed": 1, "trust_tier": "high", "resolution_kind": "accepted_answer", "topics": "[]", "exit_codes": "[]", "error_strings": "[]"}
            db.execute(f"INSERT INTO tickets ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})", [row.get(c) for c in COLUMNS])
    collection = chromadb.PersistentClient(path=str(root / "vector")).create_collection(COLLECTION, configuration={"hnsw": {"space": "l2"}})
    texts = [f"{t[1]}\n\n{t[2]}" for t in OLD]
    collection.add(ids=[t[0] for t in OLD], embeddings=model.encode(texts).tolist(), documents=texts)
    tickets.build_bm25([t[0] for t in OLD], texts, root / "bm25")
    (root / "tickets_manifest.json").write_text(json.dumps({"embedding_model": "fake", "max_tokens": 256, "collection": COLLECTION, "topics": ["registry", "build"],
                                                           "tickets_indexed": 2, "vectors_stored": 2}), encoding="utf-8")
    queue = W.Queue(root / "writeback.db")
    return root, queue, model


def run(store, **kw):
    root, queue, model = store
    return T.ingest(root, queue, model=model, counter=Counter(), hard_split=hard_split, **kw)


def rows(root, where="1=1"):
    with closing(sqlite3.connect(root / "tickets.db")) as db:
        db.row_factory = sqlite3.Row
        return db.execute(f"SELECT * FROM tickets WHERE {where}").fetchall()


# ---------------- a normal ingest ----------------
def test_an_approved_candidate_lands_in_all_three_indexes_and_the_manifest(store):
    root, queue, _ = store
    queue.add(candidate(error_strings=["toomanyrequests: You have reached your pull rate limit"], topics=["registry"]))
    result = run(store)
    assert result["ingested"] == 1 and result["version"] == 1
    new = rows(root, "ticket_id LIKE 'W-%'")
    assert len(new) == 1 and new[0]["indexed"] == 1 and new[0]["source"] == "triage/resolved" and new[0]["resolution_kind"] == "customer_confirmed"
    assert new[0]["trust_tier"] == "medium" and json.loads(new[0]["topics"]) == ["registry"] and new[0]["embed_text"].startswith("docker pull rate limit error")
    assert chromadb.PersistentClient(path=str(root / "vector")).get_collection(COLLECTION).count() == 3
    manifest = json.loads((root / "tickets_manifest.json").read_text())
    assert manifest["tickets_indexed"] == 3 and manifest["vectors_stored"] == 3 and manifest["writeback"]["version"] == 1 and manifest["writeback"]["tickets_added"] == 1
    assert (root / "bm25" / "bm25_index.pkl.prev").exists()
    assert queue.rows("ingested")[0]["version"] == 1


def test_the_old_tickets_are_untouched(store):
    root, queue, _ = store
    queue.add(candidate())
    run(store)
    assert [r["ticket_id"] for r in rows(root, "ticket_id LIKE 'T-%'")] == ["T-old1", "T-old2"]


def test_the_retriever_finds_the_new_ticket_by_meaning_and_by_exact_words(store):
    root, queue, model = store
    queue.add(candidate(error_strings=["toomanyrequests: You have reached your pull rate limit"]))
    run(store)
    hits = TicketRetriever(store_root=str(root), model_name="fake", model=model).search("docker pull toomanyrequests rate limit", top_k=3, min_trust="low")
    assert hits[0].ticket_id.startswith("W-") and hits[0].resolution_kind == "customer_confirmed" and "docker login" in hits[0].resolution


def test_running_again_with_nothing_new_changes_nothing(store):
    root, queue, _ = store
    queue.add(candidate())
    run(store)
    again = run(store)
    assert again["ingested"] == 0 and again["version"] == 1 and len(rows(root)) == 3


def test_a_second_batch_gets_the_next_version(store):
    root, queue, _ = store
    queue.add(candidate())
    run(store)
    queue.add(candidate(title="bind mount permission error on windows", problem="writing to a bind mounted folder from the container fails with permission errors "
                                                                           "on windows", fix="Share the drive in Docker Desktop settings and restart Docker Desktop, then "
                                                                                              "check the folder permissions again for the container user account."))
    assert run(store)["version"] == 2 and len(rows(root, "ticket_id LIKE 'W-%'")) == 2


# ---------------- safety ----------------
def test_a_near_duplicate_of_an_existing_ticket_is_rejected_with_the_reason(store):
    root, queue, _ = store
    queue.add(candidate(title=OLD[0][1], problem=OLD[0][2], fix="Raise the memory limit in Docker Desktop resources to at least four gigabytes and restart the engine."))
    result = run(store)
    assert result["ingested"] == 0 and result["rejected"] == 1
    assert "near-duplicate of T-old1" in queue.rows("rejected")[0]["reason"] and rows(root, "ticket_id LIKE 'W-%'") == []


def test_two_near_identical_candidates_in_one_batch_add_only_one(store):
    root, queue, _ = store
    queue.add(candidate())
    queue.add(candidate(fix=FIX + " Then confirm that the pull works again after logging in to the registry."))
    assert run(store)["ingested"] == 1 and len(rows(root, "ticket_id LIKE 'W-%'")) == 1


def test_dry_run_changes_nothing(store):
    root, queue, _ = store
    queue.add(candidate())
    assert run(store, dry_run=True)["would_ingest"] == [candidate()["id"]]
    assert rows(root, "ticket_id LIKE 'W-%'") == [] and queue.counts()["approved"] == 1


def test_due_only_waits_for_a_batch_or_a_day(store):
    queue = store[1]
    queue.add(candidate())
    assert run(store, due_only=True)["ingested"] == 0 and queue.counts()["approved"] == 1


def test_a_running_ingest_blocks_another(store):
    root, queue, _ = store
    queue.add(candidate())
    (root / "writeback.lock").write_text("")
    with pytest.raises(SystemExit):
        run(store)
    assert queue.counts()["approved"] == 1


def test_the_lock_is_released_after_a_failure(store):
    root, queue, _ = store
    queue.add(candidate())
    with pytest.raises(AttributeError):
        T.ingest(root, queue, model=object(), counter=Counter(), hard_split=hard_split)       # a model without encode()
    assert not (root / "writeback.lock").exists()


def test_a_crash_after_the_vectors_were_added_is_repaired_by_running_again(store):
    root, queue, model = store
    c = candidate()
    queue.add(c)
    chromadb.PersistentClient(path=str(root / "vector")).get_collection(COLLECTION).add(ids=[c["id"]], embeddings=model.encode([c["title"]]).tolist())
    result = run(store)
    assert result["ingested"] == 1 and len(rows(root, "ticket_id LIKE 'W-%'")) == 1
    assert chromadb.PersistentClient(path=str(root / "vector")).get_collection(COLLECTION).count() == 3


# ---------------- purge ----------------
def test_purge_returns_to_the_original_dataset_and_ingest_can_be_repeated(store):
    root, queue, _ = store
    queue.add(candidate())
    run(store)
    result = T.purge(root, queue)
    assert result == {"removed": 1, "tickets_indexed": 2}
    assert [r["ticket_id"] for r in rows(root)] == ["T-old1", "T-old2"]
    assert chromadb.PersistentClient(path=str(root / "vector")).get_collection(COLLECTION).count() == 2
    manifest = json.loads((root / "tickets_manifest.json").read_text())
    assert manifest["writeback"]["version"] == 0 and manifest["tickets_indexed"] == 2
    assert queue.counts()["approved"] == 1 and queue.counts()["ingested"] == 0
    assert run(store)["ingested"] == 1                                    # the same candidate goes back in


# ---------------- helpers ----------------
def test_to_row_marks_the_origin_and_stores_exit_codes_as_text():
    row = T.to_row({**candidate(exit_codes=[137], error_strings=["x"]), "created_at": "2026-11-15T10:00:00+00:00"})
    assert row["ticket_id"].startswith("W-") and row["license"] == "internal" and row["exit_codes"] == ["137"] and row["age_years"] == 0.0 and row["created_at"] == "2026-11-15"


def test_encode_stores_lists_as_json_and_booleans_as_numbers():
    assert T.encode("topics", ["a"]) == '["a"]' and T.encode("has_code", True) == 1 and T.encode("title", "x") == "x" and T.encode("age_years", None) is None


# ---------------- a running retriever notices an ingest ----------------
def test_a_retriever_that_is_already_running_sees_tickets_written_back_afterwards(store):
    root, queue, model = store
    retriever = TicketRetriever(store_root=str(root), model_name="fake", model=model)
    assert not any(h.ticket_id.startswith("W-") for h in retriever.search("docker pull toomanyrequests rate limit", top_k=5, min_trust="low"))
    queue.add(candidate(error_strings=["toomanyrequests: You have reached your pull rate limit"]))
    run(store)
    hits = retriever.search("docker pull toomanyrequests rate limit", top_k=5, min_trust="low")           # the same object, no restart
    assert any(h.ticket_id.startswith("W-") for h in hits)


def test_the_new_kinds_have_a_rank_weight():
    from triage.hybrid import RESOLUTION_KIND_WEIGHT
    assert RESOLUTION_KIND_WEIGHT["customer_confirmed"] == 0.9 and RESOLUTION_KIND_WEIGHT["engineer_resolved"] == 1.0
