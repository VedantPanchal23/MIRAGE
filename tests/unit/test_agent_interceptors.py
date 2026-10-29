"""Unit tests for MIRAGE 3.0 Agent Framework Interceptors and Decorators."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from mirage_sdk.decorators import MirageApprovalPendingError, govern_action
from mirage_sdk.exceptions import MirageAuthorizationError
from mirage_sdk.integrations.langchain import MirageGovernedTool
from mirage_sdk.models import (
    ActionAuthorizationDecision,
    ActionExecutionResult,
    ActionState,
    Decision,
    ObservabilityClass,
    OutcomeStatus,
    OutcomeVerificationContract,
)


def _make_mock_decision(
    action_id: str,
    decision: Decision,
    state: ActionState = ActionState.AUTHORIZED,
    reason: str = "Authorized by policy",
    fencing_token: int | None = 42,
) -> ActionAuthorizationDecision:
    return ActionAuthorizationDecision(
        action_id=action_id,
        decision=decision,
        state=state,
        reason=reason,
        risk_score=15,
        autonomy_level=2,
        normalized_parameters={},
        parameters_hash="param_hash_123",
        fencing_token=fencing_token,
    )


def test_govern_action_sync_success() -> None:
    """Test @govern_action wraps synchronous function, enforcing Gate 3 lease and Gate 5 outcome."""
    mock_client = MagicMock()
    mock_client.propose_action.return_value = _make_mock_decision("act_123", Decision.ALLOW)
    mock_client.execute_action.return_value = ActionExecutionResult(
        action_id="act_123",
        transaction_id="tx_123",
        state=ActionState.COMPLETED,
    )
    mock_client.verify_outcome.return_value = OutcomeVerificationContract(
        outcome_id="out_123",
        transaction_id="tx_123",
        action_id="act_123",
        tenant_id="default_tenant",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.VERIFIED_SUCCESS,
        epistemic_confidence=0.99,
        verifier_adapter="mock_adapter",
        verification_hash="hash_abc",
        verified_at="2026-10-29T10:00:00Z",
    )

    @govern_action(capability="payments:transfer", client=mock_client)
    def transfer(amount: float, recipient: str) -> dict[str, str]:
        return {"status": "transferred", "recipient": recipient, "amount": str(amount)}

    result = transfer(100.0, "alice")
    assert result["status"] == "transferred"
    assert result["recipient"] == "alice"

    assert mock_client.propose_action.call_count == 1
    assert mock_client.execute_action.call_count == 1
    assert mock_client.verify_outcome.call_count == 1


def test_govern_action_sync_blocked() -> None:
    """Test @govern_action strictly raises MirageAuthorizationError when Gate 3 denies action."""
    mock_client = MagicMock()
    mock_client.propose_action.return_value = _make_mock_decision(
        "act_denied",
        Decision.DENY,
        state=ActionState.BLOCKED,
        reason="Exceeds daily transfer threshold",
    )

    @govern_action(capability="payments:transfer", client=mock_client)
    def transfer(amount: float) -> str:
        return f"done_{amount}"

    with pytest.raises(MirageAuthorizationError) as exc_info:
        transfer(50000.0)

    assert "Exceeds daily transfer threshold" in str(exc_info.value)
    assert mock_client.execute_action.call_count == 0


def test_govern_action_sync_approval_required() -> None:
    """Test @govern_action raises MirageApprovalPendingError when Gate 3 requires HITL approval."""
    mock_client = MagicMock()
    mock_client.propose_action.return_value = _make_mock_decision(
        "act_pending_hitl",
        Decision.REQUIRE_APPROVAL,
        state=ActionState.AWAITING_APPROVAL,
        reason="Requires dual-custody authorization",
    )

    @govern_action(capability="admin:delete_db", client=mock_client)
    def delete_db() -> str:
        return "deleted"

    with pytest.raises(MirageApprovalPendingError) as exc_info:
        delete_db()

    assert exc_info.value.action_id == "act_pending_hitl"
    assert "Requires dual-custody authorization" in str(exc_info.value)


@pytest.mark.asyncio
async def test_govern_action_async_success() -> None:
    """Test @govern_action on async coroutine function."""
    mock_async_client = AsyncMock()
    mock_async_client.propose_action.return_value = _make_mock_decision(
        "act_async_123",
        Decision.ALLOW,
    )
    mock_async_client.execute_action.return_value = ActionExecutionResult(
        action_id="act_async_123",
        transaction_id="tx_async_123",
        state=ActionState.COMPLETED,
    )
    mock_async_client.verify_outcome.return_value = OutcomeVerificationContract(
        outcome_id="out_async",
        transaction_id="tx_async",
        action_id="act_async_123",
        tenant_id="default_tenant",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.VERIFIED_SUCCESS,
        epistemic_confidence=0.98,
        verifier_adapter="mock_adapter",
        verification_hash="hash_async",
        verified_at="2026-10-29T10:00:00Z",
    )

    @govern_action(capability="crm:update_lead", client=mock_async_client)
    async def update_lead(lead_id: str, status: str) -> dict[str, str]:
        return {"lead_id": lead_id, "status": status}

    res = await update_lead("lead_42", "QUALIFIED")
    assert res["status"] == "QUALIFIED"

    assert mock_async_client.propose_action.call_count == 1
    assert mock_async_client.execute_action.call_count == 1
    assert mock_async_client.verify_outcome.call_count == 1


def test_langchain_mirage_governed_tool_run() -> None:
    """Test MirageGovernedTool wrapping an arbitrary LangChain tool function."""
    mock_client = MagicMock()
    mock_client.propose_action.return_value = _make_mock_decision("act_lc_1", Decision.ALLOW)
    mock_client.execute_action.return_value = ActionExecutionResult(
        action_id="act_lc_1",
        transaction_id="tx_lc_1",
        state=ActionState.COMPLETED,
    )
    mock_client.verify_outcome.return_value = OutcomeVerificationContract(
        outcome_id="out_lc_1",
        transaction_id="tx_lc_1",
        action_id="act_lc_1",
        tenant_id="default_tenant",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.VERIFIED_SUCCESS,
        epistemic_confidence=0.97,
        verifier_adapter="mock_adapter",
        verification_hash="hash_lc",
        verified_at="2026-10-29T10:00:00Z",
    )

    def mock_db_query(query: str) -> dict[str, list[str]]:
        del query
        return {"rows": ["user_1", "user_2"]}

    mock_db_query.__name__ = "sql_query_tool"

    governed_tool = MirageGovernedTool(
        tool=mock_db_query,
        client=mock_client,
        capability="db:query",
    )

    res = governed_tool.run(query="SELECT * FROM users")
    assert res == {"rows": ["user_1", "user_2"]}
    assert mock_client.propose_action.call_count == 1
    assert mock_client.execute_action.call_count == 1
    assert mock_client.verify_outcome.call_count == 1
