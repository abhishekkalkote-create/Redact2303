"""Phase 6 build-plan AC: "chaos pass on workers (kill mid-job -> idempotent recovery, no
lost usage records, no partial exports)."

app/pipeline/run.py's own docstring is explicit that there are no real SQS-consumed
workers yet to chaos-test at the infrastructure level (nothing kills a Fargate task here) —
process_document/reprocess_document/create_export instead run synchronously inside ONE
request-scoped transaction (app/db/session.py's org_session). That single-transaction
design is itself the recovery mechanism: a worker killed mid-job is, from Postgres's
perspective, indistinguishable from a connection that dropped before COMMIT, and the
transaction rolls back in full. These tests simulate that kill the only way it can be
simulated without an actual OS-level process kill: let an exception escape a real
`session.begin()` block partway through a pipeline run (after some rows have already been
`session.add()`-ed and, for export, after bytes have already been written to the object
store — a non-transactional side effect the DB rollback can't undo) and prove:

1. No partial state survives — the doc/manifest/candidates/audit trail land exactly where
   they were before the killed attempt, never half-updated.
2. A retry recovers cleanly and exactly once — no lost usage record (undercounting a
   billable event) and no duplicate one (double-billing a retry), regardless of whatever
   the killed attempt already wrote to non-transactional storage.
"""

import fitz
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.llm.provider import FakeLLMProvider
from app.models.document import Document
from app.models.manifest import Manifest
from app.models.redaction_candidate import RedactionCandidate
from app.services.exemption_service import clone_library_for_org
from app.storage import get_store
from tests.conftest import set_org


def _sample_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Incident Report - Springfield PD")
    page.insert_text((72, 130), "The victim Jane Doe reported the incident.")
    page.insert_text((72, 160), "Social security number: 234-56-7890.")
    data = doc.tobytes()
    doc.close()
    return data


