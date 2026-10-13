"""
model.py -- a small, human-editable domain ontology (a knowledge graph of ~130 nodes) for the agent.

Why it exists. The agent retrieves with embeddings and BM25, which know words, not the product. They do not know that "docker for
mac", "Docker Desktop for Mac" and "Docker.app" are one thing, that WSL 2 only exists on Windows, that "exit code 137" usually means
the kernel killed the container for memory, that two near-identical 429 sections differ in who is being rate limited, or which
documented issue a customer's wording points at. This file holds that knowledge in a form people can read, review and diff
(`docker.yaml`), and this module turns it into fast lookups. It is deliberately NOT RDF/OWL/Neo4j: ~130 nodes, a handful of relation
kinds, plain dicts, one compiled regular expression.

Node types   product | component | feature | tool | platform | concept | use_case | error | issue
Relations    parent (part_of) . related . available_on (platforms) . confused_with (+ how they differ) . affects (issue -> nodes)
             kb (issue -> the documented KB issue that answers it) . kb_area (node -> the KB's own product_area label)
Matching     aliases are matched case-insensitively with hyphens/underscores read as spaces, on word boundaries, longest first, so
             "docker desktop for mac" wins over "docker desktop". `scoped` aliases (e.g. a bare "hub") count only when the text also
             contains their context words. Nodes marked `generic` ("docker", "container") are recognised but never used to expand a
             query or to boost a result: they are in almost every text and say nothing.
Background   `summary` text is DEFINITIONAL background for the agent. It is never evidence: the Resolver still cites only retrieved
             passages. Each node records its `provenance` (kb | tickets | general) so a reviewer knows what to double-check.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import yaml

DEFAULT_FILE = Path(__file__).with_name("docker.yaml")
PLATFORMS = ("windows", "mac", "linux")
TYPES = {"product", "component", "feature", "tool", "platform", "concept", "use_case", "error", "issue"}
PROVENANCE = {"kb", "tickets", "general"}

_STOP = set("a an the is are was were be been to of and or in on for with my i it this that how do does can cannot not when after "
            "before from at as by me we our you your has have had will would should could just get got using use used into out up down "
            "docker".split())


def norm(text: str) -> str:
    """Lower-case; hyphens and underscores read as spaces ('docker-compose' == 'docker compose'); whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[-_]+", " ", (text or "").lower())).strip()


def norm_title(text: str) -> str:
    """Issue titles carry markdown (backticks, quotes); links in the YAML are written without them."""
    return re.sub(r"\s+", " ", re.sub(r"[`'\"]", "", (text or "").lower())).strip()


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4 and not (suffix == "s" and word.endswith("ss")):
            return word[: -len(suffix)]
    return word


def content_tokens(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9][a-z0-9.]*", norm(text)) if len(w) > 2 and w not in _STOP}


@dataclass(frozen=True)
class KBLink:
    path: str            # fragment of the KB source path, e.g. "engine/daemon/troubleshoot.md"
    issue: str           # start of the issue title as the KB writes it (markdown quotes ignored)


@dataclass(frozen=True)
class Entity:
    id: str
    type: str
    name: str
    summary: str = ""
    aliases: tuple[str, ...] = ()
    scoped: tuple[tuple[str, tuple[str, ...]], ...] = ()          # (alias, context words that must also appear)
    parent: Optional[str] = None
    related: tuple[str, ...] = ()
    available_on: tuple[str, ...] = ()                            # empty = not platform specific
    kb_area: Optional[str] = None
    confused_with: tuple[tuple[str, str], ...] = ()               # (entity id, how they differ)
    generic: bool = False
    symptoms: tuple[str, ...] = ()                                # issues: how customers describe it
    errors: tuple[str, ...] = ()                                  # issues/errors: strings that appear verbatim
    affects: tuple[str, ...] = ()
    kb: tuple[KBLink, ...] = ()
    provenance: str = "general"

    @property
    def restricted_platforms(self) -> frozenset[str]:
        """Platforms this node is limited to, or empty when it is not platform specific (all three count as 'not restricted')."""
        return frozenset(self.available_on) if 0 < len(set(self.available_on)) < len(PLATFORMS) else frozenset()


@dataclass(frozen=True)
class Mention:
    entity: Entity
    alias: str
    start: int
    end: int


def _tuple(v) -> tuple:
    return tuple(v) if v else ()


