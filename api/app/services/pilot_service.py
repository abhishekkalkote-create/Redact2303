"""specs/01-product-spec.md § Pilot playbook: "success-metrics widget (pages processed,
est. hours saved @ configurable manual baseline, redactions by exemption)" +
"export-able one-page ROI summary (PDF) the champion can hand to their director —
designed artifact, not an afterthought." get_success_metrics feeds both the in-app widget
(app/routers/billing.py's GET /billing/success-metrics) and the PDF (GET
/billing/roi-summary), so the numbers on each always match.

Metrics are cumulative since org creation, not scoped to a billing period — this is a
"how much value have you gotten so far" story, matching Pilot's own cumulative page cap
(app/billing/plans.py's cap_kind="total"), not a monthly snapshot.
"""

from datetime import datetime

import fitz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exemption_code import ExemptionCode
from app.models.organization import DEFAULT_SETTINGS, Organization
from app.models.redaction_candidate import RedactionCandidate
from app.models.usage_record import UsageRecord

PILOT_CONVERSION_PROMPT_DAY = 75


async def get_success_metrics(session: AsyncSession, org: Organization, now: datetime) -> dict:
    pages_result = await session.execute(
        select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
            UsageRecord.org_id == org.id, UsageRecord.metric == "pages_processed"
        )
    )
    pages_processed = pages_result.scalar_one()

    manual_minutes_per_page = org.settings.get("manual_minutes_per_page", DEFAULT_SETTINGS["manual_minutes_per_page"])
    est_hours_saved = round(pages_processed * manual_minutes_per_page / 60, 1)

    exemption_result = await session.execute(
        select(ExemptionCode.code, func.count(RedactionCandidate.id))
        .join(ExemptionCode, RedactionCandidate.exemption_code_id == ExemptionCode.id)
        .where(RedactionCandidate.org_id == org.id, RedactionCandidate.state == "approved")
        .group_by(ExemptionCode.code)
        .order_by(func.count(RedactionCandidate.id).desc())
    )
    redactions_by_exemption = {code: count for code, count in exemption_result.all()}

    days_since_created = (now - org.created_at).days

    return {
        "pages_processed": pages_processed,
        "manual_minutes_per_page": manual_minutes_per_page,
        "est_hours_saved": est_hours_saved,
        "redactions_by_exemption": redactions_by_exemption,
        "days_since_created": days_since_created,
        "conversion_prompt_due": org.plan == "pilot" and days_since_created >= PILOT_CONVERSION_PROMPT_DAY,
    }


def generate_roi_summary_pdf(org_name: str, metrics: dict, generated_at: datetime) -> bytes:
    """Same fitz-primitives approach as app/pipeline/export.py's
    generate_certificate_pdf — a plain text layout is a one-pager a champion can print or
    attach to an email, not a polished design artifact; that's a frontend/design
    investment for later, not a reason to withhold the export now."""
    doc = fitz.open()
    page = doc.new_page()
    lines = [
        "REDACTPROOF — PILOT ROI SUMMARY",
        "",
        f"Organization: {org_name}",
        f"Generated (UTC): {generated_at.isoformat()}",
        f"Days since pilot start: {metrics['days_since_created']}",
        "",
        f"Pages processed: {metrics['pages_processed']}",
        f"Estimated hours saved: {metrics['est_hours_saved']} (at {metrics['manual_minutes_per_page']} min/page manual baseline)",
        "",
        "Redactions applied by exemption code:",
        *(
            [f"  {code}: {count}" for code, count in sorted(metrics["redactions_by_exemption"].items())]
            or ["  (none yet)"]
        ),
    ]
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 18
    return doc.tobytes()
