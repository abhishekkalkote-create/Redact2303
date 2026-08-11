from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PlanCardOut(BaseModel):
    """specs/07-ui-spec.md § 8: "Plan card (name, seats, included pages, renewal)." No
    renewal date yet — that needs subscription period tracking the webhook handler
    (app/services/billing_service.py) doesn't capture, left for a later slice."""

    plan: str
    plan_name: str
    plan_status: str
    seats_included: int
    seats_active: int
    pages_included: int | None


class InvoiceOut(BaseModel):
    id: str
    period: str
    status: str
    line_items: list[dict]
    pdf_url: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CheckoutRequest(BaseModel):
    plan: Literal["starter", "growth"]  # specs/09-admin-billing.md: Enterprise is sales-assisted, not self-serve
    success_url: str
    cancel_url: str


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalRequest(BaseModel):
    return_url: str


class PortalResponse(BaseModel):
    portal_url: str
