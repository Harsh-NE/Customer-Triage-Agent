"""triage/spell.py: fixes likely typos against the KB vocabulary and otherwise does nothing."""

import pytest

from triage.spell import Speller

IDF = {"container": 2.0, "containers": 2.1, "permission": 3.0, "denied": 3.5, "rootless": 5.0, "docker": 0.5, "pulling": 2.5, "image": 1.5,
       "network": 2.0, "compose": 2.2, "volume": 2.4, "bridge": 3.9, "bridges": 4.0}
S = Speller(IDF)


@pytest.mark.parametrize("typo,fixed", [("contianer", "container"), ("permisison", "permission"), ("pullign", "pulling"), ("netwrk", "network"),
                                         ("imaage", "image"), ("volumee", "volume")])
def test_common_typos_are_fixed(typo, fixed):
    assert S.correct_word(typo) == fixed


def test_a_known_word_is_never_changed_even_if_a_commoner_neighbour_exists():
    assert S.correct_word("bridges") == "bridges"           # a neighbour "bridge" is more common; the word is known, so leave it


def test_unknown_words_with_no_neighbour_are_left_alone():
    assert S.correct_word("postgresql") == "postgresql"     # a product name the vocabulary lacks


def test_short_words_capitals_digits_and_paths_are_not_touched():
    text = "ERROR contianer1 /var/lib/contianer --contianer docker0 abc the.contianer http://contianer:80 user@contianer"
    out = S.correct(text)
    assert out == text
    assert S.correct("CONTIANER") == "CONTIANER"


def test_whole_message_and_capitalisation():
    assert S.correct("Contianer fails when pullign the image") == "Container fails when pulling the image"


def test_the_most_common_neighbour_wins():
    # "containes" is one edit from both "container" (idf 2.0) and "containers" (idf 2.1): the commoner is chosen, deterministically
    assert S.correct_word("containes") in ("container", "containers")
    assert S.correct_word("containes") == S.correct_word("containes")


def test_empty_and_none_text():
    assert S.correct("") == "" and S.correct(None) == ""
