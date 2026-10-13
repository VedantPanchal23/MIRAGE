"""Phase 7: Governed Memory lifecycle, classification, purpose binding, and retention.

Revision ID: 017_phase7_governed_memory
Revises: 016_phase6_outcome_assurance
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "017_phase7_governed_memory"
down_revision: str | None = "016_phase6_outcome_assurance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Add Phase 7 Governed Memory lifecycle and provenance columns
    op.add_column(
        "governed_memories",
        sa.Column("memory_category", sa.String(32), nullable=False, server_default="USER_FACT"),
    )
    op.add_column(
        "governed_memories",
        sa.Column("purpose", sa.String(64), nullable=False, server_default="GENERAL"),
    )
    op.add_column(
        "governed_memories",
        sa.Column("lifecycle_state", sa.String(32), nullable=False, server_default="ACTIVE"),
    )
    op.add_column(
        "governed_memories",
        sa.Column("trust_level", sa.String(32), nullable=False, server_default="PROVISIONAL"),
    )
    op.add_column(
        "governed_memories",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "governed_memories",
        sa.Column("superseded_by_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "governed_memories",
        sa.Column("retention_policy", sa.String(32), nullable=False, server_default="STANDARD"),
    )
    op.add_column(
        "governed_memories",
        sa.Column("retention_exception_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "governed_memories",
        sa.Column("source_type", sa.String(64), nullable=False, server_default="USER_INPUT"),
    )
    op.add_column(
        "governed_memories",
        sa.Column("source_uri", sa.String(255), nullable=True),
    )
    op.add_column(
        "governed_memories",
        sa.Column("source_transaction_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "governed_memories",
        sa.Column("source_action_id", sa.String(64), nullable=True),
    )
    jsonb_type = JSONB() if is_postgres else sa.JSON()
    op.add_column(
        "governed_memories",
        sa.Column(
            "derivation_chain",
            jsonb_type,
            nullable=False,
            server_default=sa.text("'[]'::jsonb" if is_postgres else "'[]'"),
        ),
    )
    op.add_column(
        "governed_memories",
        sa.Column("propagation_status", sa.String(32), nullable=False, server_default="PROPAGATED"),
    )
    op.add_column(
        "governed_memories",
        sa.Column(
            "propagation_details",
            jsonb_type,
            nullable=False,
            server_default=sa.text("'{}'::jsonb" if is_postgres else "'{}'"),
        ),
    )
    op.add_column(
        "governed_memories",
        sa.Column("dispute_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "governed_memories",
        sa.Column("idempotency_key", sa.String(255), nullable=True),
    )

    # 2. Add performance & tenant isolation indexes
    op.create_index(
        "ix_governed_memories_tenant_purpose",
        "governed_memories",
        ["tenant_id", "purpose"],
    )
    op.create_index(
        "ix_governed_memories_tenant_lifecycle",
        "governed_memories",
        ["tenant_id", "lifecycle_state"],
    )
    op.create_index(
        "ix_governed_memories_tenant_expires",
        "governed_memories",
        ["tenant_id", "expires_at"],
    )
    op.create_index(
        "ix_governed_memories_tenant_category",
        "governed_memories",
        ["tenant_id", "memory_category"],
    )

    if is_postgres:
        op.create_index(
            "uq_governed_memories_tenant_idempotency",
            "governed_memories",
            ["tenant_id", "idempotency_key"],
            unique=True,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        )

        # 3. Ensure role mirage_app permissions and RLS enforcement
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mirage_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON governed_memories TO mirage_app;
                END IF;
            END
            $$;
            """
        )
        op.execute("ALTER TABLE governed_memories ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE governed_memories FORCE ROW LEVEL SECURITY;")


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.drop_index(
            "uq_governed_memories_tenant_idempotency",
            table_name="governed_memories",
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        )
    op.drop_index("ix_governed_memories_tenant_category", table_name="governed_memories")
    op.drop_index("ix_governed_memories_tenant_expires", table_name="governed_memories")
    op.drop_index("ix_governed_memories_tenant_lifecycle", table_name="governed_memories")
    op.drop_index("ix_governed_memories_tenant_purpose", table_name="governed_memories")

    op.drop_column("governed_memories", "idempotency_key")
    op.drop_column("governed_memories", "dispute_reason")
    op.drop_column("governed_memories", "propagation_details")
    op.drop_column("governed_memories", "propagation_status")
    op.drop_column("governed_memories", "derivation_chain")
    op.drop_column("governed_memories", "source_action_id")
    op.drop_column("governed_memories", "source_transaction_id")
    op.drop_column("governed_memories", "source_uri")
    op.drop_column("governed_memories", "source_type")
    op.drop_column("governed_memories", "retention_exception_reason")
    op.drop_column("governed_memories", "retention_policy")
    op.drop_column("governed_memories", "superseded_by_id")
    op.drop_column("governed_memories", "version")
    op.drop_column("governed_memories", "trust_level")
    op.drop_column("governed_memories", "lifecycle_state")
    op.drop_column("governed_memories", "purpose")
    op.drop_column("governed_memories", "memory_category")
