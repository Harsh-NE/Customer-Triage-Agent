"""Token-aware chunking (scripts/04_chunk.py). Logic tests use a deterministic whitespace tokenizer;
tests marked `real_store` use the real embedding-model tokenizer and the real cleaned docs."""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("chunk04", ROOT / "scripts" / "04_chunk.py")
C = importlib.util.module_from_spec(_spec)
sys.modules["chunk04"] = C          # @dataclass in the script looks its module up in sys.modules
_spec.loader.exec_module(C)


class WSTok:
    """One token per whitespace-separated word; offsets exact. Stands in for a fast HF tokenizer."""
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
    return C.TokenCounter(WSTok())


def words(text):
    return [w for w in text.split() if not w.startswith("```")]


# ---------------- basics ----------------
def test_counter_requires_a_fast_tokenizer():
    class Slow:
        is_fast = False
    with pytest.raises(ValueError):
        C.TokenCounter(Slow())


def test_counter_silences_the_max_length_warning_by_raising_the_limit():
    tok = WSTok()
    C.TokenCounter(tok)
    assert tok.model_max_length > 10**6


def test_text_within_budget_is_returned_unchanged(counter):
    text = "Intro paragraph.\n\nSecond paragraph with `code`."
    assert C.split_text(text, counter, 100) == [text]


# ---------------- paragraph packing ----------------
def test_paragraphs_are_packed_whole_and_every_chunk_fits(counter):
    paras = [" ".join(f"p{i}w{j}" for j in range(30)) for i in range(10)]          # 10 paragraphs x 30 tokens
    chunks = C.split_text("\n\n".join(paras), counter, 100)
    assert all(counter.count(c) <= 100 for c in chunks)
    assert len(chunks) == 4                                                         # 3 paragraphs per chunk (90) + remainder
    assert all(c.count("\n\n") + 1 == len([p for p in paras if p in c]) for c in chunks)   # no paragraph was cut
    assert words("\n\n".join(chunks)) == words("\n\n".join(paras))


def test_a_bullet_list_with_no_blank_lines_splits_on_line_boundaries(counter):
    items = [f"- item {i} " + " ".join(f"w{i}_{j}" for j in range(20)) for i in range(40)]
    chunks = C.split_text("\n".join(items), counter, 120)                           # one 40-line paragraph, 880 tokens
    assert len(chunks) > 1 and all(counter.count(c) <= 120 for c in chunks)
    assert all(line in items for c in chunks for line in c.splitlines())            # only whole items, none cut
    assert [l for c in chunks for l in c.splitlines()] == items                     # order preserved


def test_one_long_line_splits_on_sentence_boundaries(counter):
    sentences = [f"Sentence number {i} says " + " ".join(f"x{i}_{j}" for j in range(15)) + "." for i in range(20)]
    chunks = C.split_text(" ".join(sentences), counter, 90)
    assert all(counter.count(c) <= 90 for c in chunks)
    assert all(s in " ".join(chunks) for s in sentences)                            # every sentence intact


def test_unbreakable_text_falls_back_to_exact_token_windows(counter):
    blob = " ".join(f"tok{i}" for i in range(1000))                                 # no sentence ends, no newlines
    chunks = C.split_text(blob, counter, 64)
    assert all(counter.count(c) <= 64 for c in chunks)
    assert " ".join(chunks).split() == blob.split()                                 # exact slices: nothing lost or altered
    assert len(chunks) == 16


def test_hard_split_returns_nothing_for_whitespace_only_text(counter):
    assert C.hard_split("   \n  ", counter, 10) == []


# ---------------- code blocks ----------------
def test_oversized_code_block_is_split_on_lines_and_each_part_is_a_valid_fence(counter):
    body = [f"line_{i} = run({i}) # step" for i in range(200)]
    block = "```python {title=app.py}\n" + "\n".join(body) + "\n```"
    chunks = C.split_text("Run this:\n\n" + block, counter, 100)
    code_chunks = [c for c in chunks if c.startswith("```")]
    assert code_chunks and all(counter.count(c) <= 100 for c in chunks)
    for c in code_chunks:
        assert c.splitlines()[0] == "```python {title=app.py}" and c.rstrip().endswith("```")
        assert c.count("```") == 2                                                  # balanced
    assert [l for c in chunks for l in c.splitlines() if l.startswith("line_")] == body   # (the first part may share a chunk with the intro)


