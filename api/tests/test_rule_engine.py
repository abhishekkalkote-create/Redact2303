"""specs/06-exemption-taxonomy.md § Rule anatomy — pure logic, no DB needed. `Rule` is a
SQLAlchemy declarative model but constructing one in memory (no session, no flush) is
just a plain Python object; its column `default=` callables only apply at flush time."""

from app.models.rule import Rule
from app.pipeline.rule_engine import run_metadata_rule, run_rule


def _rule(trigger_type: str, config: dict, exclusions: list | None = None) -> Rule:
    return Rule(
        id="rul_test", rule_set_version_id="rsv_test", org_id=None, rule_key="TEST-1",
        name="Test Rule", trigger_type=trigger_type, config=config, exclusions=exclusions or [],
        priority=100, confidence_policy="suggest", scope="org", status="active",
    )


def test_regex_rule_matches_ssn_pattern() -> None:
    rule = _rule("regex", {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"})
    matches = run_rule("SSN on file: 234-56-7890 for this record.", rule)
    assert len(matches) == 1
    assert matches[0].text == "234-56-7890"
    assert not matches[0].excluded


def test_regex_rule_ssn_format_validator_rejects_invalid_ranges() -> None:
    rule = _rule("regex", {"pattern": r"\b\d{3}-\d{2}-\d{4}\b", "validators": ["ssn_format"]})
    matches = run_rule("Bad: 000-12-3456. Also bad: 666-12-3456. Good: 234-56-7890.", rule)
    assert [m.text for m in matches] == ["234-56-7890"]


def test_regex_rule_luhn_validator_rejects_bad_checksum() -> None:
    rule = _rule("regex", {"pattern": r"\b\d{16}\b", "validators": ["luhn"]})
    # 4532015112830366 is a real Luhn-valid test card number; the second is that with one
    # digit flipped, which must fail the checksum.
    matches = run_rule("Card A: 4532015112830366. Card B: 4532015112830367.", rule)
    assert [m.text for m in matches] == ["4532015112830366"]


def test_regex_rule_requires_context_words_nearby() -> None:
    rule = _rule(
        "regex", {"pattern": r"\b\d{3}-\d{3}-\d{4}\b", "context_words": ["cell", "mobile"], "context_window": 10}
    )
    matches = run_rule("Office main line: 206-555-0100.   Personal cell: 206-555-0199.", rule)
    assert [m.text for m in matches] == ["206-555-0199"]


def test_dictionary_rule_matches_whole_words_case_insensitively() -> None:
    rule = _rule("dictionary", {"terms": ["Officer Smith", "Det. Jones"]})
    matches = run_rule("The report was filed by officer smith and reviewed by Det. Jones.", rule)
    assert {m.text.lower() for m in matches} == {"officer smith", "det. jones"}


def test_dictionary_rule_does_not_match_substrings() -> None:
    rule = _rule("dictionary", {"terms": ["Smith"]})
    matches = run_rule("Smithsonian is not a match, but the standalone word Smith is.", rule)
    assert len(matches) == 1
    assert matches[0].text == "Smith"


def test_entity_rule_matches_configured_entity_type() -> None:
    rule = _rule("entity", {"entity_type": "US_SSN"})
    matches = run_rule("Client SSN: 234-56-7890.", rule)
    assert len(matches) == 1
    assert "234-56-7890" in matches[0].text


def test_metadata_and_llm_context_trigger_types_produce_no_deterministic_matches() -> None:
    assert run_rule("some text", _rule("metadata", {"field": "author"})) == []
    assert run_rule("some text", _rule("llm_context", {"instruction": "redact X"})) == []


def test_exclusion_allowlist_marks_match_excluded_not_dropped() -> None:
    rule = _rule(
        "dictionary", {"terms": ["555-0100"]},
        exclusions=[{"type": "allowlist", "values": ["555-0100"]}],
    )
    matches = run_rule("Call the switchboard at 555-0100 for assistance.", rule)
    assert len(matches) == 1
    assert matches[0].excluded is True
    assert "allowlist" in matches[0].excluded_reason


def test_exclusion_context_not_checks_nearby_text() -> None:
    rule = _rule(
        "dictionary", {"terms": ["Jane Doe"]},
        exclusions=[{"type": "context_not", "phrase": "responding officer"}],
    )
    excluded_match = run_rule("The responding officer, Jane Doe, filed the report.", rule)
    kept_match = run_rule("The victim, Jane Doe, was interviewed at the scene.", rule)
    assert excluded_match[0].excluded is True
    assert kept_match[0].excluded is False


def test_exclusion_pattern_carveout_matches_full_span_only() -> None:
    rule = _rule(
        "regex", {"pattern": r"\b\d{3}-\d{3}-\d{4}\b"},
        exclusions=[{"type": "pattern_carveout", "pattern": r"555-\d{3}-\d{4}"}],
    )
    matches = run_rule("Fake test number 555-555-5555 vs real number 206-555-0199.", rule)
    by_text = {m.text: m.excluded for m in matches}
    assert by_text["555-555-5555"] is True
    assert by_text["206-555-0199"] is False


def test_run_metadata_rule_matches_field_pattern() -> None:
    rule = _rule("metadata", {"field": "author", "pattern": "legal"})
    assert run_metadata_rule({"author": "Legal Department"}, rule) is True
    assert run_metadata_rule({"author": "Records Office"}, rule) is False


def test_run_metadata_rule_without_pattern_just_checks_presence() -> None:
    rule = _rule("metadata", {"field": "custodian"})
    assert run_metadata_rule({"custodian": "J. Smith"}, rule) is True
    assert run_metadata_rule({}, rule) is False
