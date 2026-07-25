"""specs/06-exemption-taxonomy.md § Natural-language rule editing. Pure unit tests
against app.pipeline.nl_rule_edit — no DB needed, matches app/pipeline/contextual.py's
FakeLLMProvider-based testability."""

from app.llm.provider import FakeLLMProvider
from app.pipeline.nl_rule_edit import parse_and_validate_diff, run_nl_edit


def test_parse_valid_new_rule_proposal() -> None:
    response = (
        '{"changes": [{"action": "new", "rule_key": "CUSTOM-1", "name": "Cell phones", '
        '"trigger_type": "regex", "config": {"pattern": "\\\\d{3}-\\\\d{3}-\\\\d{4}"}, '
        '"exemption_code": "b(6)", "exclusions": [], "rationale": "redact cell numbers"}]}'
    )
    proposals = parse_and_validate_diff(response, existing_rule_keys=set(), allowed_codes={"b(6)"})
    assert len(proposals) == 1
    assert proposals[0].is_valid
    assert proposals[0].action == "new"
    assert proposals[0].rule_key == "CUSTOM-1"


def test_parse_rejects_invented_exemption_code() -> None:
    response = (
        '{"changes": [{"action": "new", "rule_key": "CUSTOM-1", "name": "x", '
        '"trigger_type": "dictionary", "config": {"terms": ["x"]}, '
        '"exemption_code": "made-up-code", "rationale": "x"}]}'
    )
    proposals = parse_and_validate_diff(response, existing_rule_keys=set(), allowed_codes={"b(6)"})
    assert len(proposals) == 1
    assert not proposals[0].is_valid
    assert "invented a code" in proposals[0].invalid_reason


def test_parse_rejects_invalid_trigger_type() -> None:
    response = (
        '{"changes": [{"action": "new", "rule_key": "CUSTOM-1", "name": "x", '
        '"trigger_type": "made_up_type", "config": {}, "exemption_code": "b(6)", "rationale": "x"}]}'
    )
    proposals = parse_and_validate_diff(response, existing_rule_keys=set(), allowed_codes={"b(6)"})
    assert not proposals[0].is_valid
    assert "invalid trigger_type" in proposals[0].invalid_reason


def test_parse_rejects_unparseable_regex() -> None:
    response = (
        '{"changes": [{"action": "new", "rule_key": "CUSTOM-1", "name": "x", '
        '"trigger_type": "regex", "config": {"pattern": "(unclosed"}, '
        '"exemption_code": "b(6)", "rationale": "x"}]}'
    )
    proposals = parse_and_validate_diff(response, existing_rule_keys=set(), allowed_codes={"b(6)"})
    assert not proposals[0].is_valid
    assert "invalid regex" in proposals[0].invalid_reason


def test_parse_edit_action_requires_existing_rule_key() -> None:
    response = '{"changes": [{"action": "edit", "rule_key": "DOES-NOT-EXIST", "rationale": "x"}]}'
    proposals = parse_and_validate_diff(response, existing_rule_keys={"PS-1"}, allowed_codes={"b(6)"})
    assert not proposals[0].is_valid
    assert "unknown rule_key" in proposals[0].invalid_reason


def test_parse_valid_edit_action_against_known_rule_key() -> None:
    response = '{"changes": [{"action": "edit", "rule_key": "PS-1", "exclusions": [{"type": "allowlist", "values": ["x"]}], "rationale": "narrow it"}]}'
    proposals = parse_and_validate_diff(response, existing_rule_keys={"PS-1"}, allowed_codes={"b(6)"})
    assert proposals[0].is_valid
    assert proposals[0].action == "edit"


def test_parse_malformed_json_yields_no_proposals_not_a_crash() -> None:
    assert parse_and_validate_diff("not json at all", set(), set()) == []


def test_parse_empty_changes_list() -> None:
    assert parse_and_validate_diff('{"changes": []}', set(), set()) == []


def test_run_nl_edit_uses_fake_provider_and_returns_tokens() -> None:
    fake_response = (
        '{"changes": [{"action": "new", "rule_key": "CUSTOM-1", "name": "Witness cell", '
        '"trigger_type": "regex", "config": {"pattern": "\\\\d{3}-\\\\d{3}-\\\\d{4}"}, '
        '"exemption_code": "7(C)", "rationale": "witness cell numbers"}]}'
    )
    fake_provider = FakeLLMProvider(canned_responses=[("witness cell phone", fake_response)])
    proposals, in_tok, out_tok = run_nl_edit(
        fake_provider, "Redact witness cell phone numbers", existing_rules=[], allowed_codes={"7(C)"}
    )
    assert len(proposals) == 1
    assert proposals[0].is_valid
    assert in_tok > 0
    assert out_tok > 0
    assert len(fake_provider.calls) == 1
