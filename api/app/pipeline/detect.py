"""specs/05-redaction-pipeline.md Stage 3: Deterministic detection. Presidio + Core PII
starter pack only for Phase 1 — org custom rule packs and the LLM contextual pass
(Stage 4) are Phase 2+."""

from functools import lru_cache

from presidio_analyzer import AnalyzerEngine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.exemption_code import ExemptionCode, ExemptionLibrary
from app.models.organization import Organization
from app.models.redaction_candidate import RedactionCandidate
from app.pipeline.core_pii import (
    ENTITY_TO_LIBRARY_CODE,
    RULE_KEY,
    RULE_VERSION,
    STATE_PII_LIBRARY_CODE_SUFFIX,
    SUPPORTED_ENTITIES,
    Finding,
    confidence_band,
)
from app.pipeline.extract import PageExtraction, span_to_bbox

PRESIDIO_VERSION = "2.2"


@lru_cache
def _analyzer() -> AnalyzerEngine:
    # Loaded once per process — spaCy model load is the expensive part (seconds), not
    # something to repeat per document.
    return AnalyzerEngine()


def find_pii(text: str) -> list[Finding]:
    results = _analyzer().analyze(text=text, language="en", entities=SUPPORTED_ENTITIES)
    return [
        Finding(entity_type=r.entity_type, start=r.start, end=r.end, text=text[r.start : r.end], score=r.score)
        for r in results
    ]


async def _pick_exemption_code(session: AsyncSession, org_id: str, library_code: str) -> str | None:
    """Prefer the org's own state's "<STATE>-PII" cloned code over the federal library_code
    fallback (see app/pipeline/core_pii.py's module docstring)."""
    org = await session.get(Organization, org_id)
    if org is not None:
        state_code = f"{org.jurisdiction_state}{STATE_PII_LIBRARY_CODE_SUFFIX}"
        result = await session.execute(
            select(ExemptionCode)
            .join(ExemptionLibrary, ExemptionCode.library_id == ExemptionLibrary.id)
            .where(ExemptionCode.org_id == org_id, ExemptionLibrary.code == state_code)
        )
        state_match = result.scalars().first()
        if state_match is not None:
            return state_match.id

    result = await session.execute(
        select(ExemptionCode)
        .join(ExemptionLibrary, ExemptionCode.library_id == ExemptionLibrary.id)
        .where(ExemptionCode.org_id == org_id, ExemptionLibrary.code == library_code)
    )
    fallback = result.scalars().first()
    return fallback.id if fallback is not None else None


async def detect_page(
    session: AsyncSession, org_id: str, doc_id: str, page: PageExtraction
) -> list[RedactionCandidate]:
    cipher = get_cipher()
    findings = find_pii(page.full_text)
    candidates = []
    for finding in findings:
        bbox = span_to_bbox(page.word_spans, finding.start, finding.end)
        if bbox is None:
            continue  # NLP span didn't line up with any extracted word — skip rather than guess
        library_code = ENTITY_TO_LIBRARY_CODE[finding.entity_type]
        exemption_code_id = await _pick_exemption_code(session, org_id, library_code)

        candidate = RedactionCandidate(
            id=new_id("cand"),
            org_id=org_id,
            doc_id=doc_id,
            page_no=page.page_no,
            bbox=bbox,
            text_span={"start": finding.start, "end": finding.end},
            display_text_encrypted=cipher.encrypt(org_id, finding.text),
            origin="deterministic",
            source_rule_key=RULE_KEY,
            source_rule_version=RULE_VERSION,
            exemption_code_id=exemption_code_id,
            confidence=confidence_band(finding.score),
            state="suggested",
            detector_versions={"presidio_version": PRESIDIO_VERSION},
        )
        session.add(candidate)
        candidates.append(candidate)
    return candidates