def entity_from_dict(d: dict) -> Entity:
    unknown = set(d) - {"id", "type", "name", "summary", "aliases", "scoped", "parent", "related", "available_on", "kb_area", "confused_with",
                        "generic", "symptoms", "errors", "affects", "kb", "provenance"}
    if unknown:
        raise ValueError(f"entity '{d.get('id')}': unknown field(s) {sorted(unknown)}")
    return Entity(
        id=d["id"], type=d["type"], name=d["name"], summary=(d.get("summary") or "").strip(), aliases=_tuple(d.get("aliases")),
        scoped=tuple((s["alias"], _tuple(s.get("needs"))) for s in d.get("scoped") or []), parent=d.get("parent"),
        related=_tuple(d.get("related")), available_on=_tuple(d.get("available_on")), kb_area=d.get("kb_area"),
        confused_with=tuple((c["id"], c.get("differs", "")) for c in d.get("confused_with") or []), generic=bool(d.get("generic", False)),
        symptoms=_tuple(d.get("symptoms")), errors=_tuple(d.get("errors")), affects=_tuple(d.get("affects")),
        kb=tuple(KBLink(k["path"], k["issue"]) for k in d.get("kb") or []), provenance=d.get("provenance", "general"))


class Ontology:
    def __init__(self, entities: list[Entity], domain: str = "docker", version: str = "") -> None:
        self.domain, self.version = domain, version
        self.entities = entities
        self.by_id: dict[str, Entity] = {}
        for e in entities:
            if e.id in self.by_id:
                raise ValueError(f"duplicate entity id '{e.id}'")
            self.by_id[e.id] = e
        self._alias: dict[str, tuple[Entity, tuple[str, ...]]] = {}
        self.collisions: list[tuple[str, str, str]] = []
        for e in entities:
            for alias in (e.name, *e.aliases, *e.errors):
                self._register(alias, e, ())
            for alias, needs in e.scoped:
                self._register(alias, e, tuple(norm(n) for n in needs))
        phrase_df: dict[str, int] = {}
        for e in entities:
            if e.type == "issue":
                for tok in {t for p in (*e.symptoms, e.name) for t in content_tokens(p)}:
                    phrase_df[tok] = phrase_df.get(tok, 0) + 1
        n_issues = max(sum(1 for e in entities if e.type == "issue"), 1)
        self._tok_weight = {t: math.log((n_issues + 1) / (c + 0.5)) + 1.0 for t, c in phrase_df.items()}
        keys = sorted(self._alias, key=len, reverse=True)
        self._rx = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(k) for k in keys) + r")(?![a-z0-9])") if keys else None

    def _register(self, alias: str, e: Entity, needs: tuple[str, ...]) -> None:
        key = norm(alias)
        if not key:
            return
        if key in self._alias and self._alias[key][0].id != e.id:
            self.collisions.append((key, self._alias[key][0].id, e.id))
            return
        self._alias.setdefault(key, (e, needs))

    # ---- loading --------------------------------------------------------------------------------------------
    @classmethod
    def from_yaml(cls, path: Path | str = DEFAULT_FILE) -> "Ontology":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls([entity_from_dict(d) for d in raw["entities"]], raw.get("domain", "docker"), str(raw.get("version", "")))

    # ---- matching ---------------------------------------------------------------------------------------------
    def find(self, text: str) -> list[Mention]:
        """All alias mentions in `text`, non-overlapping, longest alias first."""
        if not self._rx:
            return []
        t = norm(text)
        words = set(re.findall(r"[a-z0-9]+", t))
        out = []
        for m in self._rx.finditer(t):
            entity, needs = self._alias[m.group(0)]
            if needs and not all(n in words or n in t for n in needs):
                continue
            out.append(Mention(entity, m.group(0), m.start(), m.end()))
        return out

    def entities_in(self, text: str, include_generic: bool = True) -> list[Entity]:
        seen: dict[str, Entity] = {}
        for m in self.find(text):
            if include_generic or not m.entity.generic:
                seen.setdefault(m.entity.id, m.entity)
        return list(seen.values())

    # ---- graph ------------------------------------------------------------------------------------------------
    def ancestors(self, entity_id: str) -> list[Entity]:
        out, cur = [], self.by_id.get(entity_id)
        while cur is not None and cur.parent and cur.parent in self.by_id and len(out) < 8:
            cur = self.by_id[cur.parent]
            out.append(cur)
        return out

    def children(self, entity_id: str) -> list[Entity]:
        return [e for e in self.entities if e.parent == entity_id]

    def issues(self) -> list[Entity]:
        return [e for e in self.entities if e.type == "issue"]

    # ---- query-side helpers ---------------------------------------------------------------------------------------
    def match_issues(self, text: str, min_score: float = 0.6, limit: int = 3) -> list[tuple[Entity, float]]:
        """Which known issues does this customer wording point at? An error string present verbatim scores 1.0; otherwise the best
        share of a symptom phrase's content words that the text contains (phrases need >= 2 content words, so one shared word
        never matches)."""
        t = norm(text)
        tokens = content_tokens(text)
        scored = []
        for e in self.issues():
            best = 0.0
            if any(norm(err) in t for err in e.errors if norm(err)):
                best = 1.0
            for phrase in (*e.symptoms, e.name):
                ptoks = content_tokens(phrase)
                if len(ptoks) >= 2:
                    w = self._tok_weight
                    best = max(best, sum(w.get(t, 1.0) for t in ptoks & tokens) / sum(w.get(t, 1.0) for t in ptoks))
            if best >= min_score:
                scored.append((e, round(best, 3)))
        return sorted(scored, key=lambda x: -x[1])[:limit]

    def expand(self, text: str, max_terms: int = 6) -> list[str]:
        """Extra search terms for BM25: the canonical name (and one alias) of every specific entity mentioned, and the documented title
        of a confidently matched issue. Only words not already in the query; never from generic entities."""
        present = norm(text)
        extra: list[str] = []

        def add(term: str) -> None:
            n = norm(term)
            if n and n not in present and n not in (norm(x) for x in extra):
                extra.append(term)

        for e in self.entities_in(text, include_generic=False):
            if e.type == "issue":
                continue
            add(e.name)
            for alias in e.aliases:
                if norm(alias) not in present and len(alias) > 3:
                    add(alias)
                    break
        for issue, score in self.match_issues(text, min_score=0.75, limit=2):
            add(issue.name)
        return extra[:max_terms]

    def platforms(self, text: str) -> set[str]:
        """Platforms named by the text, directly ("windows") or through a platform-bound feature ("wsl 2" -> windows)."""
        found: set[str] = set()
        for e in self.entities_in(text):
            if e.type == "platform" and e.id in PLATFORMS:
                found.add(e.id)
            elif e.restricted_platforms and len(e.restricted_platforms) == 1:
                found |= e.restricted_platforms
        return found

    def infer(self, text: str) -> dict:
        """Fields the wording implies. Used only to FILL gaps, never to override what the customer said."""
        ents = self.entities_in(text, include_generic=False)
        plats = self.platforms(text)
        areas = {e.kb_area for e in ents if e.kb_area and e.type in ("product", "tool", "feature")}
        return {"platform": next(iter(plats)) if len(plats) == 1 else None,
                "product_area": next(iter(areas)) if len(areas) == 1 else None, "entities": ents}

    def required_platforms(self, text: str) -> frozenset[str]:
        """Platforms an issue/section is limited to, from the platform-bound nodes in `text` (a heading). Empty = not limited."""
        sets = [e.restricted_platforms for e in self.entities_in(text) if e.restricted_platforms]
        if not sets:
            return frozenset()
        common = frozenset.intersection(*sets)
        return common

    def background(self, text: str, limit: int = 4) -> list[str]:
        """One-line definitions of the specific things the text mentions. Background for the model, never evidence."""
        lines = []
        for e in self.entities_in(text, include_generic=False):
            if e.type in ("issue", "error", "use_case") or not e.summary:
                continue
            lines.append(f"{e.name}: {e.summary}")
            if len(lines) == limit:
                break
        return lines

    # ---- quality ----------------------------------------------------------------------------------------------
    def validate(self) -> list[str]:
        problems: list[str] = [f"alias '{a}' claimed by both '{x}' and '{y}'" for a, x, y in self.collisions]
        for e in self.entities:
            if e.type not in TYPES:
                problems.append(f"{e.id}: unknown type '{e.type}'")
            if e.provenance not in PROVENANCE:
                problems.append(f"{e.id}: unknown provenance '{e.provenance}'")
            for ref in (e.parent, *e.related, *e.affects, *(c for c, _ in e.confused_with)):
                if ref and ref not in self.by_id:
                    problems.append(f"{e.id}: refers to unknown entity '{ref}'")
            for p in e.available_on:
                if p not in PLATFORMS:
                    problems.append(f"{e.id}: unknown platform '{p}'")
            if e.type == "issue" and not (e.symptoms or e.errors):
                problems.append(f"{e.id}: an issue needs symptoms or errors")
            if e.type == "platform" and e.id in PLATFORMS and not e.aliases:
                problems.append(f"{e.id}: platform without aliases")
            if e.id == e.parent:
                problems.append(f"{e.id}: is its own parent")
        for e in self.entities:                                    # parent chains must end
            seen, cur = {e.id}, e
            while cur.parent in self.by_id:
                cur = self.by_id[cur.parent]
                if cur.id in seen:
                    problems.append(f"{e.id}: parent cycle")
                    break
                seen.add(cur.id)
        return problems


