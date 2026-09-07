"""app/routers/exports.py's list_exports() `doc_id` filter - added so the review
workspace can show a document's own export history persistently (specs/07-ui-spec.md
screen 4/5) instead of only the result of whichever export the reviewer just triggered
this session."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.models.document import Document
from app.models.export_artifact import ExportArtifact
from app.routers.exports import list_exports
from tests.conftest import set_org


async def _seed_org_user_docs(session: AsyncSession, org_id: str, user_id: str, doc_ids: list[str]) -> None:
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
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    for doc_id in doc_ids:
        session.add(
            Document(
                id=doc_id, org_id=org_id, filename=f"{doc_id}.pdf", mime_type="application/pdf",
                source="upload", status="exported", uploaded_by=user_id, content_sha256="deadbeef",
            )
        )


@pytest.mark.asyncio
async def test_list_exports_filters_by_doc_id(db_session: AsyncSession) -> None:
    org_id, user_id = "org_expl_1", "usr_expl_1"
    doc_a, doc_b = new_id("doc"), new_id("doc")
    await _seed_org_user_docs(db_session, org_id, user_id, [doc_a, doc_b])
    for doc_id in (doc_a, doc_a, doc_b):
        db_session.add(
            ExportArtifact(
                id=new_id("exp"), org_id=org_id, doc_id=doc_id, type="clean_pdf",
                s3_key="k", sha256="sha", manifest_version=1, integrity_check={"passed": True},
                created_by=user_id,
            )
        )
    await db_session.flush()

    scoped = await list_exports(db=db_session, limit=20, doc_id=doc_a)
    assert len(scoped) == 2
    assert all(a.doc_id == doc_a for a in scoped)

    unscoped = await list_exports(db=db_session, limit=20, doc_id=None)
    assert len(unscoped) == 3
