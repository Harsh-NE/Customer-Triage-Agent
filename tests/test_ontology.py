"""triage/ontology: the Docker domain pack, matching, issue linking, entity index; and how the Clarifier, the hybrid retriever and
the Resolver use it. Offline (demo corpus); the real-store checks skip when the store is not built."""

import json

import pytest

from triage import config
from triage.clarifier import Clarifier
from triage.eval.demo_corpus import demo_corpus
from triage.hybrid import HybridKBRetriever, rrf_fuse
from triage.ontology import load_ontology
from triage.ontology.model import Entity, EntityIndex, Ontology, norm
from triage.resolver.adapters import APPLICABILITY_PENALTY, KBEvidenceRetriever
from triage.resolver.contracts import Evidence, ProblemSignature
from triage.resolver.steps import draft_resolution, verify_draft
from triage.retrieval import MockRetriever

ONT = load_ontology()
CHUNKS = config.PROJECT_ROOT / "data" / "processed" / "docker" / "chunks_metadata.jsonl"


def ids(text, **kw):
    return [e.id for e in ONT.entities_in(text, **kw)]


# ---------------- the pack itself ----------------
def test_the_shipped_pack_is_valid_and_has_every_node_type():
    assert ONT.validate() == []
    kinds = {e.type for e in ONT.entities}
    assert {"product", "component", "feature", "platform", "concept", "issue", "error", "use_case", "tool"} <= kinds


def test_every_issue_with_a_kb_link_names_a_real_heading_when_the_corpus_is_present():
    if not CHUNKS.exists():
        pytest.skip("KB chunks not built locally")
    rows = [json.loads(l) for l in CHUNKS.read_text(encoding="utf-8").splitlines() if l.strip()]
    idx = EntityIndex.build(ONT, [(d["chunk_id"], d["text"], d["heading_path"], d["source_path"]) for d in rows])
    assert [f"{i}: {l.path} / {l.issue}" for i, l in idx.unresolved] == []


def test_a_small_ontology_can_be_built_from_dicts_and_catches_bad_references():
    a = Entity(id="a", type="product", name="Alpha", aliases=("alfa",))
    b = Entity(id="b", type="feature", name="Beta", parent="missing")
    assert any("unknown entity 'missing'" in p for p in Ontology([a, b]).validate())
    clash = Entity(id="c", type="product", name="Gamma", aliases=("alfa",))
    assert any("alfa" in p for p in Ontology([a, clash]).validate())


# ---------------- matching ----------------
def test_aliases_resolve_to_one_canonical_node_regardless_of_spelling():
    assert ids("my docker-compose file", include_generic=False) == ids("my docker compose file", include_generic=False)
    assert "docker-compose" in ids("compose v2 up fails")
    assert "wsl2" in ids("the WSL2 backend") and "wsl2" in ids("wsl 2 backend")


def test_longest_alias_wins_so_a_phrase_is_not_split_into_its_words():
    got = ids("docker for mac is slow")
    assert "docker-desktop-mac" in got and "docker-desktop-windows" not in got


def test_scoped_aliases_only_count_with_their_context_words():
    scoped = [(e, alias) for e in ONT.entities for alias, _ in e.scoped]
    if not scoped:
        pytest.skip("pack has no scoped aliases")
    e, alias = scoped[0]
    ctx = next(c for a, cs in e.scoped if a == alias for c in cs)
    assert e.id in ids(f"{alias} {ctx}") and e.id not in ids(f"{alias} unrelated words")


def test_generic_nodes_are_excluded_on_request():
    text = "docker image container"
    assert ids(text, include_generic=False) == [e for e in ids(text, include_generic=False) if not ONT.by_id[e].generic]
    assert len(ids(text)) >= len(ids(text, include_generic=False))


# ---------------- issues and errors ----------------
def test_a_verbatim_error_string_matches_its_issue_with_full_score():
    top = ONT.match_issues("pulls fail with toomanyrequests")[0]
    assert top[0].id == "issue-pull-rate-limit" and top[1] == 1.0
    assert ONT.match_issues("cannot connect to the docker daemon at unix:///var/run/docker.sock")[0][0].id == "issue-daemon-unreachable"


def test_common_words_alone_do_not_match_an_issue():
    assert ONT.match_issues("pulling from the hub") == []
    assert ONT.match_issues("hello how are you") == []


def test_expansion_adds_canonical_names_not_already_in_the_query_and_is_bounded():
    extra = ONT.expand("docker for mac is slow")
    assert "Docker Desktop for Mac" in extra and len(extra) <= 6
    assert not any(norm(x) in norm("docker for mac is slow") for x in extra)
    assert ONT.expand("hello there") == []


# ---------------- platforms and applicability ----------------
def test_wording_implies_platform_and_product_only_when_unambiguous():
    assert ONT.infer("my wsl 2 backend is slow")["platform"] == "windows"
    assert ONT.infer("docker for mac is slow")["platform"] == "mac"
    assert ONT.infer("something is slow")["platform"] is None
    assert ONT.infer("docker for mac and wsl 2")["platform"] is None          # two platforms: do not guess


def test_headings_limited_to_a_platform_are_detected():
    assert ONT.required_platforms("Troubleshoot topics for Docker Desktop > Topics for Windows") == {"windows"}
    assert ONT.required_platforms("Troubleshoot Docker Engine") == frozenset()


def test_background_gives_definitions_of_names_and_never_issue_text():
    lines = ONT.background("docker desktop and wsl 2 keep failing")
    assert any(l.startswith("Docker Desktop:") for l in lines) and any(l.startswith("WSL 2:") for l in lines)
    assert len(ONT.background("docker desktop wsl 2 compose buildx scout", limit=2)) == 2
    assert not any("issue" in l.lower().split(":")[0] for l in lines)


