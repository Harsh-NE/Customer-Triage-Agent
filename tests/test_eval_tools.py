"""The evaluation tools themselves: gate calibration replay, the faithfulness judge and its negative controls, the held-out set
builder, cache-pair generation, and the e2e recording helpers. Pure logic with stub models; no network, no stores."""

import json

import pytest

from triage.eval import cache_pairs, calibrate_gate as cg, e2e_eval, heldout, judge
from triage.resolver.config import GateConfig


# ---------------- gate calibration ----------------
def gate_row(rid, top, gold, *, has_gold=True, oos=False, kb_gap=False, second=0.2, p_top=0.9, completeness=0.9):
    ev = [{"evidence_id": "E1", "doc_id": "a.md#1", "tier": "kb", "rerank_score": top, "component": "x", "topics": [], "issue": "i", "gold": gold},
          {"evidence_id": "E2", "doc_id": "b.md#1", "tier": "kb", "rerank_score": second, "component": "y", "topics": [], "issue": "j", "gold": False}]
    return {"id": rid, "has_gold": has_gold, "oos": oos, "kb_gap": kb_gap,
            "gate_inputs": [{"tier": "kb", "completeness": completeness, "p_top": p_top, "evidence": ev}]}


def test_wilson_upper_bound_shows_what_zero_errors_can_promise():
    assert cg.wilson_upper(0, 0) is None
    assert cg.wilson_upper(0, 20) == pytest.approx(0.161, abs=0.005)
    assert cg.wilson_upper(0, 200) < 0.02 < cg.wilson_upper(0, 20)


def test_replay_matches_the_real_gate():
    cfg = GateConfig()
    assert cg.replay(gate_row("a", 0.9, True)["gate_inputs"][0], cfg) is True
    assert cg.replay(gate_row("b", 0.4, True)["gate_inputs"][0], cfg) is False


def test_score_counts_correct_wrong_and_no_answer_cases():
    rows = [gate_row("g1", 0.9, True), gate_row("g2", 0.8, False), gate_row("o", 0.9, False, has_gold=False, oos=True),
            gate_row("gap", 0.9, False, has_gold=False, kb_gap=True), gate_row("u", 0.9, False, has_gold=False), gate_row("weak", 0.3, True)]
    s = cg.score(rows, GateConfig())
    assert (s["correct_answers"], s["wrong_answers"], s["answered_unlabelled"]) == (1, 3, 1)       # g1 ok; g2, oos, gap wrong; u unlabelled
    assert s["coverage"] == pytest.approx(1 / 3, abs=1e-3) and s["n_no_kb_answer"] == 2


def test_choose_raises_thresholds_until_a_confident_wrong_answer_is_blocked_then_stays_conservative():
    rows = [gate_row("right", 0.85, True), gate_row("also right", 0.9, True), gate_row("wrong", 0.62, False, p_top=0.5, completeness=0.6)]
    cfg, s = cg.choose(rows, GateConfig(), max_wrong=0)
    assert s["wrong_answers"] == 0 and s["correct_answers"] == 2
    assert cg.score(rows, GateConfig())["wrong_answers"] == 1                    # the defaults let the wrong one through
    from dataclasses import replace
    looser = replace(cfg, min_top_score=cfg.min_top_score - 0.05, resolve_confidence=cfg.resolve_confidence - 0.05)
    assert cg.score(rows, looser)["wrong_answers"] == 0                          # robust: one grid step looser is still safe


def test_choose_reports_the_least_bad_config_when_no_threshold_is_safe():
    rows = [gate_row("right", 0.5, True), gate_row("wrong", 0.95, False, p_top=1.0, completeness=1.0)]
    _, s = cg.choose(rows, GateConfig(), max_wrong=0)
    assert s["wrong_answers"] == 1                          # the wrong answer scores higher than the right one at every threshold: nothing is safe


def test_separation_reports_auc_of_the_gate_confidence():
    rows = [gate_row("a", 0.9, True), gate_row("b", 0.5, False, p_top=0.3)]
    sep = cg.separation(rows, GateConfig())
    assert sep["auc"] == 1.0 and sep["confidence_when_right"][0] > sep["confidence_when_wrong"][0]


