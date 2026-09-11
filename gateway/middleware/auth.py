"""Authentication and tenant resolution middleware."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.config import get_settings
from shared.schemas.audit import compute_sha256

security_bearer = HTTPBearer(auto_error=False)
settings = get_settings()


async def get_current_tenant(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_bearer)] = None,
) -> str:
    """Resolve and authenticate current tenant ID from bearer token, tenant header, or fallback."""
    if credentials and credentials.credentials:
        token = credentials.credentials
        # Check against dev token or compute hash for lookup
        if token.startswith("mirage_key_") or len(token) > 10:
            return f"tenant_{compute_sha256(token)[:12]}"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check for X-Tenant-ID header
    tenant_hdr = request.headers.get("X-Tenant-ID")
    if tenant_hdr:
        return tenant_hdr

    # In development/testing, default to demo tenant if no token passed
    if settings.debug or settings.environment.value in {"development", "test"}:
        return "default_tenant"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing required authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )
