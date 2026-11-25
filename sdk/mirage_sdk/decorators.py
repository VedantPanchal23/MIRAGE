"""MIRAGE 3.0 Action Governance Decorators.

Provides @govern_action (and @governed_action alias) for wrapping Python tool
and agent functions with Gate 3 Pre-Execution Lease Fencing and Gate 5 Epistemic
Outcome Verification.
"""

from __future__ import annotations

import functools
import inspect
import os
import uuid
import warnings
from collections.abc import Callable
from typing import Any, Literal, TypeVar, cast

from mirage_sdk.client import AsyncMirageClient, MirageClient
from mirage_sdk.exceptions import (
    MirageAuthorizationError,
    MirageError,
)
from mirage_sdk.models import (
    ActionProposal,
    ActionType,
    Decision,
    IndependentObservation,
    ObservabilityClass,
    OutcomeVerificationRequest,
)

F = TypeVar("F", bound=Callable[..., Any])


class MirageApprovalPendingError(MirageError):
    """Raised when an action is paused awaiting human approval."""

    def __init__(self, action_id: str, message: str) -> None:
        super().__init__(f"Action '{action_id}' requires human approval: {message}")
        self.action_id = action_id


def _build_outcome_request(
    *,
    tx_id: str,
    action_id: str,
    result: Any,
    observed_dict: dict[str, Any] | None,
    has_independent_observer: bool,
) -> OutcomeVerificationRequest:
    """Construct Gate 5 outcome request upholding Epistemic Outcome Independence.

    Only independent external observers qualify for OBS_DIRECT; self-reported
    tool returns default strictly to OBS_INFERRED.
    """
    if has_independent_observer and observed_dict is not None:
        obs = IndependentObservation(
            source_id="independent_observer",
            observed_state=observed_dict,
            epistemic_confidence=1.0,
        )
        return OutcomeVerificationRequest(
            transaction_id=tx_id,
            action_id=action_id,
            observability_class=ObservabilityClass.OBS_DIRECT,
            observation=obs,
        )

    warnings.warn(
        "No independent observer wired to @govern_action; recording Gate 5 status as OBS_INFERRED "
        "rather than OBS_DIRECT to uphold Epistemic Outcome Independence.",
        UserWarning,
        stacklevel=3,
    )
    inferred_payload = dict(result) if isinstance(result, dict) else {"output": str(result)}
    inferred_payload["_epistemic_note"] = "Tool return value is inferred, not independent reality verification"
    obs = IndependentObservation(
        source_id="tool_return_inferred",
        observed_state=inferred_payload,
        epistemic_confidence=0.5,
    )
    return OutcomeVerificationRequest(
        transaction_id=tx_id,
        action_id=action_id,
        observability_class=ObservabilityClass.OBS_INFERRED,
        observation=obs,
    )


def govern_action(
    capability: str,
    client: Any = None,
    action_type: ActionType = ActionType.EXECUTE,
    target_resource: str = "default_resource",
    auto_verify_outcome: bool = True,
    observer: Callable[[Any, tuple[Any, ...], dict[str, Any]], dict[str, Any]] | None = None,
    enforcement_mode: Literal["enforce", "shadow"] = "enforce",
) -> Callable[[F], F]:
    """Decorator wrapping a function with Gate 3 Governance and Gate 5 Verification.

    Args:
        capability: Required tool name or capability identifier.
        client: Active MirageClient or AsyncMirageClient instance.
        action_type: ActionType category.
        target_resource: Target resource URI/identifier.
        auto_verify_outcome: If True, invokes Gate 5 verify_outcome post-execution.
        observer: Optional independent observer callable receiving `(result, args, kwargs)`
            and querying external target state (`OBS_DIRECT`). When omitted, Gate 5 records
            honestly as `OBS_INFERRED`.
        enforcement_mode: `'enforce'` or non-blocking `'shadow'` telemetry mode.
    """

    def decorator(func: F) -> F:
        action_name = func.__name__
        is_async = inspect.iscoroutinefunction(func)

        if is_async:

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                sdk_client = client or AsyncMirageClient(api_key=os.environ.get("MIRAGE_API_KEY", "mirage_default_key"))
                tx_id = f"tx_{uuid.uuid4().hex[:12]}"
                idempotency_key = f"idemp_{uuid.uuid4().hex[:16]}"

                proposal = ActionProposal(
                    transaction_id=tx_id,
                    tool_name=capability or action_name,
                    action_type=action_type,
                    target_resource=target_resource,
                    parameters=kwargs if kwargs else {"args": [str(a) for a in args]},
                    idempotency_key=idempotency_key,
                    enforcement_mode=enforcement_mode,
                )

                decision = await sdk_client.propose_action(proposal)
                if decision.decision == Decision.DENY:
                    raise MirageAuthorizationError(
                        f"Gate 3 blocked action '{action_name}': {decision.reason or 'Policy violation'}"
                    )
                if decision.decision == Decision.REQUIRE_APPROVAL:
                    raise MirageApprovalPendingError(
                        action_id=decision.action_id,
                        message=decision.reason or "Awaiting Human-In-The-Loop approval",
                    )

                result = await func(*args, **kwargs)

                await sdk_client.execute_action(
                    decision.action_id,
                    approval_token=getattr(decision, "approval_id", None),
                )

                if auto_verify_outcome:
                    observed_dict: dict[str, Any] | None = None
                    if observer is not None:
                        raw_obs = observer(result, args, kwargs)
                        observed_dict = await raw_obs if inspect.isawaitable(raw_obs) else raw_obs
                    req_outcome = _build_outcome_request(
                        tx_id=tx_id,
                        action_id=decision.action_id,
                        result=result,
                        observed_dict=observed_dict,
                        has_independent_observer=observer is not None,
                    )
                    await sdk_client.verify_outcome(decision.action_id, req_outcome)

                return result

            return cast(F, async_wrapper)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            sdk_client = client or MirageClient(api_key=os.environ.get("MIRAGE_API_KEY", "mirage_default_key"))
            tx_id = f"tx_{uuid.uuid4().hex[:12]}"
            idempotency_key = f"idemp_{uuid.uuid4().hex[:16]}"

            proposal = ActionProposal(
                transaction_id=tx_id,
                tool_name=capability or action_name,
                action_type=action_type,
                target_resource=target_resource,
                parameters=kwargs if kwargs else {"args": [str(a) for a in args]},
                idempotency_key=idempotency_key,
                enforcement_mode=enforcement_mode,
            )

            decision = sdk_client.propose_action(proposal)
            if decision.decision == Decision.DENY:
                raise MirageAuthorizationError(
                    f"Gate 3 blocked action '{action_name}': {decision.reason or 'Policy violation'}"
                )
            if decision.decision == Decision.REQUIRE_APPROVAL:
                raise MirageApprovalPendingError(
                    action_id=decision.action_id,
                    message=decision.reason or "Awaiting Human-In-The-Loop approval",
                )

            result = func(*args, **kwargs)

            sdk_client.execute_action(
                decision.action_id,
                approval_token=getattr(decision, "approval_id", None),
            )

            if auto_verify_outcome:
                observed_dict = observer(result, args, kwargs) if observer is not None else None
                req_outcome = _build_outcome_request(
                    tx_id=tx_id,
                    action_id=decision.action_id,
                    result=result,
                    observed_dict=observed_dict,
                    has_independent_observer=observer is not None,
                )
                sdk_client.verify_outcome(decision.action_id, req_outcome)

            return result

        return cast(F, sync_wrapper)

    return decorator


governed_action = govern_action
