"""agent_metrics: the metric arithmetic on small hand-made rows, and the log audit on hand-made events. No model, no stores."""

import json
import sqlite3

from triage.eval import agent_metrics as M


def row(i, *, gold=True, oos=False, outcome="resolved", fixes=(), asked=(), facts=None, first_gold=None, **kw):
    fixes = [{"tier": t, "gold": g, "cited": ["E1"], "message": "m", "evidence": []} for t, g in fixes]
    return {"id": i, "has_gold": gold, "oos": oos, "kb_gap": not gold and not oos, "outcome": outcome, "escalation_reason": None,
            "questions": len(asked), "asked": [{"message": m, "reply": r} for m, r in asked], "fixes_sent": fixes,
            "first_gold": bool(fixes and fixes[0]["gold"]) if first_gold is None else first_gold,
            "resolved_gold": outcome == "resolved" and any(f["gold"] for f in fixes), "opening_facts": facts or {}, "gate_inputs": [], **kw}


def test_correct_end_needs_no_kb_fix_when_there_is_no_gold():
    assert M.correct_end(row("a", fixes=[("kb", True)]))
    assert not M.correct_end(row("b", fixes=[("kb", False)], outcome="escalated"))
    assert M.correct_end(row("c", gold=False, outcome="escalated"))
    assert not M.correct_end(row("d", gold=False, outcome="resolved", fixes=[("kb", False)]))
    assert not M.correct_end(row("e", gold=False, oos=True, outcome="rejected", fixes=[("tickets", False)]))        # out of scope: no fix at all


def test_pass_hat_k_counts_runs_that_are_all_right():
    out = M.pass_hat_k({"a": [True, True, True], "b": [True, False, True], "c": [False, False, False]})
    assert out["pass^1"] == round((1 + 2 / 3 + 0) / 3, 3)
    assert out["pass^3"] == round((1 + 0 + 0) / 3, 3)                     # only scenario a is right in all three


def test_resolution_and_safe_decisions():
    rows = [row("g1", fixes=[("kb", True)]),
            row("g2", fixes=[("kb", False), ("kb", True)]),                                  # right on the second attempt
            row("g3", outcome="escalated"),                                                  # gold, but gave up
            row("n1", gold=False, outcome="escalated"),
            row("n2", gold=False, outcome="resolved", fixes=[("kb", False)])]               # sent a KB fix where none exists
    res = M.resolution([rows])
    assert (res["gold_first_attempt_correct"]["k"], res["gold_first_attempt_correct"]["n"]) == (1, 3)
    assert res["gold_fixed_within_2_attempts"]["k"] == 2
    safe = M.safe_decisions(rows)
    assert (safe["wrong_fix_rate"]["k"], safe["wrong_fix_rate"]["n"]) == (2, 5)                # g2's first fix and n2's fix
    assert (safe["escalation_recall"]["k"], safe["escalation_recall"]["n"]) == (1, 2)
    assert (safe["escalation_precision"]["k"], safe["escalation_precision"]["n"]) == (1, 2)    # g3 was escalated needlessly
    assert safe["unnecessary_escalation_rate"]["k"] == 1


def test_effort_flags_repeats_and_questions_about_what_the_opening_said():
    plat = "Which operating system are you using? (Windows, macOS, Linux)"
    rows = [row("a", asked=[(plat, "I'm not sure"), (plat, "windows")], facts={"platform": "windows"}, vagueness="low"),
            row("b", asked=[], vagueness="low")]
    e = M.effort(rows)
    assert e["repeated_question_rate"]["k"] == 1
    assert e["redundant_question_rate"]["k"] == 1                          # asked the platform though the opening gave it (counted once)
    assert e["not_sure_answer_rate"]["k"] == 1
    assert e["zero_question_rate_clear_openings"]["k"] == 1 and e["question_type_mix"] == {"platform": 2}


