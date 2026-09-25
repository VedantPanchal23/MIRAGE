"""Authentication and Authorization schemas adhering to Security & Access Document §3 and §13."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Role(StrEnum):
    """Enterprise authorization roles (Security & Access Document §13.1)."""

    SUPER_ADMIN = "super_admin"
    TENANT_ADMIN = "tenant_admin"
    OPERATOR = "operator"
    AUDITOR = "auditor"
    API_CLIENT = "api_client"


class Permission(StrEnum):
    """Granular resource action permissions (Security & Access Document §13.2)."""

    VERIFY_WRITE = "verify:write"
    VERIFY_READ = "verify:read"
    DASHBOARD_READ = "dashboard:read"
    CONFIG_WRITE = "config:write"
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    CIRCUITS_MANAGE = "circuits:manage"
    KB_WRITE = "kb:write"
    KB_READ = "kb:read"
    ALERTS_ACKNOWLEDGE = "alerts:acknowledge"


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
        Permission.KB_READ,
        Permission.ALERTS_ACKNOWLEDGE,
    },
    Role.TENANT_ADMIN: {
        Permission.VERIFY_WRITE,
        Permission.VERIFY_READ,
        Permission.DASHBOARD_READ,
        Permission.CONFIG_WRITE,
        Permission.AUDIT_READ,
        Permission.AUDIT_EXPORT,
        Permission.KB_WRITE,
        Permission.KB_READ,
        Permission.ALERTS_ACKNOWLEDGE,
    },
    Role.OPERATOR: {
        Permission.DASHBOARD_READ,
        Permission.AUDIT_READ,
        Permission.CIRCUITS_MANAGE,
        Permission.KB_READ,
        Permission.ALERTS_ACKNOWLEDGE,
    },
    Role.AUDITOR: {
        Permission.VERIFY_READ,
        Permission.DASHBOARD_READ,
        Permission.AUDIT_READ,
        Permission.AUDIT_EXPORT,
        Permission.KB_READ,
    },
    Role.API_CLIENT: {
        Permission.VERIFY_WRITE,
        Permission.VERIFY_READ,
    },
}


class AuthContext(BaseModel):
    """Verified identity and authorization context attached to request.state."""

    tenant_id: str = Field(..., description="Authoritative tenant identifier")
    role: Role = Field(..., description="Cryptographically verified role")
    user_id: str = Field(default="anonymous", description="User or subject identifier")
    is_authenticated: bool = Field(default=True, description="Whether authentication was cryptographically verified")
    token_type: Literal["jwt", "api_key"] = Field(default="jwt", description="Credential type used for authentication")
