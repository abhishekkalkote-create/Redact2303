"""Phase 1: exemption library/codes, requests, documents, processing_jobs, manifests,
redaction_candidates, review_actions, export_artifacts, audit_events, usage_records + RLS.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DB_ROLE = "redactproof"  # local dev role; prod uses the RDS-managed app role — see api/.env.example


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING (org_id = current_setting('app.org_id', true)) "
        f"WITH CHECK (org_id = current_setting('app.org_id', true))"
    )


def _append_only(table: str) -> None:
    """specs/03-data-model.md: append-only / immutable tables. REVOKE works against the
    table owner too — ownership only grants DDL (ALTER/DROP/GRANT) unconditionally; DML
    privileges (SELECT/INSERT/UPDATE/DELETE) are ordinary ACL grants that can be revoked
    even from the owning role. Verified empirically, not assumed (see project memory)."""
    op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM {DB_ROLE}")


def upgrade() -> None:
    # --- Exemption taxonomy (specs/06-exemption-taxonomy.md) ---
    op.create_table(
        "exemption_library",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("code", sa.String, nullable=False),
        sa.Column("level", sa.String, nullable=False),
        sa.Column("state", sa.String(2), nullable=True),
        sa.Column("label", sa.String, nullable=False),
        sa.Column("statute_citation", sa.String, nullable=True),
        sa.Column("description", sa.String, nullable=True),
        sa.Column("guidance_url", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("level in ('federal','state')", name="ck_exemption_library_level"),
        sa.CheckConstraint("status in ('active','archived')", name="ck_exemption_library_status"),
    )

    op.create_table(
        "exemption_codes",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("library_id", sa.String, sa.ForeignKey("exemption_library.id"), nullable=True),
        sa.Column("code", sa.String, nullable=False),
        sa.Column("label", sa.String, nullable=False),
        sa.Column("statute_citation", sa.String, nullable=True),
        sa.Column("description", sa.String, nullable=True),
        sa.Column("guidance_url", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('active','archived')", name="ck_exemption_codes_status"),
    )
    op.create_index("ix_exemption_codes_org_id", "exemption_codes", ["org_id"])
    _rls("exemption_codes")

    # --- Requests ---
    op.create_table(
        "requests",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reference_no", sa.String, nullable=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="open"),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assignee_id", sa.String, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('open','in_review','complete','closed')", name="ck_requests_status"),
    )
    op.create_index("ix_requests_org_id", "requests", ["org_id"])
    _rls("requests")

    # --- Documents & pages ---
    op.create_table(
        "documents",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.String, sa.ForeignKey("requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filename", sa.String, nullable=False),
        sa.Column("mime_type", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=False, server_default="upload"),
        sa.Column("status", sa.String, nullable=False, server_default="uploaded"),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("ocr_used", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("rule_set_version_ids", sa.ARRAY(sa.String), nullable=True),
        sa.Column("assignee_id", sa.String, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by", sa.String, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("s3_key_original", sa.String, nullable=True),
        sa.Column("content_sha256", sa.String, nullable=True),
        sa.Column("error", sa.JSON, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source in ('upload','email','batch')", name="ck_documents_source"),
        sa.CheckConstraint(
            "status in ('uploaded','scanning','queued','extracting','detecting','ready_for_review',"
            "'in_review','review_complete','awaiting_approval','approved','exported','error','deleted')",
            name="ck_documents_status",
        ),
    )
    op.create_index("ix_documents_org_id", "documents", ["org_id"])
    _rls("documents")

    op.create_table(
        "document_pages",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("doc_id", sa.String, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_no", sa.Integer, nullable=False),
        sa.Column("s3_key_preview", sa.String, nullable=True),
        sa.Column("width", sa.Numeric, nullable=True),
        sa.Column("height", sa.Numeric, nullable=True),
        sa.Column("rotation", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ocr_confidence", sa.Numeric, nullable=True),
        sa.Column("has_text_layer", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_pages_doc_id", "document_pages", ["doc_id"])
    op.create_index("ix_document_pages_org_id", "document_pages", ["org_id"])
    _rls("document_pages")

    # --- Processing jobs ---
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("doc_id", sa.String, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="queued"),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.JSON, nullable=True),
        sa.Column("metrics", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "type in ('intake','extract','detect','export','verify','rule_extraction')",
            name="ck_processing_jobs_type",
        ),
        sa.CheckConstraint(
            "status in ('queued','running','succeeded','failed','dead')", name="ck_processing_jobs_status"
        ),
    )
    op.create_index("ix_processing_jobs_org_id", "processing_jobs", ["org_id"])
    op.create_index("ix_processing_jobs_doc_id", "processing_jobs", ["doc_id"])
    _rls("processing_jobs")

    # --- Manifests ---
    op.create_table(
        "manifests",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("doc_id", sa.String, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("snapshot_s3_key", sa.String, nullable=True),
        sa.Column("completeness", sa.JSON, nullable=False, server_default='{"pages_viewed": [], "low_conf_resolved": false}'),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_manifests_org_id", "manifests", ["org_id"])
    _rls("manifests")

    # --- Redaction candidates ---
    op.create_table(
        "redaction_candidates",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("doc_id", sa.String, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_no", sa.Integer, nullable=False),
        sa.Column("bbox", sa.JSON, nullable=False),
        sa.Column("text_span", sa.JSON, nullable=True),
        sa.Column("display_text_encrypted", sa.String, nullable=False),
        sa.Column("origin", sa.String, nullable=False),
        sa.Column("source_rule_key", sa.String, nullable=True),
        sa.Column("source_rule_version", sa.String, nullable=True),
        sa.Column("recurrence_group_id", sa.String, nullable=True),
        sa.Column("exemption_code_id", sa.String, sa.ForeignKey("exemption_codes.id"), nullable=True),
        sa.Column("ai_justification", sa.String, nullable=True),
        sa.Column("confidence", sa.String, nullable=False),
        sa.Column("state", sa.String, nullable=False, server_default="suggested"),
        sa.Column("detector_versions", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "origin in ('deterministic','llm','manual','search_apply')", name="ck_candidates_origin"
        ),
        sa.CheckConstraint(
            "confidence in ('high','medium','low','n/a-manual')", name="ck_candidates_confidence"
        ),
        sa.CheckConstraint(
            "state in ('suggested','approved','rejected','modified')", name="ck_candidates_state"
        ),
        # specs/03-data-model.md: "redaction_candidates.state = approved requires
        # exemption_code_id NOT NULL (DB CHECK)."
        sa.CheckConstraint(
            "state != 'approved' or exemption_code_id is not null", name="ck_candidates_approved_needs_code"
        ),
    )
    op.create_index("ix_candidates_org_id", "redaction_candidates", ["org_id"])
    op.create_index("ix_candidates_doc_id", "redaction_candidates", ["doc_id"])
    _rls("redaction_candidates")

    # --- Review actions (append-only) ---
    op.create_table(
        "review_actions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("doc_id", sa.String, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_id", sa.String, sa.ForeignKey("redaction_candidates.id"), nullable=True),
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("note", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "action in ('approve','reject','modify','create','bulk_approve','complete_review',"
            "'approve_doc','return_doc','reopen')",
            name="ck_review_actions_action",
        ),
    )
    op.create_index("ix_review_actions_org_id", "review_actions", ["org_id"])
    op.create_index("ix_review_actions_doc_id", "review_actions", ["doc_id"])
    _rls("review_actions")
    _append_only("review_actions")

    # --- Export artifacts (immutable) ---
    op.create_table(
        "export_artifacts",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("doc_id", sa.String, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("request_id", sa.String, sa.ForeignKey("requests.id", ondelete="CASCADE"), nullable=True),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("s3_key", sa.String, nullable=False),
        sa.Column("sha256", sa.String, nullable=False),
        sa.Column("manifest_version", sa.Integer, nullable=False),
        sa.Column("integrity_check", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "type in ('clean_pdf','annotated_pdf','exemption_log_pdf','exemption_log_csv',"
            "'exemption_log_json','certificate_pdf')",
            name="ck_export_artifacts_type",
        ),
    )
    op.create_index("ix_export_artifacts_org_id", "export_artifacts", ["org_id"])
    _rls("export_artifacts")
    _append_only("export_artifacts")

    # --- Audit events (append-only, hash chain; content-free, no CASCADE FKs) ---
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, nullable=False),
        sa.Column("actor_type", sa.String, nullable=False),
        sa.Column("actor_id", sa.String, nullable=True),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("object_type", sa.String, nullable=False),
        sa.Column("object_id", sa.String, nullable=False),
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("prev_hash", sa.String, nullable=True),
        sa.Column("hash", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("actor_type in ('user','system','platform_admin')", name="ck_audit_events_actor_type"),
    )
    op.create_index("ix_audit_events_org_id", "audit_events", ["org_id"])
    _rls("audit_events")
    _append_only("audit_events")

    # --- Usage records ---
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("doc_id", sa.String, sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("job_id", sa.String, sa.ForeignKey("processing_jobs.id"), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("billing_period", sa.String(7), nullable=False),
        sa.Column("reported_to_billing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("job_id", "metric", name="uq_usage_job_metric"),
        sa.CheckConstraint(
            "metric in ('pages_processed','ocr_pages','llm_pages','documents','exports','seats_active')",
            name="ck_usage_records_metric",
        ),
    )
    op.create_index("ix_usage_records_org_id", "usage_records", ["org_id"])
    _rls("usage_records")


def downgrade() -> None:
    op.drop_table("usage_records")
    op.drop_table("audit_events")
    op.drop_table("export_artifacts")
    op.drop_table("review_actions")
    op.drop_table("redaction_candidates")
    op.drop_table("manifests")
    op.drop_table("processing_jobs")
    op.drop_table("document_pages")
    op.drop_table("documents")
    op.drop_table("requests")
    op.drop_table("exemption_codes")
    op.drop_table("exemption_library")
