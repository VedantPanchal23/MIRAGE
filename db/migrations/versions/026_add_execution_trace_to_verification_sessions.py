"""Add execution_trace JSONB column to verification_sessions and ai_transactions.

Consolidates unstructured verification traces directly into PostgreSQL,
eliminating the dual-write window and MongoDB dependency.

Revision ID: 026_add_execution_trace
Revises: 025_webhooks_table
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "026_add_execution_trace"
down_revision: str | None = "025_webhooks_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = JSONB() if is_postgres else sa.JSON()

    # Add execution_trace to verification_sessions if not present
    inspector = sa.inspect(bind)
    sess_cols = [c["name"] for c in inspector.get_columns("verification_sessions")]
    if "execution_trace" not in sess_cols:
        op.add_column(
            "verification_sessions",
            sa.Column("execution_trace", json_type, nullable=True),
        )

    # Add execution_trace to ai_transactions if not present
    txn_cols = [c["name"] for c in inspector.get_columns("ai_transactions")]
    if "execution_trace" not in txn_cols:
        op.add_column(
            "ai_transactions",
            sa.Column("execution_trace", json_type, nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    sess_cols = [c["name"] for c in inspector.get_columns("verification_sessions")]
    if "execution_trace" in sess_cols:
        op.drop_column("verification_sessions", "execution_trace")

    txn_cols = [c["name"] for c in inspector.get_columns("ai_transactions")]
    if "execution_trace" in txn_cols:
        op.drop_column("ai_transactions", "execution_trace")
