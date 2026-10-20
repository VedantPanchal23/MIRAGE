"""Gate 5 Reality Verification Uncertainty Remediation Security Suite.

Governing principle: "Control AI before it acts. Verify AI after it acts."

Authoritative tests for EXECUTION_UNCERTAIN action resolution:
1. Timeout after remote side effect occurred -> independent probe confirms -> VERIFIED_SUCCESS -> COMPLETED.
2. Timeout before remote side effect occurred -> independent probe detects failure -> VERIFIED_FAILURE -> FAILED.
3. Mutating action in EXECUTION_UNCERTAIN strictly blocks redispatch with HTTP 409 Conflict.
4. Attempting to resolve EXECUTION_UNCERTAIN with OBS_INFERRED is rejected with HTTP 400 Bad Request.
5. Inconclusive probe / timeout yields UNKNOWN (confidence 0.0) and preserves EXECUTION_UNCERTAIN state.
6. Replay, stale, future, or forged observation evidence against EXECUTION_UNCERTAIN is rejected fail-closed.
7. Unexecuted action states strictly reject verification with HTTP 409 Conflict.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import ActionContract, OutcomeVerificationRecord
from services.action_governor import ActionGovernorService
from services.reality_verifier import RealityVerifierService
from shared.schemas.action import (
    ActionExecutionRequest,
    ActionState,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    IndependentObservation,
    ObservabilityClass,
    OutcomeStatus,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
    compute_evidence_digest,
)


@pytest.fixture
def reality_service() -> RealityVerifierService:
    return RealityVerifierService()


@pytest.fixture
def governor_service() -> ActionGovernorService:
    return ActionGovernorService()


@pytest.fixture
def auth_tenant() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_remediation_test",
        identity_id="usr_remediation_admin",
        role=Role.TENANT_ADMIN,
        token_id="tok_remediation",
    )


def _make_uncertain_action(
    action_id: str = "act_unc_001",
    tenant_id: str = "tenant_remediation_test",
    target_resource: str = "db://accounts/acct_500/balance",
    postconditions: list[dict] | None = None,
    executed_seconds_ago: int = 15,
) -> ActionContract:
    now = datetime.now(UTC)
    exec_dt = now - timedelta(seconds=executed_seconds_ago)
    if postconditions is None:
        postconditions = [
            {"assertion": "EQUALS", "target": "balance", "expected_value": 750.0},
            {"assertion": "EQUALS", "target": "status", "expected_value": "SETTLED"},
        ]
    return ActionContract(
        id=action_id,
        tenant_id=tenant_id,
        transaction_id="txn_unc_001",
        actor_identity_id="usr_remediation_admin",
        tool_id="tool_banking_transfer",
        tool_name="account_transfer",
        action_type="EXECUTE",
        target_resource=target_resource,
        parameters={"amount": 250.0, "account_id": "acct_500"},
        normalized_parameters={"amount": 250.0, "account_id": "acct_500"},
        parameters_hash="hash_param_unc_001",
        required_capability="banking:transfer",
        taint_flags=[],
        risk_score=70,
        blast_radius={"target_environment": "PROD"},
        state=ActionState.EXECUTION_UNCERTAIN.value,
        idempotency_key=f"idem_{action_id}",
        preconditions=[],
        postconditions=postconditions,
        requires_outcome_assurance=True,
        outcome_contract={
            "requires_outcome_assurance": True,
            "verification_deadline_seconds": 120.0,
            "acceptable_evidence_sources": ["core-banking-observer", "DatabaseStateAdapter"],
            "risk_sensitive_verification_policy": "DEFAULT",
        },
        error_message="Transport timeout waiting for downstream remote response",
        created_at=exec_dt - timedelta(seconds=5),
        authorized_at=exec_dt - timedelta(seconds=2),
        executed_at=exec_dt,
    )


# -----------------------------------------------------------------------------
# 1. Test: Timeout after side effect -> Independent probe confirms -> VERIFIED_SUCCESS -> COMPLETED
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_uncertain_action_resolved_to_success_by_independent_probe(
    reality_service: RealityVerifierService,
    auth_tenant: AuthContext,
):
    """When tool execution timed out but side effects actually occurred, independent probe

    confirms postconditions -> status VERIFIED_SUCCESS, ActionContract transitions to COMPLETED.
    """
    action = _make_uncertain_action()
    obs_state = {"balance": 750.0, "status": "SETTLED"}
    obs = IndependentObservation(
        observation_id="obs_succ_001",
        source_id="core-banking-observer",
        target_resource=action.target_resource,
        observed_at=datetime.now(UTC),
        observed_state=obs_state,
        evidence_digest=compute_evidence_digest(obs_state),
        epistemic_confidence=1.0,
    )

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"balance": 750.0, "status": "SETTLED"},
        observation=obs,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        # Mock scalar_one_or_none for ActionContract lookup (first query) and existing outcome (second query)
        mock_session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=action)),  # ActionContract
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),    # Existing OutcomeVerificationRecord
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),  # Replay check
            ]
        )
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await reality_service.verify_action_outcome(req, auth_tenant)

        assert contract.outcome_status in (OutcomeStatus.VERIFIED_SUCCESS, OutcomeStatus.SUCCESS_CONFIRMED)
        assert contract.epistemic_confidence == 1.0
        # Contract state must transition from EXECUTION_UNCERTAIN to COMPLETED
        assert action.state == ActionState.COMPLETED.value
        assert action.completed_at is not None
        assert action.outcome_status in (OutcomeStatus.VERIFIED_SUCCESS.value, OutcomeStatus.SUCCESS_CONFIRMED.value)


# -----------------------------------------------------------------------------
# 2. Test: Timeout before side effect -> Independent probe confirms failure -> VERIFIED_FAILURE -> FAILED
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_uncertain_action_resolved_to_failure_by_independent_probe(
    reality_service: RealityVerifierService,
    auth_tenant: AuthContext,
):
    """When tool execution timed out before side effects occurred, independent probe

    detects postcondition failure -> status VERIFIED_FAILURE, ActionContract transitions to FAILED.
    """
    action = _make_uncertain_action()
    # Actual state shows mutation did NOT occur (balance is unchanged at 500.0, status is PENDING)
    obs_state = {"balance": 500.0, "status": "PENDING"}
    obs = IndependentObservation(
        observation_id="obs_fail_001",
        source_id="core-banking-observer",
        target_resource=action.target_resource,
        observed_at=datetime.now(UTC),
        observed_state=obs_state,
        evidence_digest=compute_evidence_digest(obs_state),
        epistemic_confidence=1.0,
    )

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"balance": 750.0, "status": "SETTLED"},
        observation=obs,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=action)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            ]
        )
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await reality_service.verify_action_outcome(req, auth_tenant)

        assert contract.outcome_status in (OutcomeStatus.VERIFIED_FAILURE, OutcomeStatus.FAILED)
        assert len(contract.discrepancies) > 0
        # Contract state must transition from EXECUTION_UNCERTAIN to FAILED
        assert action.state == ActionState.FAILED.value
        assert action.outcome_status in (OutcomeStatus.VERIFIED_FAILURE.value, OutcomeStatus.FAILED.value)


# -----------------------------------------------------------------------------
# 3. Test: Redispatch of EXECUTION_UNCERTAIN action is strictly blocked (HTTP 409)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_uncertain_action_redispatch_strictly_blocked_409(
    governor_service: ActionGovernorService,
    auth_tenant: AuthContext,
):
    """Mutating action in EXECUTION_UNCERTAIN strictly rejects retry with HTTP 409 Conflict

    to prevent duplicate external side effects.
    """
    action = _make_uncertain_action()

    with patch("services.action_governor.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = action
        mock_session.execute = AsyncMock(return_value=mock_res)
        mock_ctx.return_value.__aenter__.return_value = mock_session

        req = ActionExecutionRequest(action_id=action.id)
        with pytest.raises(HTTPException) as exc_info:
            await governor_service.execute_action(auth_tenant, req)

        assert exc_info.value.status_code == 409
        assert "EXECUTION_UNCERTAIN" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 4. Test: Attempting to verify EXECUTION_UNCERTAIN with OBS_INFERRED is rejected (HTTP 400)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_uncertain_action_rejects_obs_inferred_with_400(
    reality_service: RealityVerifierService,
    auth_tenant: AuthContext,
):
    """Attempting to resolve EXECUTION_UNCERTAIN using transport acknowledgment (OBS_INFERRED)

    is rejected with HTTP 400 Bad Request, as physical readback or independent probe is mandatory.
    """
    action = _make_uncertain_action()

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_INFERRED,
        verifier_type=OutcomeVerifierType.HTTP_RESOURCE,
        expected_postconditions={"balance": 750.0},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=action))
        )
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await reality_service.verify_action_outcome(req, auth_tenant)

        assert exc_info.value.status_code == 400
        detail_msg = exc_info.value.detail.lower()
        assert "cannot resolve execution_uncertain action using transport acknowledgment" in detail_msg


# -----------------------------------------------------------------------------
# 5. Test: Inconclusive probe / timeout yields UNKNOWN and preserves EXECUTION_UNCERTAIN
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_uncertain_action_inconclusive_probe_preserves_uncertain_state(
    reality_service: RealityVerifierService,
    auth_tenant: AuthContext,
):
    """When an independent probe is inconclusive (e.g. deadline expired, no stable read),

    outcome is UNKNOWN with confidence 0.0, and ActionContract state remains EXECUTION_UNCERTAIN.
    """
    # Create action where execution was 200 seconds ago, exceeding 120s deadline
    action = _make_uncertain_action(executed_seconds_ago=200)

    # Empty postconditions or unresolvable state
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.DATABASE,
        expected_postconditions={"balance": 750.0},
        adapter_config={"table_name": "accounts", "record_id": "acct_99999_nonexistent"},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        # Mock database readback returning None (record not found -> discrepancy)
        mock_session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=action)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            ]
        )
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await reality_service.verify_action_outcome(req, auth_tenant)

        # Because deadline expired, status is forced to UNKNOWN with confidence 0.0
        assert contract.outcome_status == OutcomeStatus.UNKNOWN
        assert contract.epistemic_confidence == 0.0
        # Contract state must NOT transition to COMPLETED or FAILED; remains EXECUTION_UNCERTAIN
        assert action.state == ActionState.EXECUTION_UNCERTAIN.value
        assert action.outcome_status == OutcomeStatus.UNKNOWN.value


# -----------------------------------------------------------------------------
# 6. Test: Replay, stale, future, or forged observation evidence rejected
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_uncertain_action_stale_observation_rejected(
    reality_service: RealityVerifierService,
    auth_tenant: AuthContext,
):
    """Observation timestamp prior to action execution is rejected with HTTP 400 (anti-staleness)."""
    action = _make_uncertain_action(executed_seconds_ago=30)
    obs_state = {"balance": 750.0, "status": "SETTLED"}
    # Stale timestamp: 60 seconds ago, which is earlier than executed_at (30s ago)
    stale_time = datetime.now(UTC) - timedelta(seconds=60)
    obs = IndependentObservation(
        observation_id="obs_stale_001",
        source_id="core-banking-observer",
        target_resource=action.target_resource,
        observed_at=stale_time,
        observed_state=obs_state,
        evidence_digest=compute_evidence_digest(obs_state),
        epistemic_confidence=1.0,
    )

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"balance": 750.0, "status": "SETTLED"},
        observation=obs,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=action)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            ]
        )
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await reality_service.verify_action_outcome(req, auth_tenant)

        assert exc_info.value.status_code == 400
        assert "stale observation" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_uncertain_action_replayed_observation_id_rejected(
    reality_service: RealityVerifierService,
    auth_tenant: AuthContext,
):
    """Replaying an observation_id already consumed for another action in the tenant

    is rejected with HTTP 409 Conflict.
    """
    action = _make_uncertain_action()
    obs_state = {"balance": 750.0, "status": "SETTLED"}
    obs = IndependentObservation(
        observation_id="obs_replayed_001",
        source_id="core-banking-observer",
        target_resource=action.target_resource,
        observed_at=datetime.now(UTC),
        observed_state=obs_state,
        evidence_digest=compute_evidence_digest(obs_state),
        epistemic_confidence=1.0,
    )

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"balance": 750.0, "status": "SETTLED"},
        observation=obs,
    )

    # Existing record in tenant with same observation_id on another action
    existing_other_rec = OutcomeVerificationRecord(
        id="outc_prior_001",
        tenant_id=auth_tenant.tenant_id,
        action_id="act_other_prior",
        evidence_payload={"observation_id": "obs_replayed_001"},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=action)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing_other_rec])))),
            ]
        )
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await reality_service.verify_action_outcome(req, auth_tenant)

        assert exc_info.value.status_code == 409
        assert "replay attack detected" in exc_info.value.detail.lower()


# -----------------------------------------------------------------------------
# 7. Test: Truly unexecuted action states strictly rejected with 409 Conflict
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "unexecuted_state",
    [
        ActionState.PROPOSED.value,
        ActionState.AUTHORIZED.value,
        ActionState.AWAITING_APPROVAL.value,
        ActionState.BLOCKED.value,
        ActionState.EXECUTING.value,
        ActionState.FAILED.value,
        "CANCELLED",
    ],
)
@pytest.mark.asyncio
async def test_unexecuted_states_strictly_rejected_with_409(
    unexecuted_state: str,
    reality_service: RealityVerifierService,
    auth_tenant: AuthContext,
):
    """In-flight, proposed, blocked, or cancelled actions cannot undergo reality verification (HTTP 409)."""
    action = _make_uncertain_action()
    action.state = unexecuted_state

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=action))
        )
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await reality_service.verify_action_outcome(req, auth_tenant)

        assert exc_info.value.status_code == 409
        assert "cannot verify unexecuted action" in exc_info.value.detail.lower()
        assert unexecuted_state in exc_info.value.detail
