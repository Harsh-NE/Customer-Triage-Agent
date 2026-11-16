"""features: the three switches, their defaults (the system as it was), and the three ablation arms."""

import pytest

from triage.features import ARMS, Features


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("USE_KG", "USE_JEV", "USE_SEMANTIC_CACHE", "ONTOLOGY_MODE"):
        monkeypatch.delenv(name, raising=False)


def test_unset_environment_keeps_the_system_as_it_was():
    assert Features.from_env() == Features(use_kg=True, use_jev=False, use_semantic_cache=True)


def test_ontology_mode_off_still_means_no_knowledge_graph(monkeypatch):
    monkeypatch.setenv("ONTOLOGY_MODE", "off")
    assert Features.from_env().use_kg is False


def test_use_variables_override(monkeypatch):
    monkeypatch.setenv("USE_KG", "0")
    monkeypatch.setenv("USE_JEV", "on")
    monkeypatch.setenv("USE_SEMANTIC_CACHE", "False")
    assert Features.from_env() == Features(use_kg=False, use_jev=True, use_semantic_cache=False)


def test_use_kg_beats_ontology_mode(monkeypatch):
    monkeypatch.setenv("ONTOLOGY_MODE", "off")
    monkeypatch.setenv("USE_KG", "1")
    assert Features.from_env().use_kg is True


def test_a_typo_is_an_error_not_a_silent_default(monkeypatch):
    monkeypatch.setenv("USE_JEV", "yess")
    with pytest.raises(ValueError, match="USE_JEV"):
        Features.from_env()


def test_the_three_arms_differ_only_in_kg_and_jev():
    assert ARMS["A"].to_dict() == {"use_kg": False, "use_jev": False, "use_semantic_cache": True}
    assert ARMS["B"].to_dict() == {"use_kg": True, "use_jev": False, "use_semantic_cache": True}
    assert ARMS["C"].to_dict() == {"use_kg": True, "use_jev": True, "use_semantic_cache": True}
