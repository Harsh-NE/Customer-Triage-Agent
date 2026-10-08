"""
10_tickets.py -- Prepare, embed and store the Tier-2 historical tickets (one script, start to finish).

Reads   data/raw/tickets/docker_tickets_v5_fixed.csv   (13,899 resolved Docker problems, 28 columns)
Writes  data/processed/docker/store/tickets/
            vector/        Chroma collection  tickets__<model>      (symptom text embedded, flat filter metadata)
            bm25/          bm25_index.pkl + ticket_ids.json         (title + errors + FULL problem + tags)
            tickets.db     SQLite docstore, one row per ticket      (the source of truth: full row + resolution)
            tickets_manifest.json

Why a separate store from the KB (scripts/06_store.py): different unit (a whole case, not a doc section), different
trust, voice and licences, and 13k ticket vectors would crowd the 11k KB chunks if ranked as peers. Same embedding model,
so one query embedding can search both.

What is embedded: ONE vector per ticket (a ticket is a short problem -> fix case; splitting it would separate the
problem from its fix). The text is   title + cleaned error lines + head of the problem   capped at 256 tokens of the
embedding model's own tokenizer (--max-tokens; the model reads at most 512 and silently drops the rest). The error lines
go first so they survive the cap. Only multi-word, error-looking lines are kept: the CSV's `error_strings` column holds any
quoted span (paths, commands) and ~19% prose fragments cut at apostrophes, which are dropped. The resolution is NOT embedded -- it is stored whole in the docstore and trimmed when context is built.

Not indexed (kept in the docstore, flagged with exclude_reason): is_synthetic rows (LLM-generated Q&A of unknown
quality) and overlaps_kb rows (duplicates of KB FAQ entries). Low-trust tickets ARE indexed; filter them at query time.

Usage:
    python scripts/10_tickets.py --dry-run          # prepare + report only, writes nothing, no embedding (seconds)
    python scripts/10_tickets.py --sample 300 --rebuild  # smoke test the whole path on a random sample, to time it
    python scripts/10_tickets.py --rebuild          # full build (embedding is the slow part)
    python scripts/10_tickets.py --query "container exits with code 137"   # search the built store
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import pickle
import re
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "raw" / "tickets" / "docker_tickets_v5_fixed.csv"

# 256, not the model's 512: measured on a 16-core CPU laptop, 500-token texts embed at ~0.6/s (13k tickets ~ 6 h) but
# 256-token texts at ~3.6/s (~1 h), and the symptom (title, error lines, start of the problem) is in the head anyway.
MAX_TOKENS = 256
HEADER_MAX_TOKENS = 128     # title + error lines may use at most this much of the cap
MAX_ERRORS = 3
MAX_ERROR_CHARS = 160
CHROMA_BATCH = 500
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
TOKEN_RE = re.compile(r"\w+")


def load_script(filename: str):
    """The pipeline scripts start with a digit, so they cannot be imported by name."""
    name = "pipeline_" + filename[:2]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module           # @dataclass looks its own module up in sys.modules
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Step 1: read the CSV
# ---------------------------------------------------------------------------

JSON_LIST_COLUMNS = ("trust_reasons", "topics", "tags", "docker_versions", "error_strings", "exit_codes")
FLOAT_COLUMNS = ("trust_score", "age_years", "problem_score", "resolution_score", "problem_words", "resolution_words")
BOOL_COLUMNS = ("is_synthetic", "overlaps_kb", "has_code")


def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def parse_float(value: str) -> float | None:
    try:
        return float(value) if str(value).strip() != "" else None
    except ValueError:
        return None


def parse_list(value: str) -> list:
    try:
        parsed = json.loads(value) if str(value).strip() else []
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def read_tickets(path: Path, limit: int | None = None) -> list[dict]:
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    rows: list[dict] = []
    with path.open(encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            if limit is not None and len(rows) >= limit:
                break
            row = dict(raw)
            for col in JSON_LIST_COLUMNS:
                row[col] = parse_list(raw.get(col, ""))
            for col in FLOAT_COLUMNS:
                row[col] = parse_float(raw.get(col, ""))
            for col in BOOL_COLUMNS:
                row[col] = parse_bool(raw.get(col, ""))
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Step 2: decide what is indexed
# ---------------------------------------------------------------------------

def exclude_reason(row: dict) -> str:
    if row["is_synthetic"]:
        return "synthetic"                  # LLM-generated Q&A: unknown quality, never a ground-truth source
    if row["overlaps_kb"]:
        return "overlaps_kb"                # the KB already holds this FAQ entry, authoritatively
    if not (row.get("title") or "").strip() or not (row.get("problem") or "").strip():
        return "empty"
    return ""


# ---------------------------------------------------------------------------
# Step 3: clean the extracted error strings (the raw column is noisy: binary junk, bare URLs, fragments)
# ---------------------------------------------------------------------------

ERROR_WORDS = re.compile(
    r"error|fail|cannot|can't|denied|refused|unable|no such|not found|invalid|panic|fatal|exception|timeout|timed out|"
    r"unauthorized|forbidden|conflict|exited|killed|unreachable|permission|not allowed|not supported", re.I)
URL_ONLY = re.compile(r"^(https?://|[\w.-]+:\d+/?)\S*$", re.I)
# The CSV's extractor mis-reads apostrophes ("I've ... doesn't") as quote marks, so ~19% of its "error strings" are prose
# cut between two apostrophes: they start with a contraction tail ("ve got", "t work") or speak in the first person.
CONTRACTION_TAIL = re.compile(r"^(ve|t|s|re|ll|d|m)\s", re.I)
FIRST_PERSON = re.compile(r"(?<![\w/.-])(?:I|I'm|I've|I'd|[Mm]y|[Ww]e|[Oo]ur|[Mm]e)(?![\w/.'-])")


def clean_errors(raw: list) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for item in raw:
        s = " ".join(str(item).split())
        if len(s) < 8 or URL_ONLY.match(s) or "\\x" in s:
            continue
        if sum(ch.isalpha() for ch in s) < 0.4 * len(s):         # mostly symbols/digits: not a message
            continue
        if CONTRACTION_TAIL.match(s) or FIRST_PERSON.search(s):  # prose fragment, not an error message
            continue
        if len(s.split()) < 2 or not ERROR_WORDS.search(s):      # the column holds ANY quoted span (paths, commands,
            continue                                            # values); only multi-word error-looking ones are signal
        if s.lower() in seen:
            continue
        seen.add(s.lower())
        kept.append(s[:MAX_ERROR_CHARS])
    return kept[:MAX_ERRORS]


# ---------------------------------------------------------------------------
# Step 4: build the texts
# ---------------------------------------------------------------------------

def build_embed_text(row: dict, errors: list[str], counter, hard_split, max_tokens: int = MAX_TOKENS) -> str:
    """title + error lines + head of the problem, at most max_tokens. Slices are exact (never decoded from ids)."""
    title = row["title"].strip()
    header = title + "".join(f"\nError: {e}" for e in errors)
    if counter.count(header) > HEADER_MAX_TOKENS:
        header = hard_split(header, counter, HEADER_MAX_TOKENS)[0]
    problem = row["problem"].strip()
    if problem.lower() == title.lower():
        problem = ""                                            # FAQ-style rows repeat the title
    room = max_tokens - counter.count(header) - 2
    if problem and room >= 20:
        body = problem if counter.count(problem) <= room else hard_split(problem, counter, room)[0]
        text = f"{header}\n\n{body}"
    else:
        text = header
    if counter.count(text) > max_tokens:                        # invariant guard (re-tokenising a join can differ)
        text = hard_split(text, counter, max_tokens)[0]
    return text


def build_bm25_text(row: dict, errors: list[str]) -> str:
    """Lexical side has no length limit: use the FULL problem. GitHub labels are workflow state
    (status/needs-more-info), not topics, so only other sources' tags are added."""
    parts = [row["title"], *errors, row["problem"]]
    if not str(row.get("source", "")).startswith("github/"):
        parts.append(" ".join(str(t) for t in row["tags"]))
    return "\n".join(p for p in parts if p)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def topic_flag(topic: str) -> str:
    return "topic_" + re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")


