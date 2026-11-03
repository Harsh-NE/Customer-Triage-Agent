"""The optional cross-encoder rerank (triage/rerank.py, hooked into HybridKBRetriever behind RERANK). The ranking logic is tested with no model;
one test uses the real cross-encoder when it is cached locally."""

import math
import os
from pathlib import Path

import pytest

from triage import config
from triage import rerank as R
from triage.state import Candidate


def cand(i, score, heading=("Troubleshoot", "Issue"), text="body"):
    return Candidate(f"c{i}", f"{text} {i}", score, f"p{i}.md", "Troubleshoot", list(heading), {"doc_kind": "troubleshooting"})


POOL = [cand(0, 0.80), cand(1, 0.70), cand(2, 0.60), cand(3, 0.55), cand(4, 0.50)]
RELEVANCE = [0.10, 0.20, 0.95, 0.05, 0.60]            # the cross-encoder prefers c2, then c4, then c1


def ids(cs):
    return [c.chunk_id for c in cs]


# ---------------------------------------------------------------- the pure logic
def test_off_returns_the_fused_order_untouched():
    assert ids(R.rerank_candidates(POOL, RELEVANCE, "off", 0.5, 3)) == ["c0", "c1", "c2"]
    assert R.rerank_candidates([], [], "order", 0.5, 3) == []


def test_order_mode_follows_the_cross_encoder_but_keeps_the_calibrated_score_scale():
    out = R.rerank_candidates(POOL, RELEVANCE, "order", 0.5, 3)
    assert ids(out) == ["c2", "c4", "c1"]
    assert [c.score for c in out] == [0.80, 0.70, 0.60]                       # the same similarity values, handed out best-first
    assert out == sorted(out, key=lambda c: -c.score)                          # and still sorted, as downstream code sorts by score
    assert out[0].metadata["vector_score"] == 0.60 and out[0].metadata["ce_score"] == 0.95    # the chunk's own numbers stay visible


def test_blend_mode_mixes_similarity_and_relevance():
    out = R.rerank_candidates(POOL, RELEVANCE, "blend", 0.5, 5)
    assert ids(out) == ["c2", "c4", "c0", "c1", "c3"]
    assert out[0].score == pytest.approx(0.5 * 0.60 + 0.5 * 0.95)
    assert all(a.score >= b.score for a, b in zip(out, out[1:]))
    assert ids(R.rerank_candidates(POOL, RELEVANCE, "blend", 0.0, 3)) == ["c0", "c1", "c2"]            # weight 0 = the fused order
    assert ids(R.rerank_candidates(POOL, RELEVANCE, "blend", 1.0, 3)) == ["c2", "c4", "c1"]            # weight 1 = the cross-encoder alone
    assert R.rerank_candidates(POOL, RELEVANCE, "blend", 7.0, 1)[0].score == pytest.approx(0.95)       # out-of-range weights are clamped


def test_the_input_candidates_are_never_mutated():
    before = [(c.chunk_id, c.score, dict(c.metadata)) for c in POOL]
    R.rerank_candidates(POOL, RELEVANCE, "order", 0.5, 3)
    R.rerank_candidates(POOL, RELEVANCE, "blend", 0.5, 3)
    assert [(c.chunk_id, c.score, dict(c.metadata)) for c in POOL] == before


def test_unknown_modes_are_refused():
    with pytest.raises(ValueError):
        R.rerank_candidates(POOL, RELEVANCE, "banana", 0.5, 3)


def test_sigmoid_squashes_logits_to_a_relevance():
    assert R.sigmoid(0) == 0.5 and R.sigmoid(3.02) > 0.95 and R.sigmoid(-9.08) < 0.001
    assert 0.0 < R.sigmoid(-1000) < 1e-20 and R.sigmoid(1000) == pytest.approx(1.0)       # extreme logits do not overflow


def test_the_text_the_model_reads_leads_with_the_issue_heading():
    c = Candidate("x", "Run docker login.", 0.7, "a.md", "Article", ["Article", "Group", "You have reached your pull rate limit"], {})
    assert R.candidate_text(c).startswith("Group > You have reached your pull rate limit. Run docker login.")
    assert len(R.candidate_text(Candidate("y", "z" * 5000, 0.7, "a.md", "A", ["A"], {}))) == R.MAX_CHARS


# ---------------------------------------------------------------- the reranker object
class FakeCrossEncoder:
    def __init__(self):
        self.calls = []

    def predict(self, pairs):
        self.calls.append(list(pairs))
        return [3.0 if "rate limit" in text else -9.0 for _, text in pairs]


