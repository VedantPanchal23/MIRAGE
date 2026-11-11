"""Unified FastAPI Dependency Injection Layer for MIRAGE 3.0 Gateway.

Consolidates authentication context, tenant isolation boundaries, RBAC authorization,
and database session injection across all gateway routes.
"""

from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from gateway.middleware.auth import get_current_auth, get_current_tenant
from gateway.middleware.rbac import require_permission
from shared.schemas.auth import AuthContext, Role

__all__ = [
    "get_current_auth",
    "get_current_tenant",
    "require_permission",
    "require_roles",
    "verify_tenant_access",
    "get_tenant_db",
    "Auth",
    "TenantId",
]

# Common type aliases for FastAPI endpoint signatures
Auth = Annotated[AuthContext, Depends(get_current_auth)]
TenantId = Annotated[str, Depends(get_current_tenant)]


def require_roles(*allowed_roles: Role) -> Callable[..., Coroutine[Any, Any, AuthContext]]:
    """FastAPI dependency factory enforcing that caller belongs to one of allowed_roles (or SUPER_ADMIN)."""

    async def _role_dependency(
        auth: Annotated[AuthContext, Depends(get_current_auth)],
    ) -> AuthContext:
        if auth.role == Role.SUPER_ADMIN:
            return auth
        if auth.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Access denied: Role '{auth.role.value}' is unauthorized. "
                    f"Requires one of: {[r.value for r in allowed_roles]}"
                ),
            )
        return auth

    return _role_dependency


def verify_tenant_access(auth: AuthContext, target_tenant_id: str | None) -> str:
    """Validate cross-tenant access boundaries, fail-closed for non-super-admins.

    Returns the authorized target tenant ID.
    """
    if target_tenant_id and target_tenant_id != auth.tenant_id and auth.role != Role.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Tenant '{auth.tenant_id}' cannot access records for tenant '{target_tenant_id}'",
        )
    return target_tenant_id or auth.tenant_id


async def get_tenant_db(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> AsyncGenerator[AsyncSession, None]:
    """Dependency yielding an async database session scoped to caller's authenticated tenant."""
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        yield session
