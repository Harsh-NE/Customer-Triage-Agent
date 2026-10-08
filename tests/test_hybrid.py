"""triage/hybrid.py: fusion, ticket ranking and rendering (pure logic), then both retrievers on the real stores."""

import pytest
from rank_bm25 import BM25Okapi

from triage import config
from triage.hybrid import (HybridKBRetriever, TicketRetriever, bm25_top, query_exit_codes, rank_tickets, recency_factor,
                           render_ticket_card, rrf_fuse, tokenize)
from triage.retrieval import ChromaRetriever
from triage.state import TicketHit


# ---------------- fusion and lexical search ----------------
def test_rrf_rewards_agreement_between_lists():
    fused = rrf_fuse([["a", "b", "c"], ["c", "a", "d"]])
    assert fused["a"] > fused["c"] > fused["b"] and fused["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert rrf_fuse([]) == {} and set(rrf_fuse([["x"], ["y"]])) == {"x", "y"}


def test_bm25_top_finds_the_rare_term_and_ignores_empty_queries():
    docs = ["docker pull fails registry", "rootless mode user namespaces", "docker daemon socket", "disk space"]
    bm25 = BM25Okapi([tokenize(d) for d in docs])
    ids = ["a", "b", "c", "d"]
    assert bm25_top(bm25, ids, "rootless", 3) == ["b"]                   # only positive scores are returned
    assert bm25_top(bm25, ids, "!!! ???", 3) == []


def test_exit_codes_are_read_from_the_query_and_http_codes_are_not():
    assert query_exit_codes("container exited with code 137") == {"137"}
    assert query_exit_codes("process exit status 1 then exit code 0") == {"0", "1"}
    assert query_exit_codes("pulls fail with a 429 response") == set()
    assert query_exit_codes("error code 500 from the hub") == set()      # > 255 cannot be an exit code


def test_recency_is_mild_floored_and_unknown_is_neutral():
    assert recency_factor(1.0) == 1.0 and recency_factor(3.0) == 1.0
    assert recency_factor(8.0) == pytest.approx(0.8) and recency_factor(40.0) == 0.6
    assert recency_factor(None) == 0.9


# ---------------- ticket ranking ----------------
def row(tid, title="Some problem", trust_tier="high", trust_score=0.8, kind="accepted_answer", age=3.0, url=None,
        topics=(), errors=(), codes=(), kind_guess="troubleshooting"):
    return {"ticket_id": tid, "title": title, "problem": "p", "resolution": "fix", "source": "stackoverflow",
            "source_type": "stackoverflow_accepted", "trust_tier": trust_tier, "trust_score": trust_score,
            "resolution_kind": kind, "kind_guess": kind_guess, "age_years": age, "topics": list(topics),
            "errors_clean": list(errors), "exit_codes": list(codes), "docker_versions": [],
            "url": url if url is not None else f"https://x/{tid}", "license": "CC BY-SA 4.0"}


def ranked_ids(rows, fused, query, top_k=5, **kw):
    return [r["ticket_id"] for r, _, _ in rank_tickets(rows, fused, query, top_k, **kw)]


def test_exact_exit_code_beats_a_slightly_better_fused_rank_and_a_mismatch_is_demoted():
    rows = [row("other", codes=["139"]), row("exact", codes=["137"]), row("none")]
    fused = {"other": 0.0328, "exact": 0.0300, "none": 0.0310}
    assert ranked_ids(rows, fused, "container exits with code 137")[0] == "exact"
    why = {r["ticket_id"]: w for r, _, w in rank_tickets(rows, fused, "container exits with code 137", 5)}
    assert why["exact"] == ["exit_code:137"] and why["other"] == []
    assert ranked_ids(rows, fused, "container keeps crashing")[0] == "other"        # no code in the query: just the fused rank


def test_exit_code_in_the_title_counts_when_the_column_is_empty():
    rows = [row("t", title="GitLab pipeline exiting with error code 137"), row("u", title="Something else")]
    assert ranked_ids(rows, {"t": 0.03, "u": 0.0305}, "exit code 137")[0] == "t"


def test_error_line_match_is_rewarded():
    rows = [row("a", errors=["Error response from daemon: manifest for x:latest not found"]), row("b")]
    out = rank_tickets(rows, {"a": 0.030, "b": 0.0305}, "docker: Error response from daemon: manifest for y:latest not found", 5)
    assert out[0][0]["ticket_id"] == "a" and "error_line" in out[0][2]


def test_trust_and_resolution_kind_and_age_break_ties_in_the_expected_direction():
    rows = [row("weak", trust_tier="medium", trust_score=0.5, kind="community_comment", age=9.0), row("strong")]
    assert ranked_ids(rows, {"weak": 0.03, "strong": 0.03}, "q") == ["strong", "weak"]


def test_low_trust_only_fills_the_list_when_too_few_good_tickets_exist():
    rows = [row("good1"), row("good2"), row("low", trust_tier="low", trust_score=0.3)]
    fused = {"good1": 0.02, "good2": 0.019, "low": 0.0328}
    assert ranked_ids(rows, fused, "q", top_k=2) == ["good1", "good2"]                # low is excluded while 2 good ones exist
    assert ranked_ids(rows, fused, "q", top_k=3) == ["good1", "good2", "low"]          # ...but still available as a last resort
    assert ranked_ids(rows, fused, "q", top_k=3, min_trust="low")[0] == "low"


def test_kind_filter_exclusions_and_duplicate_urls():
    rows = [row("a", kind_guess="how_to"), row("b"), row("c", url="https://dup"), row("d", url="https://dup")]
    fused = {"a": 0.03, "b": 0.029, "c": 0.028, "d": 0.027}
    assert "a" not in ranked_ids(rows, fused, "q", kind="troubleshooting")
    assert "b" not in ranked_ids(rows, fused, "q", exclude_ids={"b"})
    assert {"c", "d"} & set(ranked_ids(rows, fused, "q")) == {"c"}                    # one per URL, the better one


def test_topic_boost_is_soft_and_scores_stay_within_zero_and_one():
    rows = [row("a", topics=["networking"]), row("b")]
    out = rank_tickets(rows, {"a": 0.0300, "b": 0.0305}, "q", 5, topics={"networking"})
    assert out[0][0]["ticket_id"] == "a" and out[0][2] == ["topic:networking"]
    big = rank_tickets([row("x", codes=["137"], errors=["Error response from daemon: boom happened here"])],
                       {"x": 2 / 61}, "exit code 137 Error response from daemon: boom happened here", 5)
    assert 0 < big[0][1] <= 1.0


# ---------------- card rendering ----------------
def test_card_is_labelled_community_cites_the_source_and_trims_at_a_word_boundary():
    hit = TicketHit("T-1", "Container OOM killed", "p", " ".join(f"w{i}" for i in range(500)), 0.9, url="https://so/1",
                    license="CC BY-SA 4.0", source="stackoverflow", trust_tier="high", age_years=5.4)
    card = render_ticket_card(hit, max_words=50)
    assert card.startswith("[Community ticket - not official documentation")
    assert "https://so/1 (CC BY-SA 4.0)" in card and "w49 ..." in card and "w50" not in card and "5 years old" in card
    assert "..." not in render_ticket_card(TicketHit("T-2", "t", "p", "short fix", 0.5, url="u", license="l"))


# ---------------- real stores ----------------
STORE = config.PROJECT_ROOT / config.get_env()["VECTOR_DB_PATH"]
TICKETS = config.PROJECT_ROOT / config.get_env()["TICKETS_STORE_PATH"]
BM25 = config.PROJECT_ROOT / config.get_env()["BM25_PATH"]


@pytest.fixture(scope="module")
def kb():
    if not ((STORE / "chroma.sqlite3").exists() and (BM25 / "bm25_index.pkl").exists()):
        pytest.skip("Docker KB store not built locally")
    try:
        r = HybridKBRetriever(expand_siblings=False)
        r.search("docker", top_k=1)
        return r
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"embedding model/store unavailable: {exc}")


