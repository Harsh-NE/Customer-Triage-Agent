"""ablation: the stream, the arithmetic, the tables, and (on the real stores) the arm switches and one tiny end-to-end run."""

import csv
import json

import pytest

from triage import config
from triage.eval import ablation as A
from triage.eval import agent_metrics as M
from triage.eval import telemetry as T
from triage.features import ARMS, Features
from triage.resolver.contracts import CacheStatus, Evidence


class Scn:
    def __init__(self, i):
        self.id = i


def test_the_stream_is_every_scenario_then_a_seeded_sample_repeated():
    scenarios = [Scn(f"S{i}") for i in range(10)]
    stream = A.build_stream(scenarios, 0.3, seed=0)
    assert [p for p, _ in stream] == ["first_ask"] * 10 + ["repeat"] * 3
    assert [s.id for p, s in stream if p == "first_ask"] == [s.id for s in scenarios]
    assert [s.id for _, s in stream] == [s.id for _, s in A.build_stream(scenarios, 0.3, seed=0)]      # the same every time
    assert len({s.id for p, s in stream if p == "repeat"}) == 3


def test_wilson_interval_matches_known_values():
    assert A.wilson(6, 6) == (61.0, 100.0)
    assert A.wilson(0, 10)[0] == 0.0
    lo, hi = A.wilson(50, 100)
    assert (lo, hi) == (40.4, 59.6)


def test_fmt_shows_rates_with_interval_and_counts():
    assert A.fmt(M.rate(18, 29)) == "62.1% [44.0-77.3] (18/29)"
    assert A.fmt(M.rate(0, 0)) == "n/a" and A.fmt(None) == "n/a"
    assert A.fmt(1234.6) == "1,235"
    assert A.fmt(0.000713) == "0.000713" and A.fmt(12) == "12"


def fake_row(i, *, gold=True, first_gold=True, cached=False):
    fix = {"tier": "kb", "gold": first_gold, "cited": ["E1"], "message": "m", "evidence": []}
    return {"id": i, "opening": "q", "has_gold": gold, "oos": False, "kb_gap": not gold, "outcome": "resolved", "escalation_reason": None,
            "questions": 1, "asked": [{"message": "Which version?", "reply": "1"}], "fixes_sent": [fix], "first_gold": first_gold,
            "resolved_gold": gold and first_gold, "opening_facts": {}, "total_s": 1.0, "first_fix_s": 0.5,
            "gate_inputs": [] if cached else [{"tier": "kb", "evidence": [{"evidence_id": "E1", "gold": first_gold, "rerank_score": 0.9}]}]}


def pair(i, **kw):
    cached = kw.get("cached", False)
    row = fake_row(i, **kw)
    events = [{"event": "cache_lookup", "status": "hit_exact" if cached else "miss", "similarity": 1.0}]
    return row, T.case_record("A", "first_ask", row, events, {})


def test_measure_skips_cache_served_cases_for_retrieval_and_citations():
    pairs = [pair("a"), pair("b", first_gold=False), pair("c", cached=True)]
    m = A.measure(pairs, repeat_speedup=2.0)
    assert (m["first_attempt_correct"]["k"], m["first_attempt_correct"]["n"]) == (2, 3)       # the cached answer counts as a first fix
    assert (m["recall_at_3"]["k"], m["recall_at_3"]["n"]) == (1, 2)                           # but there was no search to score
    assert (m["citation_validity"]["k"], m["citation_validity"]["n"]) == (2, 2)
    assert m["questions_per_case"] == 1 and m["repeat_speedup"] == 2.0 and m["first_fix_p50_ms"] == 500.0


def test_questions_that_any_arm_served_from_the_cache_can_be_skipped_for_every_arm():
    pairs = [pair("a"), pair("b", first_gold=False)]
    assert A.measure(pairs, None)["recall_at_3"]["n"] == 2
    assert A.measure(pairs, None, skip={"b"})["recall_at_3"] == M.rate(1, 1)


