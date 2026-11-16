"""paraphrase_scenarios: the paraphrase set as scenarios the harness can load."""

import json

from triage.eval import paraphrase_scenarios as P
from triage.sim.customer import RuleBasedCustomer, load_scenarios


def test_one_acceptable_answer_becomes_a_scenario_with_that_gold():
    s = P.to_scenario({"id": "P01", "query": "docker for mac says the app is damaged", "gold": [{"path": "troubleshoot/topics.md", "issue": "Docker.app is damaged"}]})
    assert s["id"] == "P01" and s["opening"] == "docker for mac says the app is damaged" and s["oos"] is False
    assert s["gold"] == {"source_path_contains": "troubleshoot/topics.md", "issue_contains": "Docker.app is damaged"}
    assert not s["note"].startswith("kb_gap")                                     # a note starting that way marks "the KB has no answer"


def test_two_acceptable_answers_are_left_out():
    two = {"id": "P09", "query": "q", "gold": [{"path": "a.md", "issue": "x"}, {"path": "a.md", "issue": "y"}]}
    assert P.to_scenario(two) is None


def test_the_written_file_loads_as_scenarios_and_covers_the_unambiguous_paraphrases(tmp_path, monkeypatch):
    out = tmp_path / "s.jsonl"
    monkeypatch.setattr(P, "OUT", out)
    P.main()
    scenarios = load_scenarios(out)
    items = [json.loads(line) for line in P.SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(scenarios) == sum(len(i["gold"]) == 1 for i in items) == 40
    assert all(s.gold and s.opening for s in scenarios) and len({s.id for s in scenarios}) == 40
    assert RuleBasedCustomer(scenarios[0]).opening() == scenarios[0].opening      # the simulated customer can play it