def test_a_mixed_paragraph_keeps_its_code_fence_atomic_when_it_fits(counter):
    para = "Run:\n```console\n$ docker ps\n```\nthen check the output."
    big = "\n\n".join([" ".join(f"w{i}_{j}" for j in range(40)) for i in range(5)] + [para])
    chunks = C.split_text(big, counter, 100)
    assert any("```console\n$ docker ps\n```" in c for c in chunks)


def test_a_single_oversized_line_inside_a_code_block_is_hard_split_inside_the_fence(counter):
    block = "```text\n" + " ".join(f"t{i}" for i in range(300)) + "\n```"
    chunks = C.split_text(block, counter, 80)
    assert all(counter.count(c) <= 80 and c.startswith("```text") and c.rstrip().endswith("```") for c in chunks)
    assert " ".join(w for c in chunks for w in c.split() if not w.startswith("```")) == " ".join(f"t{i}" for i in range(300))


# ---------------- whole documents ----------------
DOC = {"rel_path": "content/manuals/x/troubleshoot.md", "title": "Troubleshoot X", "tags": ["Troubleshooting"],
       "front_matter": {"weight": 10},
       "cleaned_markdown": "# Troubleshoot X\n\nIntro text.\n\n## Big issue\n\n### Error message\n\n" +
                           "\n\n".join(" ".join(f"e{i}_{j}" for j in range(60)) for i in range(8)) +
                           "\n\n### Solution\n\nShort fix.\n"}


def test_chunk_document_respects_the_budget_and_records_token_counts(counter):
    chunks = C.chunk_document(DOC, counter, 100)
    assert all(c["token_count"] == counter.count(c["text"]) <= 100 for c in chunks)
    assert all(c["word_count"] == len(c["text"].split()) for c in chunks)
    parts = [c for c in chunks if c["split_part"]]
    assert parts and all(c["heading_path"][1] == "Big issue" for c in parts)
    assert [c["chunk_id"] for c in chunks] == sorted(c["chunk_id"] for c in chunks)         # sequence ids stay ordered
    assert chunks[0]["metadata"]["is_troubleshooting"] is True


def test_chunk_document_with_a_generous_budget_is_unchanged_by_token_awareness(counter):
    chunks = C.chunk_document(DOC, counter, 100000)
    assert not any(c["split_part"] for c in chunks)


# ---------------- real tokenizer / real data ----------------
@pytest.fixture(scope="module")
def real_counter():
    try:
        return C.load_token_counter("BAAI/bge-base-en-v1.5")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"embedding tokenizer unavailable: {exc}")


def test_real_tokenizer_budget_holds_for_adversarial_synthetic_text(real_counter):
    code = "```console\n" + "\n".join(f"docker run --rm -e KEY_{i}=value_{i} -v /host/path_{i}:/c{i} image:{i}.{i}.{i}"
                                      for i in range(400)) + "\n```"
    prose = " ".join(f"identifier_{i}_with_underscores https://example.com/a/b/c/{i}?q={i}&r={i}." for i in range(300))
    table = "| a | b |\n|:" + "-" * 3000 + "|:" + "-" * 3000 + "|\n| 1 | 2 |"
    for text in (code, prose, table, "\n\n".join([code, prose, table])):
        chunks = C.split_text(text, real_counter, 500)
        assert all(real_counter.count(c) <= 500 for c in chunks), "a chunk exceeds the budget"
        assert sum(map(len, chunks)) > 0.5 * len(text)                                # nothing wholesale dropped


def test_real_tokenizer_hard_split_prefers_word_boundaries_and_slices_exactly(real_counter):
    text = " ".join(f"alpha{i} beta{i}" for i in range(600))
    pieces = C.hard_split(text, real_counter, 100)
    assert all(real_counter.count(p) <= 100 for p in pieces)
    assert all(p == p.strip() for p in pieces) and " ".join(pieces).split() == text.split()


CLEANED = ROOT / "data" / "processed" / "docker" / "cleaned_docs.jsonl"


@pytest.mark.real_store
@pytest.mark.skipif(not CLEANED.exists(), reason="Docker cleaned docs not built locally")
def test_real_docs_produce_no_chunk_over_the_token_limit(real_counter):
    over, total = 0, 0
    for line in CLEANED.read_text(encoding="utf-8").splitlines():
        for c in C.chunk_document(json.loads(line), real_counter, 500):
            total += 1
            over += c["token_count"] > 500
    assert total > 10000 and over == 0
