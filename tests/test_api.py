"""The HTTP backend, end to end and offline: demo-corpus retrieval, a metered fake LLM (1000 in / 200 out tokens per call, priced as
gemini-3.5-flash-lite), a real SQLite case store and a real SQLite LangGraph checkpointer."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver

from triage import pricing
from triage.api.app import create_app
from triage.api.settings import Settings
from triage.clarifier import Clarifier
from triage.eval.demo_corpus import demo_corpus
from triage.joint import build_joint_graph
from triage.resolver.adapters import KBEvidenceRetriever
from triage.resolver.cache import SemanticCache
from triage.resolver.graph import ResolverDeps
from triage.resolver.interface import LexicalRetriever, TieredRetriever, load_tickets_jsonl
from triage.resolver.llm import FakeLLM
from triage.retrieval import MockRetriever

FX = Path(__file__).resolve().parents[1] / "triage" / "resolver" / "fixtures"
RATE_LIMIT = "docker pull fails with 'You have reached your pull rate limit' HTTP 429 on Docker Hub"
AMBIGUOUS_429 = "docker pull on Docker Hub keeps failing with a 429"
IN_TOK, OUT_TOK = 1000, 200


class MeteredFake(FakeLLM):
    """FakeLLM that reports token usage on every call and can be told to fail while drafting."""

    def __init__(self, model="gemini-3.5-flash-lite", fail_draft=False):
        self.model, self.fail_draft = model, fail_draft
        self.name = f"metered:{model}"
        self.last_usage = {}

    def complete_json(self, system, user, max_tokens=1200):
        if self.fail_draft and "TASK: draft" in system:
            raise RuntimeError("provider is down")
        out = super().complete_json(system, user, max_tokens)
        self.last_usage = {"input_tokens": IN_TOK, "output_tokens": OUT_TOK}
        return out


def offline_factory(model="gemini-3.5-flash-lite", fail_draft=False):
    def factory(logger, settings):
        mock = MockRetriever(demo_corpus())
        tickets = LexicalRetriever(load_tickets_jsonl(FX / "tickets_mini.jsonl"), "tickets")
        deps = ResolverDeps(retriever=TieredRetriever(KBEvidenceRetriever(mock), tickets), llm=MeteredFake(model, fail_draft),
                            cache=SemanticCache(), logger=logger)
        saver = SqliteSaver(sqlite3.connect(settings.checkpoint_path, check_same_thread=False))
        return build_joint_graph(Clarifier(None, mock), deps, checkpointer=saver)
    return factory


def make_settings(tmp_path):
    return Settings(database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}", checkpoint_path=str(tmp_path / "cp.sqlite"),
                    secret="test-secret-which-is-long-enough-for-hs256", engineer_passcode="pw", resolver_llm="fake")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), offline_factory())) as c:
        yield c


def login(client, name, role="customer"):
    r = client.post("/api/auth/login", json={"username": name, "role": role, "passcode": "pw" if role == "engineer" else None})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def last(view, kind=None):
    msgs = [m for m in view["messages"] if kind is None or m["kind"] == kind]
    return msgs[-1]


def escalate(client, h, text=RATE_LIMIT):
    """Drive a conversation to RETRY_EXHAUSTED by rejecting every fix."""
    view = client.post("/api/conversations", json={"message": text}, headers=h).json()
    for _ in range(5):
        if view["status"] != "active" or last(view)["kind"] != "fix":
            break
        view = client.post(f"/api/conversations/{view['id']}/messages", json={"action": "not_fixed"}, headers=h).json()
    return view


# ---------------------------------------------------------------- auth
def test_login_roles_tokens_and_protection(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "eve", "role": "engineer", "passcode": "wrong"}).status_code == 403
    alice = login(client, "alice")
    assert client.get("/api/me", headers=alice).json() == {"id": 1, "username": "alice", "role": "customer"}
    assert client.post("/api/auth/login", json={"username": "alice", "role": "engineer", "passcode": "pw"}).status_code == 403   # no role switching
    assert client.get("/api/cases", headers=alice).status_code == 403
    assert client.get("/api/analytics/summary", headers=alice).status_code == 403
    assert client.post("/api/conversations", json={"message": "x"}, headers=login(client, "enid", "engineer")).status_code == 403
    assert client.post("/api/auth/login", json={"username": "a b!", "role": "customer"}).status_code == 422


# ---------------------------------------------------------------- customer flows
def test_clear_report_gets_a_cited_fix_and_resolves_on_the_customers_button(client):
    h = login(client, "alice")
    view = client.post("/api/conversations", json={"message": RATE_LIMIT}, headers=h).json()
    assert view["status"] == "active" and view["can_reply"] and view["id"].startswith("C-")
    fix = last(view)
    assert fix["kind"] == "fix" and fix["role"] == "agent" and fix["payload"]["steps"]
    src = fix["payload"]["sources"][0]
    assert src["official"] and src["url"].startswith("https://github.com/docker/docs") and src["id"] == "E1"
    assert set(fix["payload"]) == {"diagnosis", "steps", "verification", "sources"}           # customers never see scores
    done = client.post(f"/api/conversations/{view['id']}/messages", json={"action": "resolved"}, headers=h).json()
    assert done["status"] == "resolved" and not done["can_reply"] and done["closed_at"] and done["resolved_by"] == "agent"
    assert [m["role"] for m in done["messages"]][:2] == ["customer", "agent"] and last(done)["kind"] == "resolved"
    assert client.post(f"/api/conversations/{view['id']}/messages", json={"text": "more"}, headers=h).status_code == 409


def test_ambiguous_report_asks_a_question_with_menu_options_then_answers(client):
    h = login(client, "alice")
    view = client.post("/api/conversations", json={"message": AMBIGUOUS_429}, headers=h).json()
    q = last(view)
    assert q["kind"] == "question" and q["payload"]["feature"] and q["payload"]["options"] and "?" in q["content"] + "?"
    view = client.post(f"/api/conversations/{view['id']}/messages", json={"text": "Too Many Requests"}, headers=h).json()
    assert last(view)["kind"] == "fix" and view["status"] == "active"
    assert [m["role"] for m in view["messages"]] == ["customer", "agent", "customer", "agent"]


def test_out_of_scope_request_is_declined_and_never_reaches_engineers(client):
    h, eng = login(client, "alice"), login(client, "enid", "engineer")
    view = client.post("/api/conversations", json={"message": "how do I reset my Netflix password"}, headers=h).json()
    assert view["status"] == "declined" and not view["can_reply"] and last(view)["kind"] == "decline" and not view["escalated"]
    assert client.get("/api/cases", headers=eng).json()["total"] == 0
    assert client.get("/api/cases?status=declined", headers=eng).json()["total"] == 1


def test_history_feedback_and_polling(client):
    h = login(client, "alice")
    first = client.post("/api/conversations", json={"message": RATE_LIMIT}, headers=h).json()
    client.post(f"/api/conversations/{first['id']}/messages", json={"action": "resolved"}, headers=h)
    second = client.post("/api/conversations", json={"message": "how do I reset my Netflix password"}, headers=h).json()
    hist = client.get("/api/conversations", headers=h).json()["conversations"]
    assert [c["id"] for c in hist] == [second["id"], first["id"]] and hist[1]["status"] == "resolved" and hist[1]["duration_s"] >= 0
    assert client.post(f"/api/conversations/{first['id']}/feedback", json={"rating": 9}, headers=h).status_code == 422
    client.post(f"/api/conversations/{first['id']}/feedback", json={"rating": 5, "helpful": True, "comment": "great"}, headers=h)
    full = client.get(f"/api/conversations/{first['id']}", headers=h).json()
    assert full["feedback"] == {"rating": 5, "helpful": True, "comment": "great"}
    newer = client.get(f"/api/conversations/{first['id']}?after={full['messages'][1]['id']}", headers=h).json()
    assert [m["id"] for m in newer["messages"]] == [m["id"] for m in full["messages"][2:]]   # polling returns only what is new


def test_customers_cannot_see_each_others_conversations(client):
    a, b = login(client, "alice"), login(client, "bob")
    cid = client.post("/api/conversations", json={"message": RATE_LIMIT}, headers=a).json()["id"]
    assert client.get(f"/api/conversations/{cid}", headers=b).status_code == 404
    assert client.post(f"/api/conversations/{cid}/messages", json={"text": "hi"}, headers=b).status_code == 404
    assert client.post(f"/api/conversations/{cid}/feedback", json={"rating": 1}, headers=b).status_code == 404
    assert client.get("/api/conversations", headers=b).json()["conversations"] == []


# ---------------------------------------------------------------- escalation and the engineer
def test_rejected_fixes_escalate_into_the_engineer_queue_with_the_agents_reasoning(client):
    h, eng = login(client, "alice"), login(client, "enid", "engineer")
    view = escalate(client, h)
    assert view["status"] == "escalated" and view["escalated"] and view["can_reply"] and last(view)["kind"] == "escalation"
    q = client.get("/api/cases", headers=eng).json()
    assert q["total"] == 1 and q["cases"][0]["priority"] == "P2" and q["cases"][0]["reason"] == "RETRY_EXHAUSTED"
    case = client.get(f"/api/cases/{view['id']}", headers=eng).json()
    assert case["customer"] == "alice" and len(case["agent"]["attempts"]) >= 1 and case["agent"]["evidence"]
    first = case["agent"]["attempts"][0]["sources"][0]                 # each attempt keeps what it cited (the evidence list is overwritten)
    assert first["url"].startswith("https://github.com/docker/docs") and first["id"] == "E1" and first["tier"] == "kb"
    assert case["agent"]["hypotheses"] and case["agent"]["clarifier"]["status"] == "ready"
    assert case["agent"]["escalation"]["reason_code"] == "RETRY_EXHAUSTED" and case["agent"]["escalation"]["summary_md"]
    labels = [a["label"] for a in case["activity"]]
    assert any(l.startswith("Clarifier") for l in labels) and any(l.startswith("Evidence gate") for l in labels)
    assert any(l.startswith("Escalated") for l in labels) and any(l.startswith("LLM draft") for l in labels)
    assert case["usage"]["llm_calls"] >= 3 and case["usage"]["unpriced_calls"] == 0


def test_engineer_actions_reply_assign_priority_notes_resolve_reopen(client):
    h, eng = login(client, "alice"), login(client, "enid", "engineer")
    cid = escalate(client, h)["id"]
    base = f"/api/cases/{cid}"
    assert client.post(f"{base}/reply", json={"text": "Looking at this now."}, headers=eng).status_code == 200
    mine = client.get(f"/api/conversations/{cid}", headers=h).json()
    reply = last(mine, "engineer_reply")
    assert reply["author"] == "enid" and reply["content"] == "Looking at this now." and mine["assigned"]     # replying auto-assigns
    client.post(f"{base}/notes", json={"text": "customer is on the free tier"}, headers=eng)
    assert "free tier" not in str(client.get(f"/api/conversations/{cid}", headers=h).json())             # internal notes stay internal
    assert client.get(base, headers=eng).json()["notes"][0]["body"] == "customer is on the free tier"
    assert client.post(f"{base}/priority", json={"priority": "P9"}, headers=eng).status_code == 422
    assert client.post(f"{base}/priority", json={"priority": "P1"}, headers=eng).json()["priority"] == "P1"
    client.post(f"/api/conversations/{cid}/messages", json={"text": "it is urgent, thanks"}, headers=h)     # customer can still write
    assert any(m["content"] == "it is urgent, thanks" for m in client.get(base, headers=eng).json()["messages"])
    assert client.post(f"{base}/resolve", json={"resolution": ""}, headers=eng).status_code == 422
    done = client.post(f"{base}/resolve", json={"resolution": "Authenticate with docker login.", "promote_to_kb": True}, headers=eng).json()
    assert done["status"] == "resolved" and done["resolved_by"] == "engineer" and done["promote_to_kb"] and done["resolution_text"]
    assert [a["action"] for a in done["actions"]] == ["reply", "note", "priority", "resolve"]
    assert client.get(f"/api/conversations/{cid}", headers=h).json()["status"] == "resolved"
    assert client.post(f"/api/conversations/{cid}/messages", json={"text": "x"}, headers=h).status_code == 409
    assert client.post(f"{base}/reply", json={"text": "late"}, headers=eng).status_code == 409           # closed: reopen first
    assert client.post(f"{base}/reopen", headers=eng).json()["status"] == "escalated"
    assert client.post(f"{base}/reopen", headers=eng).status_code == 409
    assert client.post("/api/cases/C-doesnotexist/reply", json={"text": "x"}, headers=eng).status_code == 404


def test_queue_filters_and_ordering(client):
    h, eng = login(client, "alice"), login(client, "enid", "engineer")
    ids = [escalate(client, h)["id"] for _ in range(2)]
    client.post(f"/api/cases/{ids[1]}/priority", json={"priority": "P1"}, headers=eng)
    client.post(f"/api/cases/{ids[0]}/assign", json={}, headers=eng)
    cases = client.get("/api/cases", headers=eng).json()["cases"]
    assert [c["id"] for c in cases] == [ids[1], ids[0]]                                       # P1 before P2
    assert [c["id"] for c in client.get("/api/cases?priority=P1", headers=eng).json()["cases"]] == [ids[1]]
    assert [c["id"] for c in client.get("/api/cases?assigned=unassigned", headers=eng).json()["cases"]] == [ids[1]]
    assert [c["id"] for c in client.get("/api/cases?assigned=enid", headers=eng).json()["cases"]] == [ids[0]]
    assert client.get("/api/cases?reason=LOW_EVIDENCE", headers=eng).json()["total"] == 0
    assert client.get("/api/cases?q=pull", headers=eng).json()["total"] == 2
    assert client.get("/api/cases?status=all", headers=eng).json()["total"] == 2


# ---------------------------------------------------------------- resilience and persistence
def test_a_failing_llm_escalates_the_conversation_instead_of_stranding_the_customer(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), offline_factory(fail_draft=True))) as client:
        h, eng = login(client, "alice"), login(client, "enid", "engineer")
        view = client.post("/api/conversations", json={"message": RATE_LIMIT}, headers=h).json()
        assert view["status"] == "escalated" and last(view)["role"] == "system" and "support engineer" in last(view)["content"]
        case = client.get(f"/api/cases/{view['id']}", headers=eng).json()
        assert case["reason"] == "SYSTEM_ERROR" and case["priority"] == "P2" and "provider is down" in case["agent"]["error"]
        assert any(a["level"] == "error" for a in case["activity"])


def test_a_conversation_survives_a_server_restart(tmp_path):
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, offline_factory())) as first:
        h = login(first, "alice")
        cid = first.post("/api/conversations", json={"message": AMBIGUOUS_429}, headers=h).json()["id"]
        assert last(first.get(f"/api/conversations/{cid}", headers=h).json())["kind"] == "question"
    with TestClient(create_app(settings, offline_factory())) as second:                       # new process, same files
        h = login(second, "alice")
        assert second.get("/api/conversations", headers=h).json()["conversations"][0]["id"] == cid
        view = second.post(f"/api/conversations/{cid}/messages", json={"text": "Too Many Requests"}, headers=h).json()
        assert last(view)["kind"] == "fix"                                                    # the graph resumed mid-conversation


# ---------------------------------------------------------------- cost and analytics
def test_cost_is_computed_from_the_price_table_per_call_and_per_conversation(client):
    h, eng = login(client, "alice"), login(client, "enid", "engineer")
    cid = client.post("/api/conversations", json={"message": RATE_LIMIT}, headers=h).json()["id"]
    client.post(f"/api/conversations/{cid}/messages", json={"action": "resolved"}, headers=h)
    usage = client.get(f"/api/cases/{cid}", headers=eng).json()["usage"]
    per_call = pricing.cost_usd("gemini-3.5-flash-lite", {"input_tokens": IN_TOK, "output_tokens": OUT_TOK})
    assert per_call == pytest.approx((IN_TOK * 0.30 + OUT_TOK * 2.50) / 1e6)
    assert usage["llm_calls"] >= 3                                                          # scope + draft + classify
    assert usage["input_tokens"] == usage["llm_calls"] * IN_TOK and usage["output_tokens"] == usage["llm_calls"] * OUT_TOK
    assert usage["cost_usd"] == pytest.approx(usage["llm_calls"] * per_call) and usage["unpriced_calls"] == 0


def test_unpriced_models_are_reported_as_unpriced_never_as_free(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), offline_factory(model="mystery-model-9"))) as client:
        h, eng = login(client, "alice"), login(client, "enid", "engineer")
        cid = client.post("/api/conversations", json={"message": RATE_LIMIT}, headers=h).json()["id"]
        usage = client.get(f"/api/cases/{cid}", headers=eng).json()["usage"]
        assert usage["llm_calls"] >= 2 and usage["unpriced_calls"] == usage["llm_calls"] and usage["cost_usd"] == 0
        overall = client.get("/api/analytics/cost", headers=eng).json()["overall"]
        assert overall["unpriced_calls"] == overall["llm_calls"] and overall["total_cost_usd"] == 0
        assert "mystery-model-9" in client.get("/api/analytics/cost", headers=eng).json()["by_model"]
        assert "mystery-model-9" not in client.get("/api/health").json()["priced_models"]


def test_dashboard_numbers_follow_the_stored_rows(client):
    a, b, c = login(client, "alice"), login(client, "bob"), login(client, "carol")
    eng = login(client, "enid", "engineer")
    ok = client.post("/api/conversations", json={"message": RATE_LIMIT}, headers=a).json()["id"]
    client.post(f"/api/conversations/{ok}/messages", json={"action": "resolved"}, headers=a)
    client.post(f"/api/conversations/{ok}/feedback", json={"rating": 5, "helpful": True}, headers=a)
    esc = escalate(client, b)["id"]
    client.post("/api/conversations", json={"message": "how do I reset my Netflix password"}, headers=c)
    client.post("/api/conversations", json={"message": AMBIGUOUS_429}, headers=c)                  # left waiting on a question
    s = client.get("/api/analytics/summary?days=7", headers=eng).json()
    assert s["totals"] == {"conversations": 4, "active": 1, "resolved": 1, "resolved_by_agent": 1, "resolved_by_engineer": 0,
                           "escalated_open": 1, "declined": 1}
    assert s["rates"]["resolution_rate"] == 0.5 and s["rates"]["agent_resolution_rate"] == 0.5     # 1 / (1 resolved + 1 escalated)
    assert s["rates"]["decline_rate"] == pytest.approx(1 / 3, abs=1e-3)                             # 1 of 3 FINISHED conversations
    assert s["feedback"] == {"avg_rating": 5.0, "ratings": 1, "helpful_rate": 1.0, "helpful_votes": 1}
    assert s["escalation_reasons"] == {"RETRY_EXHAUSTED": 1} and s["agent_behaviour"]["cache_lookups"] >= 2
    assert s["agent_behaviour"]["avg_questions_per_conversation"] == 0.25                           # one question across four conversations
    assert s["timing"]["avg_time_to_resolution_s"] is not None and "resolution_rate" in s["definitions"]
    cost = client.get("/api/analytics/cost", headers=eng).json()
    assert cost["overall"]["total_cost_usd"] == pytest.approx(s["cost"]["total_cost_usd"]) and cost["overall"]["unpriced_calls"] == 0
    assert set(cost["by_node"]) >= {"scope", "draft", "classify"} and "gemini-3.5-flash-lite" in cost["by_model"]
    assert cost["by_model"]["gemini-3.5-flash-lite"]["calls"] == cost["overall"]["llm_calls"]
    series = client.get("/api/analytics/timeseries", headers=eng).json()["days"]
    assert sum(d["created"] for d in series) == 4
    # bob's identical problem was served from alice's confirmed fix (no retrieval, no draft call): 2 LLM calls instead of 3
    assert s["agent_behaviour"]["cache_hit_rate"] == 0.5
    assert s["cost"]["avg_cost_escalated_usd"] < s["cost"]["avg_cost_resolved_usd"]


def test_pricing_table_lookup():
    assert pricing.price_for("google/gemini-3.5-flash-lite") == pricing.price_for("Gemini-3.5-Flash-Lite")
    assert pricing.cost_usd("gemini-3.5-flash-lite", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}) == pytest.approx(2.80)
    assert pricing.cost_usd("gemini-3.5-flash-lite", {"input_tokens": 1_000_000, "cached_input_tokens": 1_000_000}) == pytest.approx(0.03)
    assert pricing.cost_usd("no-such-model", {"input_tokens": 5}) is None and pricing.cost_usd("", {}) is None
    assert pricing.table()["retrieved"] and pricing.price_for("gemini-3.5-flash-lite")["source"].startswith("https://openrouter.ai")


# ---------------------------------------------------------------- the real stores behind the same API
@pytest.mark.real_store
def test_real_stores_through_the_api(tmp_path):
    from triage import config
    needed = [config.PROJECT_ROOT / config.get_env()["VECTOR_DB_PATH"] / "chroma.sqlite3",
              config.PROJECT_ROOT / config.get_env()["TICKETS_STORE_PATH"] / "tickets.db"]
    if not all(p.exists() for p in needed):
        pytest.skip("real KB / ticket stores not built locally")
    try:
        app = create_app(make_settings(tmp_path))                  # real_graph_factory, resolver_llm = "fake" (offline)
        ctx = TestClient(app)
        client = ctx.__enter__()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"embedding model/stores unavailable: {exc}")
    try:
        h = login(client, "alice")
        view = client.post("/api/conversations", json={"message": "docker commands fail and say they cannot connect to the docker daemon on linux"}, headers=h).json()
        assert last(view)["kind"] == "question" and last(view)["payload"]["options"]                  # the menu arrives as buttons
        view = client.post(f"/api/conversations/{view['id']}/messages", json={"text": "1"}, headers=h).json()
        fix = last(view)
        assert fix["kind"] == "fix" and fix["payload"]["sources"][0]["official"]
        assert "engine/daemon/troubleshoot.md" in fix["payload"]["sources"][0]["url"]
        done = client.post(f"/api/conversations/{view['id']}/messages", json={"action": "resolved"}, headers=h).json()
        assert done["status"] == "resolved"
        declined = client.post("/api/conversations", json={"message": "how do I reset my Netflix password"}, headers=h).json()
        assert declined["status"] == "declined"
        eng = login(client, "enid", "engineer")
        summary = client.get("/api/analytics/summary", headers=eng).json()
        assert summary["totals"]["resolved"] == 1 and summary["totals"]["declined"] == 1
    finally:
        ctx.__exit__(None, None, None)


# ---------------------------------------------------------------- serving the built frontend
def test_the_api_can_serve_the_built_frontend_with_client_side_routing(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("do not serve", encoding="utf-8")
    settings = make_settings(tmp_path)
    settings.frontend_dir = str(dist)
    with TestClient(create_app(settings, offline_factory())) as client:
        assert "<title>app</title>" in client.get("/").text
        assert "<title>app</title>" in client.get("/chat/C-abc12345").text              # a deep link opens the app, not a 404
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/api/nope").status_code == 404 and client.get("/api/nope").headers["content-type"].startswith("application/json")
        assert "do not serve" not in client.get("/..%2fsecret.txt").text and "do not serve" not in client.get("/../secret.txt").text
        assert client.get("/api/health").json()["status"] == "ok"                       # the API is unaffected


def test_without_a_built_frontend_the_api_has_no_catch_all(tmp_path):
    settings = make_settings(tmp_path)
    settings.frontend_dir = str(tmp_path / "does-not-exist")
    with TestClient(create_app(settings, offline_factory())) as client:
        assert client.get("/").status_code == 404
