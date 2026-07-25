"""specs/06-exemption-taxonomy.md § Manual-to-rule extraction. Pure unit tests against
app.pipeline.manual_extraction — no DB needed."""

from app.pipeline.manual_extraction import parse_and_ground_page, run_extraction_for_page


def test_parse_valid_draft_rule_grounded_in_page_text() -> None:
    page_text = "Section 4: Confidential Sources. Officer notes must not disclose informant identities."
    response = (
        '{"section_type": "exemptions", "draft_rules": [{"name": "Informant identity", '
        '"trigger_type": "entity", "config": {"entity_type": "PERSON"}, "exemption_code": "7(D)", '
        '"exclusions": [], "source_quote": "must not disclose informant identities", '
        '"ambiguity_notes": ""}]}'
    )
    section_type, drafts = parse_and_ground_page(response, page_text, page_no=4, allowed_codes={"7(D)"})
    assert section_type == "exemptions"
    assert len(drafts) == 1
    assert drafts[0].is_valid
    assert "page 4" in drafts[0].source_ref


def test_parse_rejects_hallucinated_quote_not_in_page_text() -> None:
    page_text = "Section 1: Definitions. This manual defines key terms used throughout."
    response = (
        '{"section_type": "definitions", "draft_rules": [{"name": "x", "trigger_type": "dictionary", '
        '"config": {"terms": ["x"]}, "exemption_code": null, '
        '"source_quote": "this text does not appear anywhere on the page at all", "ambiguity_notes": ""}]}'
    )
    _section_type, drafts = parse_and_ground_page(response, page_text, page_no=1, allowed_codes=set())
    assert len(drafts) == 1
    assert not drafts[0].is_valid
    assert "hallucination" in drafts[0].invalid_reason


def test_parse_rejects_invented_exemption_code() -> None:
    page_text = "Employee medical records are confidential."
    response = (
        '{"section_type": "exemptions", "draft_rules": [{"name": "Medical", "trigger_type": "entity", '
        '"config": {"entity_type": "PERSON"}, "exemption_code": "made-up-code", '
        '"source_quote": "Employee medical records are confidential", "ambiguity_notes": ""}]}'
    )
    _section_type, drafts = parse_and_ground_page(response, page_text, page_no=2, allowed_codes={"b(6)"})
    assert not drafts[0].is_valid
    assert "invented a code" in drafts[0].invalid_reason


def test_parse_empty_draft_rules_for_non_substantive_page() -> None:
    response = '{"section_type": "other", "draft_rules": []}'
    section_type, drafts = parse_and_ground_page(response, "Table of Contents", page_no=1, allowed_codes=set())
    assert section_type == "other"
    assert drafts == []


def test_parse_malformed_response_yields_no_drafts() -> None:
    section_type, drafts = parse_and_ground_page("not json", "some page text", page_no=1, allowed_codes=set())
    assert section_type == "other"
    assert drafts == []


def test_run_extraction_for_page_skips_blank_pages_without_calling_llm() -> None:
    from app.llm.provider import FakeLLMProvider

    fake_provider = FakeLLMProvider()
    section_type, drafts, in_tok, out_tok = run_extraction_for_page(fake_provider, "   ", 1, set())
    assert section_type == "other"
    assert drafts == []
    assert in_tok == 0 and out_tok == 0
    assert fake_provider.calls == []
