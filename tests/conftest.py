import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triage.clarifier import Clarifier  # noqa: E402
from triage.eval.demo_corpus import demo_corpus  # noqa: E402
from triage.retrieval import MockRetriever  # noqa: E402


@pytest.fixture
def retriever():
    return MockRetriever(demo_corpus())


@pytest.fixture
def make_clarifier(retriever):
    """factory(llm=None, cfg=None) -> Clarifier on the offline demo corpus (no network, no model)."""
    def factory(llm=None, cfg=None):
        return Clarifier(llm, retriever, cfg)
    return factory
