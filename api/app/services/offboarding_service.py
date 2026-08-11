"""specs/08-security-compliance.md § Data lifecycle: "Org offboarding: full export
package (documents, manifests, audit CSV) then destruction with attestation; per-org CMK
scheduled for deletion (crypto-shred)."

crypto-shred is NOT performed here. app/crypto/envelope.py's per-org CMK encryption
isn't wired yet (KmsEnvelopeCipher raises NotImplementedError; local dev uses ONE shared
key for every org, so there is no per-org key to shred without breaking every other
org). offboard_org records that the step is deferred in the audit metadata rather than
silently skipping it or faking an AWS call with nothing real behind it.

Legal hold is still respected during offboarding — ending the customer relationship
doesn't erase an active legal obligation. Held documents' content survives offboarding
until the hold is cleared, same rule as the routine retention sweep
(app/services/retention_service.py), which purge_document_content is reused from here.

Manages its own sessions (system_session for the cross-tenant org lookup,
org_session for the actual writes) rather than taking one as a parameter — same
self-managed-session pattern as app/services/platform_service.py, for the same reason:
a platform admin has no membership to scope a normal org_session to on its own.
"""

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime

import fitz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, ConflictError, NotFoundError
from app.db.session import org_session, system_session
from app.models.audit_event import AuditEvent
from app.models.document import Document
from app.models.organization import Organization
from app.models.request import RecordsRequest
from app.services.audit_service import list_audit_events, write_audit_event
from app.services.document_service import get_manifest_data
from app.services.retention_service import purge_document_content
from app.storage import get_store


async def _add_documents_and_manifests(session: AsyncSession, org_id: str, zf: zipfile.ZipFile) -> None:
    store = get_store()
    docs_result = await session.execute(select(Document).where(Document.org_id == org_id))
    for document in docs_result.scalars().all():
        if document.s3_key_original:
            try:
                zf.writestr(f"originals/{document.id}/{document.filename}", store.get(org_id, document.s3_key_original))
            except FileNotFoundError:
                pass
        try:
            manifest_data = await get_manifest_data(session, document.id)
        except NotFoundError:
            continue
        zf.writestr(f"manifests/{document.id}.json", json.dumps(manifest_data, default=str, indent=2))


async def _add_audit_csv(session: AsyncSession, zf: zipfile.ZipFile) -> None:
    events = await list_audit_events(session)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "created_at", "actor_type", "actor_id", "action", "object_type", "object_id", "metadata"])
    for event in events:
        writer.writerow(
            [event.id, event.created_at.isoformat(), event.actor_type, event.actor_id or "",
             event.action, event.object_type, event.object_id, event.metadata_]
        )
    zf.writestr("audit.csv", buffer.getvalue())


async def generate_offboarding_package(session: AsyncSession, org_id: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        await _add_documents_and_manifests(session, org_id, zf)
        await _add_audit_csv(session, zf)
    return buffer.getvalue()


async def find_documents_eligible_for_offboarding_purge(session: AsyncSession, org_id: str) -> list[str]:
    """Unlike the routine retention sweep, every not-already-deleted document is
    eligible regardless of status/export-age — offboarding is an immediate, explicit
    destruction request, not a scheduled expiry. legal_hold on the document or its
    request still blocks it."""
    result = await session.execute(
        select(Document.id)
        .outerjoin(RecordsRequest, Document.request_id == RecordsRequest.id)
        .where(
            Document.org_id == org_id,
            Document.deleted_at.is_(None),
            Document.legal_hold.is_(False),
            (RecordsRequest.id.is_(None)) | (RecordsRequest.legal_hold.is_(False)),
        )
    )
    return [row[0] for row in result.all()]


async def offboard_org(platform_admin_user_id: str, org_id: str, confirm_slug: str, now: datetime) -> tuple[bytes, int]:
    async with system_session() as sys_session:
        org = await sys_session.get(Organization, org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    if org.plan_status == "canceled":
        raise ConflictError("Organization is already offboarded")
    if confirm_slug != org.slug:
        raise ApiError(422, "Unprocessable Entity", "confirm_slug does not match the organization's slug")

    async with org_session(org_id) as session:
        package = await generate_offboarding_package(session, org_id)

        doc_ids = await find_documents_eligible_for_offboarding_purge(session, org_id)
        for doc_id in doc_ids:
            await purge_document_content(session, org_id, doc_id, now)

        org_row = await session.get(Organization, org_id)
        assert org_row is not None
        org_row.plan_status = "canceled"

        await write_audit_event(
            session, org_id=org_id, actor_type="platform_admin", actor_id=platform_admin_user_id,
            action="platform.org_offboarded", object_type="organization", object_id=org_id,
            metadata={
                "offboarded_at": now.isoformat(),
                "documents_purged": len(doc_ids),
                "package_sha256": hashlib.sha256(package).hexdigest(),
                "crypto_shred": "deferred — per-org CMK encryption not yet wired (app/crypto/envelope.py)",
            },
        )
        await session.flush()

    return package, len(doc_ids)


@dataclass
class DestructionAttestationFacts:
    org_id: str
    org_name: str
    offboarded_at: str
    documents_purged: int
    package_sha256: str


async def get_destruction_attestation_facts(org_id: str) -> DestructionAttestationFacts:
    async with system_session() as sys_session:
        org = await sys_session.get(Organization, org_id)
    if org is None:
        raise NotFoundError("Organization not found")

    async with org_session(org_id) as session:
        result = await session.execute(
            select(AuditEvent)
            .where(AuditEvent.org_id == org_id, AuditEvent.action == "platform.org_offboarded")
            .order_by(AuditEvent.created_at.desc())
            .limit(1)
        )
        event = result.scalars().first()
    if event is None:
        raise NotFoundError("This organization has not been offboarded — no destruction attestation exists")

    metadata = event.metadata_
    return DestructionAttestationFacts(
        org_id=org_id, org_name=org.name, offboarded_at=metadata["offboarded_at"],
        documents_purged=metadata["documents_purged"], package_sha256=metadata["package_sha256"],
    )


def generate_destruction_attestation_pdf(facts: DestructionAttestationFacts) -> bytes:
    """Same fitz-primitives approach as app/services/retention_service.py's deletion
    certificate — generated on demand, never stored."""
    doc = fitz.open()
    page = doc.new_page()
    lines = [
        "REDACTPROOF — CERTIFICATE OF ORGANIZATION DESTRUCTION",
        "",
        f"Organization: {facts.org_name} ({facts.org_id})",
        f"Offboarded (UTC): {facts.offboarded_at}",
        f"Documents purged: {facts.documents_purged}",
        f"Export package SHA-256: {facts.package_sha256}",
        "",
        "This certificate attests that the above organization's document content was",
        "exported to the organization and then destroyed per specs/08-security-",
        "compliance.md's offboarding process, following the applicable legal-hold check.",
        "",
        "Per-org encryption key destruction (crypto-shred) is deferred: this deployment",
        "does not yet provision per-org KMS customer master keys.",
    ]
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 18
    return doc.tobytes()
