"""
14_export_for_labelling.py -- turn REAL conversations from the app database into candidates for the gold test set.

The only source of genuinely new, untouched test data is people actually using the system. This is the bridge: it reads `app.db`, takes each
customer's opening message, strips personal data and secrets, and writes a candidate file plus a labelling sheet. A person then labels each one
(see docs/DATASET_PLAN.md) and the labelled rows are appended to the gold set with `python -m triage.eval.gold_v1`.

CONSENT. Real people's words must not be reused without their agreement. The script therefore refuses to run unless you pass
`--i-have-consent`, which is you stating that every participant knew their messages would be used to test and improve the system and agreed.
It does not check this for you.

What is removed or kept
  * usernames and user ids are never exported (a random candidate id is used); engineer accounts are skipped
  * emails, tokens, passwords and keys are masked (triage.understand.redact_pii and triage.ocr.redact)
  * the agent's observed outcome is recorded as a HINT in a separate field. It is not a label: the label must come from a person reading the question,
    otherwise the test set would just agree with the system that is being tested
  * conversations whose opening text duplicates one already in the gold set are skipped

    python scripts/14_export_for_labelling.py --i-have-consent
    python scripts/14_export_for_labelling.py --i-have-consent --db data/processed/docker/app.db --out-dir data/curated
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def mask(text: str) -> str:
    from triage.ocr import redact
    from triage.understand import redact_pii
    return redact(redact_pii(text or "")[0])


def existing_openings() -> set[str]:
    out: set[str] = set()
    for name in ("gold_v1_dev.jsonl", "gold_v1_test.jsonl", "heldout_scenarios.jsonl", "scenarios.jsonl"):
        path = PROJECT_ROOT / "triage" / "eval" / name
        if path.exists():
            out |= {json.loads(line)["opening"].strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    return out


def export(db: Path, skip: set[str]) -> list[dict]:
    from sqlalchemy import select

    from triage.api.db import Conversation, Message, User, make_engine, session_factory
    engine = make_engine(f"sqlite:///{db.as_posix()}")
    rows: list[dict] = []
    with session_factory(engine)() as s:
        engineers = {u.id for u in s.scalars(select(User).where(User.role == "engineer"))}
        for conv in s.scalars(select(Conversation).order_by(Conversation.created_at)):
            if conv.user_id in engineers:
                continue
            first = s.scalars(select(Message).where(Message.conversation_id == conv.id, Message.role == "customer").order_by(Message.id)).first()
            if first is None or not first.content.strip() or first.content.strip() == "(screenshot attached)":
                continue
            text = mask(first.content).strip()
            if text.lower() in skip:
                continue
            attachment = (first.payload or {}).get("attachment")
            rows.append({"candidate_id": "R" + hashlib.sha1(conv.id.encode()).hexdigest()[:8], "opening": text,
                         "has_screenshot": bool(attachment), "screenshot_text": mask(attachment["text"]) if attachment else "",
                         "hint_observed_status": conv.status, "hint_escalation_reason": conv.escalation_reason,
                         "hint_note": "what the SYSTEM did; NOT a label"})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Export real conversations (masked) as candidates for the gold test set.")
    ap.add_argument("--i-have-consent", action="store_true", help="required: every participant agreed their messages may be used to test the system")
    ap.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "processed" / "docker" / "app.db")
    ap.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "data" / "curated")
    args = ap.parse_args()
    if not args.i_have_consent:
        raise SystemExit("refusing to export: real people's messages need their agreement first. Re-run with --i-have-consent once that is true.")
    if not args.db.exists():
        raise SystemExit(f"no database at {args.db}")
    rows = export(args.db, existing_openings())
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "candidates_from_users.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    with (args.out_dir / "candidates_from_users.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["candidate_id", "question", "class (answerable|kb_gap|vague|urgent|out_of_scope|injection)", "kb_section_if_answerable", "notes"])
        w.writerows([[r["candidate_id"], r["opening"], "", "", ""] for r in rows])
    print(f"exported {len(rows)} candidates to {args.out_dir} (masked; no usernames; the system's own outcome is a hint, not a label)")


if __name__ == "__main__":
    main()
