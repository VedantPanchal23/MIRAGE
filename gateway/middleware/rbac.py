"""Role-Based Access Control (RBAC) and Permission Enforcement Middleware.

Implements Security & Access Document §13:
- Roles: SUPER_ADMIN, TENANT_ADMIN, OPERATOR, AUDITOR, API_CLIENT
- Permission Matrix: VERIFY_WRITE, VERIFY_READ, DASHBOARD_READ, CONFIG_WRITE,
  AUDIT_READ, AUDIT_EXPORT, CIRCUITS_MANAGE, KB_WRITE
- require_permission(...) FastAPI dependency
- Complete elimination of trust in client-supplied X-Role headers
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from gateway.middleware.auth import get_current_auth, get_current_tenant, security_bearer
from shared.logging import get_logger
from shared.schemas.auth import ROLE_PERMISSIONS, AuthContext, Permission, Role

# Re-export for backward compatibility
__all__ = [
    "Role",
    "Permission",
    "ROLE_PERMISSIONS",
    "AuthContext",
    "require_permission",
    "resolve_role_from_request",
    "get_current_tenant",
    "security_bearer",
]

logger = get_logger("rbac_middleware")


def resolve_role_from_request(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = None,
) -> Role:
    """Resolve role strictly from cryptographically verified request state.

    CRITICAL SECURITY INVARIANT:
    X-Role headers are completely ignored and stripped. Role is derived
    exclusively from request.state.auth.
    """
    auth: AuthContext | None = getattr(request.state, "auth", None)
    if auth is not None and isinstance(auth, AuthContext):
        return auth.role
    return Role.API_CLIENT


def require_permission(required_perm: Permission) -> Callable[..., Coroutine[Any, Any, str]]:
    """Factory returning a FastAPI dependency enforcing that the caller possesses required_perm."""

    async def _dependency(
        request: Request,
        auth: Annotated[AuthContext, Depends(get_current_auth)],
    ) -> str:
        # Derive role ONLY from cryptographically verified auth context
        role = auth.role
        allowed_permissions = ROLE_PERMISSIONS.get(role, set())

        if required_perm not in allowed_permissions:
            logger.warning(
                "RBAC permission denied",
                tenant_id=auth.tenant_id,
                role=role.value,
                required_permission=required_perm.value,
                client_sent_x_role=request.headers.get("X-Role"),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Role '{role.value}' lacks permission '{required_perm.value}'",
            )

        request.state.role = role.value
        request.state.tenant_id = auth.tenant_id
        return auth.tenant_id

    return _dependency
