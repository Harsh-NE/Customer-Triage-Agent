"""scripts/13_ticket_gaps.py: error-line normalisation, grouping, the leakage guard, extractive draft cards and the KB check. Offline; no store."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ticket_gaps", ROOT / "scripts" / "13_ticket_gaps.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)


def ticket(i, title="A title", errors=(), resolution="Do this and then that. " * 4, kind="accepted_answer", trust=0.9, age=2.0, words=40, **kw):
    return {"ticket_id": f"T-{i}", "title": title, "errors_clean": json.dumps(list(errors)), "error_strings": json.dumps([]), "resolution": resolution,
            "resolution_kind": kind, "trust_score": trust, "trust_tier": "high", "age_years": age, "resolution_words": words,
            "url": f"https://example.org/q/{i}", "license": "CC BY-SA 4.0", "source_type": "stackoverflow_accepted", **kw}


# ---------------------------------------------------------------- normalisation and signatures
def test_numbers_ids_and_paths_are_replaced_so_equal_errors_group_together():
    a = G.normalise("Bind for 0.0.0.0:8080 failed: port is already allocated (a1b2c3d4e5f6a7b8c9d0)")
    b = G.normalise("Bind for 0.0.0.0:9090 failed: port is already allocated (ffeeddccbbaa99887766)")
    assert a == b and "<id>" in a and "8080" not in a
    assert "<path>" in G.normalise("open /var/lib/docker/overlay2/layer/diff: no such file or directory")


def test_a_unix_socket_url_is_kept_intact_because_it_is_part_of_the_error():
    sig = G.normalise("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?")
    assert "unix:///var/run/docker.sock" in sig
    assert len(sig.split()) <= 12


def test_the_signature_is_the_first_error_line_with_at_least_three_words():
    assert G.signature_of(ticket(1, errors=["exit status 1", "toomanyrequests: You have reached your pull rate limit"])) == "toomanyrequests: you have reached your pull rate limit"
    assert G.signature_of(ticket(2, errors=[])) is None and G.signature_of(ticket(3, errors=["failed"])) is None


def test_short_signatures_are_not_specific_enough_for_a_card():
    assert not G.is_specific("no such file or directory") and G.is_specific("cannot connect to the docker daemon at unix:///var/run/docker.sock is")


def test_screenshot_filenames_that_landed_in_the_error_field_are_noise():
    assert not G.is_specific("screen shot #-#-# at # # # pm") and not G.is_specific("screenshot from #-#-# with docker desktop open on my mac")
    assert not G.is_specific("image.png shows the docker desktop failing to start on windows")
    assert G.is_specific("failed to solve with frontend dockerfile.v#: failed to create llb definition")


# ---------------------------------------------------------------- grouping and the leakage guard
def test_tickets_group_by_signature_and_the_leaked_ones_are_left_out():
    rows = [ticket(i, errors=["port is already allocated on host"]) for i in range(5)] + [ticket(9, errors=["something else entirely happened here"])]
    groups = G.group_by_signature(rows, excluded={"T-0", "T-1"})
    assert sorted(len(g) for g in groups.values()) == [1, 3]
    assert all(r["ticket_id"] not in {"T-0", "T-1"} for g in groups.values() for r in g)


def test_the_guard_excludes_the_held_out_source_tickets_and_near_copy_titles(tmp_path):
    held = [{"id": "H1", "opening": "How to restart a stopped container. I ran docker run ...", "hidden": {"source_ticket_id": "T-1"}}]
    f = tmp_path / "held.jsonl"
    f.write_text(json.dumps(held[0]) + "\n", encoding="utf-8")
    rows = [ticket(1, title="How to restart a stopped container"), ticket(2, title="How to restart a stopped container?"),
            ticket(3, title="restart the stopped container how to"), ticket(4, title="Overlay network ports across swarm nodes")]
    excluded, why = G.leakage_exclusions(rows, f)
    assert {"T-1", "T-2", "T-3"} <= excluded and "T-4" not in excluded
    assert why[0].startswith("1 held-out") and "near-copy" in why[1]


# ---------------------------------------------------------------- draft cards
def test_the_best_ticket_prefers_accepted_trusted_recent_answers_of_a_usable_length():
    rows = [ticket(1, kind="community_comment", trust=0.99), ticket(2, kind="accepted_answer", trust=0.6, age=9), ticket(3, kind="accepted_answer", trust=0.9, age=1),
            ticket(4, kind="accepted_answer", trust=0.95, words=900)]                       # too long to be a card
    assert G.best_ticket(rows)["ticket_id"] == "T-3"


def test_trim_cuts_at_a_sentence_and_keeps_short_text_whole():
    assert G.trim("Short answer.") == "Short answer."
    long = "First sentence here. " * 60
    out = G.trim(long, 100)
    assert out.endswith(".") and len(out) <= 100


def test_a_draft_card_is_extractive_attributed_and_cannot_be_mistaken_for_approved():
    rows = [ticket(i, title=f"Port clash {i}", errors=["port is already allocated on host"], resolution="Stop the other container using the port.") for i in range(4)]
    card = G.draft_card("port is already allocated on host", rows, {"contained": 0.2, "top": ["x.md > Y (0.6)"]})
    assert card["status"] == "draft" and card["reviewer"] is None and card["id"].startswith("CARD-") and card["cluster_size"] == 4
    assert card["fix_text_extract"] == "Stop the other container using the port." and card["title"].startswith("Port clash")
    assert len(card["sources"]) == 3 and all(s["url"].startswith("https://") and s["license"] == "CC BY-SA 4.0" for s in card["sources"])
    assert any("never loaded" in c for c in card["caveats"]) and card["kb_contained"] == 0.2
    assert G.draft_card("port is already allocated on host", rows, None)["id"] == card["id"]          # the id depends only on the signature


# ---------------------------------------------------------------- the KB check
def test_kb_contained_is_the_best_share_of_the_errors_words_found_in_the_top_chunks():
    def chunk(text, score, path="content/manuals/x/troubleshoot.md", heading=("Troubleshoot", "Pull rate limit")):
        return SimpleNamespace(text=text, score=score, source_path=path, article_title="T", heading_path=list(heading), metadata={"doc_kind": "troubleshooting"})

    class FakeKB:
        def __init__(self, chunks):
            self.chunks = chunks

        def search(self, query, top_k=8):
            return self.chunks

    sig = "you have reached your pull rate limit"
    hit = G.kb_check(FakeKB([chunk("You have reached your pull rate limit. Authenticate to raise it.", 0.8)]), sig)
    miss = G.kb_check(FakeKB([chunk("Configure the daemon to use a proxy server.", 0.8)]), sig)
    assert hit["contained"] >= 0.8 and miss["contained"] < 0.4 and hit["top"][0].startswith("troubleshoot.md")
    assert G.kb_check(FakeKB([]), sig) == {"contained": 0.0, "top": []}
