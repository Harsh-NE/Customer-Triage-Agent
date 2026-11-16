"""
text_metrics.py -- the metrics a paper needs, in one small dependency-light module (offline, no model calls).

RANKING (retrieval). Input is a list of 1-based ranks of the gold item per question (None = not retrieved in the list).
  recall_at_k, mrr, ndcg_at_k, hit_rate.  One gold item per question, so NDCG@K = 1/log2(rank+1) when rank <= K, else 0
  (the ideal DCG is 1). `ranking_report` gives all of them plus a bootstrap 95% interval for each.

GENERATION (answer text against a reference answer). Tokens are lower-cased words; code and error strings are kept whole.
  bleu            sentence BLEU-4 with add-one smoothing on n-grams > 1 (Lin & Och 2004), brevity penalty included; the corpus score is
                  the mean of sentence scores (stated in the report: this is not sacreBLEU's corpus-level score).
  rouge_1/2/l     F1 of unigram / bigram overlap and of the longest common subsequence.
  meteor          nltk's METEOR (exact + stem + WordNet synonyms) when nltk and its WordNet data are present, else an exact+stem fallback
                  that is labelled as such in the output. Never a silent change: `meteor_variant()` says which one ran.
  semantic_sim    optional cosine similarity of sentence embeddings (BERTScore-like, but one vector per text); pass an `encode` function.

STATISTICS. `bootstrap_ci` resamples questions (not tokens) with a fixed seed, so a rate or a mean comes with an interval; with n=19 the
interval is wide and that is the honest thing to print. `paired_bootstrap` gives the interval of the difference of two systems on the
SAME questions, which is the right test for "is A better than B".

Everything here is deterministic. Run the tests with `python -m pytest tests/test_text_metrics.py`.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from typing import Callable, Sequence

KS = (1, 3, 5, 8)
_WORD = re.compile(r"[\w.\-/:]+", re.UNICODE)          # keeps docker0, 429, --rm, /var/run/docker.sock as single tokens


def tokenize(text: str) -> list[str]:
    return [t.strip(".:,") or t for t in _WORD.findall((text or "").lower())]


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------

def recall_at_k(ranks: Sequence[int | None], k: int) -> float:
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def mrr(ranks: Sequence[int | None]) -> float:
    return sum(1.0 / r for r in ranks if r) / len(ranks) if ranks else 0.0


def ndcg_at_k(ranks: Sequence[int | None], k: int) -> float:
    """One relevant item per question: DCG = 1/log2(rank+1), ideal DCG = 1."""
    return sum(1.0 / math.log2(r + 1) for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def bootstrap_ci(values: Sequence[float], stat: Callable[[Sequence[float]], float] = lambda v: sum(v) / len(v),
                 n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap interval of `stat` over `values` (one value per question). Fixed seed: same data, same interval."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    draws = sorted(stat([values[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot))
    return (draws[int(alpha / 2 * n_boot)], draws[min(n_boot - 1, int((1 - alpha / 2) * n_boot))])


def paired_bootstrap(a: Sequence[float], b: Sequence[float], n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> dict:
    """Mean of (a - b) on the same questions with its interval, and the share of resamples where a beats b."""
    if len(a) != len(b):
        raise ValueError("paired_bootstrap needs the same questions for both systems")
    diffs = [x - y for x, y in zip(a, b)]
    if not diffs:
        return {"mean_diff": 0.0, "ci": (0.0, 0.0), "p_a_better": 0.0, "n": 0}
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return {"mean_diff": sum(diffs) / n, "ci": (means[int(alpha / 2 * n_boot)], means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]),
            "p_a_better": sum(1 for m in means if m > 0) / n_boot, "n": n}


def ranking_report(ranks: Sequence[int | None], ks: Sequence[int] = KS, n_boot: int = 2000) -> dict:
    """Recall@K, NDCG@K and MRR, each with a 95% bootstrap interval. `ranks` holds one entry per question."""
    ranks = list(ranks)
    out: dict = {"n": len(ranks)}
    per_q: dict[str, list[float]] = {"mrr": [1.0 / r if r else 0.0 for r in ranks]}
    for k in ks:
        per_q[f"recall@{k}"] = [1.0 if r is not None and r <= k else 0.0 for r in ranks]
        per_q[f"ndcg@{k}"] = [1.0 / math.log2(r + 1) if r is not None and r <= k else 0.0 for r in ranks]
    for name, vals in per_q.items():
        lo, hi = bootstrap_ci(vals, n_boot=n_boot)
        out[name] = {"value": round(sum(vals) / len(vals), 4) if vals else 0.0, "ci95": [round(lo, 4), round(hi, 4)]}
    return out


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------

def _ngrams(tokens: list[str], n: int) -> Counter:
    return Counter(tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1))


def bleu(reference: str, hypothesis: str, max_n: int = 4) -> float:
    """Sentence BLEU-4, add-one smoothing for n >= 2, brevity penalty. 0 for an empty hypothesis."""
    ref, hyp = tokenize(reference), tokenize(hypothesis)
    if not hyp or not ref:
        return 0.0
    log_sum = 0.0
    for n in range(1, max_n + 1):
        h, r = _ngrams(hyp, n), _ngrams(ref, n)
        match, total = sum(min(c, r[g]) for g, c in h.items()), max(sum(h.values()), 0)
        if n == 1:
            if match == 0:
                return 0.0
            p = match / total
        else:
            p = (match + 1) / (total + 1)
        log_sum += math.log(p) / max_n
    bp = 1.0 if len(hyp) > len(ref) else math.exp(1 - len(ref) / len(hyp))
    return bp * math.exp(log_sum)


def _f1(match: float, hyp_len: int, ref_len: int) -> float:
    if match == 0 or not hyp_len or not ref_len:
        return 0.0
    p, r = match / hyp_len, match / ref_len
    return 2 * p * r / (p + r)


def rouge_n(reference: str, hypothesis: str, n: int) -> float:
    ref, hyp = tokenize(reference), tokenize(hypothesis)
    h, r = _ngrams(hyp, n), _ngrams(ref, n)
    return _f1(sum(min(c, r[g]) for g, c in h.items()), sum(h.values()), sum(r.values()))


def _lcs(a: list[str], b: list[str]) -> int:
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def rouge_l(reference: str, hypothesis: str) -> float:
    ref, hyp = tokenize(reference), tokenize(hypothesis)
    return _f1(_lcs(ref, hyp), len(hyp), len(ref))


def meteor_variant() -> str:
    """'nltk-wordnet' when the real METEOR can run, else 'exact+stem (no WordNet)'."""
    try:
        from nltk.corpus import wordnet
        wordnet.synsets("dog")
        return "nltk-wordnet"
    except Exception:  # noqa: BLE001 -- missing package or missing corpus
        return "exact+stem (no WordNet)"


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def meteor(reference: str, hypothesis: str) -> float:
    """METEOR in [0, 1]. See `meteor_variant()` for which implementation ran."""
    ref, hyp = tokenize(reference), tokenize(hypothesis)
    if not ref or not hyp:
        return 0.0
    if meteor_variant() == "nltk-wordnet":
        from nltk.translate.meteor_score import single_meteor_score
        return float(single_meteor_score(ref, hyp))
    # fallback: unigram F-mean (recall weighted 9:1) with a fragmentation penalty, exact then stem matches
    used, pairs = set(), []
    for pass_stem in (False, True):
        for i, h in enumerate(hyp):
            if any(p[0] == i for p in pairs):
                continue
            for j, r in enumerate(ref):
                if j in used:
                    continue
                if (_stem(h) == _stem(r)) if pass_stem else (h == r):
                    pairs.append((i, j))
                    used.add(j)
                    break
    m = len(pairs)
    if m == 0:
        return 0.0
    pairs.sort()
    chunks = 1 + sum(1 for (i1, j1), (i2, j2) in zip(pairs, pairs[1:]) if not (i2 == i1 + 1 and j2 == j1 + 1))
    p, r = m / len(hyp), m / len(ref)
    f_mean = 10 * p * r / (r + 9 * p)
    return f_mean * (1 - 0.5 * (chunks / m) ** 3)


def semantic_sim(reference: str, hypothesis: str, encode: Callable[[list[str]], Sequence[Sequence[float]]]) -> float:
    """Cosine similarity of the two texts' embeddings (clipped to [0, 1]). `encode` maps a list of strings to vectors."""
    a, b = encode([reference, hypothesis])
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return max(0.0, dot / (na * nb)) if na and nb else 0.0


