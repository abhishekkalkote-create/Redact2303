from typing import Literal

from pydantic import BaseModel


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
