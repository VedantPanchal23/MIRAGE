"""Role-Based Access Control (RBAC) and Permission Enforcement Middleware.

Implements Security & Access Document §13:
- Roles: SUPER_ADMIN, TENANT_ADMIN, OPERATOR, AUDITOR, API_CLIENT
- Permission Matrix: VERIFY_WRITE, VERIFY_READ, DASHBOARD_READ, CONFIG_WRITE,
  AUDIT_READ, AUDIT_EXPORT, CIRCUITS_MANAGE, KB_WRITE
- require_permission(...) FastAPI dependency
"""

from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from gateway.middleware.auth import get_current_tenant, security_bearer
from shared.logging import get_logger

logger = get_logger("rbac_middleware")


class Role(StrEnum):
    """Enterprise authorization roles."""

    SUPER_ADMIN = "super_admin"
    TENANT_ADMIN = "tenant_admin"
    OPERATOR = "operator"
    AUDITOR = "auditor"
    API_CLIENT = "api_client"


class Permission(StrEnum):
    """Granular resource action permissions."""

    VERIFY_WRITE = "verify:write"
    VERIFY_READ = "verify:read"
    DASHBOARD_READ = "dashboard:read"
    CONFIG_WRITE = "config:write"
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    CIRCUITS_MANAGE = "circuits:manage"
    KB_WRITE = "kb:write"


# Role-to-Permissions Access Matrix (Security & Access Document §13.2)
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.SUPER_ADMIN: {
        Permission.VERIFY_WRITE,
        Permission.VERIFY_READ,
        Permission.DASHBOARD_READ,
        Permission.CONFIG_WRITE,
        Permission.AUDIT_READ,
        Permission.AUDIT_EXPORT,
        Permission.CIRCUITS_MANAGE,
        Permission.KB_WRITE,
    },
    Role.TENANT_ADMIN: {
        Permission.VERIFY_WRITE,
        Permission.VERIFY_READ,
        Permission.DASHBOARD_READ,
        Permission.CONFIG_WRITE,
        Permission.AUDIT_READ,
        Permission.AUDIT_EXPORT,
        Permission.KB_WRITE,
    },
    Role.OPERATOR: {
        Permission.VERIFY_WRITE,
        Permission.VERIFY_READ,
        Permission.DASHBOARD_READ,
        Permission.CIRCUITS_MANAGE,
        Permission.KB_WRITE,
    },
    Role.AUDITOR: {
        Permission.VERIFY_READ,
        Permission.DASHBOARD_READ,
        Permission.AUDIT_READ,
        Permission.AUDIT_EXPORT,
    },
    Role.API_CLIENT: {
        Permission.VERIFY_WRITE,
        Permission.VERIFY_READ,
        Permission.KB_WRITE,
    },
}


def resolve_role_from_request(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> Role:
    """Resolve role from X-Role header, API key pattern, or default API_CLIENT."""
    # Explicit role header (used by internal dashboard / admin tokens)
    role_hdr = request.headers.get("X-Role")
    if role_hdr:
        try:
            return Role(role_hdr.lower())
        except ValueError:
            pass

    if credentials and credentials.credentials:
        token = credentials.credentials
        if token.startswith("mirage_admin_"):
            return Role.SUPER_ADMIN
        if token.startswith("mirage_auditor_"):
            return Role.AUDITOR
        if token.startswith("mirage_operator_"):
            return Role.OPERATOR

    return Role.API_CLIENT


def require_permission(required_perm: Permission) -> Callable[..., Coroutine[Any, Any, str]]:
    """Factory returning a FastAPI dependency enforcing that the caller possesses required_perm."""

    async def _dependency(
        request: Request,
        tenant_id: str = Depends(get_current_tenant),
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_bearer)] = None,
    ) -> str:
        role = resolve_role_from_request(request, credentials)
        allowed_permissions = ROLE_PERMISSIONS.get(role, set())

        if required_perm not in allowed_permissions:
            logger.warning(
                "RBAC permission denied",
                tenant_id=tenant_id,
                role=role.value,
                required_permission=required_perm.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Role '{role.value}' lacks permission '{required_perm.value}'",
            )

        request.state.role = role.value
        return tenant_id

    return _dependency