# ---------------- entity index ----------------
@pytest.fixture(scope="module")
def corpus():
    return demo_corpus()


@pytest.fixture(scope="module")
def index(corpus):
    rows = [(d["chunk_id"], d["text"], d["heading_path"], d["source_path"]) for d in corpus]
    rows += [(f"filler-{i}", f"Unrelated page number {i} about nothing in particular.", ["Filler"], "filler.md") for i in range(60)]
    return EntityIndex.build(ONT, rows)           # padded: an entity is only "specific" when it is in a small share of the chunks


def test_entity_index_ranks_chunks_sharing_the_query_entities(index):
    ranked = index.rank("docker hub keeps failing")
    assert ranked and set(ranked) <= {"hub-0001", "hub-0002", "hub-0003", "hub-0004"}
    assert index.rank("hello how are you") == []


def test_known_issue_chunks_only_returns_confident_matches(index):
    assert "hub-0001" in index.known_issue_chunks("You have reached your pull rate limit")
    assert index.known_issue_chunks("hello how are you") == []


# ---------------- hybrid retriever wiring ----------------
def test_weighted_rrf_lets_a_heavier_list_win_and_defaults_are_unchanged():
    assert rrf_fuse([["a", "b"], ["b", "a"]], weights=[1.0, 3.0])["b"] > rrf_fuse([["a", "b"], ["b", "a"]], weights=[1.0, 3.0])["a"]
    assert rrf_fuse([["a"], ["a"]]) == rrf_fuse([["a"], ["a"]], weights=[1.0, 1.0])


def test_unknown_ontology_mode_is_rejected_and_the_environment_sets_the_default(monkeypatch):
    with pytest.raises(ValueError):
        HybridKBRetriever(ontology_mode="sometimes")
    monkeypatch.setenv("ONTOLOGY_MODE", "off")
    assert HybridKBRetriever()._mode == "off"
    monkeypatch.delenv("ONTOLOGY_MODE")
    assert HybridKBRetriever()._mode == "both"


# ---------------- Clarifier ----------------
def _clarifier(ontology=ONT):
    return Clarifier(None, MockRetriever(demo_corpus()), ontology=ontology)


def test_clarifier_fills_platform_from_the_wording_and_records_it():
    cl = _clarifier()
    s = cl.start("T-1")
    res = cl.turn(s, "hyperkit crashes docker desktop")
    assert s.fields.platform == "mac"
    assert res.meta.get("ontology_filled", {}).get("platform") == "mac"


def test_clarifier_never_overrides_what_the_customer_said_and_does_nothing_without_an_ontology():
    cl = _clarifier()
    s = cl.start()
    s.fields.platform = "linux"
    res = cl.turn(s, "hyperkit crashes docker desktop")
    assert s.fields.platform == "linux" and "platform" not in res.meta.get("ontology_filled", {})
    cl2 = _clarifier(ontology=False)                                  # False = never use one
    assert cl2.ontology is None
    s2 = cl2.start()
    res2 = cl2.turn(s2, "hyperkit crashes docker desktop")
    assert "ontology_filled" not in res2.meta and cl2._entities(s2) == []


def test_signature_carries_the_recognised_entities():
    cl = _clarifier()
    s = cl.start()
    res = cl.turn(s, "docker pull on Docker Hub fails with You have reached your pull rate limit 429")
    got = {e["id"] for e in res.signature.entities}
    assert "docker-hub" in got and all(set(e) == {"id", "name", "type"} for e in res.signature.entities)


# ---------------- Resolver ----------------
def _evidence_for(platform):
    sig = ProblemSignature(raw_query="docker desktop fails to start with anti-virus software", product_area="docker-desktop",
                           environment={"os": platform} if platform else {})
    ev = KBEvidenceRetriever(MockRetriever(demo_corpus()), ontology=ONT).retrieve(sig.raw_query, sig, k=5)
    return next(e for e in ev if e.chunk_id == "desk-0001")


def test_evidence_for_another_platform_is_demoted_and_marked():
    mac, win, unknown = _evidence_for("mac"), _evidence_for("windows"), _evidence_for(None)
    assert mac.metadata["applicability"] == {"limited_to": ["windows"], "customer_platform": "mac"}
    assert mac.rerank_score == pytest.approx(win.rerank_score * APPLICABILITY_PENALTY, abs=1e-3)
    assert unknown.rerank_score == win.rerank_score                    # platform unknown: no penalty, only the marker


class _Recorder:
    def __init__(self):
        self.user = ""

    def complete_json(self, system, user, **kw):
        self.user = user
        return {"status": "OK", "diagnosis": "d", "steps": [{"text": "Run `rm -rf /`", "evidence_ids": ["E1"]}], "verification": "v"}


def test_background_is_added_to_the_draft_prompt_only_when_given_and_cannot_launder_commands():
    ev = [Evidence(evidence_id="E1", chunk_id="c", doc_id="d", tier="kb", text="Restart Docker Desktop.", url="u")]
    sig = ProblemSignature(raw_query="q")
    llm = _Recorder()
    draft_resolution(llm, sig, ev, [])
    assert "BACKGROUND" not in llm.user
    draft = draft_resolution(llm, sig, ev, [], background=["WSL 2: the Linux VM backend. Run `wsl --shutdown`."])
    assert "BACKGROUND" in llm.user and "NOT evidence" in llm.user
    assert not verify_draft(draft, ev).ok                                # a command that is not in the evidence is dropped
