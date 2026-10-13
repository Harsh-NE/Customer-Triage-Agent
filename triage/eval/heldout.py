"""
heldout.py -- a held-out evaluation set made of REAL customer questions, written by strangers.

Every earlier evaluation set (scenarios, paraphrases) was written by the same author as the ontology and tuned against, so its
numbers are an upper bound. Real Stack Overflow questions from the Tier-2 ticket store are different: nobody wrote them for this
system. This tool turns them into scenarios that `triage.eval.e2e_eval --scenarios` and `ontology_eval` can run.

    python -m triage.eval.heldout sample            # draw candidates + the KB's top-3 issues for each -> heldout_candidates.jsonl/.md
    (label each candidate: set "label" in the jsonl; see below)
    python -m triage.eval.heldout build             # labelled candidates -> heldout_scenarios.jsonl

Labels ("label" in heldout_candidates.jsonl):
    "1" | "2" | "3"   the KB issue with that number in "proposed" documents THIS problem  -> gold
    "kb_gap"          a Docker question, but no KB issue documents it                     -> any KB-backed fix would be wrong
    "oos"             not a Docker support question                                        -> must be declined
    "skip"            unusable (too vague, duplicate, not a problem report)

The KB proposals come from retrieval with the ontology OFF, so the ontology does not choose its own test answers. Retrieval can
still anchor a labeller on its top result: when unsure between "1" and "kb_gap", read the KB section, not just its title. Rows
carry "verified": false until a person has checked the label; `build --verified-only` keeps only those.

The questions' own tickets are excluded from the ticket tier while an evaluation runs (otherwise the system would "find" the
accepted answer to the very question it was given).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
from pathlib import Path

from triage import config
from triage.issues import issue_key, issue_title

HERE = Path(__file__).resolve().parent
CANDIDATES = HERE / "heldout_candidates.jsonl"
SHEET = HERE / "heldout_candidates.md"
SCENARIOS = HERE / "heldout_scenarios.jsonl"
PLATFORM = re.compile(r"(?i)\b(windows|win10|win11|mac ?os|macos|osx|apple silicon|m1|m2|ubuntu|debian|linux|centos|fedora|wsl)\b")
PLATFORM_NAME = {"windows": "windows", "win10": "windows", "win11": "windows", "wsl": "windows", "macos": "mac", "mac os": "mac",
                 "osx": "mac", "apple silicon": "mac", "m1": "mac", "m2": "mac"}


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def jaccard(a: str, b: str) -> float:
    x, y = tokens(a), tokens(b)
    return len(x & y) / len(x | y) if x | y else 0.0


def existing_queries() -> list[str]:
    out = [json.loads(l)["query"] for l in (HERE / "paraphrases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    out += [json.loads(l)["opening"] for l in (HERE / "scenarios.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def prose(problem: str, limit: int = 280) -> str:
    """The first sentences of a question body, without code blocks, links or log dumps."""
    text = re.sub(r"```.*?```", " ", problem or "", flags=re.S)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(out) + len(sentence) > limit:
            break
        out = f"{out} {sentence}".strip()
    return out


def draw_pool(n: int, seed: int) -> list[sqlite3.Row]:
    db = config.PROJECT_ROOT / config.get_env()["TICKETS_STORE_PATH"] / "tickets.db"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT ticket_id, title, problem, errors_clean, url, license, source, topics FROM tickets WHERE indexed = 1 AND is_synthetic = 0 "
        "AND source = 'stackoverflow' AND kind_guess = 'troubleshooting' AND trust_tier IN ('high', 'medium') "
        "AND length(title) BETWEEN 25 AND 160 AND problem_words >= 25").fetchall()
    random.Random(seed).shuffle(rows)
    seen = existing_queries()
    pool = []
    for r in rows:
        if any(jaccard(r["title"], q) >= 0.6 for q in seen):
            continue
        pool.append(r)
        if len(pool) == n:
            break
    return pool


def proposals(kb, query: str, limit: int = 3) -> list[dict]:
    best: dict[str, dict] = {}
    for c in sorted(kb.search(query, top_k=8), key=lambda c: -c.score):
        best.setdefault(issue_key(c), {"path": c.source_path, "issue": issue_title(c), "score": round(c.score, 3)})
    return list(best.values())[:limit]


def cmd_sample(args) -> None:
    from triage.hybrid import HybridKBRetriever
    kb = HybridKBRetriever(ontology_mode="off")
    pool = draw_pool(args.pool, args.seed)
    rows = []
    for r in pool:
        query = r["title"]
        props = proposals(kb, query)
        rows.append({"ticket_id": r["ticket_id"], "url": r["url"], "license": r["license"], "title": r["title"],
                     "problem": prose(r["problem"], 500), "problem_full_head": (r["problem"] or "")[:600],
                     "errors": json.loads(r["errors_clean"] or "[]")[:2], "proposed": props,
                     "top_score": props[0]["score"] if props else 0.0, "label": None, "verified": False})
    # Real support questions are mostly NOT documented by the KB; to get enough gold cases, over-sample questions the KB scores
    # highly and keep the rest random so the set also shows how the system behaves when the KB has no answer.
    ranked = sorted(rows, key=lambda x: -x["top_score"])
    picked = ranked[:args.high] + random.Random(args.seed).sample(ranked[args.high:], min(args.rest, len(ranked) - args.high))
    for i, row in enumerate(picked, 1):
        row["id"] = f"H{i:03d}"
    CANDIDATES.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in picked) + "\n", encoding="utf-8")
    lines = ["# Held-out candidates: label each in heldout_candidates.jsonl", ""]
    for r in picked:
        lines += [f"## {r['id']}  ({r['url']})", f"**{r['title']}**", "", r["problem"], ""]
        lines += [f"{i}. [{p['score']}] `{p['path']}` > {p['issue']}" for i, p in enumerate(r["proposed"], 1)] + [""]
    SHEET.write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(picked)} candidates -> {CANDIDATES} (sheet: {SHEET}). Label them, then run: python -m triage.eval.heldout build")


def to_scenario(c: dict) -> dict | None:
    label = str(c.get("label") or "").strip().lower()
    if label in ("", "skip"):
        return None
    opening = f"{c['title']}. {prose(c['problem'])}".strip()
    text = f"{c['title']} {c['problem']}"
    plat = PLATFORM.search(text)
    platform = PLATFORM_NAME.get(plat.group(1).lower(), plat.group(1).lower()) if plat else None
    hidden = {"product_area": None, "platform": platform if platform in ("windows", "mac", "linux") else ("linux" if platform else None),
              "error_text": (c["errors"][0][:160] if c.get("errors") else None), "symptom_detail": c["title"],
              "source_ticket_id": c["ticket_id"]}
    base = {"id": c["id"], "opening": opening, "hidden": hidden, "vagueness": "unknown", "expected_hard_gaps": [], "opening_facts": {}}
    if label in ("1", "2", "3"):
        p = c["proposed"][int(label) - 1]
        return {**base, "gold": {"source_path_contains": p["path"], "issue_contains": p["issue"]}, "oos": False,
                "note": f"real question {c['url']}; label verified={c.get('verified', False)}"}
    if label == "kb_gap":
        return {**base, "gold": None, "oos": False, "note": f"kb_gap; real question {c['url']}; verified={c.get('verified', False)}"}
    if label == "oos":
        return {**base, "gold": None, "oos": True, "note": f"real question {c['url']}; verified={c.get('verified', False)}"}
    raise SystemExit(f"{c['id']}: unknown label {label!r} (use 1, 2, 3, kb_gap, oos or skip)")


def cmd_build(args) -> None:
    cands = [json.loads(l) for l in CANDIDATES.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.verified_only:
        cands = [c for c in cands if c.get("verified")]
    scenarios = [s for s in map(to_scenario, cands) if s]
    SCENARIOS.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in scenarios) + "\n", encoding="utf-8")
    gold = sum(bool(s["gold"]) for s in scenarios)
    gap = sum(s["note"].startswith("kb_gap") for s in scenarios)
    print(f"{len(scenarios)} scenarios -> {SCENARIOS}: {gold} with a gold KB issue, {gap} kb_gap, "
          f"{sum(s['oos'] for s in scenarios)} out of scope; {sum('verified=True' in s['note'] for s in scenarios)} human-verified")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="draw real questions and propose KB issues")
    s.add_argument("--pool", type=int, default=400, help="questions to score against the KB")
    s.add_argument("--high", type=int, default=45, help="how many of the best-scoring to keep")
    s.add_argument("--rest", type=int, default=25, help="how many random others to keep")
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(fn=cmd_sample)
    b = sub.add_parser("build", help="labelled candidates -> scenarios")
    b.add_argument("--verified-only", action="store_true")
    b.set_defaults(fn=cmd_build)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
