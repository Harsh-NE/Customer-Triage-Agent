"""scripts/14_export_for_labelling.py: it refuses without consent, masks personal data and secrets, hides who wrote what, never exports the system's
outcome as a label, and skips engineers, screenshot-only openings and questions already in the gold set. Offline, on a throwaway database."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from triage.api.db import Conversation, Message, User, init_db, make_engine, session_factory

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("export_for_labelling", ROOT / "scripts" / "14_export_for_labelling.py")
X = importlib.util.module_from_spec(spec)
spec.loader.exec_module(X)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "app.db"
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    init_db(engine)
    with session_factory(engine)() as s:
        s.add_all([User(username="alice_real_name", role="customer"), User(username="enid", role="engineer")])
        s.flush()
        alice, enid = 1, 2

        def conv(cid, user, first, status="resolved", reason=None, payload=None):
            s.add(Conversation(id=cid, user_id=user, title=first[:40], status=status, escalation_reason=reason))
            s.add(Message(conversation_id=cid, role="customer", kind="text", content=first, payload=payload or {}, author_id=user))
        conv("C-1", alice, "docker login fails for jane.doe@example.com password: hunter2 token ghp_ABCDEFGHIJKLMNOP1234")
        conv("C-2", alice, "container keeps restarting, exit code 1", status="escalated", reason="LOW_EVIDENCE")
        conv("C-3", enid, "an engineer's own test message about docker")
        conv("C-4", alice, "(screenshot attached)", payload={"attachment": {"id": "x.png", "text": "ERROR: password=secret123 failed"}})
        conv("C-5", alice, "docker", status="active")                                    # an opening that is already in the gold set
        s.commit()
    return path


def test_it_refuses_to_run_without_the_consent_flag(db, tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "14_export_for_labelling.py"), "--db", str(db), "--out-dir", str(tmp_path / "out")],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode != 0 and "agreement" in (result.stderr + result.stdout) and not (tmp_path / "out").exists()


def test_personal_data_and_secrets_are_masked(db):
    rows = X.export(db, set())
    first = next(r for r in rows if "docker login" in r["opening"])
    assert "jane.doe@example.com" not in first["opening"] and "hunter2" not in first["opening"] and "ghp_" not in first["opening"]


def test_nobody_can_be_identified_and_the_systems_outcome_is_only_a_hint(db):
    rows = X.export(db, set())
    blob = json.dumps(rows)
    assert "alice_real_name" not in blob and "enid" not in blob and "C-1" not in blob               # no usernames, no conversation ids
    assert all(r["candidate_id"].startswith("R") and len(r["candidate_id"]) == 9 for r in rows)
    escalated = next(r for r in rows if "restarting" in r["opening"])
    assert escalated["hint_observed_status"] == "escalated" and escalated["hint_note"] == "what the SYSTEM did; NOT a label"
    assert not any(k in escalated for k in ("class", "label", "gold", "expected"))


def test_engineers_screenshot_only_openings_and_known_questions_are_skipped(db):
    rows = X.export(db, {"docker"})
    texts = [r["opening"] for r in rows]
    assert not any("engineer's own" in t for t in texts) and not any(t == "(screenshot attached)" for t in texts) and "docker" not in texts
    assert len(rows) == 2


def test_existing_gold_questions_are_recognised_as_duplicates():
    known = X.existing_openings()
    assert "docker" in known and len(known) > 80


def test_the_command_writes_a_candidate_file_and_a_blank_labelling_sheet(db, tmp_path):
    out = tmp_path / "out"
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "14_export_for_labelling.py"), "--i-have-consent", "--db", str(db), "--out-dir", str(out)],
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    assert len((out / "candidates_from_users.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    sheet = (out / "candidates_from_users.csv").read_text(encoding="utf-8").splitlines()
    assert sheet[0].startswith("candidate_id,question,class") and all(line.count(",,") >= 1 or line.endswith(",,,") for line in sheet[1:])
