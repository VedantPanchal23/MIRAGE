"""Authentication and token bootstrap routes for MIRAGE.

Implements Security & Access §3.2 and live demonstration session enablement.
Provides cryptographically signed JWT issuance for demo operators without manual secret handling.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from gateway.middleware.auth import (
    create_access_token,
    get_current_auth,
)
from shared.schemas.auth import AuthContext, Role

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])


class DemoTokenRequest(BaseModel):
    """Payload to request a demonstration session JWT."""

    tenant_id: str = Field(default="tenant_demo", description="Tenant scope identifier")
    role: Role = Field(default=Role.TENANT_ADMIN, description="Authorized role")
    user_id: str = Field(default="demo_operator", description="Operator identity handle")


class TokenResponse(BaseModel):
    """Cryptographically signed JWT bearer token response."""

    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    role: str
    user_id: str
    expires_in: int


@router.post(
    "/demo-token",
    response_model=TokenResponse,
    summary="Generate Demo Bearer JWT",
    description="Issues an authoritative, signed Bearer JWT for live showcase and evaluation sessions.",
)
async def generate_demo_token(payload: DemoTokenRequest = DemoTokenRequest()) -> TokenResponse:
    """Issue a valid, signed Bearer JWT for live demonstration without manual token fabrication."""
    # 24-hour expiration for demonstration continuity
    expires_delta = timedelta(hours=24)
    token = create_access_token(
        tenant_id=payload.tenant_id,
        role=payload.role,
        user_id=payload.user_id,
        expires_delta=expires_delta,
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        tenant_id=payload.tenant_id,
        role=payload.role.value,
        user_id=payload.user_id,
        expires_in=int(expires_delta.total_seconds()),
    )


@router.get(
    "/me",
    response_model=AuthContext,
    summary="Current Authenticated Identity",
    description="Returns the currently authenticated user identity and role from the verified JWT.",
)
async def get_current_user_info(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> AuthContext:
    """Inspect current authenticated context."""
    return auth
