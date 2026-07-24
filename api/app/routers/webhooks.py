from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_org_db, require_role
from app.models.membership import Membership
from app.models.webhook import WebhookDelivery, WebhookSubscription
from app.schemas.webhook import (
    WebhookDeliveryOut,
    WebhookSubscriptionCreate,
    WebhookSubscriptionOut,
)
from app.services.webhook_service import (
    create_subscription,
    delete_subscription,
    list_subscriptions,
)

router = APIRouter(prefix="/orgs/current/webhooks", tags=["webhooks"])


@router.post("", response_model=WebhookSubscriptionOut, status_code=201)
async def create_webhook_subscription(
    payload: WebhookSubscriptionCreate,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> WebhookSubscriptionOut:
    """specs/07-ui-spec.md screen 5 (org settings): "API & webhooks." The signing secret
    is returned ONLY in this response — same pattern as invite tokens."""
    subscription, secret = await create_subscription(db, membership.org_id, membership.user_id, payload.url, payload.events)
    out = WebhookSubscriptionOut.model_validate(subscription)
    out.secret = secret
    return out


@router.get("", response_model=list[WebhookSubscriptionOut])
async def list_webhook_subscriptions(db: AsyncSession = Depends(get_org_db)) -> list[WebhookSubscription]:
    return await list_subscriptions(db)


@router.delete("/{subscription_id}", status_code=204)
async def delete_webhook_subscription(
    subscription_id: str,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> None:
    await delete_subscription(db, membership.org_id, membership.user_id, subscription_id)


@router.get("/{subscription_id}/deliveries", response_model=list[WebhookDeliveryOut])
async def list_webhook_deliveries(
    subscription_id: str,
    _membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> list[WebhookDelivery]:
    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == subscription_id)
        .order_by(WebhookDelivery.created_at.desc())
    )
    return list(result.scalars().all())
