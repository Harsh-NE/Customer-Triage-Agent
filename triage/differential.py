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
from triage.symptoms import choose_symptoms
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
    detail: dict = field(default_factory=dict)   # feature "trait:" / "confirm:<hypothesis key>": the question to ask and the cause it is about


@dataclass
class AmbiguityResult:
    hypotheses: list[Hypothesis]
    confidence: SignatureConfidence
    discriminators: list[Discriminator]
    candidates: list[Candidate] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    verbatim_error: bool = False    # the customer's pasted error matches the leading cause's documented error and no other's


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
        amb.confidence = decide(amb.hypotheses, cfg, amb.verbatim_error)
    return amb


def verbatim_error_leader(hyps: list[Hypothesis], error_messages: list[str], cfg: ClarifierConfig) -> bool:
    """True when what the customer pasted matches the LEADING cause's documented error text closely, is long enough to mean something,
    and no other cause's documented text comes close. Same match measure as apply_error_evidence."""
    pasted = [m for m in error_messages if len(re.findall(r"[a-z0-9]+", m.lower())) >= cfg.verbatim_min_tokens]
    if not hyps or not pasted:
        return False

    def match(h: Hypothesis) -> float:
        documented = h.features.get("error_message")
        return max(overlap_coefficient(documented, m) for m in pasted) if documented else 0.0

    lead = match(hyps[0])
    # another cause may share the same error text (a usage page quoting the same message): that only blocks the shortcut when it is
    # also nearly as likely as the leader
    return (lead >= cfg.verbatim_error_match and hyps[0].weight >= cfg.verbatim_min_p_top
            and all(lead - match(h) >= cfg.verbatim_runner_up_gap or hyps[0].weight >= cfg.verbatim_leader_ratio * h.weight for h in hyps[1:]))


def decide(hyps: list[Hypothesis], cfg: ClarifierConfig, verbatim: bool = False) -> SignatureConfidence:
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
    if verbatim:           # the customer quoted the documented error of one cause and no other: nothing left to ask
        return SignatureConfidence(p_top, margin, top_score, False, "clear")
    return SignatureConfidence(p_top, margin, top_score, True, "split")


# ---------------------------------------------------------------------------
# 3. which question would separate the competing causes?
# ---------------------------------------------------------------------------

# A TRAIT question tells two similar causes apart by asking about the one condition that sets the leading cause apart ("Does
# this happen when anti-virus software is installed?"), instead of handing the customer a list of documentation titles to pick from.
# The condition is read from the cause's own title: a clause after when / if / after / due to / with / using, else the whole title.
TRAIT_MIN_TOP2_SHARE = 0.6    # ask a yes/no only when the two leading causes hold at least this share of the plausible probability
TRAIT_MIN_LEADER_SHARE = 0.3  # ...or the leader alone holds this share and is this many times likelier than the runner-up
TRAIT_LEADER_RATIO = 1.5
TRAIT_DOMINANT_LEADER = 0.45  # a leader holding this share is the one to confirm; no yes/no about the runner-ups
PICK_SCORE = 5.0              # a symptom list for 3+ close causes outranks the concrete menus, which are junk when nothing leads
DETAIL_FIRST_SCORE = 10.0     # ...unless the field is flat, when it outranks everything (even a platform question can wait one turn)
DETAIL_SCORE = 0.05           # the open "tell me more" question ranks below every concrete discriminator
_TRAIT_CLAUSE = re.compile(r"\b(when|whenever|if|while|once|after|before|because of|due to|caused by|with|using|behind)\b\s+(.+)$", re.I)
_TRAIT_FORMS = {"when": "Does this happen when {}?", "whenever": "Does this happen whenever {}?", "if": "Does this happen if {}?",
                "while": "Does this happen while {}?", "once": "Does this happen once {}?", "after": "Did this start after {}?",
                "before": "Did this start before {}?", "because of": "Could this be related to {}?", "due to": "Could this be related to {}?",
                "caused by": "Could this be related to {}?", "with": "Does this happen with {}?", "using": "Are you using {}?",
                "behind": "Are you behind {}?"}
