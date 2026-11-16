"""
writeback.py -- feed newly resolved cases back into the historical ticket dataset (Tier 2), safely.

Two things can be learned from a finished case:
  customer_confirmed   the agent sent a fix and the customer said it worked (the same moment the semantic cache is written)
  engineer_resolved    an engineer closed an escalated case with a fix and ticked "promote" (that tick is the engineer's approval)

This module decides WHAT to keep and WHETHER it is safe. It never touches the ticket store; `triage/ticket_ingest.py` does that, in batches.

    customer / engineer  ->  candidate  ->  checks  ->  queue (writeback.db)  ->  ticket_ingest (batch)  ->  historical dataset

Checks, all cheap and run when the case is queued (a failed check rejects the candidate and records why):
  * length: a title, a problem and a fix with enough words to mean something;
  * personal data and secrets are masked in everything stored (triage.understand.redact_pii);
  * no prompt-injection or secret-request wording (the customer's text is stored as data, but a poisoned entry is not stored at all);
  * not an evaluation question: a candidate that overlaps a test question is refused, so the test sets stay clean;
  * not already queued (the id is a hash of the title and the fix).
The near-duplicate check against the existing tickets needs the embedding model, so it runs at ingest time.

Switches (environment):
  TICKET_WRITEBACK=1   record resolved cases at all (default OFF: evaluations must not change the dataset they measure)
  WRITEBACK_REVIEW=all every candidate waits for `approve` instead of being approved automatically

    python -m triage.writeback status | list [status] | approve ID | reject ID [reason]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from triage import config
from triage.resolver.guardrails import INJECTION, SECRET_REQUEST
from triage.understand import redact_pii

# what a new entry is worth when retrieval ranks it (see RESOLUTION_KIND_WEIGHT in triage/hybrid.py for the rank weight)
KINDS = {"customer_confirmed": {"trust_tier": "medium", "trust_score": 0.6, "source_type": "triage_customer_confirmed"},
         "engineer_resolved": {"trust_tier": "high", "trust_score": 0.8, "source_type": "triage_engineer_resolved"}}
MIN_WORDS = {"title": 3, "problem": 5, "resolution": 15}
EVAL_OVERLAP = 0.8                  # share of the SMALLER word set that two texts share before they count as the same question
EVAL_MIN_WORDS = 5                  # shorter texts are too generic to compare
DUE_BATCH, DUE_HOURS = 25, 24       # `ingest --due` runs when this many are approved, or the oldest has waited this long
STATUSES = ("pending", "approved", "rejected", "ingested")


def enabled() -> bool:
    return os.environ.get("TICKET_WRITEBACK", "") == "1"


def store_root() -> Path:
    return Path(config.PROJECT_ROOT) / config.get_env()["TICKETS_STORE_PATH"]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------

def make_candidate(kind: str, title: str, problem: str, resolution: str, *, error_strings=(), exit_codes=(), versions=None,
                   topics=(), url: str = "", ref: str = "") -> dict:
    """A candidate ticket with personal data masked. `ref` is the case it came from (a hash is stored, never the raw id)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}, got '{kind}'")
    masked, counts = {}, {}
    for name, text in (("title", title), ("problem", problem), ("resolution", resolution)):
        masked[name], found = redact_pii(" ".join(str(text or "").split()) if name == "title" else str(text or "").strip())
        for k, n in found.items():
            counts[k] = counts.get(k, 0) + n
    fingerprint = " ".join(sorted(_words(masked["title"]))) + "|" + " ".join(sorted(_words(masked["resolution"])))
    return {"id": "W-" + hashlib.sha1(fingerprint.encode()).hexdigest()[:12], "kind": kind, **masked,
            "error_strings": [e for e in error_strings if e], "exit_codes": [int(c) for c in exit_codes],
            "docker_versions": [f"{k} {v}" for k, v in (versions or {}).items()], "topics": sorted(set(topics)),
            "url": url or "internal://resolved/" + hashlib.sha1(ref.encode()).hexdigest()[:10],
            "redacted": counts, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def fix_text(attempt: dict) -> str:
    """The fix of one attempt as plain text: the diagnosis, then the steps, without evidence tags."""
    steps = [s.get("text", "").strip() for s in attempt.get("steps") or []]
    return "\n".join([attempt.get("diagnosis", "").strip(), *[f"{i}. {t}" for i, t in enumerate(steps, 1) if t]]).strip()


def customer_words(transcript: list[dict]) -> str:
    """What the customer said before the fix was sent. Their reply to the fix ("that worked") is not part of the problem."""
    last_agent = max((i for i, t in enumerate(transcript) if t.get("role") == "assistant"), default=len(transcript))
    return "\n".join(t["content"] for t in transcript[:last_agent] if t.get("role") == "user")


def from_attempt(signature: dict, attempt: dict, customer_text: str, evidence: list[dict], ref: str) -> dict:
    """A customer-confirmed candidate from the fix the customer said worked."""
    title = (signature.get("symptom") or customer_text.split("\n")[0])[:160]
    topics = [t for e in evidence for t in (e.get("metadata") or {}).get("topics", []) if isinstance(t, str)]
    url = next((s["url"] for s in attempt.get("sources") or [] if s.get("url")), "")
    return make_candidate("customer_confirmed", title, customer_text, fix_text(attempt), error_strings=signature.get("error_strings") or [],
                          exit_codes=signature.get("exit_codes") or [], versions=signature.get("versions"), topics=topics, url=url, ref=ref)


@lru_cache(maxsize=1)
def evaluation_questions() -> list[set[str]]:
    """Word sets of every question we evaluate on (scenarios, held-out, gold v1 dev and test, paraphrases)."""
    from triage.eval.gold_v1 import DEV, TEST, read_split
    from triage.sim.customer import load_scenarios
    here = Path(__file__).resolve().parent / "eval"
    texts = [s.opening for s in load_scenarios()] + [s.opening for s in load_scenarios(here / "heldout_scenarios.jsonl")]
    texts += [r["opening"] for r in read_split(DEV) + read_split(TEST)]
    texts += [json.loads(line)["query"] for line in (here / "paraphrases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return [w for w in map(_words, texts) if len(w) >= EVAL_MIN_WORDS]


def check(candidate: dict) -> list[str]:
    """Why this candidate must not be stored (empty list = fine)."""
    problems = [f"{name} has fewer than {n} words" for name, n in MIN_WORDS.items() if len(candidate[name].split()) < n]
    text = " ".join([candidate["title"], candidate["problem"], candidate["resolution"]])
    if INJECTION.search(text) or SECRET_REQUEST.search(text):
        problems.append("looks like prompt injection or a request for secrets")
    mine = _words(candidate["problem"])
    if len(mine) >= EVAL_MIN_WORDS and any(len(mine & q) / min(len(mine), len(q)) >= EVAL_OVERLAP for q in evaluation_questions()):
        problems.append("overlaps an evaluation question")
    return problems


# ---------------------------------------------------------------------------
# the queue
# ---------------------------------------------------------------------------

class Queue:
    """SQLite file next to the ticket store. One row per candidate; the status says where it is."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or store_root() / "writeback.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._tx() as db:
            db.execute("CREATE TABLE IF NOT EXISTS queue (id TEXT PRIMARY KEY, kind TEXT, status TEXT, reason TEXT, created_at TEXT, "
                       "updated_at TEXT, version INTEGER, record TEXT)")

    @contextmanager
    def _tx(self):
        """A connection that commits when the block ends and is always closed (an open file blocks deleting it on Windows)."""
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, candidate: dict, review_all: bool | None = None) -> str:
        """Queue a candidate; returns its status. An id that is already queued is left alone (returns that status)."""
        review_all = os.environ.get("WRITEBACK_REVIEW", "") == "all" if review_all is None else review_all
        with self._tx() as db:
            known = db.execute("SELECT status FROM queue WHERE id=?", (candidate["id"],)).fetchone()
            if known:
                return known[0]
            problems = check(candidate)
            status = "rejected" if problems else "pending" if review_all else "approved"
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            db.execute("INSERT INTO queue VALUES (?,?,?,?,?,?,?,?)", (candidate["id"], candidate["kind"], status, "; ".join(problems), now, now, None,
                                                                         json.dumps(candidate)))
            return status

    def set_status(self, cid: str, status: str, reason: str = "", version: int | None = None) -> bool:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        with self._tx() as db:
            cur = db.execute("UPDATE queue SET status=?, reason=?, version=COALESCE(?, version), updated_at=? WHERE id=?",
                             (status, reason, version, datetime.now(timezone.utc).isoformat(timespec="seconds"), cid))
            return cur.rowcount == 1

    def rows(self, status: str) -> list[dict]:
        with self._tx() as db:
            return [{**json.loads(rec), "status": status, "reason": r, "created_at": c, "version": v}      # the queue's own columns win
                    for r, c, v, rec in db.execute("SELECT reason, created_at, version, record FROM queue WHERE status=? ORDER BY created_at", (status,))]

    def counts(self) -> dict[str, int]:
        with self._tx() as db:
            found = dict(db.execute("SELECT status, COUNT(*) FROM queue GROUP BY status"))
        return {s: found.get(s, 0) for s in STATUSES}

    def due(self, min_batch: int = DUE_BATCH, max_hours: int = DUE_HOURS) -> bool:
        """Enough approved candidates, or the oldest one has waited long enough."""
        approved = self.rows("approved")
        if not approved:
            return False
        oldest = min(datetime.fromisoformat(r["created_at"]) for r in approved)
        return len(approved) >= min_batch or datetime.now(timezone.utc) - oldest >= timedelta(hours=max_hours)


# ---------------------------------------------------------------------------
# the two triggers (never raise: a write-back problem must not cost a customer their answer)
# ---------------------------------------------------------------------------

def on_resolved(state: dict, queue: Queue | None = None) -> str | None:
    """The customer confirmed the last fix. `state` is the Resolver's graph state. Returns the candidate's status, or None when off or on error."""
    if not enabled():
        return None
    try:
        attempt = (state.get("attempts") or [{}])[-1]
        cited = set(attempt.get("evidence_ids") or [])
        evidence = [e for e in state.get("evidence") or [] if e.get("evidence_id") in cited]
        customer = customer_words(state.get("transcript") or [])
        candidate = from_attempt(state.get("signature") or {}, attempt, customer, evidence, ref=str(state.get("ticket_id", "")))
        return (queue or Queue()).add(candidate)
    except Exception as exc:  # noqa: BLE001
        print(f"writeback: skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None


def on_engineer_resolved(title: str, customer_text: str, resolution: str, signature: dict | None, ref: str, queue: Queue | None = None) -> str | None:
    """An engineer closed an escalated case and ticked "promote". Their tick is the approval, so the candidate is not held for review."""
    if not enabled():
        return None
    try:
        sig = signature or {}
        candidate = make_candidate("engineer_resolved", title, customer_text, resolution, error_strings=sig.get("error_strings") or [],
                                   exit_codes=sig.get("exit_codes") or [], versions=sig.get("versions"), ref=ref)
        return (queue or Queue()).add(candidate, review_all=False)
    except Exception as exc:  # noqa: BLE001
        print(f"writeback: skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Inspect and approve the queue of resolved cases waiting to join the historical dataset.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="how many candidates are in each state")
    ls = sub.add_parser("list", help="show candidates")
    ls.add_argument("status", nargs="?", default="pending", choices=STATUSES)
    for name in ("approve", "reject"):
        p = sub.add_parser(name, help=f"{name} a candidate by id")
        p.add_argument("id")
        if name == "reject":
            p.add_argument("reason", nargs="?", default="rejected by reviewer")
    args = ap.parse_args(argv)
    q = Queue()
    if args.cmd == "status":
        print(json.dumps({**q.counts(), "due": q.due(), "writeback_enabled": enabled()}, indent=1))
    elif args.cmd == "list":
        for r in q.rows(args.status):
            print(f"{r['id']}  {r['kind']:<19} {r['title'][:70]}" + (f"   [{r['reason']}]" if r["reason"] else ""))
    else:
        ok = q.set_status(args.id, "approved") if args.cmd == "approve" else q.set_status(args.id, "rejected", args.reason)
        print("done" if ok else f"no such candidate: {args.id}")


if __name__ == "__main__":
    main()
