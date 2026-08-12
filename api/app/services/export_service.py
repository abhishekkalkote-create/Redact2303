import logging
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError, NotFoundError
from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.document import Document
from app.models.exemption_code import ExemptionCode
from app.models.export_artifact import ExportArtifact
from app.models.manifest import Manifest
from app.models.redaction_candidate import RedactionCandidate
from app.models.usage_record import UsageRecord
from app.pipeline.export import (
    CertificateFacts,
    ExemptionLogRow,
    add_annotation_labels,
    burn_in_redactions,
    generate_certificate_pdf,
    generate_exemption_log_csv,
    scrub_metadata,
    sign_certificate,
    verify_certificate,
    verify_integrity,
)
from app.pipeline.intake import content_sha256
from app.services.audit_service import write_audit_event
from app.services.webhook_service import trigger_event
from app.storage import get_store

DEFAULT_EXPORT_TYPES = ("clean_pdf", "exemption_log_csv", "certificate_pdf")

logger = logging.getLogger(__name__)


async def create_export(
    session: AsyncSession, org_id: str, doc_id: str, user_id: str, types: tuple[str, ...] = DEFAULT_EXPORT_TYPES
) -> list[ExportArtifact]:
    """specs/03-data-model.md: `documents.status = exported` requires an export_artifact
    whose `integrity_check.passed = true` — the verifier is a BLOCKING gate
    (specs/05-redaction-pipeline.md Stage 7), not advisory. A failed check raises rather
    than storing any downloadable artifact, of any type."""
    document = await session.get(Document, doc_id)
    if document is None:
        raise NotFoundError("Document not found")
    if document.status != "review_complete":
        raise ApiError(422, "Unprocessable Entity", f"Document must be review_complete to export (is {document.status})")

    manifest_result = await session.execute(select(Manifest).where(Manifest.doc_id == doc_id))
    manifest = manifest_result.scalars().first()
    if manifest is None:
        raise NotFoundError("Manifest not found")

    result = await session.execute(
        select(RedactionCandidate, ExemptionCode)
        .outerjoin(ExemptionCode, RedactionCandidate.exemption_code_id == ExemptionCode.id)
        .where(RedactionCandidate.doc_id == doc_id, RedactionCandidate.state == "approved")
    )
    rows = result.all()

    cipher = get_cipher()
    approved_boxes = [(c.page_no, c.bbox) for c, _code in rows]
    redacted_texts = [cipher.decrypt(org_id, c.display_text_encrypted) for c, _code in rows]

    store = get_store()
    assert document.s3_key_original is not None
    original_bytes = store.get(org_id, document.s3_key_original)

    clean = burn_in_redactions(original_bytes, approved_boxes)
    clean = scrub_metadata(clean)

    integrity = verify_integrity(clean, approved_boxes, redacted_texts)
    if not integrity.passed:
        # specs/02-architecture.md § Observability: "integrity-verifier failure (blocks
        # export, pages on-call)" — a count, not integrity.checks itself: those strings can
        # contain the actual leftover/leaked redacted text (see verify_integrity's own
        # "FAIL: ... still contains text: {leftover!r}" format), which must never reach a
        # shared infra log (CLAUDE.md invariant #6), unlike the audit_events row below —
        # that one's RLS-scoped and encrypted at rest, a different trust boundary than
        # CloudWatch.
        logger.warning(
            "export.integrity_failed",
            extra={
                "event": "export.integrity_failed",
                "org_id": org_id,
                "doc_id": doc_id,
                "failed_check_count": sum(1 for c in integrity.checks if c.startswith("FAIL")),
            },
        )
        await write_audit_event(
            session, org_id=org_id, actor_type="system", actor_id=user_id,
            action="export.integrity_failed", object_type="document", object_id=doc_id,
            metadata={"checks": integrity.checks},
        )
        await session.flush()
        raise ApiError(422, "Unprocessable Entity", f"Export blocked: integrity verification failed. {integrity.checks}")

    artifacts: list[ExportArtifact] = []

    def _store_artifact(export_type: str, content: bytes) -> ExportArtifact:
        key = f"exports/{doc_id}/{export_type}"
        store.put(org_id, key, content)
        artifact = ExportArtifact(
            id=new_id("exp"), org_id=org_id, doc_id=doc_id, type=export_type, s3_key=key,
            sha256=content_sha256(content), manifest_version=manifest.version,
            integrity_check={"passed": integrity.passed, "checks": integrity.checks},
            created_by=user_id,
        )
        session.add(artifact)
        artifacts.append(artifact)
        return artifact

    if "clean_pdf" in types:
        _store_artifact("clean_pdf", clean)

    if "annotated_pdf" in types:
        labeled_boxes = [(c.page_no, c.bbox, code.code if code else "?") for c, code in rows]
        annotated = add_annotation_labels(clean, labeled_boxes)
        _store_artifact("annotated_pdf", annotated)

    counts_by_exemption: dict[str, int] = {}
    log_rows = []
    for i, (c, code) in enumerate(rows):
        code_label = code.code if code else "unknown"
        counts_by_exemption[code_label] = counts_by_exemption.get(code_label, 0) + 1
        log_rows.append(
            ExemptionLogRow(
                seq=i + 1, page_no=c.page_no, exemption_code=code_label,
                statute_citation=code.statute_citation if code else None,
                justification=c.ai_justification, source_rule_key=c.source_rule_key,
                reviewer_email=None, decided_at=c.updated_at.isoformat() if c.updated_at else None,
            )
        )

    if "exemption_log_csv" in types:
        _store_artifact("exemption_log_csv", generate_exemption_log_csv(log_rows))

    if "certificate_pdf" in types:
        settings = get_settings()
        facts = CertificateFacts(
            certificate_id=new_id("cert"), doc_id=doc_id, org_id=org_id,
            clean_pdf_sha256=content_sha256(clean), manifest_version=manifest.version,
            redaction_count=len(rows), counts_by_exemption=counts_by_exemption,
            integrity_passed=integrity.passed, exported_at=datetime.now(UTC).isoformat(),
        )
        signature = sign_certificate(facts, settings.certificate_signing_key)
        assert verify_certificate(facts, signature, settings.certificate_signing_key)  # sanity check before storing
        cert_pdf = generate_certificate_pdf(facts, signature)
        artifact = _store_artifact("certificate_pdf", cert_pdf)
        artifact.integrity_check = {
            **artifact.integrity_check,
            "certificate_facts": asdict(facts),
            "signature": signature,
        }

    document.status = "exported"
    now = datetime.now(UTC)
    session.add(
        UsageRecord(
            id=new_id("use"), org_id=org_id, metric="exports", quantity=1,
            doc_id=doc_id, job_id=None, occurred_at=now, billing_period=now.strftime("%Y-%m"),
        )
    )
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="export.created", object_type="document", object_id=doc_id,
        metadata={"redaction_count": len(rows), "integrity_passed": True, "types": list(types)},
    )
    await trigger_event(
        session, org_id, "document.exported",
        {"doc_id": doc_id, "redaction_count": len(rows), "types": list(types)},
    )
    await session.flush()
    for artifact in artifacts:
        await session.refresh(artifact)
    return artifacts


async def verify_certificate_by_id(certificate_artifact_id: str) -> dict:
    """Public, unauthenticated lookup — specs/05-redaction-pipeline.md: certificate
    "verification endpoint public". Uses the same declare-the-exact-id RLS pattern as
    invite token lookup (migration 0004's `public_certificate_lookup` policy); see that
    migration's docstring for why this can't be used to enumerate other orgs' exports."""
    from sqlalchemy import text as sa_text

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            sa_text("SELECT set_config('app.lookup_export_artifact_id', :id, true)"),
            {"id": certificate_artifact_id},
        )
        artifact = await session.get(ExportArtifact, certificate_artifact_id)

    if artifact is None or artifact.type != "certificate_pdf":
        raise NotFoundError("Certificate not found")

    facts_dict = artifact.integrity_check.get("certificate_facts")
    signature = artifact.integrity_check.get("signature")
    if not facts_dict or not signature:
        raise ApiError(500, "Internal Server Error", "Certificate artifact is missing signed facts")

    settings = get_settings()
    facts = CertificateFacts(**facts_dict)
    valid = verify_certificate(facts, signature, settings.certificate_signing_key)
    return {"valid": valid, "facts": facts_dict}
