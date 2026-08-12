# On-Call Runbook

**Status:** Alarms are written and `terraform validate`-clean; **no rotation, no paging
vendor, and no real AWS deployment exist yet** — see [Known gaps](#known-gaps--prerequisites).
This document is the policy this team commits to running once those exist, not a
description of something operating today. Owner: Engineering. Review cadence: quarterly,
alongside `docs/disaster-recovery-runbook.md`.

## 1. What "on-call" covers

One rotation, covering everything in this repo: API, web, workers, and the data they
touch. Not split by service — at this scale, splitting on-call by component creates gaps
at exactly the boundary an incident crosses (the review workspace being slow because the
API is slow because the database is under load is one incident, not three).

## 2. Alarms and what they mean

`infra/modules/alerting` provisions these against an SNS topic (`<env>-alerts`) every
alarm below publishes to:

| Alarm | Fires when | Likely cause | First move |
|---|---|---|---|
| `<env>-dlq-<stage>-non-empty` | A pipeline-stage DLQ (intake/extract/detect/export/verify/rule_extraction) has ≥1 message | A job failed all 5 redrive attempts | Inspect the DLQ message body for the failing `doc_id`/`org_id`; check that document's `processing_jobs` row for the error; fix root cause before redriving — a redrive without a fix just refills the DLQ |
| `<env>-api-5xx-rate` / `<env>-web-5xx-rate` | ALB-reported 5xx responses ≥ threshold in 5 min | Deploy regression, DB connectivity loss, unhandled exception path | Check the service's CloudWatch Logs; roll back the most recent deploy if it correlates |
| `<env>-api-p95-latency` / `<env>-web-p95-latency` | ALB target response time p95 ≥ threshold | DB contention, a slow query path, resource exhaustion | Check ECS CPU/memory alarms first (below) — if those are also firing, it's capacity, not a query regression |
| `<env>-<service>-cpu-high` / `<env>-<service>-memory-high` | ECS service CPU/memory ≥ 85% sustained | Under-provisioned service, a leak, or a genuine traffic spike | Scale `desired_count` immediately to buy time; investigate after |

Every alarm's own `alarm_description` (visible in the CloudWatch console) restates this
same guidance so it's available at 3am without this doc open.

## 3. Escalation

1. **Primary on-call** receives the page (once a paging vendor is wired up — see gaps
   below) and acknowledges within 15 minutes.
2. **Unacknowledged after 15 minutes** escalates to secondary on-call.
3. **Unacknowledged after 30 minutes, or primary declares it beyond their ability to
   resolve alone** escalates to the eng lead.
4. **Any incident touching cross-tenant data exposure** (a real RLS bypass, not a false
   alarm) escalates immediately to the eng lead and is treated with SEV-1/public-postmortem
   discipline regardless of time of day — this is the one bar `specs/10-build-plan.md`'s
   risk register sets explicitly higher than everything else here.
5. **Any incident where a legal-hold-affected document might be at risk** (e.g., a
   retention-sweep bug) additionally needs sign-off from whoever owns that org relationship
   before any remediation touches that org's data — same principle as
   `docs/disaster-recovery-runbook.md` §4's approver role.

## 4. Alarm response playbook

- **Acknowledge first, investigate second.** An unacknowledged page that escalates
  needlessly wastes the secondary's time; acknowledging costs nothing and stops the clock.
- **Check for a DR-runbook-shaped event before assuming it's routine.** A DLQ alarm plus a
  5xx spike plus a memory alarm, all at once, might not be three separate problems — check
  `docs/disaster-recovery-runbook.md`'s failure scenarios if it looks bigger than one
  service having a bad afternoon.
- **Write down what you did.** Not a formal postmortem for every page — but enough that
  the next on-call (possibly you, in a month, having forgotten) isn't starting from zero.
- **A DLQ alarm's `ok_actions` firing (it recovers on its own) still deserves a look once
  business hours resume.** A message that recovered without intervention still represents
  a job that failed 5 times before succeeding, or a page that auto-resolved for a reason
  worth understanding.

## 5. Known gaps & prerequisites

Direct about what's not actually true yet, matching `docs/disaster-recovery-runbook.md`'s
own §9:

- **No paging vendor account exists.** `infra/modules/alerting`'s
  `pagerduty_integration_email` variable is empty by default for exactly this reason —
  every alarm above publishes to an SNS topic that currently has nothing subscribed to it.
  Setting that one variable (once a PagerDuty, or equivalent, account and its
  email-integration address exist) is the entire remaining step to make these alarms
  actually page someone.
- **No rotation schedule exists.** There's no team large enough yet to rotate across —
  this document describes the escalation *policy* a rotation would follow, not an actual
  calendar.
- **RLS-policy-violation and integrity-verifier-failure alarms — the two specs/02
  explicitly names — are not built.** Both need something to alarm on that doesn't exist:
  the application has no structured logging at all (`grep -r "import logging" api/app/`
  returns nothing), so there's no log line to write a CloudWatch Logs metric filter
  against, and Aurora's log export to CloudWatch isn't enabled either. Adding structured
  logging to the app is its own piece of work — flagged here as the concrete prerequisite
  for closing this specific gap, not deferred silently.
- **None of this has been applied to real AWS.** Same as the DR runbook: `infra/envs/`
  has only `dev/`, and nothing in this repo has ever run `terraform apply` against a real
  account. `terraform validate` passes; that's the only verification possible without one.