def test_an_earlier_run_can_be_re_tabulated_from_its_logs(tmp_path):
    arm_a, arm_b = [pair("a"), pair("b")], [pair("a"), pair("b", cached=True)]       # arm B's cache answered question b
    records = [rec for _, rec in arm_a] + [rec | {"arm": "B"} for _, rec in arm_b]
    (tmp_path / "queries.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    for arm, pairs in (("A", arm_a), ("B", arm_b)):
        (tmp_path / f"rows_{arm}.json").write_text(json.dumps({"rows": [row for row, _ in pairs]}), encoding="utf-8")
    (tmp_path / "summary.json").write_text(json.dumps({"meta": {"arms": {"A": {}, "B": {}}, "baseline_arm": "A", "notes": []}}), encoding="utf-8")
    A.finish(*A.reload(tmp_path), tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert "recomputed" in summary["meta"]
    assert [summary["arms"][a]["metrics"]["recall_at_3"]["n"] for a in "AB"] == [1, 1]     # neither arm is scored on b: same questions for both
    assert (tmp_path / "comparison.md").exists() and (tmp_path / "comparison.csv").exists()


def test_every_core_metric_is_measured_and_every_telemetry_row_has_a_getter():
    m = A.measure([pair("a"), pair("b")], repeat_speedup=None)
    assert set(m) == {key for key, _, _ in A.CORE}
    assert len({label.split()[0] for _, label, _ in A.CORE}) == 9                              # nine numbered metrics


def arm_summary(pairs):
    s = A.summarize([("first_ask", row, record) for row, record in pairs])
    s["vs_baseline"] = T.versus(s["cost"], s["cost"])
    return s


def test_tables_are_written_for_the_paper(tmp_path):
    arms = {"A": arm_summary([pair("a"), pair("b")]), "B": arm_summary([pair("a"), pair("b", first_gold=False)])}
    rows = A.table(arms)
    A.write_markdown(tmp_path / "c.md", {"llm": "fake"}, rows, arms)
    A.write_csv(tmp_path / "c.csv", rows)
    md = (tmp_path / "c.md").read_text(encoding="utf-8")
    assert "| Metric | A baseline (no KG, no Jev) | B + KG |" in md and "## Definitions" in md and "1 First-attempt correct" in md
    lines = list(csv.DictReader((tmp_path / "c.csv").open(encoding="utf-8")))
    first = [r for r in lines if r["metric"] == "1 First-attempt correct"]
    assert [(r["arm"], r["k"], r["n"]) for r in first] == [("A", "2", "2"), ("B", "1", "2")]
    assert {r["arm"] for r in lines} == {"A", "B"}


def test_pacer_waits_for_old_calls_to_age_out_and_only_when_needed():
    now, slept = [0.0], []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    p = A.Pacer(10, headroom=4, clock=lambda: now[0], sleep=sleep)           # room for 6 calls in the last minute
    for _ in range(6):
        p.note_call()
    assert p.wait() == 0.0 and slept == []                                   # at the limit, not over it: no wait
    now[0] = 30.0
    p.note_call()                                                            # a seventh call, 30 s after the first six
    assert p.wait() == pytest.approx(30.1) and slept == [pytest.approx(30.1)]   # waits until the first six are a minute old
    assert len(p.calls) == 1


def test_pacer_without_a_limit_never_waits():
    p = A.Pacer(None, sleep=lambda s: pytest.fail("slept"))
    for _ in range(100):
        p.note_call()
    assert p.wait() == 0.0


def test_counting_llm_tells_the_pacer_about_every_call():
    calls = []
    pacer = type("P", (), {"note_call": lambda self: calls.append(1)})()
    llm = A.CountingLLM(type("M", (), {"complete_json": lambda self, *a, **k: {}})(), pacer)
    llm.complete_json("x"), llm.complete_json("y")
    assert len(calls) == 2


def test_counting_llm_counts_a_failure_then_lets_it_through():
    class Model:
        name, model, last_usage = "m", "model-1", {"input_tokens": 5}

        def complete_json(self, *args, **kwargs):
            if args and args[0] == "boom":
                raise RuntimeError("429 quota")
            return {"ok": True}

    llm = A.CountingLLM(Model(), retries=0)
    assert llm.complete_json("fine") == {"ok": True} and llm.failures == 0
    with pytest.raises(RuntimeError):
        llm.complete_json("boom")
    assert llm.failures == 1 and (llm.name, llm.model, llm.last_usage) == ("m", "model-1", {"input_tokens": 5})   # attributes pass through


class Flaky:
    """Fails `failures` times, then answers."""
    name, model, last_usage = "flaky", "m", {}

    def __init__(self, failures):
        self.left = failures

    def complete_json(self, *args, **kwargs):
        if self.left:
            self.left -= 1
            raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded for requests per minute")
        return {"ok": True}


def test_a_failed_call_is_retried_after_a_wait_and_only_counts_when_every_retry_fails():
    waits, calls = [], []
    pacer = type("P", (), {"note_call": lambda self: calls.append(1)})()
    llm = A.CountingLLM(Flaky(2), pacer, retries=2, wait_s=20, sleep=waits.append)
    assert llm.complete_json("x") == {"ok": True}
    assert (llm.failures, llm.retried, waits, len(calls)) == (0, 2, [20, 40], 3)           # waited 20 s then 40 s; every attempt counted for the pacer
    assert llm.errors[0].startswith("RuntimeError: 429 RESOURCE_EXHAUSTED")                  # the cause is kept, not just the count

    hopeless = A.CountingLLM(Flaky(99), retries=2, wait_s=0, sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        hopeless.complete_json("x")
    assert (hopeless.failures, hopeless.retried, len(hopeless.errors)) == (1, 2, 3)           # one failed call, three tries


def test_a_run_whose_calls_keep_failing_stops_with_the_last_error():
    run = type("Run", (), {"arm": "A", "counted": type("C", (), {"failures": 5, "errors": ["RuntimeError: quota"]})()})()
    with pytest.raises(SystemExit, match="STOPPED: 5 model calls failed.*quota"):
        A.check_failures([run], limit=5)
    A.check_failures([run], limit=6)                                                          # below the limit: carries on


def test_the_seed_is_set_by_re_running_the_command_when_it_is_missing(monkeypatch):
    seen = {}
    monkeypatch.setattr(A.subprocess, "call", lambda cmd, env: seen.update(cmd=cmd, env=env) or 7)
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    assert A.ensure_seed() == 7 and seen["env"]["PYTHONHASHSEED"] == "0" and seen["cmd"][1:3] == ["-m", "triage.eval.ablation"]
    monkeypatch.setenv("PYTHONHASHSEED", "3")
    assert A.ensure_seed() is None                                                            # already set: run as asked


def test_failed_calls_are_totalled_in_the_cost_summary_and_the_table():
    done = [("first_ask", *pair("a")), ("first_ask", *pair("b"))]
    done[1][2]["llm_errors"] = 2
    s = A.summarize(done)
    s["vs_baseline"] = T.versus(s["cost"], s["cost"])
    assert s["cost"]["llm_errors"] == 2
    assert dict((label, get(s)) for label, get in A.TELEMETRY)["Failed model calls (must be 0)"] == 2


class FakeCache:
    def __init__(self, status, evidence):
        self._res = type("Res", (), {"status": status, "entry": type("Entry", (), {"evidence": evidence})() if evidence else None})()

    def lookup(self, signature):
        return self._res

    def put(self, *a, **k):
        return "stored"


def test_recording_cache_shows_the_oracle_the_evidence_behind_a_cached_fix():
    ev = Evidence(evidence_id="E1", chunk_id="c", doc_id="d", tier="kb", text="t", rerank_score=0.9).to_dict()
    rec = type("Rec", (), {"calls": []})()
    cache = A.RecordingCache(FakeCache(CacheStatus.HIT_EXACT, [ev]), rec)
    assert cache.lookup(None).status == CacheStatus.HIT_EXACT
    assert rec.calls[-1][0] == "kb" and rec.calls[-1][1][0].evidence_id == "E1"
    assert cache.put() == "stored"                                              # everything else passes straight through
    miss = A.RecordingCache(FakeCache(CacheStatus.MISS, None), rec)
    miss.lookup(None)
    assert len(rec.calls) == 1                                                  # a miss records nothing


# ---------------------------------------------------------------- the real stores
STORE = config.PROJECT_ROOT / config.get_env()["VECTOR_DB_PATH"]


@pytest.mark.real_store
@pytest.mark.skipif(not (STORE / "chroma.sqlite3").exists(), reason="Docker vector store not built locally")
def test_the_flags_switch_the_kg_and_both_caches_on_the_real_system():
    from triage.joint import build_clarifier, build_default_deps
    from triage.resolver.llm import FakeLLM
    kb, deps = build_default_deps(FakeLLM(), features=Features(use_kg=False, use_semantic_cache=False))
    assert deps.cache is None and deps.negative_cache is None and deps.ontology is None and kb.ontology is None
    assert build_clarifier(kb).ontology is None
    kb, deps = build_default_deps(FakeLLM(), features=Features())
    assert deps.cache is not None and deps.negative_cache is not None and deps.ontology is not None
    assert build_clarifier(kb).ontology is not None and deps.jev is None


@pytest.mark.real_store
@pytest.mark.skipif(not (STORE / "chroma.sqlite3").exists(), reason="Docker vector store not built locally")
def test_a_tiny_stream_runs_and_a_repeat_is_served_from_the_cache(tmp_path):
    from triage.resolver.llm import FakeLLM
    from triage.sim.customer import load_scenarios
    scenarios = load_scenarios()[:2]
    stream = A.build_stream(scenarios, 1.0, seed=0)
    done = A.run_arm("A", ARMS["A"], stream, FakeLLM(), tmp_path)
    assert [p for p, _, _ in done] == ["first_ask"] * 2 + ["repeat"] * 2
    first = {row["id"]: (row, rec) for p, row, rec in done if p == "first_ask"}
    for p, row, rec in done:
        if p == "repeat" and first[row["id"]][0]["outcome"] == "resolved":
            assert rec["cache_served"] and rec["cache_served_correct"] and rec["llm_calls"] < first[row["id"]][1]["llm_calls"]
    assert all(json.dumps(rec) for _, _, rec in done)                           # every record is serialisable
    assert (tmp_path / "events_A.jsonl").exists()
    assert len((tmp_path / "queries.jsonl").read_text(encoding="utf-8").splitlines()) == 4        # written as each query finished
    assert all(rec["llm_errors"] == 0 and rec["llm_retries"] == 0 and rec["llm_error_details"] == [] for _, _, rec in done)


@pytest.mark.real_store
@pytest.mark.skipif(not (STORE / "chroma.sqlite3").exists(), reason="Docker vector store not built locally")
def test_the_arms_advance_together_and_take_turns_going_first(tmp_path):
    from triage.resolver.llm import FakeLLM
    from triage.sim.customer import load_scenarios
    stream = A.build_stream(load_scenarios()[:2], 0.0, seed=0)
    done = A.run_arms({"A": ARMS["A"], "B": ARMS["B"]}, stream, FakeLLM(), tmp_path)
    lines = [json.loads(line) for line in (tmp_path / "queries.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["arm"], r["id"]) for r in lines] == [("A", "S01"), ("B", "S01"), ("B", "S02"), ("A", "S02")]      # A first, then B first
    assert set(done) == {"A", "B"} and [len(d) for d in done.values()] == [2, 2]
