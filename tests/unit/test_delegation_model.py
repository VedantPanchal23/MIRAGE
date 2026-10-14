"""Unit tests for Phase 8 AgentDelegation SQLAlchemy ORM model.

Validates:
1. ORM table configuration, column types, nullabilities, and defaults.
2. Nullability of child_transaction_id allowing pre-child grant creation.
3. Foreign key constraints and ondelete="RESTRICT" preserving security audit lineage.
4. Tenant-scoped idempotency uniqueness constraint.
5. Index definitions for tenant-scoped parent/child lookups, status, and expiry sweeps.
"""

from db.models import AgentDelegation


class TestAgentDelegationModel:
    """Test suite validating SQLAlchemy ORM model definition for AgentDelegation."""

    def test_table_name_and_metadata(self) -> None:
        """Verify the table name is 'agent_delegations'."""
        assert AgentDelegation.__tablename__ == "agent_delegations"

    def test_columns_and_nullability(self) -> None:
        """Verify all mandatory and nullable columns exist with expected configurations."""
        table = AgentDelegation.__table__

        # Mandatory columns
        assert table.c.id.nullable is False
        assert table.c.tenant_id.nullable is False
        assert table.c.parent_agent_id.nullable is False
        assert table.c.parent_transaction_id.nullable is False
        assert table.c.child_agent_id.nullable is False
        assert table.c.delegated_capabilities.nullable is False
        assert table.c.resource_scope.nullable is False
        assert table.c.max_autonomy_level.nullable is False
        assert table.c.delegation_depth.nullable is False
        assert table.c.max_turns.nullable is False
        assert table.c.status.nullable is False
        assert table.c.purpose.nullable is False
        assert table.c.idempotency_key.nullable is False
        assert table.c.expires_at.nullable is False
        assert table.c.created_at.nullable is False
        assert table.c.updated_at.nullable is False

        # Lifecycle nullable columns
        # Crucial invariant: child_transaction_id must be nullable so grant exists before child transaction
        assert table.c.child_transaction_id.nullable is True
        # Revocation timestamp is None until explicitly revoked
        assert table.c.revoked_at.nullable is True

    def test_foreign_key_audit_preservation_semantics(self) -> None:
        """Verify foreign keys use ondelete='RESTRICT' for transactions and agents to preserve audit lineage."""
        table = AgentDelegation.__table__

        fks = {fk.parent.name: fk for fk in table.foreign_keys}

        assert "tenant_id" in fks
        assert fks["tenant_id"].target_fullname == "tenants.id"
        assert fks["tenant_id"].ondelete == "CASCADE"

        assert "parent_agent_id" in fks
        assert fks["parent_agent_id"].target_fullname == "agents.id"
        assert fks["parent_agent_id"].ondelete == "RESTRICT"

        assert "parent_transaction_id" in fks
        assert fks["parent_transaction_id"].target_fullname == "ai_transactions.id"
        assert fks["parent_transaction_id"].ondelete == "RESTRICT"

        assert "child_agent_id" in fks
        assert fks["child_agent_id"].target_fullname == "agents.id"
        assert fks["child_agent_id"].ondelete == "RESTRICT"

        assert "child_transaction_id" in fks
        assert fks["child_transaction_id"].target_fullname == "ai_transactions.id"
        assert fks["child_transaction_id"].ondelete == "RESTRICT"

    def test_unique_constraint_on_tenant_idempotency(self) -> None:
        """Verify unique constraint on (tenant_id, idempotency_key)."""
        table = AgentDelegation.__table__

        unique_names = {u.name for u in table.constraints if hasattr(u, "columns")}
        assert "uq_agent_delegations_tenant_idempotency" in unique_names

        # Verify the columns involved in the uniqueness constraint
        for constraint in table.constraints:
            if constraint.name == "uq_agent_delegations_tenant_idempotency":
                col_names = [col.name for col in constraint.columns]
                assert col_names == ["tenant_id", "idempotency_key"]

    def test_composite_indexes_configured(self) -> None:
        """Verify tenant-scoped lookup indexes are configured."""
        table = AgentDelegation.__table__

        index_names = {idx.name for idx in table.indexes}
        assert "ix_agent_delegations_tenant_parent_txn" in index_names
        assert "ix_agent_delegations_tenant_child_txn" in index_names
        assert "ix_agent_delegations_tenant_status" in index_names
        assert "ix_agent_delegations_tenant_expires" in index_names
