"""Authenticated identity inspection endpoints.

MIRAGE does not expose a gateway token issuer. Production tokens originate from
the configured identity authority and authorization comes from PostgreSQL.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from gateway.middleware.auth import get_current_auth
from services.api_key_service import api_key_service
from services.tenant_service import TenantService
from shared.schemas.api_key import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyListResponse,
    ApiKeyMetadata,
    ApiKeyRotateRequest,
)
from shared.schemas.auth import AuthContext
from shared.schemas.tenant import (
    TenantRegistrationRequest,
    TenantRegistrationResponse,
)

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])
tenant_service = TenantService()


@router.post(
    "/register-tenant",
    response_model=TenantRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Self-service enterprise tenant registration",
)
async def register_tenant_endpoint(
    req: TenantRegistrationRequest,
) -> TenantRegistrationResponse:
    """Self-service enterprise onboarding: provisions tenant, admin user, identity, API key, and budget."""
    return await tenant_service.register_tenant(req)


@router.get("/me", response_model=AuthContext, summary="Current authenticated identity")
async def get_current_user_info(auth: Annotated[AuthContext, Depends(get_current_auth)]) -> AuthContext:
    """Return the identity resolved by the control plane."""
    return auth


# =============================================================================
# API Key Lifecycle Management Endpoints
# =============================================================================


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    req: ApiKeyCreateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> ApiKeyCreatedResponse:
    """Issue a new high-entropy API key. Plaintext secret is returned ONCE only."""
    return await api_key_service.create_api_key(auth=auth, req=req)


@router.get("/api-keys", response_model=ApiKeyListResponse)
async def list_api_keys(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    tenant_id: Annotated[str | None, Query(description="Target tenant ID (Super Admin only)")] = None,
) -> ApiKeyListResponse:
    """List safe metadata for all API keys within authorized tenant scope."""
    return await api_key_service.list_api_keys(auth=auth, tenant_id=tenant_id)


@router.get("/api-keys/{key_id}", response_model=ApiKeyMetadata)
async def get_api_key(
    key_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> ApiKeyMetadata:
    """Retrieve safe metadata for a specific API key."""
    return await api_key_service.get_api_key(auth=auth, key_id=key_id)


@router.post("/api-keys/{key_id}/rotate", response_model=ApiKeyCreatedResponse)
async def rotate_api_key(
    key_id: str,
    req: ApiKeyRotateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> ApiKeyCreatedResponse:
    """Rotate an existing API key, returning the new secret ONCE and managing revocation."""
    return await api_key_service.rotate_api_key(auth=auth, key_id=key_id, req=req)


@router.post("/api-keys/{key_id}/revoke", response_model=ApiKeyMetadata)
async def revoke_api_key(
    key_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> ApiKeyMetadata:
    """Immediately revoke an API key."""
    return await api_key_service.revoke_api_key(auth=auth, key_id=key_id)
