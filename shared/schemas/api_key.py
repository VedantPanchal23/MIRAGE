"""Schemas for API Key Lifecycle Management."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreateRequest(BaseModel):
    """Payload to generate a new hashed API key."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Default API Key", min_length=1, max_length=255, description="Human-readable key label")
    tenant_id: str | None = Field(
        default=None,
        description="Target tenant ID (Super Admin only; derived from auth for others)",
    )
    scopes: list[str] = Field(default_factory=lambda: ["*"], description="Authorized permission scopes for this key")
    expires_in_days: int | None = Field(default=None, ge=1, le=365, description="Optional validity duration in days")


class ApiKeyRotateRequest(BaseModel):
    """Payload to rotate an existing API key."""

    model_config = ConfigDict(extra="forbid")

    immediate_revocation: bool = Field(
        default=True,
        description="If True, immediately revokes the old key. If False, allows bounded overlap.",
    )
    grace_period_seconds: int = Field(
        default=0,
        ge=0,
        le=86400,
        description="Grace period in seconds before old key is invalidated when immediate_revocation is False",
    )


class ApiKeyMetadata(BaseModel):
    """Safe public API key metadata (plaintext secret is NEVER stored or returned here)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    key_prefix: str
    scopes: list[str]
    is_active: bool
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class ApiKeyCreatedResponse(BaseModel):
    """Response returned upon key creation or rotation containing the one-time raw secret."""

    key_metadata: ApiKeyMetadata
    raw_key: str = Field(description="Plaintext secret. Returned ONCE only; never stored or displayed again.")
    key_secret: str = Field(description="Convenience accessor for raw_key.")

    @property
    def id(self) -> str:
        return self.key_metadata.id

    @property
    def name(self) -> str:
        return self.key_metadata.name

    @property
    def key_prefix(self) -> str:
        return self.key_metadata.key_prefix

    @property
    def scopes(self) -> list[str]:
        return self.key_metadata.scopes


class ApiKeyListResponse(BaseModel):
    """List of safe API key metadata entries."""

    keys: list[ApiKeyMetadata]
    total: int
