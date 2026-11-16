"""Tests for triage/eval/text_metrics.py: hand-computed values, not just 'it runs'."""

import math

import pytest

from triage.eval import text_metrics as tm


def test_recall_mrr_ndcg_hand_values():
    ranks = [1, 3, None, 2]
    assert tm.recall_at_k(ranks, 1) == 0.25
    assert tm.recall_at_k(ranks, 3) == 0.75
    assert tm.mrr(ranks) == pytest.approx((1 + 1 / 3 + 0 + 1 / 2) / 4)
    # rank 1 -> 1, rank 3 -> 1/log2(4) = 0.5, rank 2 -> 1/log2(3)
    assert tm.ndcg_at_k(ranks, 3) == pytest.approx((1 + 0.5 + 1 / math.log2(3)) / 4)
    assert tm.ndcg_at_k(ranks, 1) == 0.25                      # only the rank-1 question counts at K=1


def test_ndcg_ignores_ranks_beyond_k_and_empty_input():
    assert tm.ndcg_at_k([9, None], 8) == 0.0
    assert tm.recall_at_k([], 3) == tm.mrr([]) == tm.ndcg_at_k([], 3) == 0.0


def test_bootstrap_is_deterministic_and_contains_the_mean():
    vals = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    lo, hi = tm.bootstrap_ci(vals)
    assert (lo, hi) == tm.bootstrap_ci(vals)
    assert lo <= sum(vals) / len(vals) <= hi
    assert tm.bootstrap_ci([]) == (0.0, 0.0)


def test_small_samples_have_wide_intervals():
    small = tm.bootstrap_ci([1.0] * 4 + [0.0] * 15)            # 4/19
    large = tm.bootstrap_ci([1.0] * 40 + [0.0] * 150)          # 40/190, same rate
    assert (small[1] - small[0]) > (large[1] - large[0])


def test_paired_bootstrap_detects_a_consistent_difference_and_checks_lengths():
    a, b = [1.0] * 20, [0.0] * 20
    res = tm.paired_bootstrap(a, b)
    assert res["mean_diff"] == 1.0 and res["p_a_better"] == 1.0
    same = tm.paired_bootstrap(a, a)
    assert same["mean_diff"] == 0.0 and same["ci"] == (0.0, 0.0)
    with pytest.raises(ValueError):
        tm.paired_bootstrap([1.0], [1.0, 2.0])


def test_ranking_report_shape():
    rep = tm.ranking_report([1, 2, None, 5])
    assert rep["n"] == 4
    for key in ("mrr", "recall@1", "recall@8", "ndcg@1", "ndcg@8"):
        assert set(rep[key]) == {"value", "ci95"}
    assert rep["recall@1"]["value"] == 0.25


def test_tokenize_keeps_commands_and_errors_whole():
    toks = tm.tokenize("Run docker0 --rm at /var/run/docker.sock, exit 137.")
    assert "docker0" in toks and "--rm" in toks and "/var/run/docker.sock" in toks and "137" in toks


def test_identical_text_scores_one():
    t = "Run docker login and then pull the image again from the registry"
    s = tm.generation_scores(t, t)
    assert s["bleu"] == pytest.approx(1.0)
    assert s["rouge1"] == s["rouge2"] == s["rougeL"] == pytest.approx(1.0)
    assert s["meteor"] > 0.95


def test_disjoint_text_scores_zero():
    s = tm.generation_scores("restart the docker daemon now", "banana smoothie recipe tomorrow")
    assert s["bleu"] == 0.0 and s["rouge1"] == 0.0 and s["rougeL"] == 0.0 and s["meteor"] == 0.0


def test_rouge_hand_values():
    ref, hyp = "the cat sat on the mat", "the cat on the mat"
    # unigram overlap 5 of hyp 5 and ref 6: p=1, r=5/6, f1 = 2*1*(5/6)/(1+5/6)
    assert tm.rouge_n(ref, hyp, 1) == pytest.approx(2 * (5 / 6) / (1 + 5 / 6))
    # LCS is "the cat on the mat" = 5
    assert tm.rouge_l(ref, hyp) == pytest.approx(2 * (5 / 6) / (1 + 5 / 6))
    # bigrams: hyp {the cat, cat on, on the, the mat} all but "cat on" appear in ref -> match 3 of 4; ref has 5
    assert tm.rouge_n(ref, hyp, 2) == pytest.approx(2 * (3 / 4) * (3 / 5) / (3 / 4 + 3 / 5))


def test_bleu_brevity_penalty_and_empty():
    ref = "pull the image again after you log in to the registry"
    assert tm.bleu(ref, "") == 0.0
    assert tm.bleu(ref, "pull the image") < tm.bleu(ref, "pull the image again after you log in")


def test_bleu_is_lower_for_a_worse_paraphrase():
    ref = "set the memory limit in docker desktop settings under resources"
    close = "set the memory limit in docker desktop settings under resources tab"
    far = "open the app and change something in the options window"
    assert tm.bleu(ref, close) > tm.bleu(ref, far)


def test_meteor_rewards_a_stem_match_and_labels_the_variant():
    assert tm.meteor_variant() in ("nltk-wordnet", "exact+stem (no WordNet)")
    assert tm.meteor("restart the containers", "restarting the container") > tm.meteor("restart the containers", "delete the images")


def test_semantic_sim_uses_the_given_encoder():
    enc = lambda texts: [[1.0, 0.0] if "a" in t else [0.0, 1.0] for t in texts]        # noqa: E731
    assert tm.semantic_sim("a", "aa", enc) == pytest.approx(1.0)
    assert tm.semantic_sim("a", "b", enc) == 0.0


def test_generation_report_averages_over_pairs():
    pairs = [("pull the image", "pull the image"), ("pull the image", "banana split")]
    rep = tm.generation_report(pairs)
    assert rep["n"] == 2 and rep["rouge1"]["value"] == pytest.approx(0.5)
    assert "sacreBLEU" in rep["bleu_note"]
