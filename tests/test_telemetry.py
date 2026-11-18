"""telemetry: the per-query record and the cache, latency and cost summaries, on hand-made rows and events."""

import pytest

from triage.eval import telemetry as T


def row(i="S1", *, fixes=(True,), outcome="resolved", total_s=2.0, first_fix_s=1.0, gold=True):
    return {"id": i, "opening": "q", "has_gold": gold, "outcome": outcome, "escalation_reason": None, "questions": 1,
            "fixes_sent": [{"gold": g} for g in fixes], "total_s": total_s, "first_fix_s": first_fix_s}


def llm_event(tokens_in=100, tokens_out=20, cost=0.001):
    return {"event": "llm_call", "input_tokens": tokens_in, "output_tokens": tokens_out, "cost_usd": cost, "latency_ms": 5}


def record(arm="A", phase="first_ask", *, cache="miss", fixes=(True,), calls=1, cost=0.001, total_s=2.0, **kw):
    events = [{"event": "cache_lookup", "status": cache, "similarity": 0.9}] + [llm_event(cost=cost)] * calls
    return T.case_record(arm, phase, row(fixes=fixes, total_s=total_s, **kw), events, {"use_kg": True})


def test_case_record_reads_cache_cost_and_timing_from_the_events():
    events = [{"event": "cache_lookup", "status": "hit_semantic", "similarity": 0.95},
              {"event": "retrieval", "latency_ms": 300.0}, {"event": "stage_timing", "stage": "gate", "latency_ms": 1.5},
              llm_event(100, 20, 0.001), llm_event(50, 10, 0.0005),
              {"event": "jev_call", "input_tokens": 200, "cost_usd": 0.0000084}]
    r = T.case_record("B", "repeat", row(), events, {"use_kg": True})
    assert (r["arm"], r["phase"], r["cache_status"], r["cache_served"], r["cache_served_correct"]) == ("B", "repeat", "hit_semantic", True, True)
    assert (r["llm_calls"], r["input_tokens"], r["cost_usd"]) == (2, 150, 0.0015)
    assert (r["jev_calls"], r["jev_input_tokens"], r["jev_cost_usd"]) == (1, 200, 0.0000084)
    assert r["retrieval_ms"] == [300.0] and r["stage_ms"] == {"gate": 1.5} and r["first_fix_s"] == 1.0


def test_jev_calls_overrides_errors_and_the_first_probability_are_recorded():
    events = [{"event": "jev_call", "p": 0.95, "override": True, "input_tokens": 300, "cost_usd": 0.00001},
              {"event": "jev_call", "p": 0.2, "override": False, "input_tokens": 300, "cost_usd": 0.00001},
              {"event": "jev_call", "error": "RuntimeError: 503"}]
    r = T.case_record("C", "first_ask", row(), events, {})
    assert (r["jev_calls"], r["jev_p"], r["jev_overrides"], r["jev_errors"]) == (3, 0.95, 1, 1)
    assert (r["jev_input_tokens"], r["jev_cost_usd"]) == (600, 0.00002)                 # a failed call costs nothing
    cost = T.cost_summary([r])
    assert (cost["jev_calls"], cost["jev_overrides"], cost["jev_errors"]) == (3, 1, 1)


def test_a_case_that_never_consulted_the_cache_is_marked_none():
    r = T.case_record("A", "first_ask", row(), [], {})
    assert r["cache_status"] == "none" and not r["cache_served"] and r["jev_cost_usd"] == 0.0


def test_cache_hit_rate_precision_and_false_hits():
    records = [record(cache="hit_exact"), record(cache="hit_semantic", fixes=(False,)), record(cache="miss"), record(cache="hit_redraft")]
    c = T.cache_summary(records + [T.case_record("A", "first_ask", row(), [], {})])
    assert (c["hit_rate"]["k"], c["hit_rate"]["n"]) == (2, 4)                  # the case that never looked is not counted
    assert (c["precision"]["k"], c["precision"]["n"]) == (1, 2)
    assert (c["false_hit_rate"]["k"], c["false_hit_rate"]["n"]) == (1, 2)
    assert c["redraft_rate"]["k"] == 1


def test_a_cache_hit_on_a_case_with_no_documented_answer_is_a_false_hit():
    r = record(cache="hit_exact", gold=False, fixes=(False,))
    assert T.cache_summary([r])["false_hit_rate"]["value"] == 1.0


def test_latency_percentiles_and_repeat_speedup_compares_like_with_like():
    records = [record(total_s=s) for s in (1.0, 2.0, 3.0)]
    records += [record(phase="repeat", cache="hit_exact", total_s=0.5), record(phase="repeat", total_s=9.0)]     # the second repeat missed the cache
    lat = T.latency_summary(records)
    assert lat["end_to_end_ms"]["p50"] == 2000.0                               # nearest rank of 500, 1000, 2000, 3000, 9000
    assert lat["repeat_speedup"] == 4.0                                        # resolved first asks p50 2000 ms / cache-served repeat 500 ms
    assert lat["end_to_end_ms_by_phase"]["repeat"]["n"] == 2
    assert T.latency_summary([record(total_s=2.0)])["repeat_speedup"] is None   # nothing was served from the cache


def test_cost_totals_are_none_when_a_called_model_has_no_price():
    assert T.cost_summary([record(cost=0.002), record(cost=0.003)])["cost_usd"] == 0.005
    assert T.cost_summary([record(cost=None)])["cost_usd"] is None
    assert T.cost_summary([record(calls=0, cost=None)])["cost_usd"] == 0.0     # no call, nothing to price


def test_cache_savings_estimate_uses_the_average_paid_case():
    records = [record(calls=2, cost=0.001), record(calls=4, cost=0.001), record(cache="hit_exact", calls=0, cost=None)]
    s = T.cache_savings(records)
    assert s["served_from_cache"] == 1 and s["avoided_llm_calls"] == 3.0


def test_a_served_case_is_not_free_its_own_calls_are_subtracted():
    records = [record(calls=3, cost=0.001), record(cache="hit_exact", calls=1, cost=0.001)]       # the served case still classified the reply
    s = T.cache_savings(records)
    assert s["avoided_llm_calls"] == 2.0 and s["avoided_cost_usd"] == pytest.approx(0.002)           # 3 - 1 calls, 0.003 - 0.001 USD


def test_versus_reports_percent_saved_and_none_without_a_baseline():
    v = T.versus({"llm_calls": 60, "input_tokens": 500, "cost_usd": None}, {"llm_calls": 100, "input_tokens": 1000, "cost_usd": None})
    assert v == {"llm_calls_saved_vs_baseline": 40.0, "input_tokens_saved_vs_baseline": 50.0, "cost_usd_saved_vs_baseline": None}
    assert T.versus({"llm_calls": 5, "input_tokens": 0}, {"llm_calls": 0, "input_tokens": 0})["llm_calls_saved_vs_baseline"] is None