_TRAIT_STOP = set("a an the is are was were be been to of in on at for and or it its this that these those i you my we your with by as from "
                  "if when then so do does did not no can could would will docker desktop fails fail failing unable error errors issue "
                  "issues problem problems cannot cant dont doesnt".split())
_TRAIT_TOKEN = re.compile(r"[a-z0-9][a-z0-9.\-]{2,}")


def _clean_title(title: str) -> str:
    t = re.sub(r"\{#[^}]*\}", "", title or "")           # Hugo anchors: {#install-using-the-apt-repository}
    t = re.sub(r"[`*_]", "", t)
    return re.sub(r"\s+", " ", t).strip(" .:;?!-")


def _trait_tokens(text: str) -> set[str]:
    return {w for w in _TRAIT_TOKEN.findall(_clean_title(text).lower()) if w not in _TRAIT_STOP}


def trait_question(title: str, others: list[str]) -> tuple[str, float] | None:
    """(question, distinctiveness 0..1) for a cause with this title versus the other plausible causes' titles, or None when nothing
    sets it apart (or the title is too generic to ask about). Deterministic: no model call."""
    clean = _clean_title(title)
    if _norm(clean) in FIELD_SUBSECTIONS or len(_trait_tokens(clean)) < 2:
        return None
    rest_tokens = set().union(*(_trait_tokens(o) for o in others)) if others else set()
    m = _TRAIT_CLAUSE.search(clean)
    clause = bool(m and len(m.group(2).split()) >= 2)
    if clause:
        phrase = m.group(2).strip()
        if len(phrase) > 80:
            phrase = phrase[:80].rsplit(" ", 1)[0]
        tokens = _trait_tokens(phrase)
        question = _TRAIT_FORMS[m.group(1).lower()].format(phrase)
    else:
        tokens, question = _trait_tokens(clean), f'Does this describe your problem: "{clean}"?'
    if not tokens:
        return None
    quality = len(tokens - rest_tokens) / len(tokens)
    # a condition must really set the cause apart; confirming the cause in its own words only has to be more than a shared phrase
    return (question, quality) if quality >= (0.5 if clause else 0.3) else None


