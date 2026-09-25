"""PostgreSQL schema and RLS policies for operator alerts and audit reports.

Revision ID: 003_alerts_and_reports
Revises: 002_row_level_security
Create Date: 2026-09-22 21:00:00.000000

Implements Technical Architecture §8.2, PRD FR-DFT-04, FR-AUD-01..04, and ADR 0005:
- operator_alerts table with lifecycle states (active, acknowledged, resolved)
- audit_reports table with execution states (PENDING, PROCESSING, COMPLETED, FAILED)
- PostgreSQL Row-Level Security (RLS) policies for multi-tenant isolation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "003_alerts_and_reports"
down_revision: str | None = "002_row_level_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Operator Alerts Table
    op.create_table(
        "operator_alerts",
        sa.Column("alert_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), server_default="medium", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("current_value", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("alert_id"),
    )
    op.create_index("ix_operator_alerts_tenant_id", "operator_alerts", ["tenant_id"])
    op.create_index("ix_operator_alerts_alert_type", "operator_alerts", ["alert_type"])
    op.create_index("ix_operator_alerts_status", "operator_alerts", ["status"])
    op.create_index("ix_operator_alerts_created_at", "operator_alerts", ["created_at"])

    # Enable and enforce RLS on operator_alerts
    op.execute("ALTER TABLE operator_alerts ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE operator_alerts FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_alerts ON operator_alerts
            FOR ALL
            USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """
    )

    # 2. Audit Reports Table
    op.create_table(
        "audit_reports",
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("risk_tier", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("summary", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("report_id"),
    )
    op.create_index("ix_audit_reports_tenant_id", "audit_reports", ["tenant_id"])
    op.create_index("ix_audit_reports_status", "audit_reports", ["status"])
    op.create_index("ix_audit_reports_created_at", "audit_reports", ["created_at"])
    op.create_index("ix_audit_reports_idempotency_key", "audit_reports", ["idempotency_key"])

    # Enable and enforce RLS on audit_reports
    op.execute("ALTER TABLE audit_reports ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE audit_reports FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_reports ON audit_reports
            FOR ALL
            USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """
    )


def downgrade() -> None:
    # Drop policies and tables for audit_reports
    op.execute("DROP POLICY IF EXISTS tenant_isolation_reports ON audit_reports;")
    op.execute("ALTER TABLE audit_reports NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE audit_reports DISABLE ROW LEVEL SECURITY;")
    op.drop_table("audit_reports")

    # Drop policies and tables for operator_alerts
    op.execute("DROP POLICY IF EXISTS tenant_isolation_alerts ON operator_alerts;")
    op.execute("ALTER TABLE operator_alerts NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE operator_alerts DISABLE ROW LEVEL SECURITY;")
    op.drop_table("operator_alerts")
