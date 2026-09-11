"""Initial PostgreSQL schema for tenants, sessions, claims, and audit logs.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-09-11 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Tenants Table
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column("tier", sa.String(length=32), server_default="free", nullable=False),
        sa.Column("scs_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("pii_detection_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key_hash"),
    )

    # 2. Verification Sessions Table
    op.create_table(
        "verification_sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("response_hash", sa.String(length=64), nullable=False),
        sa.Column("hrs_score", sa.Float(), nullable=False),
        sa.Column("risk_tier", sa.String(length=32), nullable=False),
        sa.Column("correction_applied", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("ix_verification_sessions_tenant_id", "verification_sessions", ["tenant_id"])
    op.create_index("ix_verification_sessions_trace_id", "verification_sessions", ["trace_id"])
    op.create_index("ix_verification_sessions_prompt_hash", "verification_sessions", ["prompt_hash"])
    op.create_index("ix_verification_sessions_risk_tier", "verification_sessions", ["risk_tier"])
    op.create_index("ix_verification_sessions_created_at", "verification_sessions", ["created_at"])

    # 3. Claims Table
    op.create_table(
        "claims",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(length=32), nullable=False),
        sa.Column("criticality", sa.String(length=16), server_default="medium", nullable=False),
        sa.Column("criticality_weight", sa.Float(), server_default="0.6", nullable=False),
        sa.Column("rav_score", sa.Float(), nullable=True),
        sa.Column("scs_score", sa.Float(), nullable=True),
        sa.Column("nli_score", sa.Float(), nullable=True),
        sa.Column("ics_score", sa.Float(), nullable=True),
        sa.Column("vgs_score", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("signal_attribution", JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["verification_sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claims_session_id", "claims", ["session_id"])
    op.create_index("ix_claims_tenant_id", "claims", ["tenant_id"])

    # 4. Audit Logs Table (Cryptographically Chained)
    op.create_table(
        "audit_logs",
        sa.Column("entry_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("response_hash", sa.String(length=64), nullable=False),
        sa.Column("hrs_score", sa.Float(), nullable=False),
        sa.Column("risk_tier", sa.String(length=32), nullable=False),
        sa.Column("claims_count", sa.Integer(), nullable=False),
        sa.Column("claims_summary", JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("correction_applied", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("chain_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("entry_id"),
        sa.UniqueConstraint("chain_hash"),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_session_id", "audit_logs", ["session_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("claims")
    op.drop_table("verification_sessions")
    op.drop_table("tenants")
