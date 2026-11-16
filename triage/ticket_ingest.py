"""
ticket_ingest.py -- add the approved write-back candidates to the historical ticket dataset. A batch job, safe to re-run.

    python -m triage.ticket_ingest ingest [--dry-run] [--due]     add approved candidates (--due: only if a batch is ready)
    python -m triage.ticket_ingest purge --yes                    remove everything written back (back to the original dataset)
    python -m triage.ticket_ingest status

New tickets are prepared by the SAME functions that built the original store (scripts/10_tickets.py), so they look exactly like the old ones.
One run does, in this order (every step can be repeated without harm, so a crash half way is fixed by running again):
  1. embed the new tickets and drop near-duplicates of existing tickets or of each other (rejected, with the reason);
  2. add the vectors to Chroma (upsert) and the rows to SQLite (replace);
  3. rebuild the keyword (BM25) index from SQLite, because that index cannot be appended to (the old one is kept as bm25_index.pkl.prev);
  4. write the manifest last: it carries a version number, and a running retriever reloads when the manifest changes;
  5. mark the candidates `ingested` with that version.
Written-back tickets are recognisable (id starts with "W-", source "triage/resolved"), which is what `purge` relies on.
A lock file stops two runs from overlapping.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import sys
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from triage import config, writeback

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
NEAR_DUPLICATE = 0.06        # squared distance under which two embeddings say the same thing (cosine similarity about 0.97)
JSON_COLUMNS = ("trust_reasons", "topics", "tags", "docker_versions", "error_strings", "exit_codes")
PREFIX = "W-"


def load_script(filename: str):
    """The pipeline scripts start with a digit, so they cannot be imported by name."""
    spec = importlib.util.spec_from_file_location("pipeline_" + filename[:2], SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def lock(root: Path):
    """One ingest at a time. The lock file is removed even if the run fails."""
    path = root / "writeback.lock"
    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL))
    except FileExistsError:
        raise SystemExit(f"another ingest is running (or crashed: delete {path})") from None
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def to_row(c: dict) -> dict:
    """The ticket-store row for a candidate (the columns scripts/10_tickets.py writes)."""
    spec = writeback.KINDS[c["kind"]]
    return {"ticket_id": c["id"], "source_id": c["id"], "source": "triage/resolved", "source_type": spec["source_type"],
            "trust_tier": spec["trust_tier"], "trust_score": spec["trust_score"], "trust_reasons": [f"base {c['kind']}"],
            "is_synthetic": False, "overlaps_kb": False, "license": "internal", "url": c["url"], "created_at": c["created_at"][:10], "age_years": 0.0,
            "title": c["title"], "problem": c["problem"], "resolution": c["resolution"], "resolution_kind": c["kind"],
            "kind_guess": "troubleshooting", "topics": c["topics"], "tags": [], "docker_versions": c["docker_versions"],
            "error_strings": c["error_strings"], "exit_codes": [str(x) for x in c["exit_codes"]],
            "has_code": "`" in c["resolution"] or bool(re.search(r"(?m)^\s*\$ ", c["resolution"])),
            "problem_words": float(len(c["problem"].split())), "resolution_words": float(len(c["resolution"].split()))}


def encode(column: str, value):
    """A value as the docstore holds it: lists as JSON text, booleans as 0/1."""
    if column in JSON_COLUMNS or column == "errors_clean":
        return json.dumps(value)
    return int(value) if isinstance(value, bool) else value


def insert_rows(db_path: Path, rows: list[dict], prepared: list[dict]) -> None:
    """INSERT OR REPLACE into the docstore. Columns the table has and we do not know stay empty."""
    with closing(sqlite3.connect(db_path)) as db, db:
        columns = [r[1] for r in db.execute("PRAGMA table_info(tickets)")]
        for row, prep in zip(rows, prepared):
            values = {**row, "indexed": 1, "exclude_reason": "", "errors_clean": prep["errors"], "embed_text": prep["embed_text"]}
            db.execute(f"INSERT OR REPLACE INTO tickets ({','.join(columns)}) VALUES ({','.join('?' * len(columns))})",
                       [encode(c, values.get(c)) for c in columns])


def rebuild_bm25(root: Path, tickets_mod) -> int:
    """Rebuild the keyword index from the docstore (every indexed ticket, written back or not). The previous index is kept as .prev."""
    with closing(sqlite3.connect(root / "tickets.db")) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT ticket_id, source, title, problem, tags, errors_clean FROM tickets WHERE indexed=1 ORDER BY rowid").fetchall()
    ids = [r["ticket_id"] for r in rows]
    texts = [tickets_mod.build_bm25_text({**dict(r), "tags": json.loads(r["tags"] or "[]")}, json.loads(r["errors_clean"] or "[]")) for r in rows]
    fresh = root / "bm25.new"
    tickets_mod.build_bm25(ids, texts, fresh)
    live = root / "bm25"
    if (live / "bm25_index.pkl").exists():
        shutil.copy2(live / "bm25_index.pkl", live / "bm25_index.pkl.prev")
    for name in ("bm25_index.pkl", "ticket_ids.json"):
        os.replace(fresh / name, live / name)
    fresh.rmdir()
    return len(ids)


def update_manifest(root: Path, indexed: int, vectors: int, added: int, version: int) -> None:
    path = root / "tickets_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update({"tickets_indexed": indexed, "vectors_stored": vectors, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                     "writeback": {"version": version, "tickets_added": added, "last_ingest_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}})
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def current_version(root: Path) -> int:
    manifest = json.loads((root / "tickets_manifest.json").read_text(encoding="utf-8"))
    return int(manifest.get("writeback", {}).get("version", 0))


def added_count(root: Path) -> int:
    with closing(sqlite3.connect(root / "tickets.db")) as db:
        return db.execute("SELECT COUNT(*) FROM tickets WHERE ticket_id LIKE ?", (PREFIX + "%",)).fetchone()[0]


def find_near_duplicates(collection, ids: list[str], vectors: list[list[float]]) -> dict[str, str]:
    """{candidate id: what it duplicates}: the nearest existing ticket, or an earlier candidate in the same batch."""
    found: dict[str, str] = {}
    nearest = collection.query(query_embeddings=vectors, n_results=1)
    for cid, near_ids, dists in zip(ids, nearest["ids"], nearest["distances"]):
        if near_ids and near_ids[0] != cid and dists[0] <= NEAR_DUPLICATE:
            found[cid] = near_ids[0]
    for i, vec in enumerate(vectors):
        for j in range(i):
            if ids[j] not in found and sum((a - b) ** 2 for a, b in zip(vec, vectors[j])) <= NEAR_DUPLICATE:
                found.setdefault(ids[i], ids[j])
    return found


def ingest(root: Path | None = None, queue: writeback.Queue | None = None, model=None, counter=None, hard_split=None, dry_run: bool = False,
           due_only: bool = False) -> dict:
    """Add the approved candidates. `model`, `counter` and `hard_split` are loaded from the real pipeline when not given (tests pass small ones)."""
    root = Path(root or writeback.store_root())
    queue = queue or writeback.Queue(root / "writeback.db")
    approved = queue.rows("approved")
    if not approved or (due_only and not queue.due()):
        return {"ingested": 0, "rejected": 0, "reason": "nothing due" if due_only and approved else "nothing approved", "version": current_version(root)}
    if dry_run:
        return {"would_ingest": [c["id"] for c in approved], "version": current_version(root)}
    with lock(root):
        tickets, chunk = load_script("10_tickets.py"), load_script("04_chunk.py")
        manifest = json.loads((root / "tickets_manifest.json").read_text(encoding="utf-8"))
        if model is None:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(manifest["embedding_model"], local_files_only=True)
        counter = counter or chunk.load_token_counter(manifest["embedding_model"])
        hard_split = hard_split or chunk.hard_split
        rows = [to_row(c) for c in approved]
        prepared = []
        for row in rows:
            errors = tickets.clean_errors(row["error_strings"])
            prepared.append({"errors": errors, "embed_text": tickets.build_embed_text(row, errors, counter, hard_split, manifest["max_tokens"])})
        vectors = model.encode([p["embed_text"] for p in prepared]).tolist()

        import chromadb
        collection = chromadb.PersistentClient(path=str(root / "vector")).get_collection(manifest["collection"])
        duplicates = find_near_duplicates(collection, [r["ticket_id"] for r in rows], vectors)
        for cid, other in duplicates.items():
            queue.set_status(cid, "rejected", f"near-duplicate of {other}")
        keep = [i for i, r in enumerate(rows) if r["ticket_id"] not in duplicates]
        if keep:
            kept_rows = [rows[i] for i in keep]
            kept_prep = [prepared[i] for i in keep]
            collection.upsert(ids=[r["ticket_id"] for r in kept_rows], embeddings=[vectors[i] for i in keep],
                              documents=[p["embed_text"] for p in kept_prep],
                              metadatas=[tickets.vector_metadata(r, p["errors"], manifest["topics"]) for r, p in zip(kept_rows, kept_prep)])
            insert_rows(root / "tickets.db", kept_rows, kept_prep)
            indexed = rebuild_bm25(root, tickets)
            version = current_version(root) + 1
            update_manifest(root, indexed, collection.count(), added_count(root), version)
            for r in kept_rows:
                queue.set_status(r["ticket_id"], "ingested", version=version)
        else:
            version = current_version(root)
        return {"ingested": len(keep), "rejected": len(duplicates), "duplicates": duplicates, "version": version}


def purge(root: Path | None = None, queue: writeback.Queue | None = None) -> dict:
    """Remove every written-back ticket (vectors, rows, keyword index) and put its candidates back to `approved`. The original dataset is what remains."""
    root = Path(root or writeback.store_root())
    queue = queue or writeback.Queue(root / "writeback.db")
    with lock(root):
        manifest = json.loads((root / "tickets_manifest.json").read_text(encoding="utf-8"))
        import chromadb
        collection = chromadb.PersistentClient(path=str(root / "vector")).get_collection(manifest["collection"])
        with closing(sqlite3.connect(root / "tickets.db")) as db, db:
            ids = [r[0] for r in db.execute("SELECT ticket_id FROM tickets WHERE ticket_id LIKE ?", (PREFIX + "%",))]
            db.execute("DELETE FROM tickets WHERE ticket_id LIKE ?", (PREFIX + "%",))
        if ids:
            collection.delete(ids=ids)
        indexed = rebuild_bm25(root, load_script("10_tickets.py"))
        update_manifest(root, indexed, collection.count(), 0, 0)
        for row in queue.rows("ingested"):
            queue.set_status(row["id"], "approved")
        return {"removed": len(ids), "tickets_indexed": indexed}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Add approved resolved cases to the historical ticket dataset.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("ingest")
    run.add_argument("--dry-run", action="store_true", help="list what would be added; change nothing")
    run.add_argument("--due", action="store_true", help=f"only when {writeback.DUE_BATCH} are approved or the oldest has waited {writeback.DUE_HOURS} h")
    pg = sub.add_parser("purge")
    pg.add_argument("--yes", action="store_true", help="required: this removes every written-back ticket")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    root = writeback.store_root()
    if args.cmd == "ingest":
        print(json.dumps(ingest(root, dry_run=args.dry_run, due_only=args.due), indent=1))
    elif args.cmd == "purge":
        if not args.yes:
            raise SystemExit("purge removes every written-back ticket; run again with --yes")
        print(json.dumps(purge(root), indent=1))
    else:
        print(json.dumps({"dataset_version": current_version(root), "written_back_tickets": added_count(root), **writeback.Queue(root / "writeback.db").counts()}, indent=1))


if __name__ == "__main__":
    main()