def test_retrieval_ranks_and_context_precision():
    def gi(flags):
        return {"tier": "kb", "evidence": [{"gold": f, "rerank_score": 0.9 - i / 10, "evidence_id": f"E{i}"} for i, f in enumerate(flags)]}
    rows = [row("a", gate_inputs=[gi([True, False, False])]), row("b", gate_inputs=[gi([False, False, True, True])]),
            row("c", gate_inputs=[gi([False, False])])]
    r = M.retrieval(rows)
    assert (r["recall@1"]["k"], r["recall@3"]["k"], r["recall@8"]["k"]) == (1, 2, 2)
    assert r["mrr"] == round((1 + 1 / 3 + 0) / 3, 3)
    assert r["context_precision"] == round((1.0 + (1 / 3 + 2 / 4) / 2 + 0) / 3, 3)


def test_cost_and_speed_leave_cost_empty_for_unpriced_models():
    rows = [row("a", fixes=[("kb", True)], total_s=4.0, first_reply_s=1.0, usage={"cost_usd": 0.02, "llm_calls": 3, "input_tokens": 1000, "output_tokens": 100}),
            row("b", outcome="escalated", total_s=8.0, first_reply_s=2.0, usage={"cost_usd": 0.01, "llm_calls": 2, "input_tokens": 500, "output_tokens": 50})]
    out = M.cost_speed(rows)
    assert out["cost_per_verified_resolution_usd"] == 0.03 and out["tokens_per_verified_resolution"] == 1650        # the escalated case's cost counts too
    rows[1]["usage"]["cost_usd"] = None
    assert M.cost_speed(rows)["total_cost_usd"] is None


def test_audit_reports_missing_fields_and_incomplete_conversations():
    events = [{"event": "llm_call", "conversation_id": "c1", "model": "m", "node": "draft", "latency_ms": 5, "input_tokens": 1, "output_tokens": 1,
               "cost_usd": None, "status": "ok"},
              {"event": "gate", "conversation_id": "c1", "decision": "answer", "confidence": 0.8, "tier": "kb", "reasons": []},
              {"event": "outcome", "conversation_id": "c1", "outcome": "resolved", "attempts": 1},
              {"event": "gate", "conversation_id": "c2", "decision": "escalate", "confidence": 0.2, "tier": "kb", "reasons": ["x"]}]
    a = M.audit_events(events)
    assert a["fields_present"]["llm_call"]["cost_usd"]["k"] == 0 and a["unpriced_llm_calls"]["k"] == 1
    assert a["conversation_has"]["outcome"]["k"] == 1 and a["conversations"] == 2
    assert "trace id on every event" in a["not_logged"] and "decision reason (answer / ask / escalate)" not in a["not_logged"]


def test_database_events_and_online_numbers(tmp_path):
    db = tmp_path / "app.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE agent_events (id INTEGER PRIMARY KEY, conversation_id TEXT, ts TEXT, event TEXT, node TEXT, model TEXT, latency_ms REAL,
                                   input_tokens INT, output_tokens INT, cost_usd REAL, data TEXT);
        CREATE TABLE conversations (id TEXT, status TEXT, escalation_reason TEXT, rating INT, helpful INT, resolved_by TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id TEXT, role TEXT, created_at TEXT);""")
    con.execute("INSERT INTO agent_events VALUES (1,'c1','t','llm_call','draft','m',12.0,10,5,0.01,?)", (json.dumps({"status": "ok"}),))
    con.execute("INSERT INTO conversations VALUES ('c1','resolved',NULL,5,1,'agent')")
    con.execute("INSERT INTO messages VALUES (1,'c1','customer','2026-01-01T10:00:00Z')")
    con.execute("INSERT INTO messages VALUES (2,'c1','agent','2026-01-01T10:00:07Z')")
    con.commit()
    con.close()
    ev = M.load_db_events(db)
    assert ev[0]["cost_usd"] == 0.01 and ev[0]["status"] == "ok" and ev[0]["conversation_id"] == "c1"
    online = M.online_from_db(db)
    assert online["time_to_first_agent_reply_seconds"]["p50"] == 7.0
    assert online["cost_per_conversation_usd"]["mean"] == 0.01 and online["helpful_rate"]["k"] == 1 and online["mean_rating"] == 5
