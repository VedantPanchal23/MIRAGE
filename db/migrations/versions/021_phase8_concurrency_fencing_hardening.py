"""Phase 8: Concurrency Lease Serialization & Fencing Token Hardening.

Revision ID: 021_phase8_fencing_hard
Revises: 020_phase8_handoff_concurrency
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "021_phase8_fencing_hard"
down_revision: str | None = "020_phase8_handoff_concurrency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Unique constraint guaranteeing distinct, non-regressing fencing tokens per resource
    op.create_unique_constraint(
        "uq_resource_leases_tenant_resource_token",
        "resource_leases",
        ["tenant_id", "resource_uri", "fencing_token"],
    )

    # 2. Partial unique index guaranteeing at most ONE active EXCLUSIVE lease per resource
    # (while preserving legitimate concurrent SHARED leases)
    if is_postgres:
        op.create_index(
            "uq_resource_leases_tenant_resource_exclusive_active",
            "resource_leases",
            ["tenant_id", "resource_uri"],
            unique=True,
            postgresql_where=sa.text("status = 'ACQUIRED' AND concurrency_mode = 'EXCLUSIVE'"),
        )
    else:
        op.create_index(
            "uq_resource_leases_tenant_resource_exclusive_active",
            "resource_leases",
            ["tenant_id", "resource_uri"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(
        "uq_resource_leases_tenant_resource_exclusive_active",
        table_name="resource_leases",
    )
    op.drop_constraint(
        "uq_resource_leases_tenant_resource_token",
        "resource_leases",
        type_="unique",
    )
