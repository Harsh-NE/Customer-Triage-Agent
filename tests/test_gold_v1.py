"""The gold test set: its integrity, the stratified split, the per-class scorer and the agreement statistic. Offline."""

import csv
import json

import pytest

from triage.eval import gold_v1 as G


def test_the_built_files_are_valid_and_complete():
    assert G.validate() == []
    dev, test = G.read_split(G.DEV), G.read_split(G.TEST)
    assert len(dev) + len(test) == 89 and len(test) == 18
    manifest = json.loads(G.MANIFEST.read_text(encoding="utf-8"))
    assert manifest["by_class"] == {"kb_gap": 46, "answerable": 19, "vague": 8, "urgent": 6, "out_of_scope": 6, "injection": 4}
    assert manifest["total"] == 89 and any("not untouched" in c for c in manifest["caveats"])        # the limits are written next to the numbers


def test_the_checked_in_files_match_what_the_builder_produces():
    rows = G.load_rows()
    splits = G.assign_splits(rows)
    assert [r for r in rows if splits[r["id"]] == "dev"] == G.read_split(G.DEV)
    assert [r for r in rows if splits[r["id"]] == "test"] == G.read_split(G.TEST)


def test_the_split_is_stratified_deterministic_and_disjoint():
    rows = G.load_rows()
    a, b = G.assign_splits(rows), G.assign_splits(list(reversed(rows)))
    assert a == b                                                                   # independent of input order
    for cls in G.CLASSES:
        members = [r for r in rows if G.class_of(r) == cls]
        in_test = [r for r in members if a[r["id"]] == "test"]
        assert in_test and len(in_test) <= len(members) // 4 + 1, cls                # every class is represented, none is mostly test
    assert {r["id"] for r in G.read_split(G.DEV)}.isdisjoint({r["id"] for r in G.read_split(G.TEST)})


def test_classes_follow_the_note_and_the_gold_label():
    rows = {r["id"]: r for r in G.load_rows()}
    assert G.class_of(rows["V01"]) == "vague" and G.class_of(rows["U03"]) == "urgent" and G.class_of(rows["I02"]) == "injection"
    assert G.class_of(rows["H003"]) == "answerable" and G.class_of(rows["H001"]) == "kb_gap"
    assert rows["I01"]["oos"] and rows["O01"]["oos"] and not rows["V01"]["oos"] and not rows["U01"]["oos"]


def test_the_validator_catches_a_label_that_points_nowhere(tmp_path, monkeypatch):
    rows = G.read_split(G.DEV)
    bad = next(r for r in rows if r["gold"])
    bad = {**bad, "gold": {"source_path_contains": "content/does/not/exist.md", "issue_contains": "Nothing"}}
    dev = tmp_path / "dev.jsonl"
    dev.write_text("\n".join(json.dumps(r if r["id"] != bad["id"] else bad) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(G, "DEV", dev)
    assert any(bad["id"] in p and "not found in the KB" in p for p in G.validate())


def row(**kw):
    base = {"id": "X", "outcome": "escalated", "escalation_reason": "LOW_EVIDENCE", "questions": 1, "fixes_sent": [], "resolved_gold": False}
    return {**base, **kw}


def kb_fix(gold=False):
    return {"tier": "kb", "gold": gold}


@pytest.mark.parametrize("cls,r,ok", [
    ("answerable", row(outcome="resolved", resolved_gold=True, fixes_sent=[kb_fix(True)]), True),
    ("answerable", row(), False),                                                        # escalated instead of answering
    ("kb_gap", row(), True),
    ("kb_gap", row(outcome="resolved", fixes_sent=[kb_fix()]), False),                     # a KB fix where the KB has no answer
    ("kb_gap", row(fixes_sent=[{"tier": "tickets", "gold": False}]), True),                # a ticket attempt is not a KB fix
    ("vague", row(escalation_reason="CLARIFY_LOOP_EXHAUSTED"), True),
    ("vague", row(outcome="rejected"), False),                                             # told "not Docker"
    ("vague", row(fixes_sent=[kb_fix()]), False),
    ("urgent", row(questions=0, escalation_reason="SECURITY_OR_DATA_LOSS"), True),
    ("urgent", row(questions=1, escalation_reason="SECURITY_OR_DATA_LOSS"), False),        # asked a question first
    ("urgent", row(questions=0, escalation_reason="LOW_EVIDENCE"), False),                 # escalated, but not as urgent
    ("out_of_scope", row(outcome="rejected", escalation_reason="OUT_OF_SCOPE"), True),
    ("injection", row(outcome="escalated"), False),
])
def test_per_class_correctness(cls, r, ok):
    assert G.expected_ok(cls, r) is ok


def test_score_reports_each_class_and_lists_the_misses(tmp_path):
    rows = [row(id="H003", outcome="resolved", resolved_gold=True, fixes_sent=[kb_fix(True)]), row(id="H001"),
            row(id="V01", outcome="rejected"), row(id="U01", questions=0, escalation_reason="SECURITY_OR_DATA_LOSS")]
    f = tmp_path / "rows.json"
    f.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    out = G.score(f)
    assert out["answerable"]["rate"] == 1.0 and out["kb_gap"]["rate"] == 1.0 and out["urgent"]["rate"] == 1.0
    assert out["vague"] == {"n": 1, "correct": 0, "wrong_ids": ["V01"], "rate": 0.0}
    assert set(G.score(f, "test")) <= set(G.CLASSES)


def test_cohen_kappa_is_zero_for_chance_agreement_and_one_for_perfect():
    assert G.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert G.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    assert G.cohen_kappa([], []) is None and G.cohen_kappa(["a", "a"], ["a", "a"]) is None       # undefined when there is only one label


def test_the_labelling_sheet_hides_the_current_label_and_agreement_reads_two_filled_sheets(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    G.sheet(a)
    with a.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0][0] == "id" and all(r[2] == "" for r in rows[1:]) and len(rows) == 90
    assert not any("kb_gap" in cell or "answerable" in cell for r in rows[1:] for cell in r[1:2])      # nothing leaks the label
    truth = {r["id"]: G.class_of(r) for r in G.load_rows()}
    for path, flip in ((a, None), (b, {"V01", "V02"})):
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(rows[0])
            for r in rows[1:]:
                w.writerow([r[0], r[1], "kb_gap" if flip and r[0] in flip else truth[r[0]], "", ""])
    out = G.agreement(a, b)
    assert out["items_labelled_by_both"] == 89 and out["disagreements"] == ["V01", "V02"] and out["a_vs_current_labels"] == 1.0
    assert 0.9 < out["cohen_kappa"] < 1.0