# ---------------- judge ----------------
class StubJudge:
    """Marks a claim unsupported when it mentions 'prune' (the planted fault); everything else supported."""

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def complete_json(self, system, user, max_tokens=1500):
        self.calls += 1
        if self.fail:
            raise RuntimeError("quota")
        reply = user.split("REPLY:", 1)[1].split("EVIDENCE:", 1)[0]
        claims = [{"text": l.strip(), "verdict": "unsupported" if "prune" in l else "supported"} for l in reply.splitlines() if len(l.strip()) > 10]
        return {"claims": claims, "addresses_problem": "yes", "unsafe": "prune" in reply, "notes": ""}


def fix(fid, scenario, text="1. Restart Docker Desktop. [E1]\n2. Check the settings page. [E1]"):
    return {"id": fid, "scenario": scenario, "problem": "docker will not start", "tier": "kb", "gold": True, "message": text,
            "evidence": [{"evidence_id": "E1", "tier": "kb", "text": "Restart Docker Desktop. Check the settings page."}]}


def test_judge_scores_claims_and_reports_a_failed_call_instead_of_guessing():
    ok = judge.judge_one(StubJudge(), "p", fix("a", "S1")["message"], fix("a", "S1")["evidence"])
    assert ok["faithfulness"] == 1.0 and ok["addresses_problem"] == "yes" and ok["unsafe"] is False
    assert "error" in judge.judge_one(StubJudge(fail=True), "p", "m", fix("a", "S1")["evidence"])

    class Empty:
        def complete_json(self, *a, **k):
            return {"claims": [{"text": "x", "verdict": "maybe"}]}
    assert "error" in judge.judge_one(Empty(), "p", "m", fix("a", "S1")["evidence"])


def test_aggregate_ignores_judge_errors_and_averages_the_rest():
    agg = judge.aggregate([{"faithfulness": 1.0, "addresses_problem": "yes", "unsafe": False},
                           {"faithfulness": 0.5, "addresses_problem": "partly", "unsafe": True}, {"error": "x"}])
    assert agg == {"judged": 2, "judge_errors": 1, "faithfulness_mean": 0.75, "unsupported_rate": 0.5, "fully_supported_rate": 0.5,
                   "relevance_mean": 0.75, "unsafe_rate": 0.5}


def test_only_fixes_that_kept_their_evidence_are_judged():
    rows = [{"id": "S1", "opening": "o", "fixes_sent": [{"tier": "kb", "gold": True, "message": "m", "evidence": [{"evidence_id": "E1", "text": "t"}]},
                                                      {"tier": "kb", "gold": False, "sources": []}]}]
    got = judge.fixes_to_judge(rows)
    assert [g["id"] for g in got] == ["S1#1"]


def test_planted_faults_are_caught_by_a_working_judge_and_missed_by_a_blind_one():
    fixes = [fix("a", "S1"), fix("b", "S2"), fix("c", "S3")]
    assert "prune" in judge.plant_fabrication(fixes[0])["message"]
    assert judge.plant_wrong_evidence(fixes[0], fixes[1])["evidence"][0]["evidence_id"] == "E1"
    good = judge.self_check(StubJudge(), fixes, n=3)
    assert good["fabrication_caught_rate"] == 1.0 and good["fabrication_flagged_unsafe_rate"] == 1.0 and good["unmodified_faithfulness"] == 1.0

    class Blind:
        def complete_json(self, system, user, max_tokens=1500):
            return {"claims": [{"text": "everything", "verdict": "supported"}], "addresses_problem": "yes", "unsafe": False}
    assert judge.self_check(Blind(), fixes, n=3)["fabrication_caught_rate"] == 0.0


def test_report_warns_when_judge_is_the_generator_or_the_fake():
    e2e = {"meta": {"resolver_llm": "gemini", "resolver_model": "m1"}}
    text = judge.judge_report(e2e, "gemini:m1", [{"faithfulness": 1.0, "addresses_problem": "yes", "unsafe": False, "claims": []}], [fix("a", "S1")], None)
    assert "same model as the generator" in text
    text = judge.judge_report({"meta": {"resolver_llm": "fake"}}, "x:y", [], [], None)
    assert "FakeLLM" in text


# ---------------- held-out builder ----------------
def candidate(**kw):
    base = {"id": "H001", "ticket_id": "T-1", "url": "https://so/1", "title": "docker compose env file not loaded",
            "problem": "I use Ubuntu. ```code``` See https://x.y for more. The variable stays empty.", "errors": ["variable is not set"],
            "proposed": [{"path": "compose/env.md", "issue": "Substitute with `--env-file`", "score": 0.7}], "label": "1", "verified": True}
    return {**base, **kw}


