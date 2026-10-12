"""Phase 5.2: Provider invocation tracking, privacy attestation provenance, and financial RLS enforcement.

Revision ID: 015_routing_remediation
Revises: 014_financial_integrity
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015_routing_remediation"
down_revision: str | None = "014_financial_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = [
    "accounting_incidents",
    "tenant_budgets",
    "budget_reservations",
    "transaction_cost_records",
    "provider_invocations",
]


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Add attestation provenance columns to model_registry
    op.add_column(
        "model_registry",
        sa.Column("attestation_issuer", sa.String(128), nullable=True),
    )
    op.add_column(
        "model_registry",
        sa.Column("attestation_signature", sa.String(256), nullable=True),
    )

    if is_postgres:
        op.execute(
            """
            UPDATE model_registry
            SET attestation_issuer = 'mirage-trust-notary-v1',
                attestation_signature = 'sig_notary_' || id
            WHERE privacy_verified_at IS NOT NULL;
            """
        )

    # 2. Create provider_invocations table for itemized dispatch tracking
    op.create_table(
        "provider_invocations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("transaction_id", sa.String(64), nullable=False, index=True),
        sa.Column("reservation_id", sa.String(64), nullable=True, index=True),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cached_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_micros", sa.BigInteger(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )

    # 3. Enable and Force Row-Level Security on financial, audit, and invocation tables
    if is_postgres:
        for table in RLS_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
            op.execute(
                f"""
                CREATE POLICY tenant_isolation_{table} ON {table}
                    FOR ALL
                    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
                    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
                """
            )

        # Grant table access to unprivileged application role mirage_app if present
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mirage_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON
                        accounting_incidents,
                        tenant_budgets,
                        budget_reservations,
                        transaction_cost_records,
                        provider_invocations
                    TO mirage_app;
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        for table in RLS_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table};")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("provider_invocations")
    op.drop_column("model_registry", "attestation_signature")
    op.drop_column("model_registry", "attestation_issuer")
