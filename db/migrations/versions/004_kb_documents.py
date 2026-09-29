"""PostgreSQL schema and RLS policies for knowledge base documents.

Revision ID: 004_kb_documents
Revises: 003_alerts_and_reports
Create Date: 2026-09-25 22:00:00.000000

Implements Technical Architecture §2.10, Security & Access §9.1, and ADR 0005:
- kb_documents table with durable metadata, content hashes, and chunks count
- Deterministic document identity scoped per tenant
- PostgreSQL Row-Level Security (RLS) policies for strict multi-tenant isolation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_kb_documents"
down_revision: str | None = "003_alerts_and_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_documents",
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("chunks_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("collection_name", sa.String(length=128), server_default="default_kb", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="INDEXED", nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id"),
        sa.UniqueConstraint("tenant_id", "filename", name="uq_kb_documents_tenant_filename"),
    )
    op.create_index("ix_kb_documents_tenant_id", "kb_documents", ["tenant_id"])
    op.create_index("ix_kb_documents_content_hash", "kb_documents", ["content_hash"])
    op.create_index("ix_kb_documents_created_at", "kb_documents", ["created_at"])

    # Enable and enforce Row-Level Security on kb_documents
    op.execute("ALTER TABLE kb_documents ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE kb_documents FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_kb_documents ON kb_documents
            FOR ALL
            USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_kb_documents ON kb_documents;")
    op.drop_index("ix_kb_documents_created_at", table_name="kb_documents")
    op.drop_index("ix_kb_documents_content_hash", table_name="kb_documents")
    op.drop_index("ix_kb_documents_tenant_id", table_name="kb_documents")
    op.drop_table("kb_documents")
