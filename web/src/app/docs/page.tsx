import type { Metadata } from "next";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = {
  title: "Docs — RedactProof",
  description: "How RedactProof's upload, review, rules, and export workflow fits together.",
};

const SECTIONS = [
  {
    title: "Getting started",
    body:
      "Create your organization, choose your jurisdiction, and you'll get a starter rule pack for your state " +
      "plus federal exemption codes pre-loaded. Invite your team by email — everyone gets a role (reviewer, " +
      "supervisor, or agency admin) that controls what they can see and do.",
  },
  {
    title: "Uploading & processing",
    body:
      "Upload a single PDF, a ZIP of many files, or forward an email — each becomes a document (or several) " +
      "in your queue. Every document runs through text extraction and detection automatically: deterministic " +
      "rules first, then an optional AI contextual pass that proposes exemption codes and draft justifications. " +
      "Nothing is redacted yet — every proposal is a suggestion for a human to decide on.",
  },
  {
    title: "Review workspace",
    body:
      "Step through each page, accept or reject proposed redactions, adjust boxes, and add ones the automated " +
      "passes missed. Every redaction needs an exemption code before it can be approved. A completeness check " +
      "runs before you can mark a document reviewed, and supervisors can require a second approval before " +
      "export.",
  },
  {
    title: "Rules & policies",
    body:
      "Your organization's rule packs are yours alone — clone from the federal/state library, edit rules " +
      "directly, or describe a change in plain language and confirm the resulting diff. You can also upload an " +
      "existing policy manual and get draft rules extracted with citations back to the source text, tested " +
      "against real documents before you publish.",
  },
  {
    title: "Exports & audit",
    body:
      "Export a clean redacted PDF, an annotated version showing exemption codes, and an exemption log " +
      "(PDF, CSV, or JSON) in one action. Every export is verified automatically — the redacted content is " +
      "confirmed unrecoverable before the file is stored — and comes with a signed certificate. Every action " +
      "anyone takes is recorded in a hash-chained audit trail you can filter and export.",
  },
  {
    title: "Usage & billing",
    body:
      "Your usage page shows exactly what you've used against your plan's allowance, with warnings at 80% and " +
      "95% — no hidden caps. Overage on paid plans is billed, never a mid-document block. Invoices, plan " +
      "changes, and the billing portal are all in one place.",
  },
];

export default function DocsPage() {
  return (
    <MarketingShell>
      <div className="mx-auto max-w-3xl px-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight">Docs</h1>
        <p className="mt-3 text-sm text-neutral-600">
          An overview of how RedactProof fits together. In-depth guides land here as the product matures — for
          now, this is the map.
        </p>

        <div className="mt-10 flex flex-col gap-4">
          {SECTIONS.map((section) => (
            <Card key={section.title}>
              <CardHeader>
                <CardTitle>{section.title}</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-neutral-600">{section.body}</CardContent>
            </Card>
          ))}
        </div>
      </div>
    </MarketingShell>
  );
}
