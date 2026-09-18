"""Authentication test factory for generating deterministic, cryptographically signed credentials.

Implements Testing Strategy §7 and Security & Access Document §3.1, §3.2, §13:
- Reusable test credential generator for JWT and API keys
- Provides valid, expired, tampered, and malformed tokens without hardcoded magic strings
- Ensures tests cleanly specify tenant identity and role context
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import jwt

from gateway.middleware.auth import create_access_token, register_api_key, revoke_api_key
from shared.config import get_settings
from shared.schemas.auth import Role

settings = get_settings()


class AuthTestFactory:
    """Deterministic security test fixture and credential factory."""

    @staticmethod
    def valid_jwt(
        tenant_id: str = "default_tenant",
        role: Role = Role.API_CLIENT,
        user_id: str = "test_user_01",
        expires_delta: timedelta | None = None,
    ) -> str:
        """Generate a valid cryptographically signed JWT access token."""
        return create_access_token(
            tenant_id=tenant_id,
            role=role,
            user_id=user_id,
            expires_delta=expires_delta,
        )

    @staticmethod
    def auth_headers(
        tenant_id: str = "default_tenant",
        role: Role = Role.API_CLIENT,
        user_id: str = "test_user_01",
    ) -> dict[str, str]:
        """Generate HTTP Authorization Bearer header dictionary for given tenant and role."""
        token = AuthTestFactory.valid_jwt(tenant_id=tenant_id, role=role, user_id=user_id)
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def expired_jwt(
        tenant_id: str = "default_tenant",
        role: Role = Role.API_CLIENT,
    ) -> str:
        """Generate an expired JWT token (expired 1 hour ago)."""
        return create_access_token(
            tenant_id=tenant_id,
            role=role,
            expires_delta=timedelta(seconds=-3600),
        )

    @staticmethod
    def tampered_jwt(
        tenant_id: str = "default_tenant",
        role: Role = Role.API_CLIENT,
        bad_secret: str = "attacker-tampered-secret-key-32chars!!",
    ) -> str:
        """Generate a token signed with an invalid cryptographic secret key."""
        return create_access_token(
            tenant_id=tenant_id,
            role=role,
            secret_key=bad_secret,
        )

    @staticmethod
    def missing_claim_jwt(
        omit_claim: str = "tenant_id",
        tenant_id: str = "default_tenant",
        role: Role = Role.API_CLIENT,
    ) -> str:
        """Generate a signed JWT token deliberately omitting a mandatory claim."""
        now = datetime.now(UTC)
        claims: dict[str, Any] = {
            "sub": "test_user_01",
            "tenant_id": tenant_id,
            "role": role.value,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "iss": "mirage-auth",
        }
        claims.pop(omit_claim, None)
        return jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)

    @staticmethod
    def valid_api_key(
        api_key: str = "mrg_test_factory_key_123456789012",
        tenant_id: str = "default_tenant",
        role: Role = Role.API_CLIENT,
    ) -> str:
        """Register and return a valid scoped API key."""
        register_api_key(api_key, tenant_id=tenant_id, role=role)
        return api_key

    @staticmethod
    def revoked_api_key(
        api_key: str = "mrg_test_revoked_key_999999999999",
        tenant_id: str = "default_tenant",
        role: Role = Role.API_CLIENT,
    ) -> str:
        """Register and immediately revoke an API key."""
        register_api_key(api_key, tenant_id=tenant_id, role=role)
        revoke_api_key(api_key)
        return api_key
