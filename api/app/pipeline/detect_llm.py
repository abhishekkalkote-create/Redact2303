"""Creates redaction_candidates from contextual LLM findings — the LLM-origin counterpart
to app/pipeline/detect.py's deterministic pass. specs/05-redaction-pipeline.md Stage 4."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.llm.provider import LLMProvider
from app.models.exemption_code import ExemptionCode, ExemptionLibrary
from app.models.redaction_candidate import RedactionCandidate
from app.pipeline.contextual import confidence_band, run_contextual_pass
from app.pipeline.extract import PageExtraction, span_to_bbox
from app.pipeline.public_safety import (
    ALLOWED_LIBRARY_CODES,
    DOCUMENT_TYPE,
    LLM_CONTEXT_RULES,
    RULE_KEY,
    RULE_VERSION,
)


async def _taxonomy_summary_and_code_map(session: AsyncSession, org_id: str) -> tuple[str, dict[str, str]]:
    result = await session.execute(
        select(ExemptionCode, ExemptionLibrary.code)
        .join(ExemptionLibrary, ExemptionCode.library_id == ExemptionLibrary.id)
        .where(ExemptionCode.org_id == org_id, ExemptionLibrary.code.in_(ALLOWED_LIBRARY_CODES))
    )
    rows = result.all()
    code_map = {lib_code: exc.id for exc, lib_code in rows}
    summary_lines = [f"{lib_code} -> {exc.label} -> {exc.statute_citation}" for exc, lib_code in rows]
    return "\n".join(summary_lines), code_map


async def detect_page_contextual(
    session: AsyncSession, provider: LLMProvider, org_id: str, doc_id: str, page: PageExtraction
) -> tuple[list[RedactionCandidate], int, int, int]:
    """Returns (candidates, hallucination_count, input_tokens, output_tokens)."""
    taxonomy_summary, code_map = await _taxonomy_summary_and_code_map(session, org_id)
    if not code_map:
        return [], 0, 0, 0  # org has none of the Public Safety pack's codes cloned — nothing to ground findings against

    findings, hallucinated, in_tokens, out_tokens = run_contextual_pass(
        provider, page.full_text, document_type=DOCUMENT_TYPE,
        llm_context_rules=LLM_CONTEXT_RULES, exemption_taxonomy_summary=taxonomy_summary,
    )

    cipher = get_cipher()
    candidates = []
    for finding in findings:
        exemption_code_id = code_map.get(finding.exemption_code)
        if exemption_code_id is None:
            continue  # LLM cited a code outside the taxonomy we gave it — drop, don't guess

        bbox = span_to_bbox(page.word_spans, finding.start, finding.end)
        if bbox is None:
            continue  # grounded in the raw text but didn't line up with an extracted word

        candidate = RedactionCandidate(
            id=new_id("cand"), org_id=org_id, doc_id=doc_id, page_no=page.page_no, bbox=bbox,
            text_span={"start": finding.start, "end": finding.end},
            display_text_encrypted=cipher.encrypt(org_id, finding.quote),
            origin="llm", source_rule_key=RULE_KEY, source_rule_version=RULE_VERSION,
            exemption_code_id=exemption_code_id, ai_justification=finding.justification,
            confidence=confidence_band(finding.confidence), state="suggested",
            detector_versions={"model_id": provider.model_id, "prompt_version": "1"},
        )
        session.add(candidate)
        candidates.append(candidate)

    return candidates, hallucinated, in_tokens, out_tokens