def rank_discriminators(hyps: list[Hypothesis], fields: ExtractedFields, exclude: set[str],
                        cfg: ClarifierConfig, symptoms=None) -> list[Discriminator]:
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
        if feature == "trait" or feature in exclude or already_known.get(feature):
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
    # SYMPTOM LIST for three or more close causes: say what each looks like and ask which the customer is seeing
    picked = None
    if cfg.feature_answerability.get("pick") and symptoms is not None and not any(f.startswith("pick:") for f in exclude):
        close = [h for h in plausible if h.weight >= cfg.pick_close_ratio * plausible[0].weight][:cfg.pick_max_options]
        if len(close) >= cfg.pick_min_close:
            chosen = choose_symptoms(close, symptoms, cfg.pick_max_options)
            if chosen:
                keys = [k for _, k in chosen]
                picked = Discriminator("pick:" + "||".join(keys), [t for t, _ in chosen], round(1.0 - 1.0 / len(chosen), 4), 1.0, {"keys": keys})
                out.append((PICK_SCORE, picked))
    trait_weight = None if picked else cfg.feature_answerability.get("trait")      # a symptom list replaces the yes/no for 3+ close causes
    top2 = sum(h.weight for h in plausible[:2]) / pool_mass
    leader = plausible[0].weight / pool_mass >= TRAIT_MIN_LEADER_SHARE and plausible[0].weight >= TRAIT_LEADER_RATIO * plausible[1].weight
    # a few close causes, one clear front-runner worth confirming, or the customer's extra detail has already been taken in and the
    # field is still open: then confirming the likeliest cause beats asking for yet more detail
    close_causes = top2 >= TRAIT_MIN_TOP2_SHARE or leader
    narrowed = close_causes or "detail" in exclude
    if trait_weight and narrowed:
        best: tuple[float, Discriminator] | None = None
        for rank, h in enumerate(plausible[:3]):                   # the leading causes: asking about a long shot separates nothing
            if f"trait:{h.key}" in exclude or f"confirm:{h.key}" in exclude:
                continue
            if rank > 0 and plausible[0].weight / pool_mass >= TRAIT_DOMINANT_LEADER and plausible[0].weight >= TRAIT_LEADER_RATIO * plausible[1].weight:
                continue                                           # a clear leader: a yes about a runner-up could not be decisive
            made = trait_question(h.features.get("issue", ""), [o.features.get("issue", "") for o in plausible if o is not h])
            if made is None:
                continue
            question, quality = made
            p = h.weight / pool_mass
            gain = 2 * p * (1 - p)                                  # yes keeps this cause (and removes the rest), no removes it
            if gain >= cfg.min_discriminator_gain and (best is None or gain * quality > best[0]):
                kind = "confirm" if question.startswith("Does this describe") else "trait"
                best = (gain * quality, Discriminator(f"{kind}:{h.key}", ["Yes", "No", "Not sure"], round(gain, 4), 1.0,
                                                      {"question": question, "key": h.key, "label": h.label, "quality": round(quality, 3)}))
        if best is not None:
            out.append((best[0] * trait_weight, best[1]))
    # Many causes and none stands out (or no condition separates the leaders): a yes/no per cause would burn the whole question
    # budget one candidate at a time. Ask for more detail instead; it is the lowest-ranked question, so anything sharper wins.
    if cfg.feature_answerability.get("trait") and "detail" not in exclude and not picked:
        # With no front-runner a menu of error texts or products (drawn from unrelated pages) is noise: a person would ask what is
        # happening first. So when the field is flat, "tell me more" goes first; otherwise it is the last-ranked fallback.
        out.append((DETAIL_FIRST_SCORE if not close_causes else DETAIL_SCORE, Discriminator("detail", [], 0.0, 1.0)))
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
            if feature.startswith("pick:"):                        # a list of symptoms: picked causes up, the other listed ones down
                keys = feature[len("pick:"):].split("||")
                if h.key in keys:
                    chosen = {int(i) - 1 for i in value.split(",") if i.strip().isdigit()}
                    w *= (cfg.pick_boost if keys.index(h.key) in chosen else cfg.pick_penalty) if chosen else cfg.pick_none_penalty
                continue
            if feature.startswith(("trait:", "confirm:")):         # a yes/no about ONE cause: yes lifts it, no sinks it
                kind, _, key = feature.partition(":")
                if h.key == key:
                    # "yes" to the cause in its own words is strong evidence; "yes" to one condition only moderate (a condition can hold
                    # for several causes). A "no" removes the cause either way.
                    yes = (1.0 / cfg.mismatch_penalty) if kind == "confirm" else cfg.trait_yes_boost
                    w *= yes if value == "yes" else cfg.mismatch_penalty
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
                    exclude: set[str], cfg: ClarifierConfig, symptoms=None) -> AmbiguityResult:
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
    verbatim = verbatim_error_leader(hyps, fields.error_messages, cfg)
    confidence = decide(hyps, cfg, verbatim)
    # A menu of causes is only worth showing when the candidates are plausible but SPLIT. For
    # no/ungrounded evidence a menu just offers junk; the Clarifier asks for the error text instead.
    # (uncovered_term also needs a question: the leader is grounded overall, so a menu of the competing issues is meaningful)
    split = confidence.ambiguous and confidence.reason in ("split", "uncovered_term")
    discriminators = rank_discriminators(hyps, fields, exclude, cfg, symptoms) if split else []
    return AmbiguityResult(hyps, confidence, discriminators, candidates, used, verbatim)
