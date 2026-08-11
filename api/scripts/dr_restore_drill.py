"""Phase 6 build-plan item: "disaster-recovery runbook + restore drill (RPO <= 24h,
RTO <= 8h verified)." Companion script to docs/disaster-recovery-runbook.md — read that
document first; this exercises its Postgres + content-storage restore procedure
end-to-end against a throwaway "drill" database and storage root, never against
`redactproof` or `redactproof_test`.

What this does and does not prove: there is no real AWS account in this environment, so
this can't exercise an actual Aurora point-in-time-restore or S3 cross-region failover.
What it DOES prove, against the same primitives (pg_dump/pg_restore, a filesystem content
store) one level of abstraction below Aurora snapshots / S3 versioning: the *procedure* —
backup, catastrophic loss, restore, integrity verification — actually works, is scripted
(not tribal knowledge), and completes in seconds against a small dataset. The runbook's
RTO target is sized for a real multi-TB production restore; this is the mechanics check,
not a timing benchmark.

Usage: `python -m scripts.dr_restore_drill [--keep-on-failure]` from /api with the venv
active and a reachable Postgres server (TEST_DATABASE_URL, else DATABASE_URL, else the
local dev default).
"""

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.audit_event import AuditEvent  # noqa: F401 — registers the table on Base.metadata
from app.models.document import Document
from app.models.manifest import Manifest
from app.models.redaction_candidate import RedactionCandidate
from app.models.usage_record import UsageRecord
from app.services.audit_service import verify_chain, write_audit_event
from app.storage.local import LocalFilesystemStore

DRILL_ORG_ID = "org_dr_drill"
DRILL_USER_ID = "usr_dr_drill"
DRILL_DOC_ID = "doc_dr_drill"
SAMPLE_CONTENT = b"%PDF-1.4 DR-drill sample document content, not a real PDF.\n"


def _source_database_url() -> str:
    return (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql+asyncpg://redactproof:redactproof@localhost:5432/redactproof_test"
    )


def _split(url: str) -> tuple[str, str, str, str, str, str]:
    parsed = urlsplit(url.replace("+asyncpg", ""))
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    user = parsed.username or "postgres"
    password = parsed.password or ""
    source_db = parsed.path.lstrip("/")
    drill_db = f"{source_db}_dr_drill"
    return host, port, user, password, source_db, drill_db


def _admin_pg_env(port: str) -> dict:
    """`audit_events` (and other append-only tables) run with FORCE ROW LEVEL SECURITY —
    deliberately, so even the table owner can't bypass tenant isolation from inside the
    app (CLAUDE.md invariant #4). That means the app's own `redactproof` role genuinely
    cannot pg_dump/pg_restore those tables — and it shouldn't be able to. In real
    production this is a non-issue: Aurora's automated backups/PITR operate at the
    storage/WAL level, entirely below the SQL layer RLS governs. The equivalent here is
    running pg_dump/pg_restore/createdb/dropdb as an actual Postgres superuser (a backup
    service account, never the app's own role) via the local Unix socket's peer auth —
    DR_DRILL_ADMIN_USER overrides the default (the current OS user, which this drill
    assumes has superuser on the target instance; see docs/disaster-recovery-runbook.md)."""
    env = os.environ.copy()
    env.pop("PGHOST", None)  # let it default to the Unix socket, not TCP, for peer auth
    env.pop("PGPASSWORD", None)
    env["PGPORT"] = port
    env["PGUSER"] = os.environ.get("DR_DRILL_ADMIN_USER", os.environ.get("USER", "postgres"))
    return env


def _app_pg_env(host: str, port: str, user: str, password: str) -> dict:
    env = os.environ.copy()
    env["PGHOST"] = host
    env["PGPORT"] = port
    env["PGUSER"] = user
    if password:
        env["PGPASSWORD"] = password
    return env


def _run(cmd: list[str], env: dict, *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=env, capture_output=True, text=True, check=check)


def _drill_url(host: str, port: str, user: str, password: str, drill_db: str) -> str:
    auth = f"{user}:{password}" if password else user
    return f"postgresql+asyncpg://{auth}@{host}:{port}/{drill_db}"


