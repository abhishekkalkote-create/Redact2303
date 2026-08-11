"""Regression coverage for the Phase 6 security self-review fixes: IDOR on
exemption_code_id (app/services/exemption_service.py's require_exemption_code_in_org),
the audit hash-chain race (app/services/audit_service.py's advisory lock), the
legal_hold TOCTOU in retention/offboarding purges (app/services/retention_service.py),
the support-grant double-decision race (app/services/support_grant_service.py), the
missing invoice audit event (app/services/billing_service.py), the insecure-secret
startup guard (app/core/config.py), the offboarding zip-slip fix
(app/services/offboarding_service.py), and the LocalFilesystemStore path-traversal
hardening (app/storage/local.py).
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ApiError, NotFoundError
from app.core.ids import new_id
from app.models.audit_event import AuditEvent
from app.models.document import Document
from app.models.manifest import Manifest
from app.services.audit_service import write_audit_event
from app.services.billing_service import _apply_billing_event
from app.services.retention_service import purge_document_content
from app.services.review_service import (
    bulk_update_candidates,
    create_manual_candidate,
    patch_candidate,
)
from app.services.search_service import search_and_redact
from app.services.support_grant_service import decide_grant
from tests.conftest import set_org

# ---------------------------------------------------------------------------
# 1. IDOR on exemption_code_id
# ---------------------------------------------------------------------------


async def _seed_two_orgs_with_candidate(session: AsyncSession) -> dict:
    """org_a has a document + candidate + its own exemption code; org_b has a
    *different* exemption code. Returns ids needed to try assigning org_b's code to
    org_a's candidate."""
    org_a, org_b, user_a, doc_id = "org_idor_a", "org_idor_b", "usr_idor_a", new_id("doc")

    await set_org(session, org_a)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES (:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_a},
    )
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": user_a, "email": f"{user_a}@example.com"},
    )
    session.add(
        Document(
            id=doc_id, org_id=org_a, filename="sample.pdf", mime_type="application/pdf",
            source="upload", status="ready_for_review", uploaded_by=user_a, content_sha256="deadbeef",
        )
    )
    session.add(Manifest(id=new_id("man"), org_id=org_a, doc_id=doc_id, version=1))
    # Autoflush does not fire ahead of a raw session.execute(text(...)) the way it would
    # for an ORM query — without this, the redaction_candidates insert below races the
    # still-pending Document row and fails its FK constraint.
    await session.flush()
    own_code_id = new_id("exc")
    await session.execute(
        text("INSERT INTO exemption_codes (id, org_id, code, label, status) VALUES (:id, :org_id, 'OWN-1', 'Own code', 'active')"),
        {"id": own_code_id, "org_id": org_a},
    )
    cand_id = new_id("cand")
    await session.execute(
        text(
            "INSERT INTO redaction_candidates (id, org_id, doc_id, page_no, bbox, display_text_encrypted, "
            "origin, confidence, state, detector_versions) VALUES "
            "(:id, :org_id, :doc_id, 1, '{}', 'ciphertext', 'manual', 'n/a-manual', 'suggested', '{}')"
        ),
        {"id": cand_id, "org_id": org_a, "doc_id": doc_id},
    )

    await set_org(session, org_b)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES (:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_b},
    )
    other_orgs_code_id = new_id("exc")
    await session.execute(
        text("INSERT INTO exemption_codes (id, org_id, code, label, status) VALUES (:id, :org_id, 'OTHER-1', 'Other org code', 'active')"),
        {"id": other_orgs_code_id, "org_id": org_b},
    )

    return {
        "org_a": org_a, "user_a": user_a, "doc_id": doc_id, "cand_id": cand_id,
        "own_code_id": own_code_id, "other_orgs_code_id": other_orgs_code_id,
    }


@pytest.mark.asyncio
async def test_patch_candidate_rejects_another_orgs_exemption_code(db_session: AsyncSession) -> None:
    async with db_session.begin():
        ids = await _seed_two_orgs_with_candidate(db_session)

    async with db_session.begin():
        await set_org(db_session, ids["org_a"])
        with pytest.raises(NotFoundError):
            await patch_candidate(
                db_session, ids["org_a"], ids["cand_id"], ids["user_a"],
                state=None, exemption_code_id=ids["other_orgs_code_id"], bbox=None,
                ai_justification=None, note=None, if_match_version=None,
            )


@pytest.mark.asyncio
async def test_patch_candidate_accepts_its_own_orgs_exemption_code(db_session: AsyncSession) -> None:
    async with db_session.begin():
        ids = await _seed_two_orgs_with_candidate(db_session)

    async with db_session.begin():
        await set_org(db_session, ids["org_a"])
        candidate = await patch_candidate(
            db_session, ids["org_a"], ids["cand_id"], ids["user_a"],
            state=None, exemption_code_id=ids["own_code_id"], bbox=None,
            ai_justification=None, note=None, if_match_version=None,
        )
    assert candidate.exemption_code_id == ids["own_code_id"]


