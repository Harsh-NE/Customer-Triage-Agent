"""
spell.py -- fix likely typos in a customer's message against the words the knowledge base actually uses.

Why: a typo ("contianer", "permisison") makes the keyword search miss and the embedding drift (reports/regression/perturb_eval.md: recall@8 of the
right issue 0.84 -> 0.78 with 12% of long words mistyped). The knowledge base's own vocabulary (the BM25 index, about 24,000 words) is a better
dictionary than a general one: it contains "rootless", "buildx" and "xdebug".

Rules, chosen to do nothing when unsure:
  * only plain alphabetic words of 5+ letters that are NOT in the vocabulary are touched (so a word the KB knows is never changed);
  * the replacement is a word in the vocabulary one edit away (swap of neighbours, one letter missing, extra or wrong); the most common one wins
    (lowest BM25 idf), because the most common word is the likeliest intended one;
  * words with digits or symbols, words in CAPITALS, and anything next to a / . _ - : (paths, flags, hostnames, image names) are left alone;
  * a word that is not in the vocabulary and has no near neighbour is left alone: it may be a product name.

It is a heuristic and is opt-in. `python -m triage.eval.perturb_eval --prep typofix` measures whether it helps and, as importantly, that it does not
change a message that has no typos.
"""

from __future__ import annotations

import re
from typing import Mapping

_WORD = re.compile(r"(?<![\w/.\-:@$#])([A-Za-z]{5,})(?![\w/.\-:@])")
_LETTERS = "abcdefghijklmnopqrstuvwxyz"


class Speller:
    def __init__(self, idf: Mapping[str, float], min_len: int = 5) -> None:
        """idf: BM25 idf by word (its keys are the vocabulary; a LOW idf means a common word)."""
        self._idf = idf
        self._min_len = min_len

    def known(self, word: str) -> bool:
        return word.lower() in self._idf

    def edits1(self, word: str) -> set[str]:
        splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
        deletes = {a + b[1:] for a, b in splits if b}
        swaps = {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1}
        replaces = {a + c + b[1:] for a, b in splits if b for c in _LETTERS}
        inserts = {a + c + b for a, b in splits for c in _LETTERS}
        return deletes | swaps | replaces | inserts

    def correct_word(self, word: str) -> str:
        """The word itself unless it is unknown to the vocabulary and has a near neighbour in it, in which case the most common neighbour."""
        low = word.lower()
        if len(low) < self._min_len or low in self._idf or word.isupper():
            return word
        near = [c for c in self.edits1(low) if c in self._idf]
        if not near:
            return word
        best = min(near, key=lambda c: (self._idf[c], c))
        return best.capitalize() if word[:1].isupper() else best

    def correct(self, text: str) -> str:
        return _WORD.sub(lambda m: self.correct_word(m.group(1)), text or "")
