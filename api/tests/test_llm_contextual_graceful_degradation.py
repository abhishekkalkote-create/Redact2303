"""app/pipeline/detect_llm.py's detect_page_contextual() used to have no error handling
around the LLM provider call at all - a real Bedrock failure (access not yet granted,
throttling, a transient outage) would crash the entire document's detection pass,
including the deterministic (regex/entity) candidates that had nothing to do with the
LLM. Found while wiring up real Bedrock access - the exact same crash shape as the
already-fixed "Bedrock not configured" bug (see test_graceful_degradation.py), just for
"configured but the call itself failed" instead of "never configured at all"."""

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.llm.provider import LLMProvider, LLMResponse
from app.models.exemption_code import ExemptionCode
from app.pipeline.detect_llm import detect_page_contextual
from app.pipeline.extract import PageExtraction
from tests.conftest import set_org

# Global federal exemption_library row seeded by migrations - stable id, same pattern as
# other tests referencing known seed ids (e.g. rsv_core_pii_v1).
_FEDERAL_7C_LIBRARY_ID = "exl_fed_b7c"


class _AlwaysFailsProvider(LLMProvider):
    model_id = "always-fails"

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> LLMResponse:
        raise RuntimeError("simulated Bedrock AccessDeniedException")


def _page(text_value: str) -> PageExtraction:
    return PageExtraction(
        page_no=1, width=612.0, height=792.0, rotation=0, has_text_layer=True,
        full_text=text_value, word_spans=[], preview_png=b"", ocr_confidence=None,
    )


async def _seed_org_with_7c_code(session: AsyncSession, org_id: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_id},
    )
    session.add(
        ExemptionCode(
            id=new_id("exc"), org_id=org_id, library_id=_FEDERAL_7C_LIBRARY_ID,
            code="7(C)", label="Personal privacy", status="active",
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_detect_page_contextual_degrades_instead_of_crashing_on_provider_failure(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    org_id = new_id("org")
    await _seed_org_with_7c_code(db_session, org_id)

    with caplog.at_level(logging.WARNING):
        candidates, hallucinated, in_tokens, out_tokens = await detect_page_contextual(
            db_session, _AlwaysFailsProvider(), org_id, "doc_test", _page("Officer Jones interviewed the victim.")
        )

    assert candidates == []
    assert (hallucinated, in_tokens, out_tokens) == (0, 0, 0)
    assert any("llm_contextual_pass.failed" in record.message for record in caplog.records)
    # Never log the provider's own exception text - it can legitimately echo request content.
    assert not any("simulated Bedrock" in record.message for record in caplog.records)