@pytest.mark.asyncio
async def test_create_manual_candidate_rejects_another_orgs_exemption_code(db_session: AsyncSession) -> None:
    async with db_session.begin():
        ids = await _seed_two_orgs_with_candidate(db_session)

    async with db_session.begin():
        await set_org(db_session, ids["org_a"])
        with pytest.raises(NotFoundError):
            await create_manual_candidate(
                db_session, ids["org_a"], ids["doc_id"], ids["user_a"],
                page_no=1, bbox={"x": 0, "y": 0, "w": 1, "h": 1},
                exemption_code_id=ids["other_orgs_code_id"], text="secret", note=None,
            )


@pytest.mark.asyncio
async def test_bulk_update_candidates_rejects_another_orgs_exemption_code(db_session: AsyncSession) -> None:
    async with db_session.begin():
        ids = await _seed_two_orgs_with_candidate(db_session)

    async with db_session.begin():
        await set_org(db_session, ids["org_a"])
        with pytest.raises(NotFoundError):
            await bulk_update_candidates(
                db_session, ids["org_a"], ids["doc_id"], ids["user_a"],
                action="approve", candidate_ids=[ids["cand_id"]], exemption_code_id=ids["other_orgs_code_id"],
            )


@pytest.mark.asyncio
async def test_search_and_redact_rejects_another_orgs_exemption_code(db_session: AsyncSession) -> None:
    async with db_session.begin():
        ids = await _seed_two_orgs_with_candidate(db_session)

    async with db_session.begin():
        await set_org(db_session, ids["org_a"])
        with pytest.raises(NotFoundError):
            await search_and_redact(
                db_session, ids["org_a"], ids["doc_id"], ids["user_a"],
                query="secret", is_pattern=False, scope="document", page_no=None,
                exemption_code_id=ids["other_orgs_code_id"],
            )


# ---------------------------------------------------------------------------
# 2. Audit hash-chain race
# ---------------------------------------------------------------------------


async def _create_org_for_audit(session: AsyncSession, org_id: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES (:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_id},
    )


@pytest.mark.asyncio
async def test_concurrent_audit_writes_for_the_same_org_never_fork_the_chain(db_engine) -> None:
    """Real concurrency, not simulated: N genuinely separate sessions/transactions
    write an audit event for the same org at (as close to) the same time. Before the
    pg_advisory_xact_lock fix, two writers could both read the same prev_hash and
    fork the chain — detected here as two rows sharing a prev_hash value."""
    org_id = "org_audit_race"
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async with session_factory() as setup_session, setup_session.begin():
        await _create_org_for_audit(setup_session, org_id)

    async def _write(n: int) -> None:
        async with session_factory() as session, session.begin():
            await set_org(session, org_id)
            await write_audit_event(
                session, org_id=org_id, actor_type="system", actor_id=f"writer-{n}",
                action="org.created", object_type="organization", object_id=org_id, metadata={"n": n},
            )

    await asyncio.gather(*[_write(n) for n in range(8)])

    async with session_factory() as session, session.begin():
        await set_org(session, org_id)
        result = await session.execute(select(AuditEvent.prev_hash, AuditEvent.hash).where(AuditEvent.org_id == org_id))
        rows = result.all()

    assert len(rows) == 8
    prev_hashes = [r.prev_hash for r in rows]
    # Exactly one head (prev_hash is NULL) and every other prev_hash value distinct —
    # a fork would show up as two rows sharing the same non-null prev_hash.
    non_null = [h for h in prev_hashes if h is not None]
    assert len(non_null) == len(set(non_null)), f"chain forked: duplicate prev_hash in {prev_hashes}"
    assert prev_hashes.count(None) == 1


# ---------------------------------------------------------------------------
# 3. legal_hold TOCTOU in purge_document_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_document_content_refuses_a_document_on_legal_hold(db_session: AsyncSession) -> None:
    org_id, doc_id, user_id = "org_toctou_a", new_id("doc"), "usr_toctou_a"
    async with db_session.begin():
        await set_org(db_session, org_id)
        await db_session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
                "plan, plan_status, settings) VALUES (:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
            ),
            {"id": org_id},
        )
        await db_session.execute(
            text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        db_session.add(
            Document(
                id=doc_id, org_id=org_id, filename="held.pdf", mime_type="application/pdf",
                source="upload", status="exported", uploaded_by=user_id, content_sha256="deadbeef",
                legal_hold=True,
            )
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        purged = await purge_document_content(db_session, org_id, doc_id, datetime.now(UTC))
    assert purged is False

    async with db_session.begin():
        await set_org(db_session, org_id)
        document = await db_session.get(Document, doc_id)
        assert document is not None
        assert document.content_sha256 == "deadbeef"  # untouched


# ---------------------------------------------------------------------------
# 4. Support-grant double-decision race
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_decide_grant_calls_only_one_wins(db_engine) -> None:
    org_id, admin_id = "org_grant_race", "usr_grant_race_admin"
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async with session_factory() as session, session.begin():
        await set_org(session, org_id)
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
                "plan, plan_status, settings) VALUES (:id, :id, :id, 'WA', 'other', 'starter', 'active', '{}')"
            ),
            {"id": org_id},
        )
        await session.execute(
            text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
            {"id": admin_id, "email": f"{admin_id}@example.com"},
        )
        grant_id = new_id("spgrt")
        await session.execute(
            text(
                "INSERT INTO support_grants (id, org_id, requested_by, reason, status, requested_at) VALUES "
                "(:id, :org_id, :admin_id, 'reason', 'requested', now())"
            ),
            {"id": grant_id, "org_id": org_id, "admin_id": admin_id},
        )

    results = []

    async def _decide(approve: bool) -> None:
        try:
            async with session_factory() as session, session.begin():
                await set_org(session, org_id)
                await decide_grant(session, org_id, grant_id, admin_id, approve=approve)
            results.append("ok")
        except ApiError:
            results.append("conflict")

    await asyncio.gather(_decide(True), _decide(False))

    assert sorted(results) == ["conflict", "ok"], f"expected exactly one winner, got {results}"


