"""scripts/10_tickets.py: ticket preparation, embedded text, docstore and the rebuild guard.
Logic tests use a whitespace "tokenizer"; the real-data test uses the real bge tokenizer and the real CSV."""

import csv
import importlib.util
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("tickets10", ROOT / "scripts" / "10_tickets.py")
T = importlib.util.module_from_spec(_spec)
sys.modules["tickets10"] = T
_spec.loader.exec_module(T)
CHUNK04 = T.load_script("04_chunk.py")


class WSTok:
    is_fast = True
    model_max_length = 512

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
        spans = [m.span() for m in re.finditer(r"\S+", text)]
        out = {"input_ids": list(range(len(spans)))}
        if return_offsets_mapping:
            out["offset_mapping"] = spans
        return out


@pytest.fixture
def counter():
    return CHUNK04.TokenCounter(WSTok())


def make_row(**over):
    row = {"ticket_id": "T-1", "source_id": "so:1", "source": "stackoverflow", "source_type": "stackoverflow_accepted",
           "trust_tier": "high", "trust_score": 0.8, "trust_reasons": [], "is_synthetic": False, "overlaps_kb": False,
           "license": "CC BY-SA 4.0", "url": "https://x/1", "created_at": "2021-01-01", "age_years": 5.0,
           "title": "Container will not start", "problem": "docker run fails with a permission problem on startup",
           "resolution": "Run it with the right user.", "resolution_kind": "accepted_answer", "problem_score": 3.0,
           "resolution_score": 5.0, "kind_guess": "troubleshooting", "topics": ["runtime", "storage"], "tags": ["docker"],
           "docker_versions": [], "error_strings": [], "exit_codes": [], "has_code": True, "problem_words": 9.0,
           "resolution_words": 5.0}
    row.update(over)
    return row


# ---------------- error-string cleaning ----------------
def test_clean_errors_keeps_real_error_lines_and_drops_junk():
    raw = ["Error response from daemon: manifest for x:latest not found",    # real
           "short",                                                          # too short
           "http://localhost:8080/health/ready",                             # bare URL
           "\\x15\\x03\\x01\\x00 binary junk here",                          # escape junk
           "12345 67890 11111 22222",                                        # mostly digits
           "ve got going in a Docker container and failed",                  # prose cut at an apostrophe
           "t work since I upgraded and it failed",                          # same
           "when I run it fails with a weird thing",                         # first person
           "/var/log/nginx/error.log",                                       # a quoted path, not an error
           "systemctl restart mysqld",                                       # a quoted command
           "Error response from daemon: manifest for x:latest not found"]    # duplicate
    assert T.clean_errors(raw) == ["Error response from daemon: manifest for x:latest not found"]


def test_clean_errors_does_not_over_filter_legitimate_lines():
    kept = T.clean_errors(["re-run failed with status 2", "can't open file /etc/x: permission denied",
                           "Error: I/O error on device sda", "refused to connect to the daemon socket"])
    assert len(kept) == 3 and "re-run failed with status 2" in kept          # capped at MAX_ERRORS, none wrongly dropped
    assert T.clean_errors(["can't open file /etc/x: permission denied"]) == ["can't open file /etc/x: permission denied"]
    assert T.clean_errors(["Error: I/O error on device sda"]) == ["Error: I/O error on device sda"]


def test_clean_errors_caps_count_and_length():
    raw = [f"Error number {i} happened in the daemon" for i in range(10)]
    assert len(T.clean_errors(raw)) == T.MAX_ERRORS
    assert all(len(e) <= T.MAX_ERROR_CHARS for e in T.clean_errors(["Error " + "x" * 500]))


# ---------------- which rows are indexed ----------------
def test_exclude_reason():
    assert T.exclude_reason(make_row()) == ""
    assert T.exclude_reason(make_row(is_synthetic=True)) == "synthetic"
    assert T.exclude_reason(make_row(overlaps_kb=True)) == "overlaps_kb"
    assert T.exclude_reason(make_row(problem="  ")) == "empty"
    assert T.exclude_reason(make_row(trust_tier="low")) == ""             # low trust stays indexed (filtered at query time)


# ---------------- embedded text ----------------
def test_embed_text_puts_title_then_errors_then_problem_within_budget(counter):
    row = make_row(problem=" ".join(f"w{i}" for i in range(2000)))
    text = T.build_embed_text(row, ["Error one happened", "Error two happened"], counter, CHUNK04.hard_split, 100)
    assert counter.count(text) <= 100
    lines = text.split("\n")
    assert lines[0] == "Container will not start" and lines[1] == "Error: Error one happened"
    assert "w0" in text and "w1999" not in text                            # head of the problem kept, tail dropped


def test_short_ticket_is_embedded_whole(counter):
    row = make_row()
    text = T.build_embed_text(row, [], counter, CHUNK04.hard_split, 100)
    assert text == f"{row['title']}\n\n{row['problem']}"


def test_faq_style_row_does_not_repeat_the_title(counter):
    row = make_row(title="Can I use Docker offline?", problem="Can I use Docker offline?")
    assert T.build_embed_text(row, [], counter, CHUNK04.hard_split, 100) == "Can I use Docker offline?"


