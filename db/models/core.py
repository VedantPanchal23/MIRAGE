from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .assurance import KBDocumentRecord, VerificationSession
    from .audit import AuditReport, OperatorAlert
    from .governance import MCPServer

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


class Tenant(Base):
    """Tenant account details and configuration."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    tier: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    scs_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pii_detection_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False, index=True)
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    sessions: Mapped[list["VerificationSession"]] = relationship("VerificationSession", back_populates="tenant")
    alerts: Mapped[list["OperatorAlert"]] = relationship("OperatorAlert", back_populates="tenant")
    reports: Mapped[list["AuditReport"]] = relationship("AuditReport", back_populates="tenant")
    kb_documents: Mapped[list["KBDocumentRecord"]] = relationship("KBDocumentRecord", back_populates="tenant")
    mcp_servers: Mapped[list["MCPServer"]] = relationship(
        "MCPServer", back_populates="tenant", cascade="all, delete-orphan"
    )


class User(Base):
    """Authoritative human principal registered by the control plane."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "external_subject", name="uq_users_tenant_subject"),)


class Agent(Base):
    """Tenant-scoped governed agent identity with explicit lifecycle state."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    max_autonomy_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    registered_by_identity_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("actor_identities.id", ondelete="SET NULL"), nullable=True
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_agents_tenant_name"),
        Index("ix_agents_tenant_status", "tenant_id", "status"),
    )


class ActorIdentity(Base):
    """A verifiable user, API client, service, or agent principal."""

    __tablename__ = "actor_identities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "subject", name="uq_actor_identities_tenant_subject"),)


class ApiCredential(Base):
    """Hashed, revocable API credential bound to one authoritative actor identity."""

    __tablename__ = "api_credentials"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actor_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), default="Default API Key", nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), default="mirage_live_", nullable=False, index=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["*"], nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None:
            now = datetime.now(UTC)
            exp = self.expires_at if self.expires_at.tzinfo is not None else self.expires_at.replace(tzinfo=UTC)
            if exp <= now:
                return False
        return True
