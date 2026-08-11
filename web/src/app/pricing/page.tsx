import type { Metadata } from "next";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = {
  title: "Pricing — RedactProof",
  description: "Published pricing for AI-assisted document redaction, from a P-card pilot to state agency contracts.",
};

const PLANS = [
  {
    key: "pilot",
    name: "Pilot",
    price: "$0 or $99 one-time",
    period: "60–90 days",
    seats: "3",
    pages: "1,000 total cap",
    overage: "Hard cap (upgrade prompt)",
    positioning: "Under P-card thresholds",
  },
  {
    key: "starter",
    name: "Starter",
    price: "$299/mo",
    period: "annual $249/mo",
    seats: "5 (extra $39)",
    pages: "2,500/mo",
    overage: "$12 / 100 pages",
    positioning: "Small clerk teams; annual ≈ $3K",
  },
  {
    key: "growth",
    name: "Growth",
    price: "$799/mo",
    period: "annual $665/mo",
    seats: "15 (extra $29)",
    pages: "10,000/mo",
    overage: "$9 / 100 pages",
    positioning: "Police records units, counties; annual ≈ $8–10K",
    highlight: true,
  },
  {
    key: "enterprise",
    name: "Enterprise",
    price: "Custom",
    period: "annual PO",
    seats: "Custom",
    pages: "Committed volume",
    overage: "Committed + true-up",
    positioning: "State agencies, big cities",
  },
];

export default function PricingPage() {
  return (
    <MarketingShell>
      <div className="mx-auto max-w-5xl px-6 py-16">
        <div className="mx-auto max-w-2xl text-center">
          <h1 className="text-3xl font-semibold tracking-tight">Published pricing, no hidden caps</h1>
          <p className="mt-3 text-sm text-neutral-600">
            Every limit is visible on your own usage page, with warnings at 80% and 95% — and going over never
            silently blocks a document mid-review. Overage is billed, not a surprise.
          </p>
        </div>

        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PLANS.map((plan) => (
            <Card key={plan.key} className={plan.highlight ? "border-neutral-900" : undefined}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>{plan.name}</CardTitle>
                  {plan.highlight && <Badge>Most popular</Badge>}
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-3 text-sm">
                <div>
                  <p className="text-xl font-semibold">{plan.price}</p>
                  <p className="text-xs text-neutral-500">{plan.period}</p>
                </div>
                <dl className="flex flex-col gap-1.5 text-neutral-600">
                  <div className="flex justify-between gap-2">
                    <dt className="text-neutral-500">Seats</dt>
                    <dd className="text-right">{plan.seats}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-neutral-500">Pages</dt>
                    <dd className="text-right">{plan.pages}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-neutral-500">Overage</dt>
                    <dd className="text-right">{plan.overage}</dd>
                  </div>
                </dl>
                <p className="text-xs text-neutral-500">{plan.positioning}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="mx-auto mt-16 max-w-2xl text-center text-sm text-neutral-600">
          <p>
            Agencies pay by PO or ACH as often as by card — every plan supports net-30 invoicing, not just
            self-serve checkout.
          </p>
          <p className="mt-2">
            Pilot orgs see their cap progress and an &ldquo;equivalent value at Growth pricing&rdquo; framing in-app,
            plus an exportable ROI summary once there&rsquo;s enough usage to show.
          </p>
        </div>
      </div>
    </MarketingShell>
  );
}
