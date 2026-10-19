"""Authentication and Authorization schemas adhering to Security & Access Document §3 and §13."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Role(StrEnum):
    """Enterprise authorization roles (Security & Access Document §13.1)."""

    SUPER_ADMIN = "super_admin"
    TENANT_ADMIN = "tenant_admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
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
    Role.VIEWER: {
        Permission.DASHBOARD_READ,
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
    identity_id: str | None = Field(default=None, description="Authoritative actor identity identifier")
    principal_type: str = Field(default="user", description="Authoritative principal category")
    agent_id: str | None = Field(default=None, description="Authoritative agent identifier if principal is an agent")
    capabilities: frozenset[str] = Field(default_factory=frozenset)
    is_authenticated: bool = Field(default=True, description="Whether authentication was cryptographically verified")
    token_type: Literal["jwt", "api_key"] = Field(default="jwt", description="Credential type used for authentication")

    def has_permission(self, permission: Permission | str) -> bool:
        """Evaluate if the identity possesses a required permission under role and scope attenuation."""
        try:
            perm = permission if isinstance(permission, Permission) else Permission(str(permission))
        except ValueError:
            # Unknown or invalid permission strings fail closed
            return False

        # 1. Base Role Boundary Check: Role must possess the permission in the canonical access matrix
        role_permissions = ROLE_PERMISSIONS.get(self.role, set())
        if perm not in role_permissions:
            return False

        # 2. Scope Attenuation for API keys:
        if self.token_type == "api_key":
            if not self.capabilities:
                # An API key without scopes has no permissions
                return False
            if "*" in self.capabilities:
                # Wildcard cannot exceed role permissions (already satisfied above)
                return True
            # Specific scopes: string value of permission must be explicitly present in capabilities
            return perm.value in self.capabilities

        # 3. Scope Attenuation for JWT tokens when capabilities are explicitly provided:
        if self.capabilities and "*" not in self.capabilities:
            return perm.value in self.capabilities

        return True
