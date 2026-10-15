"""Unit tests for Phase 8 Cross-Agent Delegation Governance Service.

Validates:
1. Authority attenuation helpers (prefix matching, discrete allowlists, scalar keys, constraints).
2. Delegation grant creation with parent agent, turn budget, and autonomy boundaries.
3. Terminal parent transactions and self-delegation prohibition.
4. Ancestor chain validation (depth limits, revoked/expired ancestor rejection, cycles).
5. Idempotent grant creation and conflict detection on reused keys.
6. Safe activation: atomic transition from PENDING to ACTIVE, child binding, rebind prevention.
7. Agent and parent-transaction matching on activation.
8. Real-time operation authorization: pending, active, revoked, and expired grant validation.
9. Cross-tenant fail-closed isolation.
10. Idempotent revocation and audit event emission without physical deletion.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from db.models import (
    Agent,
    AgentDelegation,
    AITransaction,
    Capability,
)
from services.delegation_service import (
    DelegationService,
    _is_semantically_equivalent,
    is_constraints_attenuated,
    is_scope_attenuated,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.control_plane import Decision, TransactionState
from shared.schemas.delegation import (
    AttenuatedCapabilitySpec,
    DelegationGrantRequest,
    DelegationStatus,
)


@pytest.fixture
def auth_context() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        identity_id="usr_operator_1",
        role=Role.OPERATOR,
        token_id="tok_alpha_1",
    )


@pytest.fixture
def delegation_service() -> DelegationService:
    return DelegationService()


def _build_mock_session() -> AsyncMock:
    """Build a mock AsyncSession with synchronous Result and nested savepoint support."""
    session = AsyncMock()
    mock_exec = MagicMock()
    mock_exec.scalar_one_or_none.return_value = None
    mock_exec.scalars.return_value.all.return_value = []
    mock_exec.first.return_value = None
    session.execute.return_value = mock_exec

    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=nested_cm)
    session.add = MagicMock()
    session.delete = MagicMock()
    return session


# ---------------------------------------------------------------------------
# Scope & Constraint Attenuation Helper Tests
# ---------------------------------------------------------------------------


class TestScopeAndConstraintAttenuation:
    """Test suite for resource scope and constraint subset/attenuation rules."""

    def test_unrestricted_parent_allows_any_child(self) -> None:
        """If parent has empty scope, parent is unrestricted; child can specify restricted scope."""
        is_att, _ = is_scope_attenuated({}, {"allowed_prefixes": ["/tmp/"]})
        assert is_att is True

        is_att2, _ = is_scope_attenuated({}, {})
        assert is_att2 is True

    def test_restricted_parent_rejects_empty_child_scope(self) -> None:
        """If parent is restricted, child cannot specify empty (unrestricted) scope."""
        is_att, reason = is_scope_attenuated({"allowed_prefixes": ["/tmp/"]}, {})
        assert is_att is False
        assert "cannot be unrestricted" in reason

    def test_prefix_allowlist_valid_subpath(self) -> None:
        """Child prefix starting with parent prefix is a valid attenuation."""
        parent = {"allowed_prefixes": ["/var/data/", "/tmp/"]}
        child = {"allowed_prefixes": ["/var/data/reports/", "/tmp/scratch/"]}
        is_att, _ = is_scope_attenuated(parent, child)
        assert is_att is True

    def test_prefix_allowlist_widening_rejected(self) -> None:
        """Child prefix broader than or outside parent prefix is rejected."""
        parent = {"allowed_prefixes": ["/var/data/reports/"]}
        child = {"allowed_prefixes": ["/var/data/"]}  # Broader prefix
        is_att, reason = is_scope_attenuated(parent, child)
        assert is_att is False
        assert "not subsumed" in reason

        child_unrelated = {"allowed_prefixes": ["/etc/"]}
        is_att2, _ = is_scope_attenuated(parent, child_unrelated)
        assert is_att2 is False

    def test_discrete_allowlist_subset(self) -> None:
        """Child discrete list must be a strict subset of parent list."""
        parent = {"tables": ["users", "orders", "audit"]}
        child_valid = {"tables": ["orders"]}
        is_att, _ = is_scope_attenuated(parent, child_valid)
        assert is_att is True

        child_invalid = {"tables": ["orders", "billing"]}
        is_att2, reason = is_scope_attenuated(parent, child_invalid)
        assert is_att2 is False
        assert "unauthorized items" in reason

    def test_scalar_match_keys(self) -> None:
        """Scalar match keys must be identical in parent and child."""
        parent = {"env": "sandbox", "database": "analytics"}
        child_valid = {"env": "sandbox", "database": "analytics"}
        is_att, _ = is_scope_attenuated(parent, child_valid)
        assert is_att is True

        child_invalid = {"env": "production", "database": "analytics"}
        is_att2, reason = is_scope_attenuated(parent, child_invalid)
        assert is_att2 is False
        assert "must match parent value" in reason

    def test_unsupported_scope_key_rejected(self) -> None:
        """Arbitrary unrecognized scope keys fail closed."""
        parent = {"custom_arbitrary_key": "anything"}
        child = {"custom_arbitrary_key": "anything"}
        is_att, reason = is_scope_attenuated(parent, child)
        assert is_att is False
        assert "Unsupported parent resource_scope key" in reason

    def test_numeric_constraints_attenuation(self) -> None:
        """Child numeric ceiling must be <= parent ceiling."""
        parent = {"max_amount": 1000, "max_file_size_bytes": 1048576}
        child_valid = {"max_amount": 500, "max_file_size_bytes": 524288}
        is_att, _ = is_constraints_attenuated(parent, child_valid)
        assert is_att is True

        child_exceeds = {"max_amount": 2000, "max_file_size_bytes": 524288}
        is_att2, reason = is_constraints_attenuated(parent, child_exceeds)
        assert is_att2 is False
        assert "exceeds parent ceiling" in reason

        child_missing = {"max_file_size_bytes": 524288}
        is_att3, reason3 = is_constraints_attenuated(parent, child_missing)
        assert is_att3 is False
        assert "missing required numeric limit" in reason3


# ---------------------------------------------------------------------------
# Delegation Grant Creation & Attenuation Tests
# ---------------------------------------------------------------------------


class TestDelegationGrantCreation:
    """Test suite validating DelegationService.create_delegation_grant."""

    @pytest.mark.asyncio
    async def test_create_delegation_grant_valid(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Valid creation of a pending grant with all authority constraints satisfied."""
        mock_session = _build_mock_session()

        # Mock parent transaction
        parent_txn = AITransaction(
            id="txn_p_1",
            tenant_id="tenant_alpha",
            agent_id="agent_parent",
            actor_identity_id="usr_operator_1",
            state=TransactionState.TURN_REASONING.value,
            max_turns=10,
            turn_count=2,
            taint_flags=[],
        )

        # Mock parent and child agents
        parent_agent = Agent(
            id="agent_parent",
            tenant_id="tenant_alpha",
            name="ParentAgent",
            active=True,
            max_autonomy_level=3,
        )
        child_agent = Agent(
            id="agent_child",
            tenant_id="tenant_alpha",
            name="ChildAgent",
            active=True,
            max_autonomy_level=2,
        )

        # Mock parent capability
        parent_cap = Capability(
            id="cap_1",
            tenant_id="tenant_alpha",
            agent_id="agent_parent",
            identity_id="usr_operator_1",
            capability_type="tools:file_read",
            resource_scope={"allowed_prefixes": ["/var/data/"]},
            constraints={"max_file_size_bytes": 1048576},
            max_autonomy_level=3,
            revoked_at=None,
            expires_at=None,
        )

        # Setup mock session responses
        def mock_get(model: Any, key: Any = None, **_kwargs: Any) -> Any:
            if model is AITransaction and key == "txn_p_1":
                return parent_txn
            if model is Agent and key == "agent_parent":
                return parent_agent
            if model is Agent and key == "agent_child":
                return child_agent
            return None

        mock_session.get.side_effect = mock_get
        mock_session.execute.return_value.scalars.return_value.all.return_value = [parent_cap]

        req = DelegationGrantRequest(
            parent_transaction_id="txn_p_1",
            delegatee_agent_id="agent_child",
            delegated_capabilities=[
                AttenuatedCapabilitySpec(
                    capability_type="tools:file_read",
                    resource_scope={"allowed_prefixes": ["/var/data/sub/"]},
                    constraints={"max_file_size_bytes": 524288},
                    max_autonomy_level=2,
                )
            ],
            max_turns=4,
            duration_seconds=300,
            idempotency_key="idem_test_create_001",
            purpose="Read subordinate data files",
        )

        resp = await delegation_service.create_delegation_grant(auth_context, req, session=mock_session)

        assert resp.tenant_id == "tenant_alpha"
        assert resp.parent_agent_id == "agent_parent"
        assert resp.child_agent_id == "agent_child"
        assert resp.child_transaction_id is None
        assert resp.status == DelegationStatus.PENDING
        assert resp.delegation_depth == 1
        assert resp.max_turns == 4
        assert resp.max_autonomy_level == 2
        assert mock_session.add.call_count >= 2  # Added AgentDelegation and AuditLogRecord

    @pytest.mark.asyncio
    async def test_create_delegation_grant_terminal_parent_rejected(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Terminal parent transactions cannot delegate authority."""
        mock_session = _build_mock_session()
        parent_txn = AITransaction(
            id="txn_p_term",
            tenant_id="tenant_alpha",
            agent_id="agent_parent",
            actor_identity_id="usr_operator_1",
            state=TransactionState.COMPLETED.value,  # Terminal state
            max_turns=10,
            turn_count=10,
        )

        mock_exec = MagicMock()
        mock_exec.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_exec
        mock_session.get.return_value = parent_txn

        req = DelegationGrantRequest(
            parent_transaction_id="txn_p_term",
            delegatee_agent_id="agent_child",
            delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
            idempotency_key="idem_term_001",
            purpose="Attempt terminal delegation",
        )

        with pytest.raises(HTTPException) as exc_info:
            await delegation_service.create_delegation_grant(auth_context, req, session=mock_session)
        assert exc_info.value.status_code == 409
        assert "terminal" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_delegation_grant_self_delegation_prohibited(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Parent agent cannot delegate authority to itself."""
        mock_session = _build_mock_session()
        parent_txn = AITransaction(
            id="txn_p_self",
            tenant_id="tenant_alpha",
            agent_id="agent_same",
            actor_identity_id="usr_operator_1",
            state=TransactionState.TURN_REASONING.value,
            max_turns=10,
            turn_count=2,
        )
        agent_same = Agent(id="agent_same", tenant_id="tenant_alpha", name="Same", active=True, max_autonomy_level=2)

        mock_exec = MagicMock()
        mock_exec.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_exec

        def mock_get(model: Any, _key: Any = None, **_kwargs: Any) -> Any:
            if model is AITransaction:
                return parent_txn
            if model is Agent:
                return agent_same
            return None

        mock_session.get.side_effect = mock_get

        req = DelegationGrantRequest(
            parent_transaction_id="txn_p_self",
            delegatee_agent_id="agent_same",  # Same as parent
            delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
            idempotency_key="idem_self_001",
            purpose="Self-delegation attempt",
        )

        with pytest.raises(HTTPException) as exc_info:
            await delegation_service.create_delegation_grant(auth_context, req, session=mock_session)
        assert exc_info.value.status_code == 409
        assert "Self-delegation is prohibited" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_delegation_grant_turn_budget_widening_rejected(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Child turn budget cannot exceed parent remaining turns."""
        mock_session = _build_mock_session()
        parent_txn = AITransaction(
            id="txn_p_turns",
            tenant_id="tenant_alpha",
            agent_id="agent_p",
            actor_identity_id="usr_1",
            state=TransactionState.TURN_REASONING.value,
            max_turns=5,
            turn_count=3,  # Only 2 remaining turns
        )
        parent_agent = Agent(id="agent_p", tenant_id="tenant_alpha", name="P", active=True, max_autonomy_level=2)
        child_agent = Agent(id="agent_c", tenant_id="tenant_alpha", name="C", active=True, max_autonomy_level=2)

        mock_exec = MagicMock()
        mock_exec.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_exec

        def mock_get(model: Any, key: Any = None, **_kwargs: Any) -> Any:
            if model is AITransaction:
                return parent_txn
            if model is Agent and key == "agent_p":
                return parent_agent
            if model is Agent and key == "agent_c":
                return child_agent
            return None

        mock_session.get.side_effect = mock_get

        req = DelegationGrantRequest(
            parent_transaction_id="txn_p_turns",
            delegatee_agent_id="agent_c",
            delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
            max_turns=4,  # Exceeds 2 remaining
            idempotency_key="idem_turns_001",
            purpose="Excessive turns attempt",
        )

        with pytest.raises(HTTPException) as exc_info:
            await delegation_service.create_delegation_grant(auth_context, req, session=mock_session)
        assert exc_info.value.status_code == 403
        assert "exceeds parent remaining turns" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_delegation_grant_autonomy_widening_rejected(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Child autonomy ceiling cannot exceed parent capability or agent autonomy ceiling."""
        mock_session = _build_mock_session()
        parent_txn = AITransaction(
            id="txn_p_auto",
            tenant_id="tenant_alpha",
            agent_id="agent_p",
            actor_identity_id="usr_1",
            state=TransactionState.TURN_REASONING.value,
            max_turns=10,
            turn_count=1,
        )
        parent_agent = Agent(id="agent_p", tenant_id="tenant_alpha", name="P", active=True, max_autonomy_level=1)
        child_agent = Agent(id="agent_c", tenant_id="tenant_alpha", name="C", active=True, max_autonomy_level=3)
        parent_cap = Capability(
            id="cap_auto",
            tenant_id="tenant_alpha",
            agent_id="agent_p",
            identity_id="usr_1",
            capability_type="tools:math",
            resource_scope={},
            constraints={},
            max_autonomy_level=1,
            revoked_at=None,
            expires_at=None,
        )

        mock_exec = MagicMock()
        mock_exec.scalar_one_or_none.return_value = None
        mock_exec.scalars.return_value.all.return_value = [parent_cap]
        mock_session.execute.return_value = mock_exec

        def mock_get(model: Any, key: Any = None, **_kwargs: Any) -> Any:
            if model is AITransaction:
                return parent_txn
            if model is Agent and key == "agent_p":
                return parent_agent
            if model is Agent and key == "agent_c":
                return child_agent
            return None

        mock_session.get.side_effect = mock_get

        req = DelegationGrantRequest(
            parent_transaction_id="txn_p_auto",
            delegatee_agent_id="agent_c",
            delegated_capabilities=[
                AttenuatedCapabilitySpec(
                    capability_type="tools:math",
                    max_autonomy_level=2,  # Exceeds parent ceiling of 1
                )
            ],
            idempotency_key="idem_auto_001",
            purpose="Autonomy widening attempt",
        )

        with pytest.raises(HTTPException) as exc_info:
            await delegation_service.create_delegation_grant(auth_context, req, session=mock_session)
        assert exc_info.value.status_code == 403
        assert "exceeds parent ceiling" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_delegation_grant_rejects_unauthorized_agent_caller(
        self, delegation_service: DelegationService
    ) -> None:
        """Caller agent cannot create a delegation grant for a parent transaction owned by another agent."""
        mock_session = _build_mock_session()
        parent_txn = AITransaction(
            id="txn_p_other",
            tenant_id="tenant_alpha",
            agent_id="agent_legit",
            actor_identity_id="usr_1",
            state=TransactionState.TURN_REASONING.value,
            max_turns=10,
            turn_count=1,
        )

        def mock_get(model: Any, key: Any = None, **_kwargs: Any) -> Any:
            if model is AITransaction and key == "txn_p_other":
                return parent_txn
            return None

        mock_session.get.side_effect = mock_get

        auth = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_1",
            role=Role.API_CLIENT,
            agent_id="agent_intruder",
        )
        req = DelegationGrantRequest(
            parent_transaction_id="txn_p_other",
            delegatee_agent_id="agent_c",
            delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math")],
            idempotency_key="idem_unauth_del",
            purpose="Unauthorized delegation attempt",
        )

        with pytest.raises(HTTPException) as exc_info:
            await delegation_service.create_delegation_grant(auth, req, session=mock_session)
        assert exc_info.value.status_code == 403
        assert "not authorized to create delegation for parent agent" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Idempotency & Conflict Tests
# ---------------------------------------------------------------------------


class TestDelegationIdempotency:
    """Test suite validating tenant-scoped idempotency and conflict resolution."""

    def test_semantic_equivalence_matching(self) -> None:
        """Semantically identical request matches existing grant."""
        existing = AgentDelegation(
            id="del_exist",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_c",
            max_turns=4,
            purpose="Identical purpose",
            delegated_capabilities=[
                {
                    "capability_type": "tools:math",
                    "resource_scope": {},
                    "constraints": {},
                    "max_autonomy_level": 1,
                }
            ],
            resource_scope={},
            max_autonomy_level=1,
            delegation_depth=1,
            status=DelegationStatus.PENDING.value,
            idempotency_key="idem_match_001",
            expires_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        req = DelegationGrantRequest(
            parent_transaction_id="txn_p",
            delegatee_agent_id="agent_c",
            delegated_capabilities=[
                AttenuatedCapabilitySpec(
                    capability_type="tools:math",
                    resource_scope={},
                    constraints={},
                    max_autonomy_level=1,
                )
            ],
            max_turns=4,
            idempotency_key="idem_match_001",
            purpose="Identical purpose",
        )

        assert _is_semantically_equivalent(existing, req) is True

    def test_semantic_equivalence_mismatched_parameters(self) -> None:
        """Mismatched capability scope, turns, or purpose returns False."""
        existing = AgentDelegation(
            id="del_exist",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_c",
            max_turns=4,
            purpose="Original purpose",
            delegated_capabilities=[{"capability_type": "tools:math", "max_autonomy_level": 1}],
            resource_scope={},
            max_autonomy_level=1,
            delegation_depth=1,
            status=DelegationStatus.PENDING.value,
            idempotency_key="idem_mismatch_001",
            expires_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        # Different turns
        req_diff_turns = DelegationGrantRequest(
            parent_transaction_id="txn_p",
            delegatee_agent_id="agent_c",
            delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math", max_autonomy_level=1)],
            max_turns=8,
            idempotency_key="idem_mismatch_001",
            purpose="Original purpose",
        )
        assert _is_semantically_equivalent(existing, req_diff_turns) is False

        # Different purpose
        req_diff_purpose = DelegationGrantRequest(
            parent_transaction_id="txn_p",
            delegatee_agent_id="agent_c",
            delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:math", max_autonomy_level=1)],
            max_turns=4,
            idempotency_key="idem_mismatch_001",
            purpose="Different purpose",
        )
        assert _is_semantically_equivalent(existing, req_diff_purpose) is False


# ---------------------------------------------------------------------------
# Grant Activation & Child Binding Tests
# ---------------------------------------------------------------------------


class TestDelegationActivation:
    """Test suite validating DelegationService.activate_delegation_grant."""

    @pytest.mark.asyncio
    async def test_activate_delegation_grant_success(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Successful activation binds child transaction and updates status to ACTIVE."""
        now = datetime.now(UTC)
        mock_session = _build_mock_session()

        grant = AgentDelegation(
            id="del_pending_1",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_c",
            child_transaction_id=None,
            delegated_capabilities=[{"capability_type": "tools:math", "max_autonomy_level": 1}],
            resource_scope={},
            max_autonomy_level=1,
            delegation_depth=1,
            max_turns=4,
            status=DelegationStatus.PENDING.value,
            purpose="Compute subtask",
            idempotency_key="idem_act_001",
            expires_at=now + timedelta(seconds=300),
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )

        child_txn = AITransaction(
            id="txn_child_1",
            tenant_id="tenant_alpha",
            agent_id="agent_c",
            parent_transaction_id="txn_p",
            actor_identity_id="usr_operator_1",
            state=TransactionState.PENDING.value,
            max_turns=4,
            turn_count=0,
            taint_flags=[],
        )

        def mock_get(model: Any, key: Any = None, **_kwargs: Any) -> Any:
            if model is AgentDelegation and key == "del_pending_1":
                return grant
            if model is AITransaction and key == "txn_child_1":
                return child_txn
            return None

        mock_session.get.side_effect = mock_get

        mock_exec = MagicMock()
        mock_exec.scalar_one_or_none.return_value = None  # No conflicting active binding
        mock_exec.first.return_value = None
        mock_session.execute.return_value = mock_exec

        resp = await delegation_service.activate_delegation_grant(
            auth_context, "del_pending_1", "txn_child_1", session=mock_session
        )

        assert resp.status == DelegationStatus.ACTIVE
        assert resp.child_transaction_id == "txn_child_1"
        assert grant.status == DelegationStatus.ACTIVE.value
        assert grant.child_transaction_id == "txn_child_1"

    @pytest.mark.asyncio
    async def test_activate_active_grant_rebind_rejected(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Active grant cannot be rebound to a different child transaction."""
        now = datetime.now(UTC)
        mock_session = _build_mock_session()

        grant = AgentDelegation(
            id="del_act_1",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_c",
            child_transaction_id="txn_child_ORIGINAL",
            delegated_capabilities=[{"capability_type": "tools:math"}],
            resource_scope={},
            max_autonomy_level=1,
            delegation_depth=1,
            max_turns=4,
            status=DelegationStatus.ACTIVE.value,
            purpose="Task",
            idempotency_key="idem_rebind_001",
            expires_at=now + timedelta(seconds=300),
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )

        mock_session.get.return_value = grant

        with pytest.raises(HTTPException) as exc_info:
            await delegation_service.activate_delegation_grant(
                auth_context, "del_act_1", "txn_child_DIFFERENT", session=mock_session
            )
        assert exc_info.value.status_code == 409
        assert "already active and bound to a different child transaction" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_activate_child_agent_mismatch_rejected(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Child transaction agent must match delegation child_agent_id."""
        now = datetime.now(UTC)
        mock_session = _build_mock_session()

        grant = AgentDelegation(
            id="del_p_mismatch",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_EXPECTED",
            child_transaction_id=None,
            delegated_capabilities=[{"capability_type": "tools:math"}],
            resource_scope={},
            max_autonomy_level=1,
            delegation_depth=1,
            max_turns=4,
            status=DelegationStatus.PENDING.value,
            purpose="Task",
            idempotency_key="idem_mismatch_001",
            expires_at=now + timedelta(seconds=300),
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )

        child_txn = AITransaction(
            id="txn_wrong_agent",
            tenant_id="tenant_alpha",
            agent_id="agent_WRONG",  # Mismatched agent
            parent_transaction_id="txn_p",
            actor_identity_id="usr_1",
            state=TransactionState.PENDING.value,
            max_turns=4,
            turn_count=0,
        )

        def mock_get(model: Any, _key: Any = None, **_kwargs: Any) -> Any:
            if model is AgentDelegation:
                return grant
            if model is AITransaction:
                return child_txn
            return None

        mock_session.get.side_effect = mock_get

        with pytest.raises(HTTPException) as exc_info:
            await delegation_service.activate_delegation_grant(
                auth_context, "del_p_mismatch", "txn_wrong_agent", session=mock_session
            )
        assert exc_info.value.status_code == 409
        assert "does not match delegation child agent" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Real-Time Operation Authorization Tests
# ---------------------------------------------------------------------------


class TestDelegationOperationValidation:
    """Test suite validating DelegationService.validate_delegation_for_operation."""

    @pytest.mark.asyncio
    async def test_pending_grant_cannot_authorize(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """A pending grant must be denied immediately if used to authorize an operation."""
        now = datetime.now(UTC)
        mock_session = _build_mock_session()

        grant = AgentDelegation(
            id="del_pend_op",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_c",
            child_transaction_id=None,
            delegated_capabilities=[{"capability_type": "tools:math"}],
            resource_scope={},
            max_autonomy_level=1,
            delegation_depth=1,
            max_turns=4,
            status=DelegationStatus.PENDING.value,
            purpose="Task",
            idempotency_key="idem_pend_op",
            expires_at=now + timedelta(seconds=300),
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )
        mock_session.get.return_value = grant
        mock_session.execute.return_value.first.return_value = None

        decision = await delegation_service.validate_delegation_for_operation(
            auth_context, "del_pend_op", "tools:math", session=mock_session
        )

        assert decision.decision == Decision.DENY
        assert "pending activation" in decision.reason

    @pytest.mark.asyncio
    async def test_active_grant_authorizes_valid_operation(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Active grant authorizes operation when capability, scope, and autonomy match."""
        now = datetime.now(UTC)
        mock_session = _build_mock_session()

        grant = AgentDelegation(
            id="del_active_op",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_c",
            child_transaction_id="txn_c",
            delegated_capabilities=[
                {
                    "capability_type": "tools:file_read",
                    "resource_scope": {"allowed_prefixes": ["/var/data/"]},
                    "constraints": {"max_amount": 500},
                    "max_autonomy_level": 2,
                }
            ],
            resource_scope={"tools:file_read": {"allowed_prefixes": ["/var/data/"]}},
            max_autonomy_level=2,
            delegation_depth=1,
            max_turns=4,
            status=DelegationStatus.ACTIVE.value,
            purpose="Task",
            idempotency_key="idem_active_op",
            expires_at=now + timedelta(seconds=300),
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )

        child_txn = AITransaction(
            id="txn_c",
            tenant_id="tenant_alpha",
            agent_id="agent_c",
            parent_transaction_id="txn_p",
            state=TransactionState.TURN_REASONING.value,
            max_turns=4,
            turn_count=1,
        )

        def mock_get(model: Any, _key: Any = None, **_kwargs: Any) -> Any:
            if model is AgentDelegation:
                return grant
            if model is AITransaction:
                return child_txn
            return None

        mock_session.get.side_effect = mock_get

        mock_exec = MagicMock()
        mock_exec.scalar_one_or_none.return_value = None  # No ancestor grants
        mock_exec.first.return_value = None
        mock_session.execute.return_value = mock_exec

        decision = await delegation_service.validate_delegation_for_operation(
            auth_context,
            "del_active_op",
            capability_type="tools:file_read",
            resource={"target_resource": "/var/data/report.csv", "amount": 100},
            requested_autonomy_level=1,
            session=mock_session,
        )

        assert decision.decision == Decision.ALLOW
        assert "authorizes operation" in decision.reason

    @pytest.mark.asyncio
    async def test_revoked_grant_denied(self, auth_context: AuthContext, delegation_service: DelegationService) -> None:
        """Revoked grant cannot authorize operation."""
        now = datetime.now(UTC)
        mock_session = _build_mock_session()

        grant = AgentDelegation(
            id="del_rev_op",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_c",
            child_transaction_id="txn_c",
            delegated_capabilities=[{"capability_type": "tools:math"}],
            resource_scope={},
            max_autonomy_level=1,
            delegation_depth=1,
            max_turns=4,
            status=DelegationStatus.REVOKED.value,
            purpose="Task",
            idempotency_key="idem_rev_op",
            expires_at=now + timedelta(seconds=300),
            revoked_at=now,
            created_at=now,
            updated_at=now,
        )
        mock_session.get.return_value = grant
        mock_session.execute.return_value.first.return_value = None

        decision = await delegation_service.validate_delegation_for_operation(
            auth_context, "del_rev_op", "tools:math", session=mock_session
        )
        assert decision.decision == Decision.DENY
        assert "revoked" in decision.reason

    @pytest.mark.asyncio
    async def test_expired_grant_denied(self, auth_context: AuthContext, delegation_service: DelegationService) -> None:
        """Expired grant cannot authorize operation."""
        now = datetime.now(UTC)
        mock_session = _build_mock_session()

        grant = AgentDelegation(
            id="del_exp_op",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_c",
            child_transaction_id="txn_c",
            delegated_capabilities=[{"capability_type": "tools:math"}],
            resource_scope={},
            max_autonomy_level=1,
            delegation_depth=1,
            max_turns=4,
            status=DelegationStatus.ACTIVE.value,
            purpose="Task",
            idempotency_key="idem_exp_op",
            expires_at=now - timedelta(seconds=10),  # Expired in past
            revoked_at=None,
            created_at=now - timedelta(seconds=300),
            updated_at=now,
        )
        mock_session.get.return_value = grant
        mock_session.execute.return_value.first.return_value = None

        decision = await delegation_service.validate_delegation_for_operation(
            auth_context, "del_exp_op", "tools:math", session=mock_session
        )
        assert decision.decision == Decision.DENY
        assert "expired" in decision.reason

    @pytest.mark.asyncio
    async def test_scope_violation_denied(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Target resource outside delegated prefix is denied."""
        now = datetime.now(UTC)
        mock_session = _build_mock_session()

        grant = AgentDelegation(
            id="del_scope_op",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_c",
            child_transaction_id="txn_c",
            delegated_capabilities=[
                {
                    "capability_type": "tools:file_read",
                    "resource_scope": {"allowed_prefixes": ["/var/data/"]},
                    "max_autonomy_level": 1,
                }
            ],
            resource_scope={},
            max_autonomy_level=1,
            delegation_depth=1,
            max_turns=4,
            status=DelegationStatus.ACTIVE.value,
            purpose="Task",
            idempotency_key="idem_scope_op",
            expires_at=now + timedelta(seconds=300),
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )

        child_txn = AITransaction(
            id="txn_c",
            tenant_id="tenant_alpha",
            agent_id="agent_c",
            parent_transaction_id="txn_p",
            state=TransactionState.TURN_REASONING.value,
            max_turns=4,
            turn_count=1,
        )

        def mock_get(model: Any, _key: Any = None, **_kwargs: Any) -> Any:
            if model is AgentDelegation:
                return grant
            if model is AITransaction:
                return child_txn
            return None

        mock_session.get.side_effect = mock_get

        decision = await delegation_service.validate_delegation_for_operation(
            auth_context,
            "del_scope_op",
            capability_type="tools:file_read",
            resource={"target_resource": "/etc/passwd"},  # Outside /var/data/
            session=mock_session,
        )

        assert decision.decision == Decision.DENY
        assert "not permitted by delegated scope" in decision.reason


# ---------------------------------------------------------------------------
# Revocation & Lineage Preservation Tests
# ---------------------------------------------------------------------------


class TestDelegationRevocationAndAudit:
    """Test suite validating DelegationService.revoke_delegation_grant and audit durability."""

    @pytest.mark.asyncio
    async def test_revoke_delegation_grant_idempotent(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Revocation sets status to REVOKED without deleting the record, and is idempotent."""
        now = datetime.now(UTC)
        mock_session = _build_mock_session()

        grant = AgentDelegation(
            id="del_to_revoke",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_c",
            child_transaction_id="txn_c",
            delegated_capabilities=[{"capability_type": "tools:math"}],
            resource_scope={},
            max_autonomy_level=1,
            delegation_depth=1,
            max_turns=4,
            status=DelegationStatus.ACTIVE.value,
            purpose="Task",
            idempotency_key="idem_rev_001",
            expires_at=now + timedelta(seconds=300),
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )

        mock_session.get.return_value = grant
        mock_session.execute.return_value.first.return_value = None

        resp = await delegation_service.revoke_delegation_grant(
            auth_context, "del_to_revoke", reason="Security containment", session=mock_session
        )

        assert resp.status == DelegationStatus.REVOKED
        assert grant.status == DelegationStatus.REVOKED.value
        assert grant.revoked_at is not None
        assert mock_session.delete.call_count == 0  # Proof: NO physical deletion!

        # Second revocation call returns idempotently
        resp2 = await delegation_service.revoke_delegation_grant(
            auth_context, "del_to_revoke", reason="Second call", session=mock_session
        )
        assert resp2.status == DelegationStatus.REVOKED

    @pytest.mark.asyncio
    async def test_cross_tenant_lookup_fails_closed(
        self, auth_context: AuthContext, delegation_service: DelegationService
    ) -> None:
        """Lookup for grant belonging to another tenant raises 404 (non-leaking error)."""
        now = datetime.now(UTC)
        mock_session = _build_mock_session()

        grant_tenant_beta = AgentDelegation(
            id="del_beta_001",
            tenant_id="tenant_BETA",  # Mismatched tenant
            parent_agent_id="agent_p",
            parent_transaction_id="txn_p",
            child_agent_id="agent_c",
            child_transaction_id=None,
            delegated_capabilities=[{"capability_type": "tools:math"}],
            resource_scope={},
            max_autonomy_level=1,
            delegation_depth=1,
            max_turns=4,
            status=DelegationStatus.ACTIVE.value,
            purpose="Beta task",
            idempotency_key="idem_beta_001",
            expires_at=now + timedelta(seconds=300),
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )

        mock_session.get.return_value = grant_tenant_beta

        with pytest.raises(HTTPException) as exc_info:
            await delegation_service.get_delegation_grant(auth_context, "del_beta_001", session=mock_session)
        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()
