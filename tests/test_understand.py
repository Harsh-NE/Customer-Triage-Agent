import json

import pytest

from triage import understand as U
from triage.llm import ScriptedLLM
from triage.state import ExtractedFields

KNOWN = U.DEFAULT_KNOWN_PRODUCTS


# ---- PII -----------------------------------------------------------------
@pytest.mark.parametrize("secret", ["bob@example.com", "AKIAABCDEFGHIJKLMNOP", "dckr_pat_abcdef1234567890",
                                    "sk-abcdefghijklmnopqrstuv", "ghp_abcdefghijklmnopqrstuv"])
def test_redact_pii_masks_secrets(secret):
    clean, counts = U.redact_pii(f"login fails, here is {secret} ok")
    assert secret not in clean and counts


def test_redact_pii_keeps_key_name_for_assignments_and_keeps_ips():
    clean, counts = U.redact_pii("password=hunter2 and registry 192.168.203.139:5858")
    assert "hunter2" not in clean and "password=[REDACTED:secret]" in clean
    assert "192.168.203.139" in clean                       # IPs are diagnostic in Docker errors


def test_redact_pii_is_idempotent():
    once, _ = U.redact_pii("mail me at bob@example.com")
    twice, counts = U.redact_pii(once)
    assert once == twice and not counts


# ---- normalization -------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("Docker Desktop", "desktop"), ("docker desktop for mac", "desktop"), ("Docker Hub", "docker-hub"),
    ("dockerhub", "docker-hub"), ("buildx", "build"), ("SSO", "security"), ("docker compose", "compose"),
    ("dockr hub", "docker-hub"),                                    # fuzzy
])
def test_normalize_product_maps_aliases(raw, expected):
    assert U.normalize_product(raw, KNOWN) == expected


@pytest.mark.parametrize("raw", ["Kubernetes", "", None, "banana", "__admin__"])
def test_normalize_product_rejects_unknown_rather_than_inventing(raw):
    assert U.normalize_product(raw, KNOWN) is None


@pytest.mark.parametrize("text,expected", [
    ("I'm on Windows 11", "windows"), ("my macbook, macOS 14", "mac"), ("ubuntu server", "linux"),
    ("WSL2 with Ubuntu", "windows"),                                # WSL => Windows host
    ("windows and mac both", None), ("no os mentioned", None), ("machine learning", None),
])
def test_detect_platform(text, expected):
    assert U.detect_platform(text) == expected


# ---- verbatim extractors ---------------------------------------------------
def test_error_codes():
    assert U.extract_error_codes("got a 429 error and later HTTP 500 status, exit code 137") == \
        ["HTTP 429 response code", "HTTP 500 response code", "exit code 137"]
    assert U.extract_error_codes("I have 429 items and port 4290") == []


def test_error_messages_come_from_fences_and_quotes_not_from_prose():
    msg = "SSO sign in isn't working for my team. I get 'You have reached your pull rate limit' too.\n" \
          "```\nCannot connect to the Docker daemon. Is 'docker daemon' running?\n```"
    out = U.extract_error_messages(msg)
    assert "You have reached your pull rate limit" in out
    assert any(o.startswith("Cannot connect to the Docker daemon") for o in out)
    assert not any("isn't working for my team" in o for o in out)   # regression: prose != error text


def test_error_messages_accepts_label_colon_lines_but_not_first_person_prose():
    assert U.extract_error_messages("Error response from daemon: Get http://x/v2/: malformed response") != []
    assert U.extract_error_messages("I get an error: it fails when I run it") == []


def test_looks_like_error_text():
    assert U.looks_like_error_text("Too Many Requests")
    assert U.looks_like_error_text("Not enough seats in organization 'acme'. Add more seats.")
    assert not U.looks_like_error_text("I think it's the second one")
    assert not U.looks_like_error_text("ok")


def test_versions():
    assert U.extract_versions("Docker Desktop version 4.30.0 and compose v2.27") == \
        {"docker desktop": "4.30.0", "compose": "2.27"}


# ---- vagueness / symptoms ---------------------------------------------------
@pytest.mark.parametrize("s", ["it doesn't work", "docker isn't working", "help", "error", "not working pls fix",
                               "something is wrong", "it doesn’t work"])
def test_vague_symptoms(s):
    assert U.is_vague_symptom(s)


@pytest.mark.parametrize("s", ["pull fails with 429", "can't connect to the daemon", "port already allocated"])
def test_specific_symptoms(s):
    assert not U.is_vague_symptom(s)