# ---------------------------------------------------------------------------
# Index over a corpus: which chunks mention which entities, and where each KB link points
# ---------------------------------------------------------------------------

@dataclass
class EntityIndex:
    """Entities per chunk and the reverse map, built once at start-up from the stored chunks. Chunks are tagged with the same
    matcher used on queries, so there is no separate tagging step to keep in sync and no store to rebuild."""
    ontology: Ontology
    by_chunk: dict[str, set[str]] = field(default_factory=dict)
    in_heading: dict[str, set[str]] = field(default_factory=dict)
    by_entity: dict[str, set[str]] = field(default_factory=dict)
    issue_chunks: dict[str, set[str]] = field(default_factory=dict)     # issue entity id -> chunk ids of its documented KB issue
    unresolved: list[tuple[str, KBLink]] = field(default_factory=list)  # kb links that match no chunk
    n_chunks: int = 0

    @classmethod
    def build(cls, ontology: Ontology, rows: Iterable[tuple[str, str, list[str], str]]) -> "EntityIndex":
        """rows: (chunk_id, text, heading_path, source_path)."""
        from triage.issues import issue_title
        from triage.state import Candidate
        idx = cls(ontology)
        titles: list[tuple[str, str, str]] = []
        for chunk_id, text, heading_path, source_path in rows:
            heading = " ".join(heading_path)
            ents = {e.id for e in ontology.entities_in(f"{heading} {text[:4000]}", include_generic=False)}
            heads = {e.id for e in ontology.entities_in(heading, include_generic=False)}
            idx.by_chunk[chunk_id], idx.in_heading[chunk_id] = ents, heads
            for eid in ents:
                idx.by_entity.setdefault(eid, set()).add(chunk_id)
            titles.append((chunk_id, source_path, norm_title(issue_title(Candidate(chunk_id, "", 0.0, source_path, "", heading_path, {})))))
            idx.n_chunks += 1
        for issue in ontology.issues():
            hits: set[str] = set()
            for link in issue.kb:
                found = {cid for cid, path, title in titles if link.path in path and title.startswith(norm_title(link.issue))}
                if not found:
                    idx.unresolved.append((issue.id, link))
                hits |= found
            if hits:
                idx.issue_chunks[issue.id] = hits
        return idx

    def idf(self, entity_id: str) -> float:
        return math.log((self.n_chunks + 1) / (len(self.by_entity.get(entity_id, ())) + 1))

    def specific(self, entity_id: str, max_share: float = 0.10) -> bool:
        return 0 < len(self.by_entity.get(entity_id, ())) <= max_share * max(self.n_chunks, 1)

    def known_issue_chunks(self, text: str, min_score: float = 0.9, limit: int = 12) -> list[str]:
        """Chunks of the documented KB issue(s) the wording confidently points at (a verbatim error string or nearly every distinctive
        word of a known symptom). A curated link, so it is strong evidence; the caller decides how loudly to vote with it."""
        scores: dict[str, float] = {}
        for issue, s in self.ontology.match_issues(text, min_score=min_score, limit=2):
            for cid in self.issue_chunks.get(issue.id, ()):
                scores[cid] = max(scores.get(cid, 0.0), s)
        return [cid for cid, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))][:limit]

    def rank(self, text: str, limit: int = 30) -> list[str]:
        """Chunk ids sharing the most (and the rarest) specific entities with the text, best first; a mention in a heading counts
        double. Weaker evidence than a known-issue match, so it is fused with a lower weight."""
        scores: dict[str, float] = {}
        for e in self.ontology.entities_in(text, include_generic=False):
            if e.type == "issue" or not self.specific(e.id):
                continue
            weight = self.idf(e.id)
            for cid in self.by_entity.get(e.id, ()):
                scores[cid] = scores.get(cid, 0.0) + weight * (2.0 if e.id in self.in_heading.get(cid, ()) else 1.0)
        return [cid for cid, _ in sorted(scores.items(), key=lambda kv: -kv[1])][:limit]

    def coverage(self) -> float:
        return sum(1 for v in self.by_chunk.values() if v) / max(self.n_chunks, 1)


_DEFAULT: Optional[Ontology] = None


def load_ontology(path: Path | str | None = None) -> Ontology:
    """The packaged Docker ontology (cached), or a custom domain file."""
    global _DEFAULT
    if path is not None:
        return Ontology.from_yaml(path)
    if _DEFAULT is None:
        _DEFAULT = Ontology.from_yaml(DEFAULT_FILE)
    return _DEFAULT
