from triage.state import (SCHEMA_VERSION, AttemptRecord, ExtractedFields, Hypothesis, ProblemSignature, QuestionRecord,
                          SignatureConfidence, TriageRecord, TurnRecord, canonical_string, from_dict, to_dict,
                          validate_signature)
from triage.understand import build_signature


def _fields(**kw):
    base = dict(product_area="docker-hub", component="troubleshoot", symptoms=["pull fails", "429 error"],
                platform="mac", error_codes=["HTTP 429 response code"])
    base.update(kw)
    return ExtractedFields(**base)


def test_canonical_string_is_product_component_symptoms_only():
    a = canonical_string(_fields(frustration="High", impact_scope="Organization", platform="linux", severity="Critical"))
    b = canonical_string(_fields())
    assert a == b == "docker-hub|troubleshoot|429 error; pull fails"      # sorted, lowercased symptoms


def test_canonical_string_marks_missing_parts_with_question_mark():
    assert canonical_string(ExtractedFields()) == "?|?|"


def test_triage_record_json_round_trip():
    sig = build_signature(_fields(), SignatureConfidence(0.7, 0.4, 0.66, False, "clear"),
                          [Hypothesis("a::b", "A > B", 1.0, 0.7, ["c1"], {"platform": "mac"}, 0.9)])
    rec = TriageRecord(ticket_id="T-1", created_at="2026-10-05T00:00:00+00:00",
                       transcript=[TurnRecord(0, "customer", "hi", {"k": 1})], fields=_fields(), signature=sig,
                       questions=[QuestionRecord(1, "platform", "which os?", ["mac"], True, "mac")],
                       attempts=[AttemptRecord(1, ["c1"], "not_resolved", "still broken")], outcome="escalated",
                       flagged_incorrect=True)
    restored = from_dict(TriageRecord, to_dict(rec))
    assert restored == rec
    assert restored.signature.hypotheses[0].grounding == 0.9


def test_from_dict_ignores_unknown_keys_and_defaults_missing():
    data = to_dict(ExtractedFields(product_area="engine"))
    data["field_added_in_a_future_version"] = 123
    del data["severity"]
    f = from_dict(ExtractedFields, data)
    assert f.product_area == "engine" and f.severity == "Medium"


def test_validate_signature_accepts_well_formed():
    assert validate_signature(build_signature(_fields())) == []


def test_validate_signature_reports_each_contract_violation():
    sig = build_signature(_fields())
    sig.canonical_string = "tampered|x"
    sig.schema_version = "0.0.1"
    sig.fields.platform = "beos"
    sig.fields.severity = "Apocalyptic"
    sig.hypotheses = [Hypothesis("k", "l", 0.8, 0.5), Hypothesis("k2", "l2", 0.5, 0.4)]
    problems = " | ".join(validate_signature(sig))
    for needle in ("schema_version", "canonical_string", "platform", "severity", "exceeds 1.0"):
        assert needle in problems


def test_schema_version_constant_is_embedded():
    assert build_signature(_fields()).schema_version == SCHEMA_VERSION


def test_truncated_hypothesis_lists_are_valid_because_weights_are_pool_probabilities():
    sig = build_signature(_fields(), hypotheses=[Hypothesis("a", "a", 0.5, 0.7), Hypothesis("b", "b", 0.2, 0.6)])
    assert validate_signature(sig) == []                        # 0.7 total: the tail of the pool was dropped
