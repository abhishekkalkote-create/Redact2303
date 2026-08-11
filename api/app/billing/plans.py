"""specs/09-admin-billing.md § Plans — OUR pricing/allowance catalog, not fetched from
the billing provider (Stripe has no notion of "pages included per month"; that's our own
business rule). Single source of truth for the usage API's allowance figures, the
usage-threshold-check cron handler, and (later) plan gates / the marketing pricing page.

Pilot's page cap is a one-time total across the whole trial, not a monthly allowance
(specs/09: "1,000 total cap" vs Starter/Growth's "/mo") — `cap_kind` distinguishes the two
so usage aggregation sums the right window.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PlanCatalogEntry:
    name: str
    seats_included: int
    cap_kind: Literal["monthly", "total", "custom"]
    # None on the "custom" (Enterprise) plan — committed volume is negotiated per org, no
    # fixed catalog number to check usage against.
    pages_included: int | None
    # None where there's no self-serve overage rate: Pilot is a hard cap (no overage,
    # upgrade prompt instead), Enterprise is committed-volume-plus-true-up.
    overage_price_per_100_pages_cents: int | None


PLAN_CATALOG: dict[str, PlanCatalogEntry] = {
    "pilot": PlanCatalogEntry(
        name="Pilot", seats_included=3, cap_kind="total",
        pages_included=1000, overage_price_per_100_pages_cents=None,
    ),
    "starter": PlanCatalogEntry(
        name="Starter", seats_included=5, cap_kind="monthly",
        pages_included=2500, overage_price_per_100_pages_cents=1200,
    ),
    "growth": PlanCatalogEntry(
        name="Growth", seats_included=15, cap_kind="monthly",
        pages_included=10000, overage_price_per_100_pages_cents=900,
    ),
    "enterprise": PlanCatalogEntry(
        name="Enterprise", seats_included=0, cap_kind="custom",
        pages_included=None, overage_price_per_100_pages_cents=None,
    ),
}
