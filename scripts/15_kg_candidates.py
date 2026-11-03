"""
15_kg_candidates.py -- measure how much of the KB the knowledge graph covers, check what it claims is "undocumented", and draft nodes for the rest.

The ontology (triage/ontology/docker.yaml) is hand-written. It links 51 of 137 troubleshooting issues and none of the 96 FAQ entries to the KB. This script
does the part a machine can do safely and leaves the rest to a person:

  1. COVERAGE      which troubleshooting / FAQ issues have an ontology node pointing at them, which do not
  2. CLAIM CHECK   for every ontology issue that says it is NOT documented (`kb: []`), look for its error text in the KB. A hit means the claim is wrong
                   (it was: "permission denied connecting to the Docker socket" is documented in linux-postinstall.md) and the node should link there
  3. DRAFT NODES   one draft entity per uncovered issue, in the ontology's own schema, from the KB itself: the issue title, an error line taken from its text,
                   a symptom phrase only where the title already reads like a symptom. No model, nothing invented; `status: draft` and `provenance: kb`.
                   Aliases, summaries and ticket-derived phrases are deliberately left empty: those need a person.

Writes  data/curated/ontology_candidates.yaml   draft nodes (NOT loaded by the system; copy accepted ones into docker.yaml in a reviewed commit)
        reports/KG_COVERAGE.md                  the numbers and the claim check

    python scripts/15_kg_candidates.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import OrderedDict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CHUNKS = PROJECT_ROOT / "data" / "processed" / "docker" / "chunks_metadata.jsonl"
CURATED = PROJECT_ROOT / "data" / "curated"
REPORT = PROJECT_ROOT / "reports" / "KG_COVERAGE.md"
SUPPORT_KINDS = ("troubleshooting", "faq")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]


def load_issues(chunks_path: Path = CHUNKS) -> "OrderedDict[str, dict]":
    """KB issues (key -> {title, path, kind, chunks}) for the support-relevant kinds, in file order."""
    from triage.issues import issue_key, issue_title
    from triage.state import Candidate
    issues: "OrderedDict[str, dict]" = OrderedDict()
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        if c["metadata"].get("doc_kind") not in SUPPORT_KINDS:
            continue
        cand = Candidate(c["chunk_id"], c["text"], 0.0, c["source_path"], c["article_title"], c["heading_path"], c["metadata"])
        entry = issues.setdefault(issue_key(cand), {"title": issue_title(cand), "path": c["source_path"], "kind": c["metadata"]["doc_kind"], "chunks": []})
        entry["chunks"].append(cand)
    return issues


def is_linked(ontology, path: str, title: str) -> bool:
    from triage.ontology.model import norm_title
    return any(link.path in path and norm_title(title).startswith(norm_title(link.issue)) for e in ontology.issues() for link in e.kb)


def short_path(path: str) -> str:
    """'content/manuals/engine/daemon/troubleshoot.md' -> 'engine/daemon/troubleshoot.md' (the style the ontology already uses)."""
    return re.sub(r"^content/(manuals/)?", "", path)


def draft_node(key: str, issue: dict, taken: set[str]) -> dict:
    from triage.differential import _error_text
    from triage.symptoms import SymptomBank
    node_id = base = f"issue-{slug(issue['title'])}"
    n = 2
    while node_id in taken:
        node_id, n = f"{base}-{n}", n + 1
    taken.add(node_id)
    errors = [e for e in [_error_text(issue["chunks"])] if e]
    symptoms = SymptomBank().for_issue(key)                      # title-derived only: no bank is loaded, so no generated text is used
    return {"id": node_id, "type": "issue", "name": issue["title"], "symptoms": [s.lower() for s in symptoms[:2]], "errors": errors,
            "kb": [{"path": short_path(issue["path"]), "issue": issue["title"]}], "provenance": "kb", "status": "draft"}


def check_undocumented(ontology, chunks_path: Path = CHUNKS) -> list[dict]:
    """Ontology issues with `kb: []` whose error text DOES occur in the KB: [{id, name, error, where: [section, ...]}]."""
    texts = []
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            if c["metadata"].get("doc_kind") in ("release_notes", "archive"):
                continue                                            # a bug-fix line in a changelog does not document the problem
            texts.append((c["text"].lower(), short_path(c["source_path"]) + " > " + " > ".join(c["heading_path"][-2:])))
    out = []
    for e in ontology.issues():
        if e.kb:
            continue
        for err in e.errors:
            where = sorted({label for text, label in texts if len(err) >= 12 and err.lower() in text})[:4]
            if where:
                out.append({"id": e.id, "name": e.name, "error": err, "where": where})
                break
    return out


def main() -> None:
    import yaml

    from triage.ontology import load_ontology
    ap = argparse.ArgumentParser(description="Knowledge-graph coverage, the 'undocumented' claim check, and draft nodes.")
    ap.add_argument("--out-dir", type=Path, default=CURATED)
    ap.add_argument("--report", type=Path, default=REPORT)
    args = ap.parse_args()

    onto = load_ontology()
    issues = load_issues()
    linked = {k for k, v in issues.items() if is_linked(onto, v["path"], v["title"])}
    uncovered = [(k, v) for k, v in issues.items() if k not in linked]
    taken = set(onto.by_id)
    all_drafts = [draft_node(k, v, taken) for k, v in uncovered]
    drafts = [d for d in all_drafts if d["errors"] or d["symptoms"]]          # a stub with only a generic title ("Overview") is noise, not a candidate
    stubs = len(all_drafts) - len(drafts)
    wrong = check_undocumented(onto)
    by_kind = {kind: (sum(1 for k, v in issues.items() if v["kind"] == kind and k in linked), sum(1 for v in issues.values() if v["kind"] == kind)) for kind in SUPPORT_KINDS}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "ontology_candidates.yaml").write_text(
        "# DRAFT ontology nodes generated by scripts/15_kg_candidates.py from the KB itself. NOT loaded by the system.\n"
        "# Review each: add aliases and a summary, fix the symptom wording, drop what is not useful, then copy into triage/ontology/docker.yaml.\n"
        + yaml.safe_dump({"entities": drafts}, sort_keys=False, allow_unicode=True, width=140), encoding="utf-8")

    lines = ["# Knowledge-graph coverage", "", f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python scripts/15_kg_candidates.py`._", "",
             "| KB section kind | issues | linked from the ontology | share |", "|---|---|---|---|"]
    lines += [f"| {kind} | {total} | {n} | {n / total:.0%} |" for kind, (n, total) in by_kind.items()]
    all_linked = sum(n for n, _ in by_kind.values())
    all_total = sum(t for _, t in by_kind.values())
    lines += [f"| **both** | {all_total} | {all_linked} | {all_linked / all_total:.0%} |", "",
              f"{len(all_drafts)} KB issues have no node. **{len(drafts)}** of them are written to `data/curated/ontology_candidates.yaml` as drafts because the KB text gives something to start from "
              f"({sum(1 for d in drafts if d['errors'])} an error line, {sum(1 for d in drafts if d['symptoms'])} a title that already reads like a symptom). "
              f"The other {stubs} have only a generic heading (\"Overview\", \"Run diagnostics\") and need a person to write the customer-side wording from scratch. "
              "The drafts are structural: no aliases and no summary. They are unlikely to change retrieval by themselves, because the KB retriever already matches these titles; "
              "the value of a node is the wording customers use and the docs do not.", "",
              "## Ontology issues that claim to be undocumented (`kb: []`): KB text that mentions their error (release notes and archive excluded)", ""]
    if wrong:
        lines += ["| node | error text | found in |", "|---|---|---|"] + [f"| `{w['id']}` | {w['error'][:60]} | {'; '.join(w['where'])} |" for w in wrong]
        lines += ["", "These are leads to review, not verdicts: the check matches the node's error text literally, so it can flag a page that only mentions the error and "
                   "miss one that documents the fix in other words (the socket-permission fix in `engine/install/linux-postinstall.md` never quotes the error, so it is not "
                   "listed here; a reviewer found it)."]
    else:
        lines.append("No claim is contradicted.")
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"coverage {all_linked}/{all_total}; {len(drafts)} informative drafts ({stubs} stubs left out); {len(wrong)} 'undocumented' claims with a lead -> {args.out_dir / 'ontology_candidates.yaml'}, {args.report}")


if __name__ == "__main__":
    main()