@pytest.fixture(scope="module")
def tickets(kb):
    if not (TICKETS / "tickets.db").exists():
        pytest.skip("ticket store not built locally")
    return TicketRetriever(model=kb._model)


@pytest.mark.real_store
def test_hybrid_scores_are_on_the_vector_scale_for_every_candidate(kb):
    from triage.hybrid import _sq_distance
    hits = kb.search("docker pull fails for me on rootless Docker", top_k=8)
    assert hits and all(0 < c.score <= 1 for c in hits)
    assert [c.score for c in hits] == sorted((c.score for c in hits), reverse=True)
    # a lexical-only hit is scored exactly like a dense one: our distance maths must equal Chroma's own
    q = kb._model.encode(["Represent this sentence for searching relevant passages: rootless"])[0].tolist()
    res = kb._collection.query(query_embeddings=[q], n_results=1, include=["distances"])
    got = kb._collection.get(ids=res["ids"][0], include=["embeddings"])
    assert _sq_distance(q, got["embeddings"][0]) == pytest.approx(res["distances"][0][0], rel=1e-3)


@pytest.mark.real_store
def test_hybrid_brings_in_rare_term_pages_that_vector_search_alone_misses(kb):
    query = "docker pull fails for me on rootless Docker"
    vector_only = ChromaRetriever(expand_siblings=False, model=kb._model).search(query, top_k=6)
    hybrid = kb.search(query, top_k=6)

    def rootless_pages(hits):
        return {c.source_path for c in hits if "rootless" in c.source_path.lower() or "Rootless mode" in c.heading_path[0]}
    assert len(rootless_pages(hybrid)) > len(rootless_pages(vector_only))


@pytest.mark.real_store
def test_ticket_retriever_ranks_exact_exit_code_first_and_hides_low_trust(tickets):
    hits = tickets.search("container exits with code 137", top_k=5)
    assert len(hits) == 5 and all(0 < h.score <= 1 for h in hits)
    assert any(m.startswith("exit_code:137") for m in hits[0].matched)
    assert all(h.trust_tier != "low" for h in hits[:3])
    top = hits[0]
    assert top.url.startswith("http") and top.license and top.resolution and top.problem_excerpt


@pytest.mark.real_store
def test_ticket_retriever_filters_and_excludes(tickets):
    q = "docker compose volume permission denied"
    base = tickets.search(q, top_k=5)
    assert base and tickets.search(q, top_k=5, exclude_ids={base[0].ticket_id})[0].ticket_id != base[0].ticket_id
    assert all(h.kind_guess == "troubleshooting" for h in tickets.search("docker build fails", top_k=5, kind="troubleshooting"))
    assert any(m.startswith("topic:") for h in tickets.search("docker build fails", top_k=5, topics=["build"]) for m in h.matched)
