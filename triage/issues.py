"""
issues.py -- what counts as "one KB issue" when grouping chunks.

The real Docker KB is inconsistent about heading depth: docker-hub/troubleshoot.md makes the
issue an H2 with "Error message / Possible causes / Solution" as H3, while desktop topics.md
makes the issue an H3 with those as H4. Sub-headings that merely describe PARTS of an issue
are therefore treated as belonging to their parent, so both layouts cluster the same way.
"""

from __future__ import annotations

from triage.state import Candidate

FIELD_SUBSECTIONS = {
    "overview", "error message", "error messages", "possible causes", "causes", "cause",
    "solution", "solutions", "resolution", "workaround", "symptoms", "affected environments",
    "steps to replicate", "prerequisites",
}


def norm(value: str) -> str:
    return " ".join(value.strip().lower().split())


def issue_title(c: Candidate) -> str:
    hp = c.heading_path
    section = hp[1] if len(hp) > 1 else ""
    sub = hp[2] if len(hp) > 2 else ""
    if sub and norm(sub) not in FIELD_SUBSECTIONS:
        return sub
    return section or (hp[0] if hp else c.article_title)


def issue_key(c: Candidate) -> str:
    return f"{c.source_path}::{issue_title(c)}"
