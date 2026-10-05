"""Integration check against the REAL Docker Chroma store (vector-only retriever, free heuristic
extractor, rule-based customer). Skipped automatically when the store or the cached embedding model
is missing, so CI without data stays green. Run explicitly with:  pytest -m real_store -s"""

import pytest

from triage import config
from triage.clarifier import Clarifier
from triage.retrieval import ChromaRetriever
from triage.sim.customer import RuleBasedCustomer, load_scenarios
from triage.sim.dialogue import run_dialogue

STORE = config.PROJECT_ROOT / config.get_env()["VECTOR_DB_PATH"]
pytestmark = [pytest.mark.real_store,
              pytest.mark.skipif(not (STORE / "chroma.sqlite3").exists(), reason="Docker vector store not built locally")]

# scenarios whose gold answer the vector-only baseline reliably reaches (measured, see reports/)
MUST_RESOLVE = ["S01", "S05", "S09", "S10", "S11", "S15", "S16", "S18", "S19", "S20"]


@pytest.fixture(scope="module")
def retriever():
    try:
        r = ChromaRetriever()
        r.search("docker", top_k=1)
        return r
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"embedding model/store unavailable: {exc}")


@pytest.mark.parametrize("scenario_id", MUST_RESOLVE)
def test_real_store_reaches_the_gold_issue(retriever, scenario_id):
    s = next(x for x in load_scenarios() if x.id == scenario_id)
    d = run_dialogue(Clarifier(None, retriever), RuleBasedCustomer(s), s)
    assert d.gold_rank == 1, f"{scenario_id}: status={d.status}, top={d.result.signature.hypotheses[0].label if d.result.signature else None}"


def test_real_store_out_of_scope_queries_are_never_confident(retriever):
    for s in (x for x in load_scenarios() if x.oos):
        d = run_dialogue(Clarifier(None, retriever), RuleBasedCustomer(s), s)
        assert d.status != "ready", f"{s.id} ({s.opening!r}) was answered confidently"


def test_real_store_product_taxonomy_is_clean():
    import chromadb
    meta = chromadb.PersistentClient(path=str(STORE)).get_collection(
        "kb_chunks__baai-bge-base-en-v1-5").get(include=["metadatas"])["metadatas"]
    areas = {m["product_area"] for m in meta}
    assert "content" not in areas, "regression: guides/reference chunks mislabelled product_area='content'"
    assert not any(a.endswith(".md") for a in areas), "regression: file extension leaked into product_area"
    assert {"engine", "desktop", "docker-hub"} <= areas
