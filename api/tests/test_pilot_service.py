"""app/services/pilot_service.py. get_success_metrics takes a session directly, so it's
tested against the real test database via db_session; generate_roi_summary_pdf is pure
(no DB, no I/O) and tested directly."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.organization import Organization
from app.services.pilot_service import generate_roi_summary_pdf, get_success_metrics
from tests.conftest import set_org


async def _create_org(session: AsyncSession, org_id: str, *, plan: str = "pilot", days_old: int = 10) -> None:
    await set_org(session, org_id)
    created_at = datetime.now(UTC) - timedelta(days=days_old)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings, created_at, updated_at) VALUES "
            "(:id, :id, :id, 'WA', 'other', :plan, 'trialing', '{}', :created_at, :created_at)"
        ),
        {"id": org_id, "plan": plan, "created_at": created_at},
    )


async def _seed_approved_candidate(session: AsyncSession, org_id: str, doc_id: str, user_id: str, code: str) -> None:
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    await session.execute(
        text(
            "INSERT INTO documents (id, org_id, filename, mime_type, source, status, uploaded_by, content_sha256) "
            "VALUES (:id, :org_id, 'x.pdf', 'application/pdf', 'upload', 'ready_for_review', :user_id, 'deadbeef') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": doc_id, "org_id": org_id, "user_id": user_id},
    )
    exc_id = new_id("exc")
    await session.execute(
        text(
            "INSERT INTO exemption_codes (id, org_id, code, label, status) VALUES "
            "(:id, :org_id, :code, :code, 'active')"
        ),
        {"id": exc_id, "org_id": org_id, "code": code},
    )
    cipher = get_cipher()
    await session.execute(
        text(
            "INSERT INTO redaction_candidates (id, org_id, doc_id, page_no, bbox, display_text_encrypted, "
            "origin, exemption_code_id, confidence, state, detector_versions) VALUES "
            "(:id, :org_id, :doc_id, 1, '{}', :text, 'manual', :exc_id, 'n/a-manual', 'approved', '{}')"
        ),
        {"id": new_id("cand"), "org_id": org_id, "doc_id": doc_id, "text": cipher.encrypt(org_id, "x"), "exc_id": exc_id},
    )


async def _insert_usage_record(session: AsyncSession, org_id: str, quantity: int) -> None:
    await session.execute(
        text(
            "INSERT INTO usage_records (id, org_id, metric, quantity, occurred_at, billing_period) VALUES "
            "(:id, :org_id, 'pages_processed', :quantity, now(), '2026-08')"
        ),
        {"id": new_id("use"), "org_id": org_id, "quantity": quantity},
    )


@pytest.mark.asyncio
async def test_get_success_metrics_computes_hours_saved_and_redactions_by_exemption(db_session: AsyncSession) -> None:
    org_id = "org_pilot_metrics"
    async with db_session.begin():
        await _create_org(db_session, org_id, days_old=10)
        await _insert_usage_record(db_session, org_id, 120)
        await _seed_approved_candidate(db_session, org_id, "doc_a", "usr_a", "b6")
        await _seed_approved_candidate(db_session, org_id, "doc_a", "usr_a", "b6")
        await _seed_approved_candidate(db_session, org_id, "doc_a", "usr_a", "b7c")

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        metrics = await get_success_metrics(db_session, org, datetime.now(UTC))

    assert metrics["pages_processed"] == 120
    assert metrics["manual_minutes_per_page"] == 5
    assert metrics["est_hours_saved"] == round(120 * 5 / 60, 1)
    assert metrics["redactions_by_exemption"] == {"b6": 2, "b7c": 1}
    assert metrics["days_since_created"] == 10
    assert metrics["conversion_prompt_due"] is False


@pytest.mark.asyncio
async def test_get_success_metrics_conversion_prompt_due_at_day_75_for_pilot(db_session: AsyncSession) -> None:
    org_id = "org_pilot_day75"
    async with db_session.begin():
        await _create_org(db_session, org_id, plan="pilot", days_old=80)

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        metrics = await get_success_metrics(db_session, org, datetime.now(UTC))

    assert metrics["conversion_prompt_due"] is True


@pytest.mark.asyncio
async def test_get_success_metrics_conversion_prompt_never_due_for_paid_plans(db_session: AsyncSession) -> None:
    org_id = "org_paid_day75"
    async with db_session.begin():
        await _create_org(db_session, org_id, plan="growth", days_old=200)

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        metrics = await get_success_metrics(db_session, org, datetime.now(UTC))

    assert metrics["conversion_prompt_due"] is False


def test_generate_roi_summary_pdf_produces_a_pdf() -> None:
    metrics = {
        "pages_processed": 340, "manual_minutes_per_page": 5, "est_hours_saved": 28.3,
        "redactions_by_exemption": {"b6": 12, "b7c": 5}, "days_since_created": 80, "conversion_prompt_due": True,
    }
    pdf_bytes = generate_roi_summary_pdf("Test Org", metrics, datetime.now(UTC))
    assert pdf_bytes.startswith(b"%PDF")


def test_generate_roi_summary_pdf_handles_no_redactions_yet() -> None:
    metrics = {
        "pages_processed": 0, "manual_minutes_per_page": 5, "est_hours_saved": 0.0,
        "redactions_by_exemption": {}, "days_since_created": 1, "conversion_prompt_due": False,
    }
    pdf_bytes = generate_roi_summary_pdf("Test Org", metrics, datetime.now(UTC))
    assert pdf_bytes.startswith(b"%PDF")
