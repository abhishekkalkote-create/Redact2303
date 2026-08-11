import type { Metadata } from "next";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = {
  title: "Security & Trust — RedactProof",
  description: "Architecture, tenant isolation, encryption, audit integrity, and AI governance for government security reviewers.",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm text-neutral-600">{children}</CardContent>
    </Card>
  );
}

export default function SecurityPage() {
  return (
    <MarketingShell>
      <div className="mx-auto max-w-3xl px-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight">Security &amp; Trust</h1>
        <p className="mt-3 text-sm text-neutral-600">
          This page is a sales asset for government security reviewers — we keep it current with what&rsquo;s
          actually built, not what&rsquo;s planned. Architecture is designed to pass a city/county security
          review and a police-department CJIS review on its own, ahead of any formal authorization.
        </p>

        <div className="mt-10 flex flex-col gap-6">
          <Section title="Tenant isolation">
            <p>Every layer of the stack is scoped to a single organization, enforced independently at each layer:</p>
            <ul className="list-disc pl-5">
              <li>API: JWT → membership check → org context set before any query runs.</li>
              <li>
                Database: Row-Level Security enabled and <em>forced</em> on every tenant table — the application
                database role has no BYPASSRLS privilege.
              </li>
              <li>Storage: one content bucket, keys prefixed by org id, with a per-org customer master key.</li>
              <li>Cross-tenant access attempts are treated as a build-breaking test failure, not a runtime edge case.</li>
            </ul>
          </Section>

          <Section title="Encryption">
            <ul className="list-disc pl-5">
              <li>At rest: KMS-backed encryption on every data store (database, object storage, queues).</li>
              <li>In transit: TLS 1.2+ everywhere, including service-to-service traffic.</li>
              <li>
                Field-level: the actual redacted text of every AI-proposed or human-added redaction is encrypted at
                the application layer before it ever reaches the database — the single most sensitive string we
                store.
              </li>
              <li>FIPS-validated cryptographic modules, in line with CJIS and GovRAMP expectations.</li>
            </ul>
          </Section>

          <Section title="Identity &amp; access">
            <ul className="list-disc pl-5">
              <li>Multi-factor authentication available to every user, enforceable by org policy (default on for new orgs).</li>
              <li>FIDO2/WebAuthn support; no SMS one-time codes, which don&rsquo;t meet phishing-resistance guidance.</li>
              <li>Enterprise SSO (SAML/OIDC) for organization-level federation.</li>
              <li>Session policy is org-configurable; sessions revoke immediately on role change or deactivation.</li>
            </ul>
          </Section>

          <Section title="Support access model">
            <p>
              By default, our platform staff can see only metadata — which org, job status, usage, and error
              state — never document content, redaction text, or page previews.
            </p>
            <p>
              Elevated access requires your own Agency Admin to approve a scoped, time-bound grant (24 hours or
              less). Every access during an active grant writes a customer-visible audit event. There is no
              standing or silent path around this — the endpoints that touch content check org membership, not
              platform role.
            </p>
          </Section>

          <Section title="Audit integrity">
            <p>
              Every state-changing action writes an immutable, append-only audit record. Each organization&rsquo;s
              audit trail is hash-chained — each entry incorporates the hash of the one before it — so tampering
              with history is detectable, not just logged. Audit records are retained for at least a year and
              survive even if the organization&rsquo;s own data is later deleted.
            </p>
          </Section>

          <Section title="Data lifecycle">
            <p>
              Retention windows are organization-configurable (uploaded originals default to 90 days after
              export; exported records default to 7 years). A legal-hold flag on any document or records request
              suspends deletion entirely until it&rsquo;s cleared. Deletions are destructive — content is removed
              from storage, not just hidden — and a certificate of deletion is available on request. Offboarding
              an organization produces a full export package before any destruction happens, with a signed
              attestation afterward.
            </p>
          </Section>

          <Section title="AI governance">
            <p>
              Contextual detection runs on Amazon Bedrock in US regions under a zero-retention configuration.
              Customer content is never used to train any model — ours or the underlying provider&rsquo;s — as a
              contractual and technical guarantee. Every AI-proposed redaction records which model and prompt
              version produced it, so any past decision is explainable after the fact. AI is always a suggestion;
              a human reviews and decides on every redaction before it&rsquo;s exported.
            </p>
            <p className="flex items-center gap-2">
              AI transparency one-pager (model inventory, accuracy report, bias testing summary):
              <Badge variant="outline">not yet published</Badge>
            </p>
          </Section>

          <Section title="CJIS alignment">
            <p>
              Built against the CJIS Security Policy from day one: FIPS-validated encryption, phishing-resistant
              MFA, one-year-plus audit retention, media sanitization on deletion, and US-only infrastructure and
              support staff. CJIS has no central certification — we maintain a control-to-evidence mapping and
              sign the CJIS Security Addendum per agency as needed.
            </p>
          </Section>

          <Section title="Compliance status">
            <p>Honest status, not aspirational marketing:</p>
            <ul className="list-disc pl-5">
              <li>SOC 2 Type II: evidence collection in progress.</li>
              <li>GovRAMP Security Snapshot: submitted.</li>
              <li>GovRAMP Ready/Authorized, TX-RAMP, FedRAMP 20x: on the roadmap, not yet started.</li>
            </ul>
            <p>We&rsquo;ll update this page as each milestone actually lands.</p>
          </Section>
        </div>
      </div>
    </MarketingShell>
  );
}
