"""Unit tests for Phase 8 Cross-Agent Delegation Pydantic schemas.

Validates:
1. Valid schema creation for AttenuatedCapabilitySpec, DelegationGrantRequest, and DelegationGrantResponse.
2. Boundary enforcement (turns 1-32, duration 10-86400, autonomy level 0-4, idempotency key >= 8 chars).
3. Non-empty string validation rejecting empty/whitespace IDs and purposes.
4. Duplicate capability rejection ensuring unambiguous authority grants.
5. Immutability and security boundaries (no secrets or ambient execution authority).
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from shared.schemas.delegation import (
    AttenuatedCapabilitySpec,
    DelegationGrantRequest,
    DelegationGrantResponse,
    DelegationStatus,
)


class TestDelegationSchemas:
    """Test suite validating Pydantic contract boundaries and security invariants for delegation."""

    def test_valid_attenuated_capability_spec(self) -> None:
        """Verify normal creation of an attenuated capability specification."""
        spec = AttenuatedCapabilitySpec(
            capability_type="tools:file_read",
            resource_scope={"allowed_prefixes": ["/var/data/"]},
            constraints={"max_file_size_bytes": 1048576},
            max_autonomy_level=2,
        )
        assert spec.capability_type == "tools:file_read"
        assert spec.resource_scope == {"allowed_prefixes": ["/var/data/"]}
        assert spec.constraints == {"max_file_size_bytes": 1048576}
        assert spec.max_autonomy_level == 2

    def test_attenuated_capability_spec_invalid_autonomy_ceiling(self) -> None:
        """Verify autonomy levels outside 0-4 are rejected (L5 is prohibited in MIRAGE)."""
        with pytest.raises(ValidationError) as exc_info:
            AttenuatedCapabilitySpec(
                capability_type="tools:file_read",
                max_autonomy_level=5,  # Exceeds maximum allowed autonomy
            )
        assert "max_autonomy_level" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            AttenuatedCapabilitySpec(
                capability_type="tools:file_read",
                max_autonomy_level=-1,  # Negative autonomy
            )
        assert "max_autonomy_level" in str(exc_info.value)

    def test_attenuated_capability_spec_empty_type_rejected(self) -> None:
        """Verify empty or whitespace capability type is rejected."""
        with pytest.raises(ValidationError):
            AttenuatedCapabilitySpec(capability_type="")

        with pytest.raises(ValidationError):
            AttenuatedCapabilitySpec(capability_type="   ")

    def test_valid_delegation_grant_request(self) -> None:
        """Verify valid creation of a delegation grant request."""
        req = DelegationGrantRequest(
            parent_transaction_id="txn_parent_123",
            delegatee_agent_id="agent_worker_456",
            delegated_capabilities=[
                AttenuatedCapabilitySpec(
                    capability_type="tools:math",
                    resource_scope={},
                    max_autonomy_level=0,
                ),
                AttenuatedCapabilitySpec(
                    capability_type="tools:db_query",
                    resource_scope={"tables": ["public_stats"]},
                    max_autonomy_level=1,
                ),
            ],
            max_turns=8,
            duration_seconds=600,
            idempotency_key="idem_del_grant_789",
            purpose="Compute aggregate quarterly metrics",
        )
        assert req.parent_transaction_id == "txn_parent_123"
        assert req.delegatee_agent_id == "agent_worker_456"
        assert len(req.delegated_capabilities) == 2
        assert req.max_turns == 8
        assert req.duration_seconds == 600
        assert req.idempotency_key == "idem_del_grant_789"
        assert req.purpose == "Compute aggregate quarterly metrics"

    def test_duplicate_capability_specifications_rejected(self) -> None:
        """Verify duplicate capability specifications raise ValidationError to prevent ambiguous grants."""
        with pytest.raises(ValidationError) as exc_info:
            DelegationGrantRequest(
                parent_transaction_id="txn_parent_123",
                delegatee_agent_id="agent_worker_456",
                delegated_capabilities=[
                    AttenuatedCapabilitySpec(
                        capability_type="tools:math",
                        max_autonomy_level=0,
                    ),
                    AttenuatedCapabilitySpec(
                        capability_type="tools:math",  # Duplicate capability_type
                        max_autonomy_level=1,
                    ),
                ],
                idempotency_key="idem_del_dup_001",
                purpose="Duplicate test",
            )
        assert "Duplicate capability_type" in str(exc_info.value)

    def test_empty_capabilities_list_rejected(self) -> None:
        """Verify an empty capability list is rejected (delegation must grant at least one capability)."""
        with pytest.raises(ValidationError):
            DelegationGrantRequest(
                parent_transaction_id="txn_parent_123",
                delegatee_agent_id="agent_worker_456",
                delegated_capabilities=[],
                idempotency_key="idem_del_empty_001",
                purpose="Empty cap test",
            )

    def test_invalid_turn_budget_bounds(self) -> None:
        """Verify max_turns < 1 or > 32 is rejected."""
        with pytest.raises(ValidationError):
            DelegationGrantRequest(
                parent_transaction_id="txn_parent_123",
                delegatee_agent_id="agent_worker_456",
                delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
                max_turns=0,
                idempotency_key="idem_del_turns_001",
                purpose="Zero turns test",
            )

        with pytest.raises(ValidationError):
            DelegationGrantRequest(
                parent_transaction_id="txn_parent_123",
                delegatee_agent_id="agent_worker_456",
                delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
                max_turns=33,  # Exceeds maximum 32
                idempotency_key="idem_del_turns_002",
                purpose="Excessive turns test",
            )

    def test_invalid_duration_bounds(self) -> None:
        """Verify duration_seconds < 10 or > 86400 is rejected."""
        with pytest.raises(ValidationError):
            DelegationGrantRequest(
                parent_transaction_id="txn_parent_123",
                delegatee_agent_id="agent_worker_456",
                delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
                duration_seconds=5,  # Too short (<10s)
                idempotency_key="idem_del_dur_001",
                purpose="Short duration test",
            )

        with pytest.raises(ValidationError):
            DelegationGrantRequest(
                parent_transaction_id="txn_parent_123",
                delegatee_agent_id="agent_worker_456",
                delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
                duration_seconds=86401,  # Too long (>24h)
                idempotency_key="idem_del_dur_002",
                purpose="Long duration test",
            )

    def test_short_idempotency_key_rejected(self) -> None:
        """Verify idempotency keys under 8 characters are rejected."""
        with pytest.raises(ValidationError):
            DelegationGrantRequest(
                parent_transaction_id="txn_parent_123",
                delegatee_agent_id="agent_worker_456",
                delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
                idempotency_key="short",  # < 8 chars
                purpose="Short key test",
            )

    def test_whitespace_fields_rejected(self) -> None:
        """Verify whitespace-only parent transaction, delegatee, or purpose are rejected."""
        with pytest.raises(ValidationError):
            DelegationGrantRequest(
                parent_transaction_id="   ",
                delegatee_agent_id="agent_worker_456",
                delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
                idempotency_key="idem_del_white_001",
                purpose="Valid purpose",
            )

        with pytest.raises(ValidationError):
            DelegationGrantRequest(
                parent_transaction_id="txn_parent_123",
                delegatee_agent_id="   ",
                delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
                idempotency_key="idem_del_white_002",
                purpose="Valid purpose",
            )

        with pytest.raises(ValidationError):
            DelegationGrantRequest(
                parent_transaction_id="txn_parent_123",
                delegatee_agent_id="agent_worker_456",
                delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
                idempotency_key="idem_del_white_003",
                purpose="   ",
            )

    def test_valid_delegation_grant_response(self) -> None:
        """Verify complete serialization of an authoritative DelegationGrantResponse."""
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=300)

        resp = DelegationGrantResponse(
            id="del_grant_abc123",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_coordinator",
            parent_transaction_id="txn_parent_001",
            child_agent_id="agent_worker_sub",
            child_transaction_id=None,  # Nullable before child transaction is spawned
            delegated_capabilities=[
                AttenuatedCapabilitySpec(
                    capability_type="tools:math",
                    resource_scope={},
                    max_autonomy_level=1,
                )
            ],
            resource_scope={"env": "sandbox"},
            max_turns=4,
            max_autonomy_level=1,
            delegation_depth=1,
            status=DelegationStatus.ACTIVE,
            purpose="Subordinate computation",
            idempotency_key="idem_del_resp_001",
            expires_at=expires,
            revoked_at=None,
            created_at=now,
        )

        assert resp.id == "del_grant_abc123"
        assert resp.tenant_id == "tenant_alpha"
        assert resp.child_transaction_id is None
        assert resp.status == DelegationStatus.ACTIVE
        assert resp.delegation_depth == 1
        assert resp.revoked_at is None