def generation_scores(reference: str, hypothesis: str, encode: Callable | None = None) -> dict[str, float]:
    row = {"bleu": bleu(reference, hypothesis), "rouge1": rouge_n(reference, hypothesis, 1), "rouge2": rouge_n(reference, hypothesis, 2),
           "rougeL": rouge_l(reference, hypothesis), "meteor": meteor(reference, hypothesis)}
    if encode is not None:
        row["semantic_sim"] = semantic_sim(reference, hypothesis, encode)
    return row


def generation_report(pairs: Sequence[tuple[str, str]], encode: Callable | None = None, n_boot: int = 2000) -> dict:
    """pairs = (reference, hypothesis) per question. Mean of each metric with a 95% bootstrap interval, and which METEOR ran."""
    rows = [generation_scores(r, h, encode) for r, h in pairs]
    out: dict = {"n": len(rows), "meteor_variant": meteor_variant(), "bleu_note": "mean of sentence BLEU-4 (add-one smoothed), not sacreBLEU corpus BLEU"}
    for name in (rows[0] if rows else {}):
        vals = [row[name] for row in rows]
        lo, hi = bootstrap_ci(vals, n_boot=n_boot)
        out[name] = {"value": round(sum(vals) / len(vals), 4), "ci95": [round(lo, 4), round(hi, 4)]}
    return out
