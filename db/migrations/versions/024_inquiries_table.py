"""Commercial Storefront: Enterprise contact, demo requests, and inquiries table.

Revision ID: 024_inquiries_table
Revises: 023_governed_mcp_servers
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "024_inquiries_table"
down_revision: str | None = "023_governed_mcp_servers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inquiries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("team_size", sa.String(64), server_default="1-10", nullable=False),
        sa.Column("use_case", sa.String(128), server_default="Agent Governance", nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), server_default="PENDING", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_inquiries_email", "inquiries", ["email"])
    op.create_index("ix_inquiries_status", "inquiries", ["status"])


def downgrade() -> None:
    op.drop_index("ix_inquiries_status", table_name="inquiries")
    op.drop_index("ix_inquiries_email", table_name="inquiries")
    op.drop_table("inquiries")
