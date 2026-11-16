"""generation_eval: the cleaning of a sent fix and the scoring plumbing, on hand-made rows. No model, no store."""

import json

from triage.eval import generation_eval as G

FIX = ("Likely cause: Rate limit reached.\n\n1. Run `docker login` to authenticate. [E1]\n2. Retry the pull. [E1, E2]\n\n"
       "To confirm: Re-run the failing command and confirm the error is gone.\n\nSources: E1 https://example.com/a; E2 https://example.com/b")


def test_clean_fix_removes_footer_tags_and_boilerplate_but_keeps_the_steps():
    out = G.clean_fix(FIX)
    assert "Sources" not in out and "To confirm" not in out and "[E1" not in out and "Likely cause" not in out
    assert "Run `docker login` to authenticate." in out and "Retry the pull." in out


def test_clean_fix_drops_markdown_table_rules_only():
    out = G.clean_fix("| Port | Use |\n| :--- | :--- |\n| 2377 | control |")
    assert "| 2377 | control |" in out and ":---" not in out


def test_score_counts_no_fix_separately_and_scores_the_rest():
    refs = {"A": "run docker login to authenticate then retry the pull", "B": "restart the daemon", "C": "x y z"}
    rows = [{"id": "A", "fixes_sent": [{"message": FIX}]}, {"id": "B", "fixes_sent": []}]
    rep = G.score(refs, rows)
    assert rep["n"] == 1 and rep["scored_ids"] == ["A"] and rep["no_fix"] == ["B"] and rep["no_row"] == ["C"]
    assert 0 < rep["rouge1"]["value"] <= 1 and rep["meteor_variant"]
    assert rep["questions_with_reference"] == 3


def test_score_with_nothing_to_score_does_not_crash():
    assert G.score({"A": "ref"}, [{"id": "A", "fixes_sent": []}])["n"] == 0


def test_references_load_from_csv_and_jsonl_and_skip_blanks(tmp_path):
    csv_path = tmp_path / "r.csv"
    csv_path.write_text("id,question,reference\nA,q,do this\nB,q,\n", encoding="utf-8")
    assert G.load_references(csv_path) == {"A": "do this"}
    jl = tmp_path / "r.jsonl"
    jl.write_text(json.dumps({"id": "A", "reference": "do that"}) + "\n" + json.dumps({"id": "B", "reference": ""}) + "\n", encoding="utf-8")
    assert G.load_references(jl) == {"A": "do that"}
