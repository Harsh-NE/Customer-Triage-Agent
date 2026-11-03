"""
13_ticket_gaps.py -- which frequent ticket errors does the knowledge base NOT document? Then draft cards for a person to review.

Reads   data/processed/docker/store/tickets/tickets.db      13,092 indexed community tickets
        data/processed/docker/chunks_metadata.jsonl, via the hybrid KB retriever   the official KB
Writes  data/curated/ticket_gap_clusters.csv     every error group with at least --min-size tickets, its KB check and a verdict column to fill
        data/curated/cards.jsonl                 DRAFT cards for the top gap groups (status "draft": nothing here reaches a customer)
        reports/TICKET_GAP_ANALYSIS.md           the summary and the top groups

How it works (no model calls, no network):
  1. Each ticket's first usable error line is normalised (numbers, ids and paths replaced) and tickets are grouped by it: a frequency
     count of what customers actually hit. Tickets without a usable error line are not grouped (about a quarter of them).
  2. For each group the hybrid KB retriever searches the error line and we measure how much of its wording occurs in the best five
     chunks ("kb_contained", 0..1). Low means the KB probably does not document it: a GAP CANDIDATE. This is a ranking aid, not a verdict:
     similarity cannot reliably tell a gap from a hit (it did not on the held-out questions), so a person decides in the sheet.
  3. For the biggest gap candidates a draft card is assembled EXTRACTIVELY from the best ticket (verbatim fix text, source URL and licence).
     No language model is used, so nothing is invented; a reviewer rewrites, approves or rejects each one.

Leakage guard: the tickets behind the held-out questions (65) and any ticket whose title is nearly the same as theirs (cross-posts) are
excluded, so an analysis built on tickets cannot "discover" the questions we test on. The numbers excluded are printed and written.

    PYTHONHASHSEED=0 HF_HUB_OFFLINE=1 python scripts/13_ticket_gaps.py
    python scripts/13_ticket_gaps.py --no-kb              # grouping only, no retriever (fast; the KB check columns stay empty)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB = PROJECT_ROOT / "data" / "processed" / "docker" / "store" / "tickets" / "tickets.db"
HELDOUT = PROJECT_ROOT / "triage" / "eval" / "heldout_scenarios.jsonl"
CURATED = PROJECT_ROOT / "data" / "curated"
REPORT = PROJECT_ROOT / "reports" / "TICKET_GAP_ANALYSIS.md"
HEX = re.compile(r"[0-9a-f]{12,}")
PATH = re.compile(r"(?<![\w:/])/(?:[\w.-]+/)+[\w.-]+|[a-z]:\\[\w.\\-]+")
BARE_STATUS = re.compile(r"(?i)^(exit(ed)?( with)? (status|code)|returned a non-zero|error:?|warning:?)\b")      # says nothing about WHAT failed
NUMBER = re.compile(r"\d+(?:\.\d+)*")
TOKEN = re.compile(r"[a-z0-9]{3,}")
KIND_RANK = {"accepted_answer": 0, "maintainer_comment": 0, "forum_accepted_answer": 1, "curated_answer": 1, "forum_op_confirmed_reply": 2, "community_comment": 3}
NOISE = re.compile(r"(?i)screen ?shot|image#?\.|\.(png|jpe?g|gif)\b|^(log|output|result|output of)\b")      # filenames and headings that landed in the error field
MIN_WORDS = 6                      # a signature shorter than this ("no such file or directory") mixes unrelated causes: listed, but never made a card
GAP_BELOW = 0.6                    # kb_contained under this = a gap candidate (a ranking aid, not a verdict)


def normalise(line: str) -> str:
    s = HEX.sub("<id>", line.lower().strip())
    s = PATH.sub("<path>", s)
    s = NUMBER.sub("#", s)
    s = re.sub(r"[\"'`]", "", s)
    return " ".join(s.split()[:12])


def is_specific(sig: str) -> bool:
    return len(sig.split()) >= MIN_WORDS and not NOISE.search(sig)


def signature_of(row: dict) -> str | None:
    """The first error line with at least three words that says what failed ("exit status 1" does not), normalised; None when none."""
    for key in ("errors_clean", "error_strings"):
        for line in json.loads(row.get(key) or "[]"):
            line = str(line).strip()
            if len(line.split()) >= 3 and not (BARE_STATUS.match(line) and len(line.split()) <= 4):
                return normalise(line)
    return None


def title_tokens(text: str) -> frozenset:
    return frozenset(TOKEN.findall((text or "").lower()))


def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def leakage_exclusions(rows: list[dict], heldout_path: Path = HELDOUT, near: float = 0.7) -> tuple[set[str], list[str]]:
    """(ticket ids to exclude, reasons). The held-out questions' own tickets, and tickets whose title is a near-copy of theirs."""
    held = [json.loads(line) for line in heldout_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    own = {h["hidden"]["source_ticket_id"] for h in held if h.get("hidden", {}).get("source_ticket_id")}
    by_id = {r["ticket_id"]: r for r in rows}
    held_titles = [title_tokens(by_id[i]["title"]) for i in own if i in by_id]
    held_titles += [title_tokens(h["opening"].split(". ")[0]) for h in held]
    excluded, near_copies = set(own), 0
    for r in rows:
        if r["ticket_id"] in excluded:
            continue
        t = title_tokens(r["title"])
        if any(jaccard(t, h) >= near for h in held_titles):
            excluded.add(r["ticket_id"])
            near_copies += 1
    return excluded, [f"{len(own)} held-out source tickets", f"{near_copies} near-copy titles (Jaccard >= {near})"]


def group_by_signature(rows: list[dict], excluded: set[str]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["ticket_id"] in excluded:
            continue
        sig = signature_of(r)
        if sig:
            groups[sig].append(r)
    return groups


def best_ticket(rows: list[dict]) -> dict:
    """The most trustworthy, most recent ticket with a fix of a usable length."""
    usable = [r for r in rows if 15 <= (r.get("resolution_words") or 0) <= 250] or rows
    return sorted(usable, key=lambda r: (KIND_RANK.get(r.get("resolution_kind"), 9), -(r.get("trust_score") or 0), r.get("age_years") or 99))[0]


def trim(text: str, limit: int = 700) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind(".\n"), cut.rfind("\n\n"))
    return (cut[:end + 1] if end > limit // 2 else cut).strip()


def draft_card(sig: str, rows: list[dict], kb: dict | None) -> dict:
    best = best_ticket(rows)
    sources = [{"url": r["url"], "license": r.get("license"), "ticket_id": r["ticket_id"], "source_type": r.get("source_type"),
                "trust_tier": r.get("trust_tier"), "age_years": round(r.get("age_years") or 0, 1)} for r in sorted(rows, key=lambda r: (KIND_RANK.get(r.get("resolution_kind"), 9), -(r.get("trust_score") or 0)))[:3]]
    return {"id": "CARD-" + hashlib.sha1(sig.encode()).hexdigest()[:8], "status": "draft", "reviewer": None, "notes": "",
            "title": best["title"], "error_signature": sig, "symptoms": [r["title"] for r in rows[:3]],
            "fix_text_extract": trim(best["resolution"]), "fix_extracted_from": best["ticket_id"], "sources": sources,
            "cluster_size": len(rows), "kb_contained": (kb or {}).get("contained"), "kb_top": (kb or {}).get("top"),
            "generated": time.strftime("%Y-%m-%d"),
            "caveats": ["verbatim extract of a community answer (attribution and licence in sources); a reviewer must check it is correct, current and complete",
                        "tickets are grouped by their error line ONLY: they can have different causes (one group of 22 'executable file not found' tickets is about 22 different programs), "
                        "so confirm the fix applies to the whole group, or narrow the card to the one case it fits",
                        "never loaded into the system while status is not 'approved'"]}


def kb_check(retriever, sig: str) -> dict:
    """How much of the error line's wording the best five KB chunks contain, and the top three KB issues for it."""
    from triage.answers import _tokens
    from triage.issues import issue_key, issue_title
    wanted = _tokens(sig)
    cands = sorted(retriever.search(sig, top_k=8), key=lambda c: -c.score)
    contained = max((len(wanted & _tokens(c.text)) / len(wanted) for c in cands[:5]), default=0.0) if wanted else 0.0
    seen, top = set(), []
    for c in cands:
        key = issue_key(c)
        if key not in seen:
            seen.add(key)
            top.append(f"{c.source_path.split('content/')[-1].rsplit('/', 1)[-1]} > {issue_title(c)[:60]} ({c.score:.2f})")
        if len(top) == 3:
            break
    return {"contained": round(contained, 2), "top": top}


def main() -> None:
    ap = argparse.ArgumentParser(description="Find frequent ticket errors the KB does not document; draft review cards.")
    ap.add_argument("--min-size", type=int, default=4, help="smallest error group to list")
    ap.add_argument("--cards", type=int, default=25, help="how many draft cards to write")
    ap.add_argument("--no-kb", action="store_true", help="group only; skip the retriever and the KB check")
    ap.add_argument("--out-dir", type=Path, default=CURATED)
    ap.add_argument("--report", type=Path, default=REPORT)
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM tickets WHERE indexed = 1")]
    excluded, why = leakage_exclusions(rows)
    groups = {s: g for s, g in group_by_signature(rows, excluded).items() if len(g) >= args.min_size}
    grouped_tickets = sum(len(g) for g in groups.values())
    print(f"{len(rows)} indexed tickets; excluded {len(excluded)} for leakage ({'; '.join(why)}); {len(groups)} error groups of >= {args.min_size} tickets ({grouped_tickets} tickets)")

    retriever = None
    if not args.no_kb:
        from triage.hybrid import HybridKBRetriever
        retriever = HybridKBRetriever(rerank_mode="off", kb_filters="")
        retriever._ensure()
    checks = {}
    for n, (sig, g) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1])), 1):
        checks[sig] = kb_check(retriever, sig) if retriever else None
        if retriever and n % 50 == 0:
            print(f"  checked {n}/{len(groups)}", flush=True)

    ordered = sorted(groups.items(), key=lambda kv: (checks[kv[0]] is not None and checks[kv[0]]["contained"] >= GAP_BELOW, -len(kv[1])))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "ticket_gap_clusters.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["error_signature", "tickets", "kb_contained", "gap_candidate", "specific_enough", "median_age_years", "high_trust_share", "example_titles", "example_urls",
                    "kb_top_1", "kb_top_2", "kb_top_3", "VERDICT (documented|gap|not_docker_support|too_vague)", "reviewer_notes"])
        for sig, g in ordered:
            c = checks[sig]
            top = (c["top"] if c else []) + ["", "", ""]
            w.writerow([sig, len(g), c["contained"] if c else "", "" if not c else ("yes" if c["contained"] < GAP_BELOW else "no"),
                        "yes" if is_specific(sig) else "no", round(statistics.median(r.get("age_years") or 0 for r in g), 1), round(sum(r.get("trust_tier") == "high" for r in g) / len(g), 2),
                        " || ".join(r["title"][:90] for r in g[:3]), " ".join(r["url"] for r in g[:2]), top[0], top[1], top[2], "", ""])
    gaps = [(s, g) for s, g in ordered if checks[s] and checks[s]["contained"] < GAP_BELOW and is_specific(s)]
    cards = [draft_card(s, g, checks[s]) for s, g in gaps[:args.cards]]
    with (args.out_dir / "cards.jsonl").open("w", encoding="utf-8") as f:
        f.write("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards))

    lines = ["# Ticket gap analysis", "",
             f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python scripts/13_ticket_gaps.py`. Method and limits are in the script's docstring._", "",
             f"* {len(rows)} indexed tickets; **{len(excluded)} excluded as leakage** ({'; '.join(why)}).",
             f"* {len(groups)} error groups with at least {args.min_size} tickets, covering {grouped_tickets} tickets ({grouped_tickets / len(rows):.0%} of the store).",
             (f"* **{len(gaps)} gap candidates** (the KB contains under {GAP_BELOW:.0%} of the error's wording in its best five chunks); the other {len(groups) - len(gaps)} look documented."
              if retriever else "* KB check skipped (`--no-kb`)."),
             f"* {len(cards)} draft cards written to `data/curated/cards.jsonl` (status `draft`; nothing is loaded into the system until a person approves).", "",
             "`kb_contained` is a ranking aid: wording overlap cannot reliably tell a gap from a hit (it lists the socket-permission error as a gap although `linux-postinstall.md` "
             "documents the fix, in words that do not quote the error). The CSV has a VERDICT column for a person to fill.", "",
             "## Read the cards with care", "",
             "Tickets are grouped by their first error line, nothing more. A generic line groups tickets that share a message but not a cause: the biggest group "
             "(`: executable file not found in $path`, 22 tickets) is about 22 different programs, and its draft card quotes one ticket's workaround (pin `registry:2.7.0`), "
             "which is right for that ticket and wrong for the rest. Title similarity inside a group is too low to catch this automatically (median 0.04 even for related tickets). "
             "So the cards are **drafts to be triaged by a person**, many to be rejected or narrowed; the ranked CSV is the real output: it shows which errors customers hit most that "
             "the KB seems not to cover. Only 6% of the store falls in an error group of four or more tickets: the long tail is wide, so this reaches the head of the "
             "distribution only.", "",
             "## Biggest gap candidates", "", "| tickets | error (normalised) | kb_contained | closest KB issue |", "|---|---|---|---|"]
    lines += [f"| {len(g)} | `{s[:80]}` | {checks[s]['contained']} | {(checks[s]['top'] or [''])[0][:70]} |" for s, g in gaps[:20]]
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out_dir / 'ticket_gap_clusters.csv'}, {args.out_dir / 'cards.jsonl'} and {args.report}")


if __name__ == "__main__":
    main()
