"""The supplementary (third-party) knowledge tier: the quality filter and repair script, and how the Resolver uses it.
Offline: mock retrievers, no stores, no models."""

import importlib.util
import sys
from pathlib import Path

import pytest

from triage.eval.demo_corpus import demo_corpus
from triage.resolver.adapters import SUPPLEMENTARY_FACTOR, KBEvidenceRetriever
from triage.resolver.contracts import Evidence
from triage.resolver.steps import DRAFT_SYSTEM, render_message
from triage.retrieval import MockRetriever

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("pipeline_11", ROOT / "scripts" / "11_supplementary.py")
supp = importlib.util.module_from_spec(spec)
sys.modules["pipeline_11"] = supp
spec.loader.exec_module(supp)


def raw(chunk_id, heading, text="word " * 60, tokens=60, src="ebook", **md):
    return {"chunk_id": chunk_id, "source_path": f"extra/{src}/x.md", "article_title": heading[0], "section_title": None, "subsection_title": None,
            "heading_path": list(heading), "split_part": None, "text": text, "token_count": tokens, "word_count": 60,
            "metadata": {"doc_kind": "tutorial", "license": "MIT", "source_url": f"https://github.com/o/r/blob/abc/{chunk_id}.md", "tags": [],
                         "error_signals": [], "is_troubleshooting": False, "product_area": "engine", "component": "x", "weight": None, **md}}


# ---------------- the filter and repair script ----------------
def test_front_matter_short_chunks_and_unknown_sources_are_dropped_with_a_reason():
    chunks = [raw("keep", ["Chapter 2: Installing Docker", "Post-Installation Steps"]),
              raw("author", ["About the book", "About the author"]), raw("sponsor", ["About the book", "Sponsors", "DevDojo"]),
              raw("licence", ["Intro", "License"]), raw("tiny", ["Rootless mode", "Overview"], tokens=12),
              {**raw("odd", ["Anything"]), "source_path": "extra/unknown/x.md"}]
    kept, rejected, _ = supp.process(chunks)
    assert [c["chunk_id"] for c in kept] == ["keep"]
    assert {r["chunk_id"]: r["reason"] for r in rejected} == {"author": "front_or_back_matter", "sponsor": "front_or_back_matter",
                                                              "licence": "front_or_back_matter", "tiny": "too_short", "odd": "unknown_source"}


def test_html_anchors_and_code_comment_headings_are_repaired_not_dropped():
    path, repairs = supp.repair_headings(['<a name="drivers"></a>Docker Bridge Network Driver', "Overview"])
    assert path == ["Docker Bridge Network Driver", "Overview"] and repairs == ["anchor_removed"]
    path, repairs = supp.repair_headings(["list of cat images", "2.0 Webapps with Docker", "2.1 Run a static website"])
    assert path == ["2.0 Webapps with Docker", "2.1 Run a static website"] and repairs == ["code_comment_heading_dropped"]
    assert supp.repair_headings(["buildkitd.toml", "Overview"])[0] == ["buildkitd.toml", "Overview"]      # a real title that happens to be lowercase
    assert supp.repair_headings(["Only a lowercase phrase here"])[0] == ["Only a lowercase phrase here"]  # never leaves an empty path


def test_kept_chunks_get_their_provenance_and_rebuilt_titles():
    kept, _, _ = supp.process([raw("c1", ["list of cat images", "2.0 Webapps with Docker", "2.1 Run it"], src="labs")])
    c = kept[0]
    assert (c["article_title"], c["section_title"], c["subsection_title"]) == ("2.0 Webapps with Docker", "2.1 Run it", None)
    md = c["metadata"]
    assert md["source_tier"] == "supplementary" and md["source_name"].startswith("docker/labs") and md["license"] == "MIT"


def test_the_shipped_chunk_file_has_no_front_matter_anchors_or_stubs_when_present():
    path = supp.OUT_CHUNKS
    if not path.exists():
        pytest.skip("supplementary chunks not built locally")
    import json
    chunks = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert chunks and all(c["metadata"]["source_tier"] == "supplementary" and c["metadata"]["license"] in ("MIT", "Apache-2.0") for c in chunks)
    assert all(c["token_count"] >= supp.MIN_TOKENS and "<a name" not in " ".join(c["heading_path"]) for c in chunks)
    assert all(c["source_path"].startswith("extra/") and c["metadata"]["source_url"].startswith("https://github.com/") for c in chunks)
    assert not any(supp.FRONT_MATTER.match(h) for c in chunks for h in c["heading_path"])


# ---------------- the Resolver's use of the tier ----------------
def supplementary_corpus():
    return [{"chunk_id": "extra__ebook__post-install__0001", "text": "Docker without sudo: add your user to the docker group, then log out and in again.",
             "source_path": "extra/ebook/content/002-installation.md", "article_title": "Installing Docker", "heading_path": ["Installing Docker", "Post-Installation Steps"],
             "metadata": {"doc_kind": "tutorial", "source_tier": "supplementary", "source_name": "Introduction to Docker ebook (community)",
                          "source_url": "https://github.com/bobbyiliev/introduction-to-docker-ebook/blob/abc/002.md", "license": "MIT"}}]


