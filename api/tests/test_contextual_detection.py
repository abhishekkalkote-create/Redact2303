from app.llm.provider import FakeLLMProvider
from app.pipeline.contextual import (
    Chunk,
    chunk_text,
    ground_findings,
    parse_findings,
    render_prompt,
    run_contextual_pass,
)


def test_chunk_text_splits_on_paragraphs_and_preserves_offsets() -> None:
    text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
    chunks = chunk_text(text, max_chars=10_000)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].start_offset == 0


def test_chunk_text_packs_into_multiple_chunks_when_over_limit() -> None:
    text = "A" * 100 + "\n\n" + "B" * 100 + "\n\n" + "C" * 100
    chunks = chunk_text(text, max_chars=150)
    assert len(chunks) >= 2
    # every chunk's claimed start_offset must actually point at its own text in the original
    for c in chunks:
        assert text[c.start_offset : c.start_offset + len(c.text.split("\n\n")[0])] == c.text.split("\n\n")[0]


def test_render_prompt_substitutes_all_fields() -> None:
    system, user = render_prompt("police_report", "rule: redact badge numbers", "b(6) -> Personal privacy", "Officer Jones responded.")
    assert "police_report" in user
    assert "redact badge numbers" in user
    assert "Personal privacy" in user
    assert "Officer Jones responded." in user
    assert "JSON" in system


def test_parse_findings_handles_valid_json() -> None:
    response = '{"findings": [{"quote": "Jane Doe", "entity_kind": "victim_name", "exemption_code": "7(C)", "confidence": 0.9, "justification": "victim identity"}]}'
    findings = parse_findings(response)
    assert len(findings) == 1
    assert findings[0].quote == "Jane Doe"
    assert findings[0].exemption_code == "7(C)"


def test_parse_findings_handles_prose_wrapped_json() -> None:
    response = 'Here is the JSON:\n```json\n{"findings": []}\n```\nThat is all.'
    findings = parse_findings(response)
    assert findings == []


def test_parse_findings_never_raises_on_garbage() -> None:
    assert parse_findings("not json at all, sorry") == []
    assert parse_findings("") == []
    assert parse_findings('{"findings": [{"quote": "x"}]}') == []  # missing required exemption_code


def test_ground_findings_exact_match() -> None:
    from app.pipeline.contextual import RawFinding

    chunk = Chunk(text="The victim Jane Doe reported the incident.", start_offset=100)
    findings = [RawFinding(quote="Jane Doe", entity_kind="victim_name", exemption_code="7(C)", confidence=0.9, justification="x")]
    grounded, hallucinated = ground_findings(findings, chunk)
    assert hallucinated == 0
    assert len(grounded) == 1
    assert chunk.text[grounded[0].start - chunk.start_offset : grounded[0].end - chunk.start_offset] == "Jane Doe"


def test_ground_findings_drops_hallucinated_quote() -> None:
    from app.pipeline.contextual import RawFinding

    chunk = Chunk(text="The victim Jane Doe reported the incident.", start_offset=0)
    findings = [RawFinding(quote="Completely different text not in the chunk at all", entity_kind="x", exemption_code="7(C)", confidence=0.9, justification="x")]
    grounded, hallucinated = ground_findings(findings, chunk)
    assert hallucinated == 1
    assert grounded == []


def test_run_contextual_pass_end_to_end_with_fake_provider() -> None:
    provider = FakeLLMProvider(
        canned_responses=[
            ("Jane Doe", '{"findings": [{"quote": "Jane Doe", "entity_kind": "victim_name", "exemption_code": "7(C)", "confidence": 0.9, "justification": "victim identity protection"}]}'),
        ]
    )
    full_text = "Incident report. The victim Jane Doe reported the incident to Officer Smith."
    findings, hallucinated, in_tokens, _out_tokens = run_contextual_pass(
        provider, full_text, document_type="police_report",
        llm_context_rules="redact victim names", exemption_taxonomy_summary="7(C) -> law enforcement privacy",
    )
    assert len(findings) == 1
    assert findings[0].quote == "Jane Doe"
    assert findings[0].exemption_code == "7(C)"
    assert hallucinated == 0
    assert in_tokens > 0
    assert len(provider.calls) == 1


def test_run_contextual_pass_counts_hallucination_and_still_returns_real_findings() -> None:
    provider = FakeLLMProvider(
        canned_responses=[
            (
                "Jane Doe",
                (
                    '{"findings": ['
                    '{"quote": "Jane Doe", "entity_kind": "victim_name", "exemption_code": "7(C)", "confidence": 0.9, "justification": "x"},'
                    '{"quote": "text the model invented that is not in the source", "entity_kind": "y", "exemption_code": "7(C)", "confidence": 0.8, "justification": "y"}'
                    "]}"
                ),
            ),
        ]
    )
    full_text = "The victim Jane Doe reported the incident."
    findings, hallucinated, _, _ = run_contextual_pass(
        provider, full_text, document_type="police_report", llm_context_rules="", exemption_taxonomy_summary="",
    )
    assert len(findings) == 1
    assert hallucinated == 1