def test_oversized_header_is_trimmed_to_its_share(counter):
    row = make_row(title=" ".join(f"t{i}" for i in range(400)))
    text = T.build_embed_text(row, [], counter, CHUNK04.hard_split, 500)
    assert counter.count(text) <= 500 and counter.count(text.split("\n")[0]) <= T.HEADER_MAX_TOKENS


def test_bm25_text_uses_full_problem_and_skips_github_labels():
    long_problem = " ".join(f"w{i}" for i in range(1500))
    so = T.build_bm25_text(make_row(problem=long_problem, tags=["mysql"]), [])
    gh = T.build_bm25_text(make_row(source="github/docker/cli", tags=["status/needs-more-info"]), [])
    assert "w1499" in so and "mysql" in so and "status/needs-more-info" not in gh


# ---------------- Chroma metadata ----------------
def test_vector_metadata_is_flat_scalars_with_topic_flags():
    md = T.vector_metadata(make_row(age_years=None, topics=["storage"]), ["Error x happened"], ["runtime", "storage"])
    assert all(isinstance(v, (str, int, float, bool)) for v in md.values())     # Chroma rejects None and lists
    assert md["topic_storage"] is True and md["topic_runtime"] is False
    assert md["age_years"] == -1.0 and md["n_errors"] == 1 and md["has_exit_code"] is False


# ---------------- CSV and docstore ----------------
def write_csv(path, rows):
    cols = list(make_row().keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            out = dict(r)
            for c in T.JSON_LIST_COLUMNS:
                out[c] = json.dumps(r[c])
            w.writerow(out)


def test_read_tickets_parses_types_and_multiline_text(tmp_path):
    path = tmp_path / "t.csv"
    write_csv(path, [make_row(problem="line one\nline two", age_years=None, topics=["build"], exit_codes=["137"])])
    row = T.read_tickets(path)[0]
    assert row["problem"] == "line one\nline two" and row["age_years"] is None
    assert row["topics"] == ["build"] and row["exit_codes"] == ["137"] and row["is_synthetic"] is False


def test_docstore_keeps_every_row_and_the_full_resolution(tmp_path, counter):
    rows = [make_row(ticket_id="T-1", resolution="the full fix " * 300),
            make_row(ticket_id="T-2", is_synthetic=True)]
    prepared = T.prepare(rows, counter, CHUNK04.hard_split, 100)
    T.write_docstore(tmp_path / "t.db", rows, prepared)
    con = sqlite3.connect(tmp_path / "t.db")
    got = {r[0]: r[1:] for r in con.execute("SELECT ticket_id, indexed, exclude_reason, length(resolution) FROM tickets")}
    assert got["T-1"][0] == 1 and got["T-1"][2] == len("the full fix " * 300)       # resolution stored untrimmed
    assert got["T-2"][:2] == (0, "synthetic")
    assert json.loads(con.execute("SELECT topics FROM tickets WHERE ticket_id='T-1'").fetchone()[0]) == ["runtime", "storage"]


# ---------------- rebuild guard ----------------
def test_guard_refuses_to_build_over_an_existing_collection(tmp_path):
    import chromadb
    model = "BAAI/bge-base-en-v1.5"
    col = chromadb.PersistentClient(path=str(tmp_path)).get_or_create_collection(T.collection_name_for_model(model))
    col.add(ids=["a", "b"], embeddings=[[0.1, 0.2]] * 2, documents=["x", "y"])
    with pytest.raises(SystemExit, match="--rebuild"):
        T.guard_existing_collection(tmp_path, model, rebuild=False)
    T.guard_existing_collection(tmp_path, model, rebuild=True)
    names = [c.name for c in chromadb.PersistentClient(path=str(tmp_path)).list_collections()]
    assert T.collection_name_for_model(model) not in names
    T.guard_existing_collection(tmp_path / "missing", model, rebuild=False)           # no store yet: fine


def test_collection_name_is_separate_from_the_kb_collection():
    assert T.collection_name_for_model("BAAI/bge-base-en-v1.5") == "tickets__baai-bge-base-en-v1-5"


# ---------------- real tokenizer + real CSV ----------------
@pytest.mark.real_store
@pytest.mark.skipif(not T.DEFAULT_INPUT.exists(), reason="ticket CSV not present")
def test_real_tickets_prepare_within_the_token_cap():
    try:
        counter = CHUNK04.load_token_counter("BAAI/bge-base-en-v1.5")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"embedding tokenizer unavailable: {exc}")
    rows = T.read_tickets(T.DEFAULT_INPUT)
    assert len(rows) > 13000
    sample = random.Random(0).sample(rows, 1500)
    prepared = T.prepare(sample, counter, CHUNK04.hard_split)
    indexed = [r for r in sample if prepared[r["ticket_id"]]["indexed"]]
    assert indexed and all(counter.count(prepared[r["ticket_id"]]["embed_text"]) <= T.MAX_TOKENS for r in indexed)
    assert not any(r["is_synthetic"] or r["overlaps_kb"] for r in indexed)
    assert all(not T.CONTRACTION_TAIL.match(e) for r in sample for e in prepared[r["ticket_id"]]["errors"])
