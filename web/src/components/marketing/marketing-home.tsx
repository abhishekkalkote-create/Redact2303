import Link from "next/link";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const STEPS = [
  { title: "Upload", body: "A single PDF, a ZIP batch, or a forwarded email — each becomes a document in your queue." },
  { title: "AI proposes", body: "Deterministic rules and an optional contextual AI pass suggest redactions with a statutory exemption code and draft justification each." },
  { title: "Human decides", body: "A reviewer accepts, rejects, or edits every proposal. Nothing is redacted without a human decision and an exemption code." },
  { title: "Export, defensibly", body: "A verified, destructively redacted PDF plus an exemption log and a hash-chained audit trail — every time." },
];

const DIFFERENTIATORS = [
  {
    title: "Exemption citation engine",
    body: "A two-level taxonomy — federal b(1)–b(9) exemptions plus a per-state statute library — with AI-drafted justifications and an exportable exemption log.",
  },
  {
    title: "Defensibility as a product",
    body: "Hash-chained audit trail, a redaction certificate on every export, an automated integrity verifier, and optional two-person approval.",
  },
  {
    title: "Your own policy engine",
    body: "Upload an agency manual and get draft rules extracted with citations back to the source. Edit rules in plain language. Never shared across organizations.",
  },
  {
    title: "Honest, published pricing",
    body: "Every plan's limits are visible on your own usage page, with warnings before you hit them — including a pilot tier under typical P-card thresholds.",
  },
];

/** specs/00-overview.md's positioning statement and differentiators, condensed for the
 * marketing homepage. Rendered for anonymous visitors to web/src/app/page.tsx — logged-in
 * visitors never see this (redirected to their dashboard first). */
export function MarketingHome() {
  return (
    <MarketingShell>
      <section className="mx-auto max-w-3xl px-6 pt-20 pb-16 text-center">
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
          Legally defensible redaction, in minutes instead of hours
        </h1>
        <p className="mt-5 text-base text-neutral-600 sm:text-lg">
          RedactProof is the AI redaction workspace for public-records and FOIA teams: context-aware AI proposes
          redactions with a statutory citation, a human always decides, and every export carries a court-ready
          audit record — at published prices a records manager can buy on a P-card.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link href="/login" className={buttonVariants({ variant: "default", size: "lg" })}>
            Log in
          </Link>
          <Link href="/pricing" className={buttonVariants({ variant: "outline", size: "lg" })}>
            See pricing
          </Link>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-6 py-12">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((step, i) => (
            <Card key={step.title}>
              <CardHeader>
                <p className="text-xs font-medium text-neutral-400">Step {i + 1}</p>
                <CardTitle>{step.title}</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-neutral-600">{step.body}</CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-6 py-12">
        <h2 className="text-center text-2xl font-semibold tracking-tight">Why teams switch from Acrobat and request-tracking add-ons</h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {DIFFERENTIATORS.map((item) => (
            <Card key={item.title}>
              <CardHeader>
                <CardTitle>{item.title}</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-neutral-600">{item.body}</CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-3xl px-6 py-16 text-center">
        <h2 className="text-2xl font-semibold tracking-tight">Built for a police-department security review</h2>
        <p className="mt-3 text-sm text-neutral-600">
          Hard tenant isolation, per-org encryption, and a support-access model that keeps our own staff out of
          your document content by default.
        </p>
        <div className="mt-6">
          <Link href="/security" className={buttonVariants({ variant: "outline" })}>
            Read the security &amp; trust page
          </Link>
        </div>
      </section>
    </MarketingShell>
  );
}