def vector_metadata(row: dict, errors: list[str], all_topics: list[str]) -> dict:
    """Flat scalars only (Chroma cannot filter on lists): one boolean per topic. age_years is -1.0 when unknown."""
    md = {
        "ticket_id": row["ticket_id"],
        "source": row["source"],
        "source_type": row["source_type"],
        "trust_tier": row["trust_tier"],
        "trust_score": row["trust_score"] if row["trust_score"] is not None else 0.0,
        "resolution_kind": row["resolution_kind"],
        "kind_guess": row["kind_guess"],
        "age_years": row["age_years"] if row["age_years"] is not None else -1.0,
        "has_code": row["has_code"],
        "n_errors": len(errors),
        "has_exit_code": bool(row["exit_codes"]),
        "topics": ", ".join(row["topics"]),
        "url": row["url"],
        "license": row["license"],
    }
    for t in all_topics:
        md[topic_flag(t)] = t in row["topics"]
    return md


# ---------------------------------------------------------------------------
# Step 5: stores
# ---------------------------------------------------------------------------

def write_docstore(db_path: Path, rows: list[dict], prepared: dict[str, dict]) -> None:
    """SQLite: one row per ticket (ALL tickets, indexed or not). Lists are stored as JSON text."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    columns = [c for c in rows[0].keys()]
    extra = ["indexed", "exclude_reason", "errors_clean", "embed_text"]
    con = sqlite3.connect(db_path)
    try:
        col_defs = ["ticket_id TEXT PRIMARY KEY"] + [
            f"{c} {'REAL' if c in FLOAT_COLUMNS else 'INTEGER' if c in BOOL_COLUMNS else 'TEXT'}"
            for c in columns if c != "ticket_id"] + ["indexed INTEGER", "exclude_reason TEXT", "errors_clean TEXT", "embed_text TEXT"]
        con.execute(f"CREATE TABLE tickets ({', '.join(col_defs)})")
        placeholders = ",".join("?" * (len(columns) + len(extra)))
        records = []
        for row in rows:
            p = prepared[row["ticket_id"]]
            values = [json.dumps(row[c]) if c in JSON_LIST_COLUMNS else row[c] for c in columns]
            records.append(values + [int(p["indexed"]), p["exclude_reason"], json.dumps(p["errors"]), p["embed_text"]])
        ordered_cols = columns + extra          # explicit names: the table's column order differs from the CSV's
        con.executemany(f"INSERT INTO tickets ({', '.join(ordered_cols)}) VALUES ({placeholders})", records)
        con.execute("CREATE INDEX idx_tickets_indexed ON tickets(indexed)")
        con.commit()
    finally:
        con.close()


def collection_name_for_model(model_name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", model_name).strip("-").lower()
    return f"tickets__{slug}"


def guard_existing_collection(vector_path: Path, model_name: str, rebuild: bool) -> None:
    """Chroma add() skips ids that already exist, so building over an old collection silently keeps stale data."""
    if not vector_path.exists():
        return
    import chromadb
    client = chromadb.PersistentClient(path=str(vector_path))
    name = collection_name_for_model(model_name)
    if name not in [c.name for c in client.list_collections()]:
        return
    existing = client.get_collection(name=name).count()
    if existing and not rebuild:
        raise SystemExit(f"Collection '{name}' already holds {existing} tickets. Re-run with --rebuild to drop it "
                         "and embed from scratch.")
    client.delete_collection(name)
    print(f"Dropped existing collection '{name}' ({existing} tickets).")


def build_bm25(ids: list[str], texts: list[str], out_dir: Path) -> None:
    from rank_bm25 import BM25Okapi
    out_dir.mkdir(parents=True, exist_ok=True)
    bm25 = BM25Okapi([tokenize(t) for t in texts])
    with (out_dir / "bm25_index.pkl").open("wb") as f:
        pickle.dump({"bm25": bm25, "ticket_ids": ids}, f)
    (out_dir / "ticket_ids.json").write_text(json.dumps(ids), encoding="utf-8")


def build_vectors(ids: list[str], texts: list[str], metadatas: list[dict], model_name: str, batch_size: int,
                  vector_path: Path) -> int:
    import chromadb
    from sentence_transformers import SentenceTransformer
    vector_path.mkdir(parents=True, exist_ok=True)
    print(f"Loading embedding model: {model_name} ...")
    model = SentenceTransformer(model_name)
    print(f"Embedding {len(texts)} tickets (batch {batch_size}) ...")
    # One encode call: sentence-transformers sorts by length internally, which cuts padding waste on CPU.
    started = time.time()
    embeddings = model.encode(texts, batch_size=batch_size, show_progress_bar=True).tolist()
    elapsed = time.time() - started
    print(f"Embedded {len(texts)} texts in {elapsed:.0f}s ({len(texts) / max(elapsed, 1e-9):.2f}/s)")
    client = chromadb.PersistentClient(path=str(vector_path))
    collection = client.get_or_create_collection(name=collection_name_for_model(model_name))
    for start in range(0, len(ids), CHROMA_BATCH):
        end = start + CHROMA_BATCH
        collection.add(ids=ids[start:end], embeddings=embeddings[start:end],
                       documents=texts[start:end], metadatas=metadatas[start:end])
    return collection.count()


# ---------------------------------------------------------------------------
# Query (smoke test of the built store; the real retriever is Member B's)
# ---------------------------------------------------------------------------

def search(query: str, store_root: Path, model_name: str, k: int = 5) -> None:
    import chromadb
    from sentence_transformers import SentenceTransformer
    con = sqlite3.connect(store_root / "tickets.db")
    con.row_factory = sqlite3.Row

    def show(label: str, ids: list[str]) -> None:
        print(f"\n--- {label} ---")
        for i, tid in enumerate(ids, 1):
            r = con.execute("SELECT title, source_type, trust_tier, url FROM tickets WHERE ticket_id=?", (tid,)).fetchone()
            print(f"{i}. [{r['trust_tier']}/{r['source_type']}] {r['title'][:90]}\n   {r['url']}")

    model = SentenceTransformer(model_name)
    emb = model.encode([BGE_QUERY_INSTRUCTION + query]).tolist()
    coll = chromadb.PersistentClient(path=str(store_root / "vector")).get_collection(collection_name_for_model(model_name))
    show("vector", coll.query(query_embeddings=emb, n_results=k)["ids"][0])
    with (store_root / "bm25" / "bm25_index.pkl").open("rb") as f:
        data = pickle.load(f)
    scores = data["bm25"].get_scores(tokenize(query))
    top = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
    show("bm25", [data["ticket_ids"][i] for i in top])
    con.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def prepare(rows: list[dict], counter, hard_split, max_tokens: int = MAX_TOKENS) -> dict[str, dict]:
    prepared: dict[str, dict] = {}
    for row in rows:
        reason = exclude_reason(row)
        errors = clean_errors(row["error_strings"])
        prepared[row["ticket_id"]] = {
            "indexed": not reason,
            "exclude_reason": reason,
            "errors": errors,
            "embed_text": "" if reason else build_embed_text(row, errors, counter, hard_split, max_tokens),
        }
    return prepared


def report(rows: list[dict], prepared: dict[str, dict], counter, max_tokens: int = MAX_TOKENS) -> int:
    indexed = [r for r in rows if prepared[r["ticket_id"]]["indexed"]]
    reasons: dict[str, int] = {}
    for r in rows:
        why = prepared[r["ticket_id"]]["exclude_reason"]
        if why:
            reasons[why] = reasons.get(why, 0) + 1
    tokens = sorted(counter.count(prepared[r["ticket_id"]]["embed_text"]) for r in indexed)
    over = sum(t > max_tokens for t in tokens)
    with_err = sum(bool(prepared[r["ticket_id"]]["errors"]) for r in indexed)
    raw_err = sum(bool(r["error_strings"]) for r in indexed)
    print("\n=== Ticket preparation summary ===")
    print(f"Rows read                  : {len(rows)}")
    print(f"Indexed                    : {len(indexed)}")
    print(f"Excluded                   : {reasons or 'none'}")
    if tokens:
        print(f"Embed text tokens          : min={tokens[0]} median={tokens[len(tokens) // 2]} "
              f"p95={tokens[int(len(tokens) * 0.95)]} max={tokens[-1]}")
    print(f"Embed texts over {max_tokens} tokens : {over}")
    print(f"Rows with raw error strings: {raw_err}   with usable cleaned errors: {with_err}")
    print(f"Trust tiers (indexed)      : { {t: sum(r['trust_tier'] == t for r in indexed) for t in ('high', 'medium', 'low')} }")
    return over


def main() -> None:
    p = argparse.ArgumentParser(description="Prepare, embed and store the historical tickets.")
    p.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--limit", "-n", type=int, default=None, help="only the first N rows (smoke test)")
    p.add_argument("--max-tokens", type=int, default=MAX_TOKENS,
                   help=f"cap on each embedded text (default {MAX_TOKENS}; lower = faster embedding, shorter problem head)")
    p.add_argument("--sample", type=int, default=None,
                   help="random N rows (fixed seed) -- representative for timing; --limit takes the CSV head, which is FAQ-heavy")
    p.add_argument("--dry-run", action="store_true", help="prepare and report only; write nothing, no embedding")
    p.add_argument("--rebuild", action="store_true", help="drop the existing tickets collection and rebuild")
    p.add_argument("--query", type=str, default=None, help="search the built store and exit")
    args = p.parse_args()

    store06 = load_script("06_store.py")
    chunk04 = load_script("04_chunk.py")
    config = store06.get_config()
    model_name = config["EMBEDDING_MODEL"]
    store_root = (PROJECT_ROOT / config["VECTOR_DB_PATH"]).parent / "tickets"

    if args.query:
        search(args.query, store_root, model_name)
        return

    if not args.input.exists():
        raise SystemExit(f"Input not found: {args.input}")
    print(f"Counting tokens with: {model_name}  (limit {args.max_tokens})")
    counter = chunk04.load_token_counter(model_name)
    rows = read_tickets(args.input, args.limit)
    if args.sample:
        rows = random.Random(0).sample(rows, min(args.sample, len(rows)))
    if not rows:
        raise SystemExit("No rows read.")
    prepared = prepare(rows, counter, chunk04.hard_split, args.max_tokens)
    over = report(rows, prepared, counter, args.max_tokens)
    if over:
        raise SystemExit(f"{over} embed texts exceed {args.max_tokens} tokens -- refusing to continue.")
    if args.dry_run:
        print("\nDry run: nothing written.")
        return

    indexed = [r for r in rows if prepared[r["ticket_id"]]["indexed"]]
    all_topics = sorted({t for r in indexed for t in r["topics"]})
    ids = [r["ticket_id"] for r in indexed]
    embed_texts = [prepared[i]["embed_text"] for i in ids]
    metadatas = [vector_metadata(r, prepared[r["ticket_id"]]["errors"], all_topics) for r in indexed]
    bm25_texts = [build_bm25_text(r, prepared[r["ticket_id"]]["errors"]) for r in indexed]

    guard_existing_collection(store_root / "vector", model_name, args.rebuild)
    print("Writing docstore ...")
    write_docstore(store_root / "tickets.db", rows, prepared)
    print("Building BM25 index ...")
    build_bm25(ids, bm25_texts, store_root / "bm25")
    stored = build_vectors(ids, embed_texts, metadatas, model_name, config["EMBEDDING_BATCH_SIZE"], store_root / "vector")

    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input_file": str(args.input), "limit_applied": args.limit,
        "rows_read": len(rows), "tickets_indexed": len(indexed), "vectors_stored": stored,
        "embedding_model": model_name, "max_tokens": args.max_tokens,
        "collection": collection_name_for_model(model_name), "topics": all_topics,
        "status": "success" if stored == len(indexed) else "partial",
    }
    (store_root / "tickets_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n=== Ticket store summary ===\nIndexed {len(indexed)} of {len(rows)} | vectors {stored} | "
          f"status {manifest['status']}\nStore: {store_root}")


if __name__ == "__main__":
    main()
