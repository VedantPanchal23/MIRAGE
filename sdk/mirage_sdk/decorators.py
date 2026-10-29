"""MIRAGE 3.0 Action Governance Decorators.

Provides the @govern_action decorator for wrapping Python tool and agent functions
with automated Gate 3 Pre-Execution Lease Fencing and Gate 5 Outcome Reality Verification.
"""

from __future__ import annotations

import functools
import inspect
import os
import uuid
from collections.abc import Callable
from typing import Any, TypeVar, cast

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


def govern_action(
    capability: str,
    client: Any = None,
    action_type: ActionType = ActionType.EXECUTE,
    target_resource: str = "default_resource",
    auto_verify_outcome: bool = True,
) -> Callable[[F], F]:
    """Decorator that wraps a function with Gate 3 Action Governance and Gate 5 Reality Verification.

    Args:
        capability: Required tool name or capability identifier.
        client: Active MirageClient or AsyncMirageClient (or mock) instance.
        action_type: ActionType (READ, WRITE, EXECUTE, DESTRUCTIVE, NETWORK, FINANCIAL).
        target_resource: Target resource identifier.
        auto_verify_outcome: If True, calls Gate 5 verify_outcome upon function success.

    Returns:
        Decorated synchronous or asynchronous function.
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
                )

                # Gate 3: Pre-Execution Action Assurance
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

                # Execute target function
                result = await func(*args, **kwargs)

                # Record execution success
                await sdk_client.execute_action(
                    decision.action_id,
                    approval_token=getattr(decision, "approval_id", None),
                )

                # Gate 5: Outcome Reality Verification
                if auto_verify_outcome:
                    observed_payload = result if isinstance(result, dict) else {"output": str(result)}
                    obs = IndependentObservation(
                        source_id="agent_function_return",
                        observed_state=observed_payload,
                    )
                    await sdk_client.verify_outcome(
                        decision.action_id,
                        OutcomeVerificationRequest(
                            transaction_id=tx_id,
                            action_id=decision.action_id,
                            observability_class=ObservabilityClass.OBS_DIRECT,
                            observation=obs,
                        ),
                    )

                return result

            return cast(F, async_wrapper)
        else:

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
                )

                # Gate 3: Pre-Execution Action Assurance
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

                # Execute target function
                result = func(*args, **kwargs)

                # Record execution success
                sdk_client.execute_action(
                    decision.action_id,
                    approval_token=getattr(decision, "approval_id", None),
                )

                # Gate 5: Outcome Reality Verification
                if auto_verify_outcome:
                    observed_payload = result if isinstance(result, dict) else {"output": str(result)}
                    obs = IndependentObservation(
                        source_id="agent_function_return",
                        observed_state=observed_payload,
                    )
                    sdk_client.verify_outcome(
                        decision.action_id,
                        OutcomeVerificationRequest(
                            transaction_id=tx_id,
                            action_id=decision.action_id,
                            observability_class=ObservabilityClass.OBS_DIRECT,
                            observation=obs,
                        ),
                    )

                return result

            return cast(F, sync_wrapper)

    return decorator