# ---------------------------------------------------------------------------
# 5. Invoice audit event for any event carrying invoice data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoice_data_is_audited_even_for_an_unrecognized_event_type(db_session: AsyncSession) -> None:
    from app.billing.provider import BillingEvent, BillingInvoice

    org_id = "org_invoice_audit"
    async with db_session.begin():
        await set_org(db_session, org_id)
        await db_session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
                "plan, plan_status, settings, stripe_customer_id) VALUES "
                "(:id, :id, :id, 'WA', 'other', 'starter', 'active', '{}', 'cus_x')"
            ),
            {"id": org_id},
        )

    invoice = BillingInvoice(provider_invoice_id="in_unknown_type", period="2026-08", status="open")
    async with db_session.begin():
        await set_org(db_session, org_id)
        await _apply_billing_event(db_session, BillingEvent(type="some.future.event", org_id=org_id, invoice=invoice))

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(
            text("SELECT count(*) FROM audit_events WHERE org_id = :id AND action = 'billing.invoice_recorded'"),
            {"id": org_id},
        )
        assert result.scalar_one() == 1


# ---------------------------------------------------------------------------
# 6. Settings startup guard against insecure secrets outside local
# ---------------------------------------------------------------------------


def test_settings_rejects_default_secrets_outside_local() -> None:
    from app.core.config import Settings

    with pytest.raises(Exception, match="certificate_signing_key"):
        Settings(env="prod", database_url="postgresql+asyncpg://x:x@localhost/x")


def test_settings_allows_overridden_secrets_outside_local() -> None:
    from app.core.config import Settings

    settings = Settings(
        env="prod", database_url="postgresql+asyncpg://x:x@localhost/x",
        certificate_signing_key="a-real-secret", internal_cron_secret="another-real-secret",
    )
    assert settings.env == "prod"


def test_settings_local_env_is_never_blocked() -> None:
    from app.core.config import Settings

    settings = Settings(env="local")
    assert settings.env == "local"


# ---------------------------------------------------------------------------
# 7. Zip-slip in the offboarding package
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_offboarding_package_flattens_a_malicious_filename(db_session: AsyncSession) -> None:
    import zipfile
    from io import BytesIO

    from app.services.offboarding_service import generate_offboarding_package
    from app.storage import get_store

    org_id, doc_id, user_id = "org_zipslip", new_id("doc"), "usr_zipslip"
    original_key = f"originals/{doc_id}"
    get_store().put(org_id, original_key, b"%PDF-fake")

    async with db_session.begin():
        await set_org(db_session, org_id)
        await db_session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
                "plan, plan_status, settings) VALUES (:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
            ),
            {"id": org_id},
        )
        await db_session.execute(
            text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        db_session.add(
            Document(
                id=doc_id, org_id=org_id, filename="../../evil.pdf", mime_type="application/pdf",
                source="upload", status="uploaded", uploaded_by=user_id, s3_key_original=original_key,
                content_sha256="deadbeef",
            )
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        package = await generate_offboarding_package(db_session, org_id)

    with zipfile.ZipFile(BytesIO(package)) as zf:
        names = zf.namelist()
        assert any(n.endswith("evil.pdf") and ".." not in n for n in names), names
        assert not any(".." in n for n in names), names


# ---------------------------------------------------------------------------
# 8. LocalFilesystemStore path-traversal hardening
# ---------------------------------------------------------------------------


def test_local_filesystem_store_blocks_traversal_and_absolute_keys(tmp_path) -> None:
    from app.storage.local import LocalFilesystemStore

    store = LocalFilesystemStore(str(tmp_path))
    store.put("org_a", "originals/doc1", b"hello")
    assert store.get("org_a", "originals/doc1") == b"hello"

    for bad_key in ["..", "/etc/passwd", "../../etc/passwd", "a/../../b"]:
        with pytest.raises(ValueError):
            store.put("org_a", bad_key, b"evil")
