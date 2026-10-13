"""
python -m triage.ontology check              validate the file, resolve every KB link against the real chunks, report coverage
python -m triage.ontology link "docker for mac won't start"   what the ontology understands about a piece of text
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from triage import config
from triage.ontology.model import EntityIndex, load_ontology

CHUNKS = config.PROJECT_ROOT / "data" / "processed" / "docker" / "chunks_metadata.jsonl"
TICKETS_DB = config.PROJECT_ROOT / "data" / "processed" / "docker" / "store" / "tickets" / "tickets.db"


def chunk_rows(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            yield d["chunk_id"], d["text"], d["heading_path"], d["source_path"]


def cmd_check(args) -> int:
    o = load_ontology(args.file)
    problems = o.validate()
    types = Counter(e.type for e in o.entities)
    prov = Counter(e.provenance for e in o.entities)
    print(f"{len(o.entities)} entities {dict(types)}; {len(o._alias)} aliases; provenance {dict(prov)}")
    print(f"validation problems: {len(problems)}")
    for p in problems:
        print("  -", p)
    exit_code = 1 if problems else 0

    if args.chunks.exists():
        idx = EntityIndex.build(o, chunk_rows(args.chunks))
        print(f"\nKB: {idx.n_chunks} chunks, {idx.coverage():.0%} mention at least one specific entity")
        print(f"KB links resolved for {len(idx.issue_chunks)} of {sum(1 for i in o.issues() if i.kb)} issues that declare one")
        for issue_id, link in idx.unresolved:
            print(f"  UNRESOLVED kb link: {issue_id} -> {link.path} :: {link.issue}")
            exit_code = 1
        unlinked = [i.id for i in o.issues() if not i.kb]
        print(f"issues with no KB coverage (kb: []): {len(unlinked)}: {', '.join(unlinked)}")
        orphans = [e.id for e in o.entities if e.type not in ("issue", "error", "use_case") and not e.generic and not idx.by_entity.get(e.id)]
        if orphans:
            print(f"entities never mentioned in the KB ({len(orphans)}): {', '.join(orphans)}")
    else:
        print(f"\n(no chunk file at {args.chunks}; skipped KB checks)")

    if args.tickets.exists():
        con = sqlite3.connect(args.tickets)
        rows = con.execute("select title, problem from tickets where indexed=1").fetchall()
        hit = Counter()
        tagged = 0
        for title, problem in rows:
            found = o.entities_in(f"{title} {(problem or '')[:1500]}", include_generic=False)
            tagged += bool(found)
            hit.update(e.id for e in found)
        print(f"\ntickets: {len(rows)} indexed, {tagged / max(len(rows), 1):.0%} mention at least one specific entity")
        print("most mentioned:", ", ".join(f"{k} ({v})" for k, v in hit.most_common(12)))
        silent = [e.id for e in o.entities if e.type in ("product", "component", "feature", "tool") and not e.generic and hit[e.id] == 0]
        if silent:
            print(f"entities never seen in tickets ({len(silent)}): {', '.join(silent)}")
    return exit_code


def cmd_link(args) -> int:
    o = load_ontology(args.file)
    text = " ".join(args.text)
    print(f"text: {text}")
    for m in o.find(text):
        print(f"  mention  '{m.alias}' -> {m.entity.id} ({m.entity.type}){' [generic]' if m.entity.generic else ''}")
    for issue, score in o.match_issues(text):
        print(f"  issue    {issue.id} score {score}: {issue.name}  | KB: {[k.path for k in issue.kb] or 'not documented'}")
    print(f"  expand   {o.expand(text)}")
    print(f"  infer    platform={o.infer(text)['platform']} product_area={o.infer(text)['product_area']}")
    print(f"  background {o.background(text)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m triage.ontology")
    ap.add_argument("--file", default=None, help="a custom domain file (default: the packaged Docker ontology)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--chunks", type=Path, default=CHUNKS)
    c.add_argument("--tickets", type=Path, default=TICKETS_DB)
    c.set_defaults(fn=cmd_check)
    link = sub.add_parser("link")
    link.add_argument("text", nargs="+")
    link.set_defaults(fn=cmd_link)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