async def _seed_drill_dataset(drill_url: str, storage_root: Path) -> dict:
    """A small, known-shape dataset covering every restore-integrity check the runbook
    calls for: relational rows (with the FK graph a real org has), envelope-encrypted
    content, and an audit hash chain — plus one file in the content store."""
    engine = create_async_engine(drill_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    store = LocalFilesystemStore(str(storage_root))
    cipher = get_cipher()

    async with session_factory() as session, session.begin():
        await session.execute(text("SELECT set_config('app.org_id', :org_id, true)"), {"org_id": DRILL_ORG_ID})
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
                "plan, plan_status, settings) VALUES "
                "(:id, 'DR Drill Org', 'dr-drill-org', 'WA', 'other', 'pilot', 'trialing', '{}')"
            ),
            {"id": DRILL_ORG_ID},
        )
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, status) VALUES "
                "(:id, 'dr-drill@example.com', 'DR Drill User', 'active')"
            ),
            {"id": DRILL_USER_ID},
        )

        original_key = f"originals/{DRILL_DOC_ID}"
        store.put(DRILL_ORG_ID, original_key, SAMPLE_CONTENT)

        session.add(
            Document(
                id=DRILL_DOC_ID, org_id=DRILL_ORG_ID, filename="drill.pdf", mime_type="application/pdf",
                source="upload", status="ready_for_review", uploaded_by=DRILL_USER_ID,
                s3_key_original=original_key, content_sha256="drillsha",
            )
        )
        session.add(Manifest(id=new_id("man"), org_id=DRILL_ORG_ID, doc_id=DRILL_DOC_ID, version=1))
        await session.flush()

        session.add(
            RedactionCandidate(
                id=new_id("cand"), org_id=DRILL_ORG_ID, doc_id=DRILL_DOC_ID, page_no=1,
                bbox={"x": 0, "y": 0, "w": 10, "h": 10},
                display_text_encrypted=cipher.encrypt(DRILL_ORG_ID, "drill-secret-value"),
                origin="manual", confidence="n/a-manual", state="suggested",
            )
        )
        session.add(
            UsageRecord(
                id=new_id("use"), org_id=DRILL_ORG_ID, metric="pages_processed", quantity=1,
                doc_id=DRILL_DOC_ID, job_id=None, occurred_at=datetime.now(UTC), billing_period="2026-08",
            )
        )
        await write_audit_event(
            session, org_id=DRILL_ORG_ID, actor_type="system", actor_id=DRILL_USER_ID,
            action="document.uploaded", object_type="document", object_id=DRILL_DOC_ID, metadata={"drill": True},
        )
        await write_audit_event(
            session, org_id=DRILL_ORG_ID, actor_type="system", actor_id=DRILL_USER_ID,
            action="document.ready_for_review", object_type="document", object_id=DRILL_DOC_ID, metadata={"drill": True},
        )

    await engine.dispose()
    return await _fingerprint(drill_url, storage_root)


