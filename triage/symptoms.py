"""
symptoms.py -- what a customer would SEE for each KB issue, in everyday words, and how the Clarifier picks a few of them to ask about.

When three or more causes are about equally likely and no single fact (operating system, error text) separates them, the Clarifier
lists what each one looks like from the customer's side ("Docker Desktop never opens", "Pulls stop with a 429 error") and asks which
they are seeing, instead of asking them to choose between documentation titles.

Where the wording comes from, best first:
  1. the symptom bank (data/processed/docker/symptoms.json), written ahead of time by scripts/12_symptoms.py: a model reads each
     issue's own text and writes 1-3 short symptoms, which are checked against that text. Nothing is generated while a customer waits.
  2. the ontology's "how customers describe it" phrases for the issue (triage/ontology/docker.yaml), when the issue is linked there
  3. the issue's own title, when it already reads as a symptom ("Docker.app is damaged and can't be opened")
An issue whose title is a cause label ("Not enough seats") and has no stored symptom simply contributes nothing.

`choose_symptoms` keeps only wording that sets a cause apart from the others in the same question.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable, Optional

from triage import config

BANK_FILE = config.PROJECT_ROOT / "data" / "processed" / "docker" / "symptoms.json"
NONE_OPTION = "None of these, let me describe it"

# a title that already describes something a customer notices, as opposed to naming a cause or a topic
_SYMPTOM_LIKE = re.compile(
    r"(?i)\b(fail\w*|unable|cannot|can't|can not|won't|doesn't|does not|not (?:work\w*|start\w*|open\w*|found|allowed|enabled|responding|recogni[sz]ed)|"
    r"error\w*|stuck|crash\w*|hang\w*|slow|denied|time[sd]? ?out|refused|missing|broken|damaged|unavailable|blocked|exceed\w*|out of|"
    r"reached|too many|incompatible|rejected|invalid|unexpected|lost|freez\w*|never|disappear\w*|ignored|overwritten)\b")
IMPERATIVE_START = {"run", "use", "set", "check", "install", "open", "go", "click", "restart", "update", "add", "remove", "make", "try", "ensure",
                    "configure", "enable", "disable", "create", "delete", "change", "verify", "contact", "reinstall", "upgrade", "download",
                    "view", "see", "find", "get", "start", "stop", "manage", "enforce", "resolve", "fix", "troubleshoot", "diagnose"}
_STOP = set("a an the is are was were be been to of in on at for and or it its this that these those i you my we your with by as from if when "
            "then so do does did not no can could would will docker desktop engine fails fail failing unable error errors issue issues "
            "problem problems cannot cant dont doesnt".split())
_TOKEN = re.compile(r"[a-z0-9][a-z0-9.\-]{2,}")


def clean(text: str) -> str:
    t = re.sub(r"\{#[^}]*\}", "", text or "")                       # Hugo anchors
    t = re.sub(r"[`*_]", "", t)
    return re.sub(r"\s+", " ", t).strip(" .:;?!-")


def tokens(text: str) -> set[str]:
    return {w for w in _TOKEN.findall(clean(text).lower()) if w not in _STOP}


def sentence(text: str) -> str:
    """'docker pull fails with 429' -> 'Docker pull fails with 429'."""
    t = clean(text)
    return t[:1].upper() + t[1:] if t else t


class SymptomBank:
    def __init__(self, entries: Optional[dict[str, dict]] = None, ontology=None) -> None:
        self.entries = entries or {}
        self._ontology_links: list[tuple[str, str, list[str]]] = []      # (path fragment, normalised title prefix, symptoms)
        if ontology is not None:
            from triage.ontology.model import norm_title
            for issue in ontology.issues():
                for link in issue.kb:
                    if issue.symptoms:
                        self._ontology_links.append((link.path, norm_title(link.issue), list(issue.symptoms)))

    @classmethod
    def load(cls, path: Path | str | None = None, ontology=None) -> "SymptomBank":
        p = Path(path) if path else BANK_FILE
        entries: dict[str, dict] = {}
        if p.exists():
            try:
                entries = json.loads(p.read_text(encoding="utf-8")).get("issues", {})
            except (json.JSONDecodeError, OSError):
                entries = {}
        return cls(entries, ontology)

    def for_issue(self, key: str) -> list[str]:
        """Symptom wordings for the issue `key` ('<source_path>::<issue title>'), best first; possibly empty."""
        stored = self.entries.get(key)
        if stored and stored.get("symptoms"):
            return [sentence(s) for s in stored["symptoms"]]
        path, _, title = key.partition("::")
        from triage.ontology.model import norm_title
        for fragment, prefix, symptoms in self._ontology_links:
            if fragment in path and norm_title(title).startswith(prefix):
                return [sentence(s) for s in symptoms[:2]]
        words = clean(title).split()
        if _SYMPTOM_LIKE.search(clean(title)) and len(words) >= 3 and words[0].lower() not in IMPERATIVE_START:     # not "Check for errors"
            return [sentence(title)]
        return []


def choose_symptoms(causes: Iterable, bank: Optional[SymptomBank], max_options: int = 4, min_options: int = 2,
                    min_distinct: float = 0.4, min_leader_distinct: float = 0.25) -> Optional[list[tuple[str, str]]]:
    """[(symptom text, hypothesis key), ...] for the given causes (best first), one symptom per cause, each of which sets that cause apart
    from the others, or None when fewer than `min_options` causes have usable wording. `causes` are Hypothesis objects."""
    if bank is None:
        return None
    causes = list(causes)
    options = {c.key: bank.for_issue(c.key) for c in causes}
    if not causes or not options[causes[0].key]:
        return None              # never list symptoms that leave out the most likely cause: the customer would pick the nearest wrong one
    chosen: list[tuple[str, str]] = []
    for rank, c in enumerate(causes):
        others: set[str] = set()
        for o in causes:
            if o is not c:
                others |= tokens(o.features.get("issue", "")) | {t for s in options[o.key] for t in tokens(s)}
        best, best_q = None, 0.0
        for s in options[c.key]:
            toks = tokens(s)
            q = len(toks - others) / len(toks) if toks else 0.0
            if q >= (min_leader_distinct if rank == 0 else min_distinct) and q > best_q:    # the leader needs less to be listed, but must still differ
                best, best_q = s, q
        if best:
            chosen.append((best, c.key))
        elif rank == 0:
            return None          # the most likely cause has no wording that sets it apart: a list without it would mislead
        if len(chosen) == max_options:
            break
    return chosen if len(chosen) >= min_options else None


def enabled() -> bool:
    return os.environ.get("SYMPTOM_LIST", "on").lower() != "off"
