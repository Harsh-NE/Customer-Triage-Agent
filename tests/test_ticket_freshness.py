"""The opt-in penalty for tickets that lean on retired Docker tooling (TICKET_LEGACY_PENALTY). Off by default; offline."""

import pytest

from triage.eval import ticket_freshness_eval as F
from triage.hybrid import LEGACY_TERMS, legacy_penalty_for, rank_tickets, score_ticket
from triage.state import TicketHit


def row(i, title="Container exits", problem="it exits", resolution="Check the logs and fix the entrypoint. " * 3, **kw):
    base = {"ticket_id": f"T-{i}", "title": title, "problem": problem, "resolution": resolution, "trust_score": 0.9, "trust_tier": "high",
            "resolution_kind": "accepted_answer", "age_years": 2.0, "exit_codes": [], "errors_clean": [], "topics": [], "kind_guess": "troubleshooting",
            "url": f"https://example.org/{i}"}
    return {**base, **kw}


@pytest.mark.parametrize("text", ["docker-machine create fails", "run docker machine ssh default", "boot2docker VM not starting", "Docker Toolbox on Windows 7",
                                  "apt install docker-engine", "docker run --link db:db web", "the old Docker Cloud builds"])
def test_retired_tooling_is_recognised(text):
    assert LEGACY_TERMS.search(text), text


@pytest.mark.parametrize("text", ["docker pull fails with 429", "docker machine learning image for GPUs", "docker compose up --build", "Docker Desktop never starts",
                                  "docker build --network host", "the docker-compose.yml file"])
def test_current_tooling_is_not_flagged(text):
    assert not LEGACY_TERMS.search(text), text


def test_the_penalty_is_off_by_default_and_changes_nothing(monkeypatch):
    monkeypatch.delenv("TICKET_LEGACY_PENALTY", raising=False)
    old = row(1, title="docker-machine create fails")
    assert legacy_penalty_for(old, "container will not start") == 1.0
    assert "legacy_tooling" not in score_ticket(old, 1.0, "container will not start", set(), set())[1]


def test_when_on_it_halves_only_legacy_tickets_and_only_when_the_customer_did_not_mention_the_tooling(monkeypatch):
    long_fix = "Check the logs and fix the entrypoint then retry it. " * 4                    # long enough that the short-answer rule does not apply
    old, modern = row(1, resolution="Use docker-machine to recreate the VM then retry. " * 4), row(2, resolution=long_fix)
    monkeypatch.delenv("TICKET_LEGACY_PENALTY", raising=False)
    s_old_off = score_ticket(old, 1.0, "container will not start", set(), set())[0]
    monkeypatch.setenv("TICKET_LEGACY_PENALTY", "0.5")
    assert legacy_penalty_for(old, "container will not start") == 0.5
    assert legacy_penalty_for(old, "docker-machine create fails") == 1.0                    # they use it: the ticket is on topic
    assert legacy_penalty_for(modern, "container will not start") == 1.0
    s_old, why = score_ticket(old, 1.0, "container will not start", set(), set())
    assert "legacy_tooling" in why and s_old == pytest.approx(s_old_off * 0.5)


def test_ranking_prefers_the_modern_ticket_when_the_penalty_is_on(monkeypatch):
    rows = [row(1, resolution="Recreate it with docker-machine and retry the command carefully. " * 4), row(2, resolution="Check the logs and fix the entrypoint then retry it. " * 4)]
    fused = {"T-1": 0.0328, "T-2": 0.0320}
    monkeypatch.delenv("TICKET_LEGACY_PENALTY", raising=False)
    assert rank_tickets(rows, fused, "container exits", 2)[0][0]["ticket_id"] == "T-1"          # slightly better fused rank wins when nothing is penalised
    monkeypatch.setenv("TICKET_LEGACY_PENALTY", "0.5")
    assert rank_tickets(rows, fused, "container exits", 2)[0][0]["ticket_id"] == "T-2"


def hit(i, title="Fix", problem="p", resolution="r"):
    return TicketHit(ticket_id=f"T-{i}", title=title, problem_excerpt=problem, resolution=resolution, score=0.5, age_years=3.0)


def test_the_stale_proxy_ignores_tooling_the_customer_named_and_summarises_both_runs():
    assert F.stale(hit(1, "docker-machine fails"), "container exits") and not F.stale(hit(1, "docker-machine fails"), "docker-machine fails to start")
    assert not F.stale(hit(2), "container exits")
    qs = ["q1", "q2"]
    base = [[hit(1, "docker-machine fix"), hit(2)], [hit(3), hit(4)]]
    other = [[hit(2), hit(1, "docker-machine fix")], [hit(3), hit(4)]]
    out = F.summarize(qs, base, other)
    assert out["off"]["stale_share"] == 0.25 and out["penalty_on"]["stale_share"] == 0.25 and out["top1_changed"] == 1
    assert out["changed_examples"][0]["before"] == "docker-machine fix"
