"""
differential.py -- A4: retrieval-informed ambiguity check, as differential diagnosis.

A symptom like "docker pull fails with 429" or "SSO login isn't working" matches several
different KB issues. Instead of asking a generic "can you give more detail?", we:

  1. retrieve top-K chunks and group them into HYPOTHESES (one per KB issue)
  2. turn retrieval scores into a probability over hypotheses (softmax, soft doc-kind weights)
  3. decide: does one hypothesis clearly lead?  -> skip asking (the original A4 behaviour)
  4. if not, pick the question whose answer would eliminate the most competing causes
     (expected elimination -- a decision-tree split), and only if it eliminates enough
  5. after the customer answers, RE-WEIGHT hypotheses (soft penalty, never a hard filter --
     the design principle "soft signals, never hard filters") and decide again

The ranking is deterministic and cheap; an LLM is only ever used to phrase the question.
"""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field

from triage.answers import overlap_coefficient
from triage.config import ClarifierConfig
from triage.issues import FIELD_SUBSECTIONS, issue_key, issue_title, norm as _norm
from triage.state import (PLATFORMS, Candidate, ExtractedFields, Hypothesis, SignatureConfidence)
from triage.tools import ToolBudgetExceeded, ToolRegistry
from triage.understand import VAGUE_STOPWORDS, retrieval_query

_PLATFORM_RE = re.compile(r"(?i)\b(windows|macos|mac|linux)(?:faqs?)?\b")
_FENCED = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)


@dataclass
class Discriminator:
    feature: str
    options: list[str]
    gain: float         # expected fraction of probability mass eliminated by the answer
    coverage: float     # probability mass of hypotheses that have a known value for the feature


@dataclass
class AmbiguityResult:
    hypotheses: list[Hypothesis]
    confidence: SignatureConfidence
    discriminators: list[Discriminator]
    candidates: list[Candidate] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. cluster chunks into hypotheses
# ---------------------------------------------------------------------------

def _platform_of(c: Candidate) -> str | None:
    haystack = " ".join([c.source_path, *c.heading_path])
    found = {("mac" if m.lower().startswith("mac") else m.lower()) for m in _PLATFORM_RE.findall(haystack)}
    return next(iter(found)) if len(found) == 1 else None


def _error_text(chunks: list[Candidate]) -> str | None:
    """First fenced block that looks like an error message (not a shell command / JSON)."""
    ordered = sorted(chunks, key=lambda c: 0 if any("error" in p.lower() for p in c.heading_path[2:]) else 1)
    for c in ordered:
        for block in _FENCED.findall(c.text):
            line = " ".join(block.split())
            if 8 <= len(line) <= 400 and not line.startswith(("$", "#", "{", "[", "docker ", "sudo ")):
                return line[:140]
    return None


_WORD = re.compile(r"[a-z0-9_.:/'-]+")
_UBIQUITOUS = {"docker"}   # appears in every page, so it grounds nothing


def _content_words(fields: ExtractedFields) -> set[str]:
    query = " ".join(fields.symptoms + fields.error_messages).lower().replace("’", "'")
    return {w for w in _WORD.findall(query) if w not in VAGUE_STOPWORDS and w not in _UBIQUITOUS and len(w) > 2}


def _haystack(chunks: list[Candidate]) -> str:
    return " ".join(c.text + " " + " ".join(c.heading_path) for c in chunks).lower()


def _mentions(haystack: str, word: str) -> bool:
    """Prefix match on 5 chars so 'starting' matches 'start'."""
    return word in haystack or (len(word) >= 5 and word[:5] in haystack)


def lexical_grounding(fields: ExtractedFields, chunks: list[Candidate]) -> float:
    """Share of the customer's content words (from symptoms + error text) that appear in this
    issue's text. If the customer gave us no content words there is nothing to check, so return
    1.0 rather than penalise."""
    words = _content_words(fields)
    if not words:
        return 1.0
    haystack = _haystack(chunks)
    return sum(1 for w in words if _mentions(haystack, w)) / len(words)


