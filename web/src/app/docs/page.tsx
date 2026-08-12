import type { Metadata } from "next";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = {
  title: "Docs — RedactProof",
  description: "User guide, keyboard shortcuts, and API reference for RedactProof's upload, review, rules, and export workflow.",
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SECTIONS = [
  {
    title: "Getting started",
    body: [
      "Create your organization and pick your jurisdiction (state) — you'll get a starter rule pack for that " +
        "state plus the federal exemption library pre-cloned into your org, ready to use immediately.",
      "Invite your team by email from the dashboard. Everyone gets exactly one role — reviewer, supervisor, or " +
        "agency admin — which controls what they can see and do; there's no separate permissions matrix to " +
        "configure.",
      "Not ready to upload something real yet? \"Try a sample document\" on the dashboard runs the full " +
        "pipeline against a synthetic incident report that exercises several exemption codes, and it never " +
        "counts against your plan's usage.",
    ],
  },
  {
    title: "Uploading & processing",
    body: [
      "Upload a single PDF, a ZIP of many PDFs (entries that fail validation are skipped individually, not the " +
        "whole batch), or forward an email (.eml/.msg) — each becomes one or more documents in your queue. " +
        "Word/Excel/PowerPoint files need to be exported to PDF first; there's no server-side conversion for " +
        "those formats.",
      "Every document runs through detection automatically the moment it's uploaded: a deterministic pass " +
        "(regex, dictionaries, and named-entity recognition against your org's rules) runs on every page, and a " +
        "contextual AI pass runs on pages with narrative text that need judgment calls a plain pattern can't " +
        "make. Nothing is redacted at this point — every result is a suggestion sitting in your review queue.",
    ],
  },
  {
    title: "Review workspace",
    body: [
      "Step through each page, and decide on every proposed redaction: approve, reject, or adjust the box. " +
        "Every approval needs an exemption code — the workspace won't let you approve without one.",
      "If detection missed something, draw a box manually or use search-and-redact to catch every remaining " +
        "occurrence of a name or phrase across the whole document in one action — the same text appearing " +
        "twice and only getting caught once is exactly what search-and-redact exists to close before export.",
      "A completeness check runs before you can mark a document reviewed: no low-confidence suggestion can be " +
        "left undecided. If your org requires dual approval, a supervisor's separate sign-off is needed before " +
        "export becomes possible — the API enforces this, not just the UI.",
    ],
  },
  {
    title: "Rules & policies",
    body: [
      "Your rule packs are yours alone. Clone a starter pack (Core PII, Public Safety, HR, Legal, or Health) to " +
        "customize it, or start from scratch. Every edit to a published pack creates a new draft version — " +
        "publishing is immutable, so a live pack's behavior never changes underneath a document mid-review.",
      "Describe a change in plain language (\"stop redacting phone numbers in the letterhead\") and confirm the " +
        "resulting structured diff before it's applied — you're always approving an explicit change, not trusting " +
        "a black box.",
      "Upload an existing policy manual (PDF) and get draft rules extracted automatically, each citing the " +
        "source page it came from. Test any draft version against real documents in the test bench — it shows " +
        "exactly what would change versus the currently published version before you publish.",
    ],
  },
  {
    title: "Exports & audit",
    body: [
      "Export produces a clean redacted PDF (content removed, not just visually covered), an exemption log CSV, " +
        "and a signed certificate by default — an annotated PDF showing exemption codes on each redaction is " +
        "also available if you select it.",
      "Every export is verified automatically before it's stored: the redacted regions are re-extracted to " +
        "confirm no text remains, and the whole document is searched to confirm the redacted text doesn't " +
        "surface anywhere else. A failed check blocks the export outright — there is no way to store a redacted " +
        "file that hasn't passed.",
      "Every action anyone takes — upload, review decision, export, admin change — writes an entry to a " +
        "hash-chained audit trail. You can filter it by document, user, or action, and it survives even after " +
        "the underlying document is deleted.",
    ],
  },
  {
    title: "Usage & billing",
    body: [
      "Your usage page shows exactly what you've used against your plan's allowance, with warnings at 80% and " +
        "95% — no hidden caps and no mid-document blocks. Pilot plans have a hard page cap (upgrade required to " +
        "keep processing past it); paid plans bill overage instead of blocking.",
      "Invoices, plan changes, and the billing portal are all in one place, including PO/net-30 invoicing for " +
        "agencies that pay that way instead of by card.",
    ],
  },
];

const SHORTCUTS = [
  { keys: "A", action: "Approve the selected candidate" },
  { keys: "R", action: "Reject the selected candidate" },
  { keys: "N", action: "Select the next candidate" },
];

export default function DocsPage() {
  return (
    <MarketingShell>
      <div className="mx-auto max-w-3xl px-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight">Docs</h1>
        <p className="mt-3 text-sm text-neutral-600">
          A user guide to how RedactProof fits together, a keyboard-shortcut reference for the review workspace,
          and where to find the API reference if you&rsquo;re integrating directly.
        </p>

        <div className="mt-10 flex flex-col gap-4">
          {SECTIONS.map((section) => (
            <Card key={section.title}>
              <CardHeader>
                <CardTitle>{section.title}</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm text-neutral-600">
                {section.body.map((paragraph, i) => (
                  <p key={i}>{paragraph}</p>
                ))}
              </CardContent>
            </Card>
          ))}

          <Card>
            <CardHeader>
              <CardTitle>Keyboard shortcuts (review workspace)</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-neutral-500">
                      <th scope="col" className="py-1.5 pr-4 font-medium">Key</th>
                      <th scope="col" className="py-1.5 font-medium">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {SHORTCUTS.map((s) => (
                      <tr key={s.keys} className="border-b last:border-0">
                        <td className="py-2 pr-4">
                          <kbd className="rounded border border-neutral-300 bg-neutral-100 px-1.5 py-0.5 font-mono text-xs">
                            {s.keys}
                          </kbd>
                        </td>
                        <td className="py-2 text-neutral-600">{s.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs text-neutral-500">
                Shortcuts are disabled while typing in any text field, textarea, or dropdown, so they never
                interfere with typing a justification or search query.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>API reference</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm text-neutral-600">
              <p>
                The full API surface is generated directly from the same OpenAPI schema the frontend&rsquo;s own
                TypeScript client is built from — it&rsquo;s never hand-documented separately, so it can&rsquo;t
                drift out of date with what&rsquo;s actually deployed.
              </p>
              <p className="flex flex-wrap items-center gap-x-1.5">
                <a href={`${API_BASE_URL}/v1/docs`} className="text-primary underline underline-offset-2">
                  Interactive reference (Swagger UI)
                </a>
                <span>·</span>
                <a href={`${API_BASE_URL}/v1/openapi.json`} className="text-primary underline underline-offset-2">
                  raw OpenAPI schema
                </a>
              </p>
              <p>
                Every endpoint is org-scoped: authenticate to get a bearer token, then send it as{" "}
                <code className="rounded bg-neutral-100 px-1 py-0.5 text-xs">Authorization: Bearer &lt;token&gt;</code>{" "}
                on every request. Users who belong to more than one org additionally send{" "}
                <code className="rounded bg-neutral-100 px-1 py-0.5 text-xs">X-Org-Id</code> to select which org a
                given request applies to.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </MarketingShell>
  );
}