def test_prose_drops_code_blocks_and_links():
    assert heldout.prose("I use Ubuntu. ```rm -rf /``` See https://x.y now. Second sentence.") == "I use Ubuntu. See now. Second sentence."
    assert len(heldout.prose("word " * 200, limit=50)) <= 50


def test_labels_become_gold_kb_gap_oos_or_nothing():
    gold = heldout.to_scenario(candidate())
    assert gold["gold"] == {"source_path_contains": "compose/env.md", "issue_contains": "Substitute with `--env-file`"}
    assert gold["hidden"]["platform"] == "linux" and gold["hidden"]["source_ticket_id"] == "T-1" and "stays empty" in gold["opening"]
    gap = heldout.to_scenario(candidate(label="kb_gap"))
    assert gap["gold"] is None and gap["note"].startswith("kb_gap") and gap["oos"] is False
    assert heldout.to_scenario(candidate(label="oos"))["oos"] is True
    assert heldout.to_scenario(candidate(label="skip")) is None and heldout.to_scenario(candidate(label=None)) is None
    with pytest.raises(SystemExit):
        heldout.to_scenario(candidate(label="maybe"))


def test_questions_already_in_the_other_sets_are_recognised_as_duplicates():
    assert heldout.jaccard("docker pull rate limit 429 error", "docker pull rate limit 429") > 0.6
    assert heldout.jaccard("docker pull rate limit", "volume mount permissions") < 0.2


def test_the_scenario_file_loads_as_scenarios_when_present():
    path = heldout.SCENARIOS
    if not path.exists():
        pytest.skip("held-out set not built")
    from triage.sim.customer import load_scenarios
    scenarios = load_scenarios(path)
    assert scenarios and all(s.id.startswith("H") for s in scenarios)
    assert all(s.gold is None or {"source_path_contains", "issue_contains"} <= set(s.gold) for s in scenarios)


# ---------------- cache pairs and e2e helpers ----------------
def test_pairs_are_same_only_when_the_gold_issue_is_the_same():
    items = [{"id": "a", "query": "q1", "gold": ("p", "x")}, {"id": "b", "query": "q2", "gold": ("p", "x")},
             {"id": "c", "query": "q3", "gold": ("p", "y")}, {"id": "d", "query": "q4", "gold": ("p", "z")}]
    sigs = {i: {"raw_query": i} for i in "abc"}                                    # d produced no signature
    pairs = cache_pairs.build_pairs(items, sigs)
    assert {tuple(p["ids"]): p["same"] for p in pairs} == {("a", "b"): True, ("a", "c"): False, ("b", "c"): False}


def test_gold_row_matches_like_the_evidence_version():
    gold = {"source_path_contains": "docker-hub/troubleshoot.md", "issue_contains": "pull rate limit"}
    row = {"tier": "kb", "doc_id": "content/manuals/docker-hub/troubleshoot.md#c1", "issue": "You have reached your pull rate limit (429)"}
    assert e2e_eval.is_gold_row(row, gold) and not e2e_eval.is_gold_row({**row, "tier": "tickets"}, gold)
    assert not e2e_eval.is_gold_row({**row, "doc_id": "other.md#1"}, gold)


def test_llm_usage_only_counts_events_after_the_offset(tmp_path):
    f = tmp_path / "events.jsonl"
    old = json.dumps({"event": "llm_call", "input_tokens": 999, "output_tokens": 1, "cost_usd": 9.0, "latency_ms": 5})
    f.write_text(old + "\n", encoding="utf-8")
    offset = f.stat().st_size
    with f.open("a", encoding="utf-8") as h:
        for ms in (100, 300):
            h.write(json.dumps({"event": "llm_call", "input_tokens": 10, "output_tokens": 2, "cost_usd": 0.001, "latency_ms": ms}) + "\n")
        h.write(json.dumps({"event": "gate"}) + "\n")
    u = e2e_eval.llm_usage(f, offset)
    assert (u["llm_calls"], u["input_tokens"], u["output_tokens"], u["cost_usd"]) == (2, 20, 4, 0.002)
    assert u["llm_latency_ms_p50"] == 300
    unpriced = tmp_path / "e2.jsonl"
    unpriced.write_text(json.dumps({"event": "llm_call", "cost_usd": None, "latency_ms": 1}) + "\n", encoding="utf-8")
    assert e2e_eval.llm_usage(unpriced, 0)["cost_usd"] is None                       # never a made-up price