# Plain English words are never "the thing that matters" (the first version flagged 'from', 'into', 'they', 'how').
_FUNCTION_WORDS = frozenset("""
about after again all already also and any are because been before being both but can could did does doing done each few for from
get gets getting got had has have her him his how into inside its just may might more most much must not off once only onto
other our out over per same she should some such than that the their them then there these they this those too under upon
very was were what when where which while who why will with within without would you your yours
""".split())


def _stem(word: str) -> str:
    """Crude suffix strip so 'pulls'/'pulling' match 'pull' (never strips the 's' of 'rootless' or 'access')."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4 and not (suffix == "s" and word.endswith("ss")):
            return word[:-len(suffix)]
    return word


def rare_pool_terms(fields: ExtractedFields, haystacks: list[str], cfg: ClarifierConfig) -> dict[str, str]:
    """Customer words that DISCRIMINATE between the retrieved issues: present in at least one but at most
    `rare_term_max_share` of them. A word in no issue is not counted (it may just be a synonym or noise, and overall
    grounding already covers it); a word in every issue ('pull') tells the issues apart not at all. Returns {word: stem}."""
    n = len(haystacks)
    if cfg.rare_term_max_share <= 0 or n < cfg.rare_term_min_hypotheses:
        return {}
    rare = {}
    for w in _content_words(fields) - _FUNCTION_WORDS:
        stem = _stem(w)
        df = sum(1 for h in haystacks if stem in h)
        if 1 <= df <= cfg.rare_term_max_share * n:
            rare[w] = stem
    return rare


def build_hypotheses(candidates: list[Candidate], cfg: ClarifierConfig,
                     fields: ExtractedFields | None = None) -> list[Hypothesis]:
    groups: "OrderedDict[str, list[Candidate]]" = OrderedDict()
    for c in candidates:
        groups.setdefault(issue_key(c), []).append(c)
    if not groups:
        return []

    adjusted: list[float] = []
    for chunks in groups.values():
        best = max(chunks, key=lambda c: c.score)
        kind_weight = cfg.doc_kind_weight.get(str(best.metadata.get("doc_kind", "")), 0.9)
        generic = cfg.generic_title_weight if _norm(issue_title(best)) in FIELD_SUBSECTIONS else 1.0
        adjusted.append(best.score * kind_weight * generic)

    haystacks = [_haystack(chunks) for chunks in groups.values()]
    rare = rare_pool_terms(fields, haystacks, cfg) if fields is not None else {}

    peak = max(adjusted)
    exps = [math.exp((a - peak) / max(cfg.softmax_temperature, 1e-6)) for a in adjusted]
    total = sum(exps)

    hyps: list[Hypothesis] = []
    for (key, chunks), hay, p in zip(groups.items(), haystacks, (e / total for e in exps)):
        best = max(chunks, key=lambda c: c.score)
        features = {
            "platform": _platform_of(best),
            "product_area": str(best.metadata.get("product_area") or "") or None,
            "component": str(best.metadata.get("component") or "") or None,  # informational only; never asked
            "doc_kind": str(best.metadata.get("doc_kind") or "") or None,
            "error_message": _error_text(chunks),
            "issue": issue_title(best),
        }
        article = best.article_title or (best.heading_path[0] if best.heading_path else "")
        hyps.append(Hypothesis(
            key=key, label=f"{article} > {issue_title(best)}".strip(" >"),
            weight=p, best_score=best.score, chunk_ids=[c.chunk_id for c in chunks],
            features={k: v for k, v in features.items() if v},
            grounding=round(lexical_grounding(fields, chunks), 3) if fields is not None else 1.0,
            missing_terms=sorted(w for w, stem in rare.items() if stem not in hay)))
    hyps.sort(key=lambda h: -h.weight)
    return hyps


# ---------------------------------------------------------------------------
# 2. decide whether the pool agrees
# ---------------------------------------------------------------------------

def waive_uncovered_terms(amb: "AmbiguityResult", cfg: ClarifierConfig) -> "AmbiguityResult":
    """The uncovered-term doubt exists to trigger ONE clarification. Once the customer has answered something it must not
    keep vetoing READY (they may simply have used a word the docs do not), so drop it and decide again."""
    if amb.confidence.reason == "uncovered_term":
        for h in amb.hypotheses:
            h.missing_terms = []
        amb.confidence = decide(amb.hypotheses, cfg)
    return amb


def decide(hyps: list[Hypothesis], cfg: ClarifierConfig) -> SignatureConfidence:
    if not hyps:
        return SignatureConfidence(0.0, 0.0, 0.0, True, "no_candidates")
    p_top = hyps[0].weight
    margin = p_top - (hyps[1].weight if len(hyps) > 1 else 0.0)
    top_score = hyps[0].best_score
    if top_score < cfg.min_top_score:
        return SignatureConfidence(p_top, margin, top_score, True, "no_evidence")
    if hyps[0].grounding < cfg.min_grounding:
        return SignatureConfidence(p_top, margin, top_score, True, "ungrounded")
    if hyps[0].missing_terms:       # the customer named something that tells the issues apart, and the leader lacks it
        return SignatureConfidence(p_top, margin, top_score, True, "uncovered_term")
    if p_top >= cfg.ready_p_top and margin >= cfg.ready_margin:
        return SignatureConfidence(p_top, margin, top_score, False, "clear")
    return SignatureConfidence(p_top, margin, top_score, True, "split")


# ---------------------------------------------------------------------------
# 3. which question would separate the competing causes?
# ---------------------------------------------------------------------------

def rank_discriminators(hyps: list[Hypothesis], fields: ExtractedFields, exclude: set[str],
                        cfg: ClarifierConfig) -> list[Discriminator]:
    """Expected elimination of feature f:  sum_v P(answer = v) * (mass removed by answer v).
    Hypotheses with no known value for f SURVIVE every answer, so a feature most hypotheses
    lack scores low automatically -- no separate coverage penalty is needed."""
    already_known = {
        "platform": fields.platform, "product_area": fields.product_area,
        # verbatim error TEXT only: a code like "HTTP 429" is what near-duplicate issues SHARE, so
        # knowing the code must not suppress the question that separates them
        "error_message": fields.error_messages,
    }
    out: list[tuple[float, Discriminator]] = []
    # Only plausible causes take part -- in the gain AND in the options a customer sees. A cause at
    # 0.03% probability is noise, and listing its error text in a menu is worse than useless.
    plausible = [h for h in hyps if h.weight >= cfg.min_option_weight and _norm(h.features.get("issue", "")) not in FIELD_SUBSECTIONS]
    pool_mass = sum(h.weight for h in plausible)
    if len(plausible) < 2 or pool_mass <= 0:
        return []
    for feature, answerability in cfg.feature_answerability.items():
        if feature in exclude or already_known.get(feature):
            continue
        known = [(h, _norm(h.features[feature])) for h in plausible if h.features.get(feature)]
        values: "OrderedDict[str, float]" = OrderedDict()
        for h, v in known:
            values[v] = values.get(v, 0.0) + h.weight / pool_mass          # renormalised over the plausible pool
        if feature == "platform":
            values = OrderedDict((v, m) for v, m in values.items() if v in PLATFORMS)
        if len(values) < 2:
            continue
        mass_known = sum(values.values())
        unknown_mass = max(1.0 - mass_known, 0.0)
        gain = 0.0
        for v, mass_v in values.items():
            surviving = mass_v + unknown_mass
            gain += (mass_v / mass_known) * (1.0 - surviving)
        if gain >= cfg.min_discriminator_gain:
            ordered = sorted(values, key=lambda v: -values[v])
            display = {_norm(h.features[feature]): h.features[feature] for h, _ in known}
            out.append((gain * answerability, Discriminator(
                feature, [display[v] for v in ordered][:cfg.max_options_in_question],
                round(gain, 4), round(mass_known, 4))))
    out.sort(key=lambda pair: -pair[0])
    return [d for _, d in out]


# ---------------------------------------------------------------------------
# 4. fold the customer's answers back in (soft re-weighting)
# ---------------------------------------------------------------------------

def apply_answers(hyps: list[Hypothesis], answered: dict[str, str], cfg: ClarifierConfig) -> list[Hypothesis]:
    """A hypothesis that CONTRADICTS an answered feature is down-weighted, not removed. 'unknown'
    answers (customer didn't know) change nothing. Weights are renormalised to sum to 1."""
    if not hyps or not answered:
        return hyps
    reweighted = []
    for h in hyps:
        w = h.weight
        for feature, value in answered.items():
            if value == "unknown":
                continue
            known = h.features.get(feature)
            if known and _norm(known) != _norm(value):
                w *= cfg.mismatch_penalty
        reweighted.append(w)
    total = sum(reweighted)
    for h, w in zip(hyps, reweighted):
        h.weight = w / total
    hyps.sort(key=lambda h: -h.weight)
    return hyps


def apply_error_evidence(hyps: list[Hypothesis], error_messages: list[str], cfg: ClarifierConfig) -> list[Hypothesis]:
    """If the customer pasted an error, hypotheses whose own documented error text matches it
    get boosted (scaled by match quality). No penalty for non-matches: the documented text is
    often just the first fenced block, and a missing match is weak evidence against."""
    if not hyps or not error_messages:
        return hyps
    for h in hyps:
        documented = h.features.get("error_message")
        if not documented:
            continue
        best = max(overlap_coefficient(documented, m) for m in error_messages)
        if best >= cfg.error_match_threshold:
            h.weight *= 1.0 + (cfg.error_match_boost - 1.0) * best
    total = sum(h.weight for h in hyps)
    for h in hyps:
        h.weight /= total
    hyps.sort(key=lambda h: -h.weight)
    return hyps


# ---------------------------------------------------------------------------
# 5. the A4 entry point
# ---------------------------------------------------------------------------

def ambiguity_check(fields: ExtractedFields, registry: ToolRegistry, answered: dict[str, str],
                    exclude: set[str], cfg: ClarifierConfig) -> AmbiguityResult:
    """Search (via the guarded tool registry), cluster, decide, and -- only if ambiguous --
    rank discriminating questions. Up to three queries, merged by best score per chunk:
      1. everything we know (product, component, symptoms, errors, platform)
      2. the same prefixed with "troubleshoot" -- found necessary on the real KB: plain symptom
         queries ("SSO login isn't working") surface FAQ entries and bury the actual
         troubleshooting entries, which are what carry the distinguishing error messages
      3. the customer's verbatim error text, when given -- in Docker docs the exact error
         string is the strongest retrieval clue."""
    base = retrieval_query(fields)
    queries = [base, f"troubleshoot {base}".strip()]
    if fields.error_messages:
        queries.append(" ".join(fields.error_messages))

    merged: dict[str, Candidate] = {}
    used: list[str] = []
    for q in queries:
        if not q:
            continue
        try:
            results = registry.call("search_kb", query=q)
        except ToolBudgetExceeded:
            break
        used.append(q)
        for c in results:
            if c.chunk_id not in merged or c.score > merged[c.chunk_id].score:
                merged[c.chunk_id] = c

    candidates = sorted(merged.values(), key=lambda c: -c.score)
    hyps = build_hypotheses(candidates, cfg, fields)
    hyps = apply_error_evidence(hyps, fields.error_messages, cfg)
    hyps = apply_answers(hyps, answered, cfg)
    confidence = decide(hyps, cfg)
    # A menu of causes is only worth showing when the candidates are plausible but SPLIT. For
    # no/ungrounded evidence a menu just offers junk; the Clarifier asks for the error text instead.
    # (uncovered_term also needs a question: the leader is grounded overall, so a menu of the competing issues is meaningful)
    split = confidence.ambiguous and confidence.reason in ("split", "uncovered_term")
    discriminators = rank_discriminators(hyps, fields, exclude, cfg) if split else []
    return AmbiguityResult(hyps, confidence, discriminators, candidates, used)