def retrievers():
    return MockRetriever(demo_corpus()), MockRetriever(supplementary_corpus())


def test_community_evidence_is_labelled_linked_to_its_own_source_and_never_called_official_docs():
    official, community = retrievers()
    ev = KBEvidenceRetriever(official, supplementary=community, supplementary_below=1.1).retrieve("run docker without sudo add your user to the docker group", k=8)
    c = next(e for e in ev if e.metadata.get("source_tier") == "supplementary")
    assert c.tier == "kb" and c.source == "community: Introduction to Docker ebook (community)"
    assert c.url.startswith("https://github.com/bobbyiliev/") and "docker/docs" not in c.url and c.metadata["license"] == "MIT"


def test_strong_official_evidence_never_consults_the_community_tier():
    official, community = retrievers()
    q = "docker pull fails with you have reached your pull rate limit 429 on docker hub"
    plain = KBEvidenceRetriever(MockRetriever(demo_corpus())).retrieve(q, k=8)
    guarded = KBEvidenceRetriever(official, supplementary=community, supplementary_below=0.0).retrieve(q, k=8)    # nothing is below 0.0
    assert community.queries == [] and [e.chunk_id for e in plain] == [e.chunk_id for e in guarded]


def test_community_relevance_is_discounted_so_official_wins_a_tie():
    official, community = retrievers()
    q = "docker without sudo add your user to the docker group"
    both = KBEvidenceRetriever(official, supplementary=community, supplementary_below=1.1)
    solo = KBEvidenceRetriever(MockRetriever(supplementary_corpus()))
    base = solo.retrieve(q, k=8)[0].rerank_score
    got = next(e for e in both.retrieve(q, k=8) if e.metadata.get("source_tier") == "supplementary").rerank_score
    assert got == pytest.approx(base * SUPPLEMENTARY_FACTOR, abs=1e-3) and got < base


def test_a_community_fix_the_customer_rejected_is_not_offered_again():
    official, community = retrievers()
    r = KBEvidenceRetriever(official, supplementary=community, supplementary_below=1.1)
    q = "run docker without sudo add your user to the docker group"
    first = next(e for e in r.retrieve(q, k=8) if e.metadata.get("source_tier") == "supplementary")
    again = r.retrieve(q, k=8, exclude_chunk_ids=[first.chunk_id])
    assert not any(e.metadata.get("source_tier") == "supplementary" for e in again)


def test_without_a_supplementary_retriever_nothing_changes():
    official = MockRetriever(demo_corpus())
    ev = KBEvidenceRetriever(official).retrieve("docker pull rate limit 429", k=8)
    assert all(e.metadata.get("source_tier") is None and e.source == "docker/docs" for e in ev)


# ---------------- what the customer and the model are told ----------------
def test_the_reply_names_a_community_guide_and_its_licence():
    ev = [Evidence(evidence_id="E1", chunk_id="c", doc_id="d", tier="kb", text="t", url="https://github.com/o/r/x.md",
                   metadata={"source_tier": "supplementary", "license": "MIT"})]
    text = render_message({"diagnosis": "d"}, [{"text": "Add your user to the docker group.", "evidence_ids": ["E1"]}], ev)
    assert "(community guide, MIT)" in text and "https://github.com/o/r/x.md" in text


def test_the_drafting_prompt_explains_community_sources_and_legacy_commands():
    assert 'starts with "community:"' in DRAFT_SYSTEM and "docker-compose v1" in DRAFT_SYSTEM


def test_the_joint_wiring_can_be_switched_off_and_is_skipped_when_the_store_is_missing(monkeypatch, tmp_path):
    from triage import config, joint
    monkeypatch.setenv("SUPPLEMENTARY_KB", "off")
    assert joint.build_supplementary(model=None) is None
    monkeypatch.setenv("SUPPLEMENTARY_KB", "on")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    assert joint.build_supplementary(model=None) is None


def test_store_metadata_gains_provenance_only_for_third_party_chunks():
    spec6 = importlib.util.spec_from_file_location("pipeline_06", ROOT / "scripts" / "06_store.py")
    store06 = importlib.util.module_from_spec(spec6)
    sys.modules["pipeline_06"] = store06
    spec6.loader.exec_module(store06)
    official = {"chunk_id": "a", "source_path": "content/x.md", "article_title": "T", "heading_path": ["T"],
                "metadata": {"license": "Apache-2.0", "source_url": "https://github.com/docker/docs/blob/main/content/x.md"}}
    assert not {"source_tier", "source_name", "source_url", "license"} & set(store06.chunk_metadata(official))      # official store: unchanged
    kept, _, _ = supp.process([raw("c1", ["Chapter 2", "Post-Installation Steps"])])
    md = store06.chunk_metadata(kept[0])
    assert md["source_tier"] == "supplementary" and md["license"] == "MIT" and md["source_url"].startswith("https://github.com/")
    assert md["source_name"].startswith("Introduction to Docker ebook")
