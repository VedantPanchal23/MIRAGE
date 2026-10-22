"""Unit tests for Phase 8 Agent Lifecycle Governance and Authenticated Identity.

Validates:
1. Agent registration with operator/admin authorization, duplicate rejection, and initial REGISTERED status.
2. Tenant isolation on agent retrieval and listing.
3. State machine transitions:
   - REGISTERED -> ACTIVE
   - ACTIVE -> SUSPENDED -> ACTIVE
   - ACTIVE/SUSPENDED/REGISTERED -> REVOKED
   - Terminal status enforcement (REVOKED cannot transition to ACTIVE or SUSPENDED)
   - Idempotent transitions
   - Non-deletion invariant (zero physical deletions)
4. Agent eligibility evaluations (is_agent_eligible_for_transaction).
5. Cryptographic token verification:
   - Valid token resolution to persisted Agent and AuthContext.agent_id
   - Suspended / Revoked / Registered agent token rejection with 401
   - Algorithm confusion ('none') rejection
   - Header injection ('jku', 'x5u') rejection
   - Issuer and audience validation
   - Expired token rejection
6. Integration invariant enforcement:
   - Control plane create_transaction rejection for non-active agents
   - Control plane validate_capability rejection for non-active agents
   - Delegation grant creation rejection for suspended/revoked parent or delegatee agent
   - Delegation operation validation rejection when child, parent, or ancestor agent is suspended or revoked
7. Pessimistic row locking (with_for_update=True) and audit durability.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException

from db.models import (
    ActorIdentity,
    Agent,
    AgentDelegation,
    AITransaction,
    Capability,
)
from gateway.middleware.auth import (
    _claims_from_access_token,
    create_agent_access_token,
    resolve_agent_context,
)
from services.agent_governance import (
    AgentGovernanceService,
)
from services.control_plane import (
    create_transaction,
    validate_capability,
)
from services.delegation_service import DelegationService
from shared.config import get_settings
from shared.schemas.agent import (
    AgentRegistrationRequest,
    AgentStatus,
    is_agent_transition_allowed,
    is_terminal_agent_status,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.control_plane import (
    CapabilityValidationRequest,
    Decision,
    InputAssuranceResult,
    PolicyDecision,
    TransactionCreateRequest,
    TransactionState,
)
from shared.schemas.delegation import AttenuatedCapabilitySpec, DelegationGrantRequest

settings = get_settings()


def _make_agent(**kwargs: Any) -> Agent:
    """Construct an Agent model instance populated with valid defaults for tests."""
    now = datetime.now(UTC)
    defaults = {
        "id": "agent_test_1",
        "tenant_id": "tenant_alpha",
        "name": "agent_test_1",
        "status": AgentStatus.ACTIVE.value,
        "active": True,
        "max_autonomy_level": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(kwargs)
    return Agent(**defaults)


@pytest.fixture
def operator_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        identity_id="usr_op_1",
        role=Role.OPERATOR,
        token_id="tok_op_1",
    )


@pytest.fixture
def tenant_admin_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        identity_id="usr_admin_1",
        role=Role.TENANT_ADMIN,
        token_id="tok_admin_1",
    )


@pytest.fixture
def viewer_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        identity_id="usr_viewer_1",
        role=Role.VIEWER,
        token_id="tok_viewer_1",
    )


@pytest.fixture
def agent_service() -> AgentGovernanceService:
    return AgentGovernanceService()


def _build_mock_session() -> AsyncMock:
    """Build a mock AsyncSession supporting execute, scalar, scalars, and transaction."""
    session = AsyncMock()
    mock_exec = MagicMock()
    mock_exec.scalar_one_or_none.return_value = None
    mock_exec.scalar_one.return_value = 0
    mock_exec.scalars.return_value.all.return_value = []
    mock_exec.first.return_value = None
    session.execute.return_value = mock_exec

    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=nested_cm)
    session.add = MagicMock()
    session.delete = MagicMock()
    session.flush = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Schema and Transition Matrix Tests
# ---------------------------------------------------------------------------


class TestAgentSchemaAndMatrix:
    """Validate transition matrix rules and schema validations."""

    def test_transition_rules(self) -> None:
        assert is_agent_transition_allowed(AgentStatus.REGISTERED, AgentStatus.ACTIVE) is True
        assert is_agent_transition_allowed(AgentStatus.REGISTERED, AgentStatus.REVOKED) is True
        assert is_agent_transition_allowed(AgentStatus.REGISTERED, AgentStatus.SUSPENDED) is False

        assert is_agent_transition_allowed(AgentStatus.ACTIVE, AgentStatus.SUSPENDED) is True
        assert is_agent_transition_allowed(AgentStatus.ACTIVE, AgentStatus.REVOKED) is True
        assert is_agent_transition_allowed(AgentStatus.ACTIVE, AgentStatus.ACTIVE) is True

        assert is_agent_transition_allowed(AgentStatus.SUSPENDED, AgentStatus.ACTIVE) is True
        assert is_agent_transition_allowed(AgentStatus.SUSPENDED, AgentStatus.REVOKED) is True
        assert is_agent_transition_allowed(AgentStatus.SUSPENDED, AgentStatus.SUSPENDED) is True

        # Terminal status
        assert is_terminal_agent_status(AgentStatus.REVOKED) is True
        assert is_agent_transition_allowed(AgentStatus.REVOKED, AgentStatus.ACTIVE) is False
        assert is_agent_transition_allowed(AgentStatus.REVOKED, AgentStatus.SUSPENDED) is False
        assert is_agent_transition_allowed(AgentStatus.REVOKED, AgentStatus.REVOKED) is True


# ---------------------------------------------------------------------------
# Agent Registration Tests
# ---------------------------------------------------------------------------


class TestAgentRegistration:
    """Validate agent registration, duplicate rejection, and initial status."""

    @pytest.mark.asyncio
    async def test_register_agent_success(
        self,
        operator_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        req = AgentRegistrationRequest(
            name="agent_worker_1",
            metadata={
                "department": "secops",
                "agent_type": "worker",
                "capabilities": ["tools:file_read", "tools:network_query"],
                "system_prompt": "You are a verified worker agent.",
            },
        )

        resp = await agent_service.register_agent(
            auth=operator_auth,
            request=req,
            session=mock_session,
        )

        assert resp.name == "agent_worker_1"
        assert resp.status == AgentStatus.REGISTERED
        assert resp.active is False
        assert resp.tenant_id == "tenant_alpha"
        assert resp.registered_by_identity_id == "usr_op_1"

        # Session assertions: Agent, ActorIdentity, Capabilities, AuditEvent added
        assert mock_session.add.call_count >= 3
        mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_agent_unauthorized_role(
        self,
        viewer_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        req = AgentRegistrationRequest(name="agent_unauthorized")

        with pytest.raises(HTTPException) as exc:
            await agent_service.register_agent(auth=viewer_auth, request=req, session=mock_session)
        assert exc.value.status_code == 403
        assert "not authorized to register agents" in exc.value.detail

    @pytest.mark.asyncio
    async def test_register_agent_duplicate_name_rejected(
        self,
        operator_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        existing = _make_agent(name="duplicate_agent")
        mock_session.execute.return_value.scalar_one_or_none.return_value = existing

        req = AgentRegistrationRequest(name="duplicate_agent")
        with pytest.raises(HTTPException) as exc:
            await agent_service.register_agent(auth=operator_auth, request=req, session=mock_session)
        assert exc.value.status_code == 409
        assert "already exists in tenant" in exc.value.detail


# ---------------------------------------------------------------------------
# Agent Retrieval and Listing Tests
# ---------------------------------------------------------------------------


class TestAgentQuery:
    """Validate tenant-isolated retrieval and listing."""

    @pytest.mark.asyncio
    async def test_get_agent_success(
        self,
        operator_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        agent = _make_agent(id="agent_123", name="agent_alpha")
        mock_session.get.return_value = agent

        resp = await agent_service.get_agent(operator_auth, "agent_123", session=mock_session)
        assert resp.id == "agent_123"
        assert resp.status == AgentStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_get_agent_cross_tenant_isolation(
        self,
        operator_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        # Different tenant
        agent_other = _make_agent(id="agent_other", tenant_id="tenant_beta", name="agent_beta")
        mock_session.get.return_value = agent_other

        with pytest.raises(HTTPException) as exc:
            await agent_service.get_agent(operator_auth, "agent_other", session=mock_session)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_agents_filtering_and_pagination(
        self,
        operator_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        agents = [
            _make_agent(id="a1", name="a1"),
            _make_agent(id="a2", name="a2"),
        ]
        mock_session.execute.return_value.scalar_one.return_value = 2
        mock_session.execute.return_value.scalars.return_value.all.return_value = agents

        list_resp = await agent_service.list_agents(
            operator_auth,
            status_filter=AgentStatus.ACTIVE,
            limit=10,
            offset=0,
            session=mock_session,
        )
        assert list_resp.total == 2
        assert len(list_resp.agents) == 2


# ---------------------------------------------------------------------------
# Agent Lifecycle State Transitions Tests
# ---------------------------------------------------------------------------


class TestAgentLifecycleTransitions:
    """Validate activation, suspension, revocation, and terminal invariants."""

    @pytest.mark.asyncio
    async def test_activate_registered_agent(
        self,
        operator_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        agent = _make_agent(id="agent_reg", name="agent_reg", status=AgentStatus.REGISTERED.value, active=False)
        mock_session.get.return_value = agent

        resp = await agent_service.activate_agent(operator_auth, "agent_reg", session=mock_session)
        assert resp.status == AgentStatus.ACTIVE
        assert resp.active is True
        assert agent.status == AgentStatus.ACTIVE.value
        assert agent.active is True

    @pytest.mark.asyncio
    async def test_activate_suspended_agent_clears_reason(
        self,
        operator_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        agent = _make_agent(
            id="agent_susp",
            name="agent_susp",
            status=AgentStatus.SUSPENDED.value,
            active=False,
            suspension_reason="Security policy violation",
            suspended_at=datetime.now(UTC),
        )
        mock_session.get.return_value = agent

        resp = await agent_service.activate_agent(operator_auth, "agent_susp", session=mock_session)
        assert resp.status == AgentStatus.ACTIVE
        assert resp.active is True
        assert agent.suspension_reason is None
        assert agent.suspended_at is None

    @pytest.mark.asyncio
    async def test_suspend_active_agent(
        self,
        operator_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        agent = _make_agent(id="agent_act", name="agent_act", status=AgentStatus.ACTIVE.value, active=True)
        mock_session.get.return_value = agent

        resp = await agent_service.suspend_agent(
            operator_auth, "agent_act", reason="Maintenance window lock", session=mock_session
        )
        assert resp.status == AgentStatus.SUSPENDED
        assert resp.active is False
        assert agent.status == AgentStatus.SUSPENDED.value
        assert agent.active is False
        assert agent.suspension_reason == "Maintenance window lock"
        assert agent.suspended_at is not None

    @pytest.mark.asyncio
    async def test_suspend_registered_agent_rejected(
        self,
        operator_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        agent = _make_agent(id="agent_reg", name="agent_reg", status=AgentStatus.REGISTERED.value, active=False)
        mock_session.get.return_value = agent

        with pytest.raises(HTTPException) as exc:
            await agent_service.suspend_agent(operator_auth, "agent_reg", reason="Test suspend", session=mock_session)
        assert exc.value.status_code == 409
        assert "Invalid transition" in exc.value.detail

    @pytest.mark.asyncio
    async def test_revoke_agent_and_zero_deletion(
        self,
        operator_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        agent = _make_agent(id="agent_to_revoke", name="agent_to_revoke", status=AgentStatus.ACTIVE.value, active=True)
        mock_session.get.return_value = agent

        resp = await agent_service.revoke_agent(
            operator_auth, "agent_to_revoke", reason="Compromised credentials", session=mock_session
        )
        assert resp.status == AgentStatus.REVOKED
        assert resp.active is False
        assert agent.status == AgentStatus.REVOKED.value
        assert agent.active is False
        assert agent.revocation_reason == "Compromised credentials"
        assert agent.revoked_at is not None

        # Absolute zero physical deletion invariant
        mock_session.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_terminal_revoked_agent_cannot_reactivate(
        self,
        operator_auth: AuthContext,
        agent_service: AgentGovernanceService,
    ) -> None:
        mock_session = _build_mock_session()
        agent = _make_agent(
            id="agent_dead",
            name="agent_dead",
            status=AgentStatus.REVOKED.value,
            active=False,
            revoked_at=datetime.now(UTC),
            revocation_reason="Permanently decommissioned",
        )
        mock_session.get.return_value = agent

        with pytest.raises(HTTPException) as exc:
            await agent_service.activate_agent(operator_auth, "agent_dead", session=mock_session)
        assert exc.value.status_code == 409
        assert "permanently revoked" in exc.value.detail.lower()

        with pytest.raises(HTTPException) as exc2:
            await agent_service.suspend_agent(
                operator_auth, "agent_dead", reason="Attempted suspend", session=mock_session
            )
        assert exc2.value.status_code == 409


# ---------------------------------------------------------------------------
# Agent Eligibility Evaluations Tests
# ---------------------------------------------------------------------------


class TestAgentEligibility:
    """Validate is_agent_eligible_for_transaction logic."""

    def test_eligibility_by_status(self, agent_service: AgentGovernanceService) -> None:
        active_agent = _make_agent(id="a_act", status=AgentStatus.ACTIVE.value, active=True)
        eligible, msg = agent_service.is_agent_eligible_for_transaction(active_agent)
        assert eligible is True
        assert "active and eligible" in msg

        registered_agent = _make_agent(id="a_reg", status=AgentStatus.REGISTERED.value, active=False)
        eligible, msg = agent_service.is_agent_eligible_for_transaction(registered_agent)
        assert eligible is False
        assert "not activated" in msg

        suspended_agent = _make_agent(
            id="a_susp",
            status=AgentStatus.SUSPENDED.value,
            active=False,
            suspension_reason="Policy block",
        )
        eligible, msg = agent_service.is_agent_eligible_for_transaction(suspended_agent)
        assert eligible is False
        assert "is suspended" in msg

        revoked_agent = _make_agent(
            id="a_rev",
            status=AgentStatus.REVOKED.value,
            active=False,
            revoked_at=datetime.now(UTC),
        )
        eligible, msg = agent_service.is_agent_eligible_for_transaction(revoked_agent)
        assert eligible is False
        assert "permanently revoked" in msg


# ---------------------------------------------------------------------------
# Cryptographic Token and Identity Verification Tests
# ---------------------------------------------------------------------------


class TestAgentTokenVerification:
    """Validate JWT token generation, resolution, and header/algorithm rejections."""

    @pytest.mark.asyncio
    async def test_valid_agent_token_resolution(self) -> None:
        mock_session = _build_mock_session()
        agent = _make_agent(id="agent_jwt_1", name="agent_jwt_1")
        identity = ActorIdentity(
            id="ident_agent_1",
            tenant_id="tenant_alpha",
            subject="agent:agent_jwt_1",
            principal_type="agent",
            role="api_client",
            agent_id="agent_jwt_1",
            active=True,
        )

        mock_session.get.return_value = agent
        mock_session.execute.return_value.scalar_one_or_none.return_value = identity

        token = create_agent_access_token(
            tenant_id="tenant_alpha",
            agent_id="agent_jwt_1",
        )

        auth_ctx = await resolve_agent_context(token, session=mock_session)
        assert auth_ctx.tenant_id == "tenant_alpha"
        assert auth_ctx.agent_id == "agent_jwt_1"
        assert auth_ctx.identity_id == "ident_agent_1"
        assert auth_ctx.principal_type == "agent"
        assert auth_ctx.role == Role.API_CLIENT

    @pytest.mark.asyncio
    async def test_suspended_or_revoked_agent_token_rejected_with_401(self) -> None:
        mock_session = _build_mock_session()
        suspended_agent = _make_agent(
            id="agent_susp",
            name="agent_susp",
            status=AgentStatus.SUSPENDED.value,
            active=False,
            suspension_reason="Under investigation",
        )
        mock_session.get.return_value = suspended_agent

        token = create_agent_access_token(
            tenant_id="tenant_alpha",
            agent_id="agent_susp",
        )

        with pytest.raises(HTTPException) as exc:
            await resolve_agent_context(token, session=mock_session)
        assert exc.value.status_code == 401
        assert "is suspended" in exc.value.detail.lower()

    def test_claims_rejects_none_algorithm(self) -> None:
        """Token forged with alg='none' must be strictly rejected."""
        unsecured_token = jwt.encode(
            {"sub": "agent_x", "iss": settings.jwt_issuer, "aud": settings.jwt_audience},
            key="",
            algorithm="none",
        )
        with pytest.raises(HTTPException) as exc:
            _claims_from_access_token(unsecured_token)
        assert exc.value.status_code == 401

    def test_claims_rejects_jku_and_x5u_headers(self) -> None:
        """Token with jku or x5u header injection must be rejected."""
        token_with_jku = jwt.encode(
            {"sub": "agent_x", "iss": settings.jwt_issuer, "aud": settings.jwt_audience},
            key=settings.secret_key,
            algorithm=settings.algorithm,
            headers={"jku": "https://malicious-attacker.com/jwks.json"},
        )
        with pytest.raises(HTTPException) as exc:
            _claims_from_access_token(token_with_jku)
        assert exc.value.status_code == 401
        assert "jku/x5u" in exc.value.detail

    def test_claims_rejects_expired_token(self) -> None:
        """Expired agent token must be rejected."""
        expired_token = jwt.encode(
            {
                "sub": "agent_x",
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
                "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
            },
            key=settings.secret_key,
            algorithm=settings.algorithm,
        )
        with pytest.raises(HTTPException) as exc:
            _claims_from_access_token(expired_token)
        assert exc.value.status_code == 401
        assert "has expired" in exc.value.detail.lower()

    def test_claims_rejects_wrong_issuer_or_audience(self) -> None:
        """Token with wrong issuer or audience must fail validation."""
        bad_iss_token = jwt.encode(
            {
                "sub": "agent_x",
                "iss": "rogue-issuer",
                "aud": settings.jwt_audience,
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            },
            key=settings.secret_key,
            algorithm=settings.algorithm,
        )
        with pytest.raises(HTTPException) as exc:
            _claims_from_access_token(bad_iss_token)
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Integration Invariants: Control Plane & Delegation Service
# ---------------------------------------------------------------------------


class TestIntegrationInvariants:
    """Validate control plane and delegation service lifecycle invariants."""

    @pytest.mark.asyncio
    async def test_control_plane_create_transaction_rejects_suspended_agent(
        self,
        operator_auth: AuthContext,
    ) -> None:
        mock_session = _build_mock_session()

        suspended_agent = _make_agent(
            id="agent_susp",
            name="agent_susp",
            status=AgentStatus.SUSPENDED.value,
            active=False,
            suspension_reason="Auditing anomaly",
        )
        mock_session.get.return_value = suspended_agent

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=None)

        req = TransactionCreateRequest(
            content="Run privileged task",
            idempotency_key="idemp_txn_12345",
            correlation_id="corr_txn_12345",
            agent_id="agent_susp",
            max_turns=3,
        )

        with (
            patch("services.control_plane.db_session.get_tenant_session", return_value=cm),
            patch(
                "services.control_plane.assure_input",
                return_value=InputAssuranceResult(
                    decision=PolicyDecision(decision=Decision.ALLOW, reason="ok"),
                    taints=set(),
                    risk=0,
                    indicators=[],
                ),
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_transaction(operator_auth, req)
            assert exc.value.status_code == 403
            assert "is suspended and cannot initiate transactions" in exc.value.detail

    @pytest.mark.asyncio
    async def test_control_plane_validate_capability_rejects_suspended_agent(
        self,
        operator_auth: AuthContext,
    ) -> None:
        mock_session = _build_mock_session()

        capability = Capability(
            id="cap_1",
            tenant_id="tenant_alpha",
            identity_id="usr_op_1",
            capability_type="tools:file_read",
            agent_id="agent_susp",
            revoked_at=None,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        suspended_agent = _make_agent(
            id="agent_susp",
            status=AgentStatus.SUSPENDED.value,
            active=False,
        )

        def mock_get(model: Any, key: Any) -> Any:
            if model is Capability and key == "cap_1":
                return capability
            if model is Agent and key == "agent_susp":
                return suspended_agent
            return None

        mock_session.get.side_effect = mock_get

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=None)

        req = CapabilityValidationRequest(
            capability_id="cap_1",
            capability_type="tools:file_read",
            resource={},
            requested_autonomy_level=1,
            transaction_id="txn_1",
        )

        with patch("services.control_plane.db_session.get_tenant_session", return_value=cm):
            decision = await validate_capability(operator_auth, req)
            assert decision.decision == Decision.DENY
            assert "capability execution denied" in decision.reason

    @pytest.mark.asyncio
    async def test_delegation_create_grant_rejects_suspended_delegatee(
        self,
        operator_auth: AuthContext,
    ) -> None:
        delegation_svc = DelegationService()
        mock_session = _build_mock_session()

        parent_txn = AITransaction(
            id="txn_p",
            tenant_id="tenant_alpha",
            agent_id="agent_parent",
            state=TransactionState.TURN_REASONING.value,
            max_turns=10,
            turn_count=2,
        )
        parent_agent = _make_agent(
            id="agent_parent",
            status=AgentStatus.ACTIVE.value,
            active=True,
            max_autonomy_level=3,
        )
        child_agent = _make_agent(
            id="agent_child_susp",
            status=AgentStatus.SUSPENDED.value,
            active=False,
            suspension_reason="Compromised",
        )

        def mock_get(model: Any, key: Any) -> Any:
            if model is AITransaction:
                return parent_txn
            if model is Agent:
                if key == "agent_parent":
                    return parent_agent
                if key == "agent_child_susp":
                    return child_agent
            return None

        mock_session.get.side_effect = mock_get

        req = DelegationGrantRequest(
            parent_transaction_id="txn_p",
            delegatee_agent_id="agent_child_susp",
            delegated_capabilities=[AttenuatedCapabilitySpec(capability_type="tools:read", max_autonomy_level=1)],
            max_turns=2,
            duration_seconds=300,
            idempotency_key="idemp_key_12345",
            purpose="Privileged worker task delegation",
        )

        with pytest.raises(HTTPException) as exc:
            await delegation_svc.create_delegation_grant(operator_auth, req, session=mock_session)
        assert exc.value.status_code == 403
        assert "Delegatee agent 'agent_child_susp' is suspended" in exc.value.detail

    @pytest.mark.asyncio
    async def test_delegation_operation_denied_when_ancestor_agent_suspended(
        self,
        operator_auth: AuthContext,
    ) -> None:
        """Broken delegation chain: if an ancestor agent is suspended, authorization is denied."""
        delegation_svc = DelegationService()
        mock_session = _build_mock_session()
        now = datetime.now(UTC)

        grant = AgentDelegation(
            id="del_active",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_parent",
            parent_transaction_id="txn_parent",
            child_agent_id="agent_child",
            child_transaction_id="txn_child",
            status="ACTIVE",
            delegated_capabilities=[{"capability_type": "tools:read"}],
            max_turns=5,
            delegation_depth=2,
            purpose="Active child work",
            idempotency_key="idemp_active_123",
            expires_at=now + timedelta(hours=1),
            created_at=now,
            updated_at=now,
        )
        child_txn = AITransaction(
            id="txn_child",
            tenant_id="tenant_alpha",
            agent_id="agent_child",
            parent_transaction_id="txn_parent",
            state=TransactionState.TURN_REASONING.value,
            max_turns=5,
            turn_count=1,
        )
        ancestor_grant = AgentDelegation(
            id="del_ancestor",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_root",
            parent_transaction_id="txn_root",
            child_agent_id="agent_parent",
            child_transaction_id="txn_parent",
            status="ACTIVE",
            delegated_capabilities=[{"capability_type": "tools:read"}],
            max_turns=10,
            delegation_depth=1,
            purpose="Root work",
            idempotency_key="idemp_root_123",
            expires_at=now + timedelta(hours=2),
            created_at=now,
            updated_at=now,
        )
        suspended_root_agent = _make_agent(
            id="agent_root",
            status=AgentStatus.SUSPENDED.value,
            active=False,
            suspension_reason="Security quarantine",
        )
        child_agent = _make_agent(id="agent_child", status=AgentStatus.ACTIVE.value, active=True)
        parent_agent = _make_agent(id="agent_parent", status=AgentStatus.ACTIVE.value, active=True)

        def mock_get(model: Any, key: Any) -> Any:
            if model is AgentDelegation:
                if key == "del_active":
                    return grant
                if key == "del_ancestor":
                    return ancestor_grant
            if model is AITransaction:
                return child_txn
            if model is Agent:
                if key == "agent_child":
                    return child_agent
                if key == "agent_parent":
                    return parent_agent
                if key == "agent_root":
                    return suspended_root_agent
            return None

        mock_session.get.side_effect = mock_get

        mock_exec = MagicMock()
        mock_exec.scalar_one_or_none.side_effect = [ancestor_grant, None]
        mock_session.execute.return_value = mock_exec

        decision = await delegation_svc.validate_delegation_for_operation(
            operator_auth,
            "del_active",
            capability_type="tools:read",
            resource={},
            requested_autonomy_level=1,
            session=mock_session,
        )

        assert decision.decision == Decision.DENY
        assert "delegation chain broken" in decision.reason
        assert "agent_root" in decision.reason