def test_relevance_is_a_sigmoid_of_the_models_logits_and_pairs_are_read_once():
    fake = FakeCrossEncoder()
    rr = R.CrossEncoderReranker(model=fake)
    got = rr.relevance("pull fails", ["You have reached your pull rate limit", "WSL 2 is required", "You have reached your pull rate limit"])
    assert got[0] == got[2] and got[0] > 0.95 and got[1] < 0.001
    assert len(fake.calls) == 1 and len(fake.calls[0]) == 2                       # the repeated passage was scored once
    rr.relevance("pull fails", ["WSL 2 is required"])
    assert len(fake.calls) == 1                                                   # cached per (query, passage)
    rr.relevance("another query", ["WSL 2 is required"])
    assert len(fake.calls) == 2


# ---------------------------------------------------------------- settings
def test_the_environment_decides_and_the_default_is_off(monkeypatch):
    monkeypatch.delenv("RERANK", raising=False)
    assert R.settings_from_env() == ("off", R.DEFAULT_POOL, R.DEFAULT_BLEND)
    monkeypatch.setenv("RERANK", "blend")
    monkeypatch.setenv("RERANK_POOL", "12")
    monkeypatch.setenv("RERANK_BLEND", "0.3")
    assert R.settings_from_env() == ("blend", 12, 0.3)
    monkeypatch.setenv("RERANK", "sometimes")
    with pytest.raises(ValueError):
        R.settings_from_env()


# ---------------------------------------------------------------- the retriever hook (needs the real store)
STORE = config.PROJECT_ROOT / config.get_env()["VECTOR_DB_PATH"]
needs_store = pytest.mark.skipif(not (STORE / "chroma.sqlite3").exists(), reason="Docker vector store not built locally")


@pytest.fixture(scope="module")
def retriever():
    from triage.hybrid import HybridKBRetriever
    try:
        r = HybridKBRetriever(rerank_mode="off")
        r.search("docker", top_k=1)
        return r
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"stores unavailable: {exc}")


QUERY = "docker pull fails with 'You have reached your pull rate limit' HTTP 429 on Docker Hub"


@needs_store
def test_rerank_is_off_by_default_and_changes_nothing_then(monkeypatch, retriever):
    monkeypatch.delenv("RERANK", raising=False)
    from triage.hybrid import HybridKBRetriever
    assert HybridKBRetriever(model=retriever._model)._rerank_mode == "off"
    baseline = ids(retriever.search(QUERY, top_k=8))
    retriever.set_rerank("off")
    assert ids(retriever.search(QUERY, top_k=8)) == baseline


@needs_store
def test_with_rerank_on_the_hook_reads_a_wider_pool_and_returns_the_asked_size(retriever):
    class Spy:
        def __init__(self):
            self.seen = []

        def relevance(self, query, texts):
            self.seen.append(len(texts))
            return [1.0 / (1 + i) for i in range(len(texts))]

    spy = Spy()
    retriever._reranker = spy
    try:
        retriever.set_rerank("order", 20, 0.5)
        hits = retriever.search(QUERY, top_k=8)
        assert spy.seen == [20] and len({c.chunk_id for c in hits}) == len(hits)
        reranked = [c for c in hits if "ce_score" in c.metadata]               # the chunks the model read (siblings added afterwards have none)
        assert len(reranked) == 8 and all(c.metadata["vector_score"] > 0 for c in reranked)
        retriever.set_rerank("off")
        spy.seen.clear()
        retriever.search(QUERY, top_k=8)
        assert spy.seen == []                                                  # off: the model is never consulted
    finally:
        retriever._reranker = None
        retriever.set_rerank("off")


@needs_store
def test_a_failing_reranker_never_costs_the_answer(retriever):
    class Broken:
        def relevance(self, query, texts):
            raise RuntimeError("model file corrupt")

    retriever._reranker = Broken()
    try:
        retriever.set_rerank("order", 20, 0.5)
        got = ids(retriever.search(QUERY, top_k=8))
        retriever.set_rerank("off")
        assert got == ids(retriever.search(QUERY, top_k=8))                    # fell back to the fused order
    finally:
        retriever._reranker = None
        retriever.set_rerank("off")


# ---------------------------------------------------------------- the real model, when it is cached
def _model_cached() -> bool:
    home = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
    return (Path(home) / "hub" / "models--cross-encoder--ms-marco-MiniLM-L-6-v2").is_dir()


@pytest.mark.skipif(not _model_cached(), reason="cross-encoder not cached locally")
def test_the_real_cross_encoder_prefers_the_passage_that_answers_the_query():
    rr = R.CrossEncoderReranker()
    try:
        scores = rr.relevance("docker pull fails with You have reached your pull rate limit",
                              ["You have reached your pull rate limit. You may increase the limit by authenticating and upgrading.",
                               "Docker Desktop for Windows requires WSL 2 and Hyper-V to be enabled in the BIOS.",
                               "To change the default log driver set the log-driver key in daemon.json."])
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"model could not load offline: {exc}")
    assert scores[0] > 0.9 and scores[1] < 0.1 and scores[2] < 0.1 and all(0.0 <= s <= 1.0 and not math.isnan(s) for s in scores)