async def _seed_org_and_user(session: AsyncSession, org_id: str, user_id: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_id},
    )
    await session.execute(
        text(
            "INSERT INTO users (id, email, name, status) VALUES "
            "(:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )


@pytest.mark.asyncio
async def test_reprocess_killed_mid_detection_leaves_no_partial_state_then_retry_is_clean(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id, user_id, doc_id = "org_chaos_reproc", "usr_chaos_reproc", new_id("doc")
    original_key = f"originals/{doc_id}"
    get_store().put(org_id, original_key, _sample_pdf_bytes())

    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        codes = await clone_library_for_org(db_session, org_id, "WA")
        code_id = next(c.id for c in codes)
        db_session.add(
            Document(
                id=doc_id, org_id=org_id, filename="sample.pdf", mime_type="application/pdf",
                source="upload", status="ready_for_review", uploaded_by=user_id,
                s3_key_original=original_key, content_sha256="deadbeef",
            )
        )
        db_session.add(Manifest(id=new_id("man"), org_id=org_id, doc_id=doc_id, version=1))
        # A prior human decision that must survive a killed-and-retried reprocess untouched
        # — a rule/detector change (or in this test, a crash) must never silently discard it.
        db_session.add(
            RedactionCandidate(
                id=new_id("cand"), org_id=org_id, doc_id=doc_id, page_no=1,
                bbox={"x": 60, "y": 115, "w": 300, "h": 20}, text_span=None,
                display_text_encrypted=get_cipher().encrypt(org_id, "Jane Doe"),
                origin="manual", confidence="n/a-manual", state="approved",
                exemption_code_id=code_id,
            )
        )

    fake_provider = FakeLLMProvider()
    monkeypatch.setattr("app.pipeline.run.get_provider", lambda: fake_provider)

    from app.pipeline.detect_llm import detect_page_contextual as real_detect_page_contextual

    call_count = {"n": 0}

    async def _flaky_detect_page_contextual(session, provider, org_id_, doc_id_, page):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Simulates the worker process dying after the deterministic pass for this
            # page already added a candidate to the (still-open) transaction, but before
            # the contextual pass — and the transaction as a whole — ever commits.
            raise RuntimeError("simulated worker kill mid-detection")
        return await real_detect_page_contextual(session, provider, org_id_, doc_id_, page)

    monkeypatch.setattr("app.pipeline.run.detect_page_contextual", _flaky_detect_page_contextual)

    from app.pipeline.run import reprocess_document

    with pytest.raises(RuntimeError):
        async with db_session.begin():
            await set_org(db_session, org_id)
            await reprocess_document(db_session, org_id, doc_id, user_id)

    # Fresh transaction, exactly as a fresh request after the killed worker would use —
    # nothing from the killed attempt should be visible.
    async with db_session.begin():
        await set_org(db_session, org_id)
        doc_row = (await db_session.execute(text("SELECT status FROM documents WHERE id = :id"), {"id": doc_id})).one()
        assert doc_row.status == "ready_for_review", "must not be stuck mid-pipeline in 'detecting'"

        manifest_row = (await db_session.execute(text("SELECT version FROM manifests WHERE doc_id = :id"), {"id": doc_id})).one()
        assert manifest_row.version == 1, "killed attempt's version bump must not have survived"

        candidate_rows = (await db_session.execute(text("SELECT state FROM redaction_candidates WHERE doc_id = :id"), {"id": doc_id})).all()
        assert len(candidate_rows) == 1, "the killed attempt's new deterministic candidate must not have survived"
        assert candidate_rows[0].state == "approved"

        job_count = (await db_session.execute(text("SELECT count(*) FROM processing_jobs WHERE doc_id = :id"), {"id": doc_id})).scalar_one()
        assert job_count == 0, "the killed attempt's detect job must not have survived"

        audit_count = (
            await db_session.execute(
                text("SELECT count(*) FROM audit_events WHERE object_id = :id AND action = 'document.reprocessed'"),
                {"id": doc_id},
            )
        ).scalar_one()
        assert audit_count == 0

    # Retry — same call, no monkeypatched failure this time (call_count is now 2).
    async with db_session.begin():
        await set_org(db_session, org_id)
        manifest = await reprocess_document(db_session, org_id, doc_id, user_id)
        assert manifest.version == 2, "exactly one bump from the single successful attempt, not two"

    async with db_session.begin():
        await set_org(db_session, org_id)
        doc_row = (await db_session.execute(text("SELECT status FROM documents WHERE id = :id"), {"id": doc_id})).one()
        assert doc_row.status == "ready_for_review"

        candidate_rows = (
            await db_session.execute(text("SELECT id, state FROM redaction_candidates WHERE doc_id = :id"), {"id": doc_id})
        ).all()
        approved = [r for r in candidate_rows if r.state == "approved"]
        assert len(approved) == 1, "the pre-existing human decision must survive completely untouched"

        audit_count = (
            await db_session.execute(
                text("SELECT count(*) FROM audit_events WHERE object_id = :id AND action = 'document.reprocessed'"),
                {"id": doc_id},
            )
        ).scalar_one()
        assert audit_count == 1, "exactly one reprocess audit event, not zero and not duplicated"

    assert call_count["n"] == 2, "sanity check: the flaky wrapper really was hit by both attempts"


@pytest.mark.asyncio
async def test_export_killed_after_storage_write_leaves_no_partial_db_state_then_retry_is_clean(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id, user_id, doc_id = "org_chaos_export", "usr_chaos_export", new_id("doc")
    original_key = f"originals/{doc_id}"
    get_store().put(org_id, original_key, _sample_pdf_bytes())
    clean_pdf_key = f"exports/{doc_id}/clean_pdf"

    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        codes = await clone_library_for_org(db_session, org_id, "WA")
        code_id = next(c.id for c in codes)
        db_session.add(
            Document(
                id=doc_id, org_id=org_id, filename="sample.pdf", mime_type="application/pdf",
                source="upload", status="review_complete", uploaded_by=user_id,
                s3_key_original=original_key, content_sha256="deadbeef",
            )
        )
        db_session.add(Manifest(id=new_id("man"), org_id=org_id, doc_id=doc_id, version=1))
        db_session.add(
            RedactionCandidate(
                id=new_id("cand"), org_id=org_id, doc_id=doc_id, page_no=1,
                # Generous box around the whole "Social security number: 234-56-7890."
                # line (baseline at y=160) so burn-in removes every glyph inside it.
                bbox={"x": 60, "y": 145, "w": 400, "h": 30}, text_span=None,
                display_text_encrypted=get_cipher().encrypt(org_id, "234-56-7890"),
                origin="manual", confidence="n/a-manual", state="approved",
                exemption_code_id=code_id,
            )
        )

    from app.pipeline.export import generate_exemption_log_csv as real_generate_exemption_log_csv

    call_count = {"n": 0}

    def _flaky_generate_exemption_log_csv(rows):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # By this point create_export has already burned in the redaction, verified
            # integrity, and store.put() the clean_pdf bytes (a non-transactional side
            # effect a DB rollback cannot undo) — simulating the worker dying right after
            # that write, before the transaction (and thus the ExportArtifact row for it)
            # ever commits.
            raise RuntimeError("simulated worker kill mid-export")
        return real_generate_exemption_log_csv(rows)

    monkeypatch.setattr("app.services.export_service.generate_exemption_log_csv", _flaky_generate_exemption_log_csv)

    from app.services.export_service import create_export

    with pytest.raises(RuntimeError):
        async with db_session.begin():
            await set_org(db_session, org_id)
            await create_export(db_session, org_id, doc_id, user_id)

    orphaned_bytes = get_store().get(org_id, clean_pdf_key)
    assert orphaned_bytes, (
        "confirms the premise: the storage write really did survive the DB rollback — "
        "proving the DB-side assertions below are meaningfully testing recovery, not "
        "testing a scenario that can't happen"
    )

    async with db_session.begin():
        await set_org(db_session, org_id)
        doc_row = (await db_session.execute(text("SELECT status FROM documents WHERE id = :id"), {"id": doc_id})).one()
        assert doc_row.status == "review_complete", "must not have flipped to exported"

        artifact_count = (await db_session.execute(text("SELECT count(*) FROM export_artifacts WHERE doc_id = :id"), {"id": doc_id})).scalar_one()
        assert artifact_count == 0, "the orphaned storage write must not be reflected in the DB"

        usage_count = (
            await db_session.execute(
                text("SELECT count(*) FROM usage_records WHERE doc_id = :id AND metric = 'exports'"), {"id": doc_id}
            )
        ).scalar_one()
        assert usage_count == 0, "no usage record for a killed, never-completed export"

        audit_count = (
            await db_session.execute(
                text("SELECT count(*) FROM audit_events WHERE object_id = :id AND action = 'export.created'"), {"id": doc_id}
            )
        ).scalar_one()
        assert audit_count == 0

    # Retry — call_count is now 2, so generate_exemption_log_csv succeeds this time.
    async with db_session.begin():
        await set_org(db_session, org_id)
        artifacts = await create_export(db_session, org_id, doc_id, user_id)
        assert {a.type for a in artifacts} == {"clean_pdf", "exemption_log_csv", "certificate_pdf"}

    async with db_session.begin():
        await set_org(db_session, org_id)
        doc_row = (await db_session.execute(text("SELECT status FROM documents WHERE id = :id"), {"id": doc_id})).one()
        assert doc_row.status == "exported"

        artifact_rows = (await db_session.execute(text("SELECT type, sha256 FROM export_artifacts WHERE doc_id = :id"), {"id": doc_id})).all()
        assert len(artifact_rows) == 3, "no leftover/duplicate artifact rows from the killed attempt"

        usage_count = (
            await db_session.execute(
                text("SELECT count(*) FROM usage_records WHERE doc_id = :id AND metric = 'exports'"), {"id": doc_id}
            )
        ).scalar_one()
        assert usage_count == 1, "exactly one billable export — not lost, not double-billed on retry"

        audit_count = (
            await db_session.execute(
                text("SELECT count(*) FROM audit_events WHERE object_id = :id AND action = 'export.created'"), {"id": doc_id}
            )
        ).scalar_one()
        assert audit_count == 1

        clean_pdf_sha = next(r.sha256 for r in artifact_rows if r.type == "clean_pdf")

    # The retry's store.put() for the same deterministic key must have overwritten the
    # orphaned blob with the successful attempt's own bytes, not left a stale/corrupt mix.
    final_bytes = get_store().get(org_id, clean_pdf_key)
    from app.pipeline.intake import content_sha256

    assert content_sha256(final_bytes) == clean_pdf_sha

    assert call_count["n"] == 2, "sanity check: the flaky wrapper really was hit by both attempts"