async def _fingerprint(drill_url: str, storage_root: Path) -> dict:
    """Everything the runbook's verification step checks: row counts across the FK graph,
    the plaintext recovered from encrypted content (proves the KMS/cipher path survives,
    not just ciphertext bytes), the audit hash chain's validity AND its exact head hash
    (proves it's the SAME chain, not just a structurally-valid one), and the stored
    document's own content hash."""
    engine = create_async_engine(drill_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    store = LocalFilesystemStore(str(storage_root))
    cipher = get_cipher()

    async with session_factory() as session, session.begin():
        await session.execute(text("SELECT set_config('app.org_id', :org_id, true)"), {"org_id": DRILL_ORG_ID})
        counts = {}
        for table in ("documents", "manifests", "redaction_candidates", "usage_records", "audit_events"):
            counts[table] = (
                await session.execute(text(f"SELECT count(*) FROM {table} WHERE org_id = :org_id"), {"org_id": DRILL_ORG_ID})
            ).scalar_one()

        candidate_text = cipher.decrypt(
            DRILL_ORG_ID,
            (
                await session.execute(
                    text("SELECT display_text_encrypted FROM redaction_candidates WHERE doc_id = :id"),
                    {"id": DRILL_DOC_ID},
                )
            ).scalar_one(),
        )
        chain_ok = await verify_chain(session, DRILL_ORG_ID)
        head_hash = (
            await session.execute(
                text("SELECT hash FROM audit_events WHERE org_id = :org_id ORDER BY id DESC LIMIT 1"),
                {"org_id": DRILL_ORG_ID},
            )
        ).scalar_one()

    await engine.dispose()
    stored_bytes = store.get(DRILL_ORG_ID, f"originals/{DRILL_DOC_ID}")

    return {
        "row_counts": counts,
        "decrypted_candidate_text": candidate_text,
        "audit_chain_valid": chain_ok,
        "audit_chain_head_hash": head_hash,
        "stored_content_matches": stored_bytes == SAMPLE_CONTENT,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-on-failure", action="store_true", help="leave the drill DB/storage in place for post-mortem inspection if a step fails")
    args = parser.parse_args()

    host, port, user, password, source_db, drill_db = _split(_source_database_url())
    env = _admin_pg_env(port)
    app_env = _app_pg_env(host, port, user, password)
    drill_url = _drill_url(host, port, user, password, drill_db)

    tmp_dir = Path(tempfile.mkdtemp(prefix="dr-drill-"))
    dump_file = tmp_dir / "drill.dump"
    storage_root = tmp_dir / "storage"
    storage_backup = tmp_dir / "storage-backup"

    print(f"== DR restore drill == source={source_db} drill_db={drill_db} host={host}:{port}")

    def cleanup() -> None:
        _run(["dropdb", "--if-exists", drill_db], env, check=False)
        shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        print("-- 1/6 provisioning a fresh drill database + storage root --")
        _run(["dropdb", "--if-exists", drill_db], env)
        # -O: owned by the app role itself, so it has CREATE on its own public schema
        # (Postgres 15+ no longer grants that to PUBLIC by default) — matches how the
        # real redactproof/redactproof_test databases are already owned.
        _run(["createdb", "-O", user, drill_db], env)
        subprocess.run(
            ["alembic", "upgrade", "head"],
            env={**app_env, "DATABASE_URL": drill_url},
            cwd=Path(__file__).resolve().parent.parent,
            check=True,
            capture_output=True,
            text=True,
        )

        print("-- 2/6 seeding a known dataset (org, doc, candidate, usage, audit chain) --")
        pre_loss_fingerprint = asyncio.run(_seed_drill_dataset(drill_url, storage_root))
        assert pre_loss_fingerprint["audit_chain_valid"], "seed data's own audit chain is invalid — drill setup is broken"

        print("-- 3/6 taking a backup (this is the most recent recovery point once taken) --")
        backup_taken_at = time.monotonic()
        _run(["pg_dump", "-Fc", "-f", str(dump_file), drill_db], env)
        shutil.copytree(storage_root, storage_backup)

        print("-- 4/6 simulating catastrophic loss (drop database + delete storage root) --")
        _run(["dropdb", drill_db], env)
        shutil.rmtree(storage_root)

        print("-- 5/6 restoring from backup (RTO mechanics timer starts now) --")
        restore_started_at = time.monotonic()
        _run(["createdb", "-O", user, drill_db], env)
        _run(["pg_restore", "-d", drill_db, str(dump_file)], env)
        shutil.copytree(storage_backup, storage_root)
        restore_elapsed = time.monotonic() - restore_started_at

        print("-- 6/6 verifying restored data matches the pre-loss fingerprint exactly --")
        post_restore_fingerprint = asyncio.run(_fingerprint(drill_url, storage_root))

        mismatches = [
            key for key in pre_loss_fingerprint
            if pre_loss_fingerprint[key] != post_restore_fingerprint[key]
        ]
        if mismatches:
            print(f"FAIL — mismatched fields after restore: {mismatches}", file=sys.stderr)
            print(f"  before: {pre_loss_fingerprint}", file=sys.stderr)
            print(f"  after:  {post_restore_fingerprint}", file=sys.stderr)
            if not args.keep_on_failure:
                cleanup()
            return 1

        backup_age = time.monotonic() - backup_taken_at
        print(
            "PASS — restore reproduced the pre-loss dataset exactly "
            "(row counts, decrypted content, audit chain head hash, stored file bytes).\n"
            f"  backup->loss elapsed: {backup_age:.2f}s (RPO proxy — real target: <= 24h backup cadence)\n"
            f"  restore procedure elapsed: {restore_elapsed:.2f}s (RTO mechanics proxy — real target: <= 8h "
            "for a production-sized restore; this measures the scripted procedure, not "
            "production-scale timing)"
        )
        cleanup()
        return 0
    except Exception as exc:  # noqa: BLE001 — top-level drill runner: report and clean up rather than a raw traceback
        print(f"FAIL — drill raised: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            print(f"  stdout: {exc.stdout}\n  stderr: {exc.stderr}", file=sys.stderr)
        if not args.keep_on_failure:
            cleanup()
        return 1


if __name__ == "__main__":
    sys.exit(main())
