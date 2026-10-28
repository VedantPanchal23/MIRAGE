"""API routes for Outbound Webhook Subscriptions and Alerting."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from gateway.middleware.auth import get_current_auth
from services.webhook_service import webhook_service
from shared.schemas.auth import AuthContext
from shared.schemas.webhook import (
    WebhookCreateRequest,
    WebhookListResponse,
    WebhookResponse,
)

router = APIRouter(prefix="/v1/webhooks", tags=["Outbound Webhooks"])


@router.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def register_webhook_endpoint(
    req: WebhookCreateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> WebhookResponse:
    """Register an outbound webhook subscription for assurance alerts (TENANT_ADMIN or SUPER_ADMIN)."""
    return await webhook_service.register_webhook(auth, req)


@router.get("", response_model=WebhookListResponse)
async def list_webhooks_endpoint(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> WebhookListResponse:
    """List registered outbound webhook subscriptions for authenticated tenant."""
    return await webhook_service.list_webhooks(auth)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook_endpoint(
    webhook_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> None:
    """Delete an outbound webhook subscription."""
    await webhook_service.delete_webhook(auth, webhook_id)
