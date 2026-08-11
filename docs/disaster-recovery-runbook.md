# Disaster Recovery Runbook

**Status:** Drafted and drill-tested against local infrastructure (see [Restore drill](#restore-drill) below). **Not yet exercised against real AWS infrastructure** — see [Known gaps](#known-gaps--prerequisites) before treating this as production-ready. Owner: Engineering. Review cadence: quarterly, or after any material change to `infra/modules/aurora` or `infra/modules/storage`.

## 1. Scope

Covers recovery of the two stateful systems RedactProof cannot function without:

- **Aurora PostgreSQL** — all relational data: orgs, users, documents, redaction candidates, manifests, rules, usage records, and the append-only audit trail.
- **Content storage (S3 + per-org KMS)** — original uploads, page previews, and export artifacts.

Out of scope for this runbook: Cognito (AWS-managed, has its own SLA and is not something we back up), CloudFront/edge config (redeployed from Terraform, not "restored"), and third-party state (Stripe, IdP-federated identities) — those recover by re-establishing webhooks/config, not by a data restore.

## 2. Objectives

| Metric | Target | Backed by |
|---|---|---|
| RPO (Recovery Point Objective) | ≤ 24 hours | Aurora automated backups (continuous, replayable to any point within the retention window) + S3 versioning on every write |
| RTO (Recovery Time Objective) | ≤ 8 hours | Scripted restore procedure (below) + a new Aurora cluster from snapshot/PITR, sized identically to production |

These are `specs/10-build-plan.md` Phase 6's stated targets. Aurora's PITR window is configured for 35 days in production (`specs/08-security-compliance.md`; `infra/modules/aurora`'s `backup_retention_days` variable — see [Known gaps](#known-gaps--prerequisites) for its current default), so the real constraint on RPO is backup *frequency* (continuous, via WAL) rather than retention.

## 3. Failure scenarios this runbook covers

1. **Single-tenant or single-document corruption/deletion.** A bug, bad migration, or operator error damages a bounded set of rows or objects. Recovery: PITR restore to a *scratch* cluster at a timestamp before the damage, extract just the affected rows/objects, apply them back — never a blanket restore-over-production for a bounded incident.
2. **Accidental mass deletion** (e.g., a runaway retention-sweep bug, a bad `DELETE`/`removeAll`). Recovery: PITR restore to a scratch cluster at the last known-good timestamp; diff against production to identify exactly what's missing; backfill.
3. **Full AZ or region outage.** Aurora is a single-region, multi-AZ cluster today (see gap below on cross-region). Recovery: fail over to the standby AZ (automatic for Aurora within a region) or, for a full regional outage, restore from the latest automated snapshot into the secondary region once cross-region snapshot copy is enabled (not yet — see gap).
4. **Compromised credentials / destructive insider or attacker action.** Recovery: rotate every credential (DB master, per-org KMS keys stay intact — they're not the compromised secret in this scenario — but application-level API keys/JWT signing keys must rotate), then treat as scenario 1 or 2 depending on blast radius, PLUS a mandatory audit-chain verification pass (`app.services.audit_service.verify_chain`, already run nightly per `specs/08-security-compliance.md`) across every org to confirm the audit trail itself wasn't tampered with.

## 4. Roles

- **Incident commander** (on-call engineer, escalating to eng lead) declares a DR event and decides scope (bounded restore vs. full cluster restore).
- **Executor** (any engineer with the runbook) runs the restore procedure below. On a bounded restore, the executor works from a scratch cluster and never touches production directly until the incident commander approves the backfill plan.
- **Approver** (eng lead or above) signs off before any restore touches production data, and before any legal-hold-affected org's data is touched at all (see `specs/08-security-compliance.md` — legal hold blocks destructive operations; a restore that would *overwrite* legal-hold-affected rows needs explicit approval, not just automated re-play).

## 5. Restore procedure — Postgres

1. **Identify the target recovery point.** From Aurora's automated backups, pick either the latest snapshot or a specific PITR timestamp (just before the incident).
2. **Restore to a NEW cluster, never in place.** `aws rds restore-db-cluster-to-point-in-time` (PITR) or `restore-db-cluster-from-snapshot`, targeting a fresh cluster identifier — production stays untouched and reachable throughout.
3. **Point a scratch app instance at the new cluster** (same app image, `DATABASE_URL` overridden) to run Alembic's current head migration if the restored snapshot predates it, then to run the verification checklist below.
4. **Verify before cutover** (see checklist §6). Do not promote the restored cluster, or copy data out of it into production, until every check passes.
5. **Cutover or backfill:**
   - *Full restore* (regional loss, total corruption): repoint `DATABASE_URL` at the restored cluster, redeploy, done. RTO clock stops here.
   - *Bounded restore* (scenario 1/2): extract only the affected rows from the scratch cluster (`pg_dump --table=... --data-only`, or a targeted `INSERT ... SELECT` over `dblink`/`postgres_fdw`) and replay them into production inside a transaction, with an audit event recording the backfill itself.
6. **Decommission the scratch cluster** once cutover/backfill is confirmed — it held a full copy of tenant data and must not be left running.

### A privilege note that matters here

`audit_events` (and every other append-only table) runs with `FORCE ROW LEVEL SECURITY` — deliberately, so not even the table owner can bypass tenant isolation from inside the app (see `CLAUDE.md` invariant #4). **The application's own database role cannot `pg_dump`/`pg_restore` those tables** — and it shouldn't be able to. In production this is a non-issue: Aurora's snapshot/PITR mechanism operates at the storage/WAL level, entirely below where RLS applies. Anywhere this runbook's procedure drops to a logical `pg_dump`/`pg_restore` (as the drill script does, for lack of a real Aurora account), it must run as an actual Postgres superuser or a role granted `BYPASSRLS` — a backup/DR service account, never the app's own constrained role. Don't "fix" an RLS permission error here by weakening `audit_events`'s policy; fix it by using the right role for the backup tooling.

## 6. Post-restore verification checklist

Run against the restored/scratch cluster before any cutover or backfill:

- [ ] Alembic is at `head` (`alembic current` matches `alembic heads`).
- [ ] Row counts for a sample of tenant tables are consistent with the pre-incident baseline (not necessarily identical for a PITR restore short of the incident, but never *zero* for an org known to have data).
- [ ] RLS still enforces tenant isolation: as a plain app-role session with `app.org_id` set to org A, querying org B's data returns nothing.
- [ ] A sample of `redaction_candidates.display_text_encrypted` decrypts correctly via `app.crypto.envelope.get_cipher()` for a spot-checked org — proves the per-org KMS/envelope-encryption path survived the restore, not just ciphertext bytes.
- [ ] `app.services.audit_service.verify_chain()` returns `True` for every org touched by the incident — the hash chain itself wasn't corrupted by the restore.
- [ ] A spot-checked document's stored content (S3/content store) hashes to the same `content_sha256` recorded on its `documents` row.
- [ ] Usage records for the recovery window are neither lost nor duplicated (cross-check `usage_records` against the billing period's expected count if a billing cycle is mid-flight — a restore must never cause double-billing or under-billing).

## 7. Restore procedure — content storage

Production: S3 versioning is enabled on the content bucket (`infra/modules/storage`), so an accidentally deleted/overwritten object recovers via `aws s3api list-object-versions` + `restore-object`/copy-the-prior-version-back, scoped to the affected org's key prefix. A full-bucket-loss scenario recovers from cross-region replication — **not yet implemented in Terraform, see gap below**; until it is, a full-bucket loss has no S3-side recovery path beyond whatever AWS-side durability guarantees apply to the bucket itself.

Per-org KMS keys (`infra/modules/storage`'s `per_org_kms_management` IAM policy) are created at runtime, one per org. A key's own deletion is a 30-day scheduled window (`kms:ScheduleKeyDeletion`) — recoverable within that window by canceling the deletion; **not** recoverable after it completes, by design (this is the intended crypto-shred mechanism for org offboarding, per `specs/08-security-compliance.md`). Never restore an offboarded org's KMS key or content — that would defeat crypto-shred's entire purpose.

## 8. Restore drill

`api/scripts/dr_restore_drill.py` scripts steps 1–6 of the Postgres procedure (plus an analogous content-storage backup/loss/restore) end-to-end against a throwaway "drill" database and storage root — never against a real dev/test/production database.

```bash
cd api && source .venv/bin/activate
TEST_DATABASE_URL=postgresql+asyncpg://redactproof:redactproof@<host>:<port>/<db> \
  python -m scripts.dr_restore_drill
```

It seeds a small known dataset (an org, a document, a redaction candidate with envelope-encrypted content, a usage record, and a two-event audit chain), takes a backup, **actually drops the database and deletes the storage root** (a real destructive loss, not a simulated one), restores from the backup, and asserts the restored data is byte-for-byte identical to the pre-loss fingerprint: row counts, the decrypted candidate text, the audit chain's head hash, and the stored file's bytes.

**What this proves:** the restore *procedure* — backup, catastrophic loss, restore, integrity verification — is scripted and actually works, including the RLS/privilege-separation detail in §5. **What it does not prove:** anything about real AWS Aurora PITR or S3 cross-region failover, at any scale — there is no AWS account behind this drill. The elapsed times it prints are a mechanics check, not an RTO benchmark; the real 8-hour target is sized for a production-scale restore this drill's small seeded dataset can't exercise.

Requires a Postgres role with `CREATEDB` (for the app role used to own the drill database) and a way to run `pg_dump`/`pg_restore`/`createdb`/`dropdb` as an actual superuser or `BYPASSRLS` role — locally, that's typically the OS user connecting over the Unix socket via peer auth (override with `DR_DRILL_ADMIN_USER` if your local Postgres superuser has a different name than your OS user).

Run this drill quarterly at minimum, and after any migration that touches an append-only or RLS-forced table.

## 9. Known gaps & prerequisites

Being direct about what's *not* actually true yet, so this runbook isn't mistaken for a completed DR posture:

- **No cross-region S3 replication in Terraform yet.** `specs/08-security-compliance.md` commits to "S3 versioning + replication us-east-1→us-west-2," but `infra/modules/storage` only configures versioning + per-org KMS today — no `aws_s3_bucket_replication_configuration` resource exists. A full-bucket loss in the primary region currently has no S3-side DR path. This is the single highest-priority gap to close before this runbook can claim regional-failure coverage.
- **`backup_retention_days` defaults to 7, not the spec's 35-day production PITR window.** `infra/modules/aurora/variables.tf` — needs an explicit override in whatever prod `.tfvars` eventually exists.
- **No production environment exists.** `infra/envs/` has only `dev/`. Nothing in this repo has been `terraform apply`'d against a real AWS account. Every claim in this runbook about Aurora/S3 behavior is based on documented AWS behavior and the Terraform module definitions, not observed behavior in this system's own infrastructure.
- **This runbook itself has never been drilled against real AWS.** The scripted drill (§8) proves the procedure's *logic* against local Postgres + local filesystem storage. A real quarterly drill against a real Aurora snapshot restore is a prerequisite for calling this "verified" in the sense `specs/10-build-plan.md`'s AC intends.
- **No on-call rotation or alarm tuning exists yet** (separate Phase 6 build-plan item) — so "declare a DR event" in §4 currently has no paging path behind it; it's a manual, best-effort escalation until that's built.

## 10. Drill log

Record every drill run here — real or scripted — so drift between "we think this works" and "we last proved this works" stays visible.

| Date | Run by | Type (scripted / real AWS) | Result | Notes |
|---|---|---|---|---|
| _(fill in at next drill)_ | | | | |
