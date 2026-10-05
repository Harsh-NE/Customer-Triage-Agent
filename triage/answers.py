"""
answers.py -- deterministic interpretation of a customer's reply to a clarifying question.

Used in two places, so it lives on its own:
  * clarifier.py  -- map the reply onto one of the options we offered
  * reflect.py    -- notice that the customer ALREADY stated the answer earlier

No LLM: option matching is cheap, testable, and has a clear failure mode (no match -> the
reply is passed to the normal extraction step and the question may be re-asked once).
"""

from __future__ import annotations

import re

from triage.understand import PRODUCT_ALIASES, detect_platform

NONE_OF_ABOVE = "unknown"
_NONE_RE = re.compile(r"(?i)\b(none of (these|them|those)|something else|neither|not sure|"
                      r"don'?t know|do not know|no idea|unsure|can'?t tell|not applicable)\b")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set("a an the is are was were be to of in on at for and or it this that i you my we your "
            "with by as from if when then so do does did not no can could would will".split())


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1}


def overlap_coefficient(a: str, b: str) -> float:
    """|A ∩ B| / min(|A|, |B|) over content tokens. Strings with fewer than 3 content tokens
    only score 1.0 on an exact token-set match (a 1-2 word string would otherwise 'match' anything)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    if min(len(ta), len(tb)) < 3:
        return 1.0 if ta == tb or (min(len(ta), len(tb)) >= 2 and (ta <= tb or tb <= ta)) else 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def is_none_of_above(text: str) -> bool:
    return bool(_NONE_RE.search(text))


_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}


def _ordinal_choice(reply: str, options: list[str]) -> str | None:
    """'2', 'number 2', 'the second one', 'option 3' -> that option. Only for SHORT replies, so a
    stray number inside a long pasted error message is never mistaken for a menu choice."""
    words = re.findall(r"[a-z0-9]+", reply.lower())
    if not words or len(words) > 6:
        return None
    for w in words:
        n = int(w) if w.isdigit() and len(w) == 1 else _ORDINALS.get(w)
        if n and 1 <= n <= len(options):
            return options[n - 1]
    return None


def match_option(feature: str, reply: str, options: list[str]) -> str | None:
    """Returns the option the reply selects, NONE_OF_ABOVE if the customer says they don't
    know / none apply, or None if nothing matches (caller treats it as unanswered)."""
    if not reply or not reply.strip():
        return None

    if feature == "platform":
        platform = detect_platform(reply)
        if platform and (not options or platform in options):
            return platform

    elif feature in ("error_message", "issue"):
        chosen = _ordinal_choice(reply, options)
        if chosen:
            return chosen
        reply_tokens = _tokens(reply)
        scored = []
        for opt in options:
            opt_tokens = _tokens(opt)
            if reply_tokens and opt_tokens:
                scored.append((len(reply_tokens & opt_tokens) / min(len(reply_tokens), len(opt_tokens)), opt))
        scored.sort(key=lambda x: -x[0])
        if scored and scored[0][0] >= 0.5 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            return scored[0][1]

    else:  # component / product_area / generic: option text, or an alias that maps to an option
        lowered = reply.lower().replace("-", " ")
        for opt in options:
            if re.search(rf"\b{re.escape(opt.lower().replace('-', ' '))}\b", lowered):
                return opt
        for alias in sorted(PRODUCT_ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", lowered) and PRODUCT_ALIASES[alias] in options:
                return PRODUCT_ALIASES[alias]

    return NONE_OF_ABOVE if is_none_of_above(reply) else None


def value_in_text(feature: str, text: str, options: list[str] | None = None) -> str | None:
    """Did this free text already state the value for `feature`? (no 'don't know' handling --
    a customer who said 'not sure' earlier hasn't answered anything)."""
    if feature == "platform":
        return detect_platform(text)
    if feature == "error_message" and options:
        found = match_option(feature, text, options)
        return None if found == NONE_OF_ABOVE else found
    if feature in ("component", "product_area") and options:
        found = match_option(feature, text, options)
        return None if found == NONE_OF_ABOVE else found
    return None
