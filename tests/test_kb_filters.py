"""The opt-in KB filters (triage/hybrid.py KB_FILTERS): dedupe, archive, notes. The filter logic is tested on synthetic candidates (no store);
the integration checks use the real store when it is built. Everything is off by default."""

import pytest

from triage import config
from triage.hybrid import FILTER_EXTRA, KB_FILTERS, OLD_VERSION_CUES, RELEASE_CUES, HybridKBRetriever
from triage.state import Candidate


def cand(i, score, kind="docs", text=None):
    return Candidate(f"c{i}", text if text is not None else f"unique text {i}", score, f"p{i}.md", "A", ["A", "B"], {"doc_kind": kind})


@pytest.fixture
def r():
    return HybridKBRetriever(ontology_mode="off", rerank_mode="off", kb_filters="")


def ids(cs):
    return [c.chunk_id for c in cs]


def test_off_by_default_even_when_the_environment_is_unset(monkeypatch):
    monkeypatch.delenv("KB_FILTERS", raising=False)
    assert HybridKBRetriever(ontology_mode="off")._filters == set()


def test_the_environment_and_the_argument_choose_the_filters(monkeypatch):
    monkeypatch.setenv("KB_FILTERS", "dedupe, archive")
    assert HybridKBRetriever(ontology_mode="off")._filters == {"dedupe", "archive"}
    assert HybridKBRetriever(ontology_mode="off", kb_filters=["notes"])._filters == {"notes"}
    assert HybridKBRetriever(ontology_mode="off", kb_filters="")._filters == set()          # an explicit empty value beats the environment


def test_unknown_filter_names_are_refused(r):
    with pytest.raises(ValueError):
        r.set_filters("dedupe,shuffle")
    assert set(KB_FILTERS) == {"dedupe", "archive", "notes"}


def test_dedupe_keeps_only_the_best_scored_copy_of_identical_text(r):
    r.set_filters("dedupe")
    hits = [cand(1, 0.9, text="Same  text\nhere"), cand(2, 0.8, text="same text here"), cand(3, 0.7), cand(4, 0.6, text="SAME TEXT HERE")]
    assert ids(r._apply_filters("anything", hits)) == ["c1", "c3"]                              # whitespace and case do not hide a duplicate


def test_archive_pages_are_dropped_unless_the_query_sounds_like_an_old_docker(r):
    r.set_filters("archive")
    hits = [cand(1, 0.9, "archive"), cand(2, 0.8, "docs"), cand(3, 0.7, "archive")]
    assert ids(r._apply_filters("docker pull fails with 429", hits)) == ["c2"]
    assert ids(r._apply_filters("docker toolbox on windows 7 will not start", hits)) == ["c1", "c2", "c3"]
    assert ids(r._apply_filters("docker-machine create fails", hits)) == ["c1", "c2", "c3"]


def test_release_notes_are_dropped_unless_the_query_is_about_a_release_or_update(r):
    r.set_filters("notes")
    hits = [cand(1, 0.9, "release_notes"), cand(2, 0.8, "docs")]
    assert ids(r._apply_filters("container exits with code 137", hits)) == ["c2"]
    assert ids(r._apply_filters("it broke after updating docker desktop", hits)) == ["c1", "c2"]
    assert ids(r._apply_filters("what changed in the latest release", hits)) == ["c1", "c2"]


def test_filters_never_touch_scores_or_order_and_do_nothing_when_off(r):
    hits = [cand(1, 0.9, "archive"), cand(2, 0.8, "release_notes", text="x"), cand(3, 0.7, text="x")]
    assert r._apply_filters("q", hits) == hits                                                  # no filter: identical list
    r.set_filters("dedupe,archive,notes")
    out = r._apply_filters("q", hits)
    assert out == [] or all(c.score == next(h.score for h in hits if h.chunk_id == c.chunk_id) for c in out)
    assert ids(out) == ["c3"]


def test_the_cues_do_not_fire_on_ordinary_support_questions():
    for q in ("docker pull fails with 'You have reached your pull rate limit'", "port is already allocated", "Docker Desktop 4.30 will not start on Windows 11"):
        assert not OLD_VERSION_CUES.search(q) and not RELEASE_CUES.search(q), q


# ---------------------------------------------------------------- with the real store
STORE = config.PROJECT_ROOT / config.get_env()["VECTOR_DB_PATH"]
needs_store = pytest.mark.skipif(not (STORE / "chroma.sqlite3").exists(), reason="Docker vector store not built locally")


@pytest.fixture(scope="module")
def kb():
    try:
        retriever = HybridKBRetriever(rerank_mode="off", kb_filters="")
        retriever.search("docker", top_k=1)
        return retriever
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"stores unavailable: {exc}")


QUERY = "docker pull fails with 'You have reached your pull rate limit' HTTP 429 on Docker Hub"


@needs_store
def test_with_filters_off_the_results_are_what_they_were(kb):
    kb.set_filters("")
    plain = ids(kb.search(QUERY, top_k=8))
    kb.set_filters("dedupe,archive,notes")
    kb.set_filters("")
    assert ids(kb.search(QUERY, top_k=8)) == plain


@needs_store
def test_filtered_results_still_return_the_asked_size_and_leave_no_filtered_kind_behind(kb):
    try:
        kb.set_filters("dedupe,archive,notes")
        hits = kb.search("container exits with code 137 and no logs", top_k=8)
        primary = [c for c in hits if c.metadata.get("doc_kind") in ("archive", "release_notes")]
        texts = [" ".join(c.text.split()).lower() for c in hits]
        assert len(hits) >= 8 and not primary and len(texts) == len(set(texts))
        assert FILTER_EXTRA > 0
    finally:
        kb.set_filters("")
