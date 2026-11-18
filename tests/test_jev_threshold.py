"""jev_threshold: how many refusals flip at each bar, and the lowest safe bar."""

import json

from triage.eval import jev_threshold as J


def case(p, gold, phase="first_ask"):
    return {"phase": phase, "jev_p": p, "has_gold": gold}


def test_load_keeps_first_asks_where_jev_answered(tmp_path):
    rows = [case(0.9, True), case(None, True), case(0.8, False, phase="repeat"), case(0.2, False)]
    (tmp_path / "queries.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert [r["jev_p"] for r in J.load(tmp_path)] == [0.9, 0.2]


def test_table_counts_documented_and_undocumented_flips_at_each_bar():
    rows = [case(0.99, True), case(0.92, True), case(0.7, False), case(0.55, True)]
    by_bar = {line["bar"]: line for line in J.table(rows, bars=(0.5, 0.9, 0.98))}
    assert (by_bar[0.5]["flips"], by_bar[0.5]["documented"], by_bar[0.5]["undocumented"]) == (4, 3, 1)
    assert (by_bar[0.9]["flips"], by_bar[0.9]["undocumented"]) == (2, 0)
    assert by_bar[0.98]["share_documented"] == 1.0
    assert J.table([], bars=(0.9,))[0]["share_documented"] is None


def test_the_recommended_bar_is_the_lowest_one_with_no_undocumented_flip():
    rows = [case(0.99, True), case(0.92, True), case(0.7, False), case(0.55, True)]
    assert J.recommend(rows, bars=(0.5, 0.6, 0.8, 0.9)) == 0.8                  # 0.7 (undocumented) stops flipping at 0.8
    assert J.recommend([case(0.9, False)], bars=(0.5, 0.9)) is None             # nothing separates the groups
    assert J.recommend([case(0.3, True)], bars=(0.5, 0.9)) is None              # nothing flips at all