def test_normalize_symptoms_dedupes_lowercases_and_caps():
    assert U.normalize_symptoms([" Pull FAILS. ", "pull fails", "x"] + ["s%d" % i for i in range(10)])[:2] == ["pull fails", "x"]
    assert len(U.normalize_symptoms(["a%d" % i for i in range(20)])) == 6


# ---- heuristic extraction & gaps ----------------------------------------------
def test_heuristic_extract_only_names_a_product_when_exactly_one_is_clear():
    f = U.heuristic_extract("docker pull fails with 429 from Docker Hub on my Mac", KNOWN)
    assert (f.product_area, f.platform, f.error_codes) == ("docker-hub", "mac", ["HTTP 429 response code"])
    assert U.heuristic_extract("fails on docker desktop and docker hub", KNOWN).product_area is None


def test_gaps_only_symptoms_is_hard_product_is_soft():
    gaps = {g.field: g.hard for g in U.detect_gaps(U.heuristic_extract("it doesn't work", KNOWN))}
    assert gaps["symptoms"] is True and gaps["product_area"] is False
    assert "symptoms" not in {g.field for g in U.detect_gaps(U.heuristic_extract("port is already allocated", KNOWN))}


def test_error_code_alone_satisfies_the_symptom_gap():
    f = ExtractedFields(symptoms=["it doesn't work"], error_codes=["HTTP 429 response code"])
    assert "symptoms" not in {g.field for g in U.detect_gaps(f)}


# ---- merging -------------------------------------------------------------------
def test_merge_never_erases_with_null_and_unions_lists():
    base = ExtractedFields(product_area="desktop", symptoms=["won't start"], platform="mac", versions={"docker desktop": "4.0"})
    new = ExtractedFields(symptoms=["crashes on login"], platform=None, product_area=None)
    merged, changed = U.merge_fields(base, new)
    assert (merged.product_area, merged.platform) == ("desktop", "mac")
    assert merged.symptoms == ["won't start", "crashes on login"] and "symptoms" in changed
    assert base.symptoms == ["won't start"]                      # inputs are not mutated


def test_merge_lets_the_customer_correct_a_scalar_and_ratchets_tone_up_only():
    base = ExtractedFields(platform="windows", severity="High", frustration="High")
    merged, _ = U.merge_fields(base, ExtractedFields(platform="mac", severity="Low", frustration="Low", impact_scope="Team"))
    assert (merged.platform, merged.severity, merged.frustration, merged.impact_scope) == ("mac", "High", "High", "Team")


# ---- LLM extraction ------------------------------------------------------------
GOOD = json.dumps({"product_area": "Docker Hub", "component": "pulls", "symptoms": ["Pull Fails "], "platform": "Mac",
                   "severity": "High", "frustration": "Low", "impact_scope": "Team"})


def test_llm_extraction_is_normalized_and_verbatim_facts_still_come_from_regex():
    res = U.extract("pull fails with 'Too Many Requests' http 429", ScriptedLLM([GOOD]), KNOWN)
    assert res.source == "llm"
    f = res.fields
    assert (f.product_area, f.platform, f.symptoms, f.severity) == ("docker-hub", "mac", ["pull fails"], "High")
    assert f.error_messages == ["Too Many Requests"] and f.error_codes == ["HTTP 429 response code"]


def test_llm_prompt_fences_customer_text_and_includes_pending_question():
    llm = ScriptedLLM([GOOD])
    U.extract("Mac", llm, KNOWN, known=ExtractedFields(product_area="desktop"), pending_question="Which OS?")
    prompt = llm.prompts[0]
    assert "<customer_message>\nMac\n</customer_message>" in prompt and "untrusted" in prompt
    assert "Which OS?" in prompt and "desktop" in prompt


@pytest.mark.parametrize("raw", ["not json at all", "", "[1, 2, 3]"])
def test_llm_garbage_falls_back_to_heuristic(raw):
    res = U.extract("docker pull fails on docker hub", ScriptedLLM([raw]), KNOWN)
    assert res.source == "heuristic_fallback" and res.fields.product_area == "docker-hub"


def test_llm_exception_falls_back_and_never_raises():
    class Boom:
        def complete(self, p): raise TimeoutError("x")
    assert U.extract("hello docker hub", Boom(), KNOWN).source == "heuristic_fallback"


def test_signature_text_and_retrieval_query_differ_on_purpose():
    f = ExtractedFields(product_area="docker-hub", symptoms=["pull fails"], platform="mac", error_codes=["HTTP 429 response code"])
    sig = U.build_signature(f, embedder=U.HashEmbedder(8))
    assert "mac" not in sig.nl_text and "429" not in sig.nl_text      # cache key text excludes platform/codes
    assert "mac" in U.retrieval_query(f) and "429" in U.retrieval_query(f)
    assert len(sig.embedding) == 8
