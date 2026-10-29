"""LangChain and LangGraph tool execution security wrapper for MIRAGE 3.0."""

from __future__ import annotations

import inspect
import os
import uuid
from typing import Any

from mirage_sdk.client import AsyncMirageClient, MirageClient
from mirage_sdk.exceptions import MirageAuthorizationError
from mirage_sdk.models import (
    ActionProposal,
    ActionType,
    Decision,
    IndependentObservation,
    ObservabilityClass,
    OutcomeVerificationRequest,
)


class MirageGovernedTool:
    """Wraps any LangChain BaseTool or arbitrary Python tool function with MIRAGE 5-Gate Assurance.

    Intercepts invocations, checks Gate 3 Action Assurance before execution,
    acquires distributed lease tokens, and confirms Gate 5 reality postconditions.
    """

    def __init__(
        self,
        tool: Any,
        client: Any = None,
        capability: str | None = None,
        action_type: ActionType = ActionType.EXECUTE,
        resource: str | None = None,
    ) -> None:
        self.tool = tool
        self.client = client
        self.name = getattr(tool, "name", getattr(tool, "__name__", "mirage_governed_tool"))
        self.description = getattr(tool, "description", getattr(tool, "__doc__", "Governed AI Tool"))
        self.capability = capability or f"tool:{self.name}"
        self.action_type = action_type
        self.resource = resource or f"resource:{self.name}"

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Execute synchronously under Gate 3 & Gate 5 assurance."""
        client = self.client or MirageClient(api_key=os.environ.get("MIRAGE_API_KEY", "mirage_default_key"))
        tx_id = f"tx_{uuid.uuid4().hex[:12]}"
        idemp = f"idemp_{uuid.uuid4().hex[:16]}"

        proposal = ActionProposal(
            transaction_id=tx_id,
            tool_name=self.name,
            action_type=self.action_type,
            target_resource=self.resource,
            parameters=kwargs if kwargs else {"args": [str(a) for a in args]},
            idempotency_key=idemp,
        )

        decision = client.propose_action(proposal)
        if decision.decision != Decision.ALLOW:
            raise MirageAuthorizationError(
                f"Gate 3 rejected action for tool '{self.name}': {decision.reason or 'Unauthorized'}"
            )

        if hasattr(self.tool, "run"):
            result = self.tool.run(*args, **kwargs)
        elif callable(self.tool):
            result = self.tool(*args, **kwargs)
        else:
            raise TypeError(f"Target tool '{self.name}' is not callable")

        client.execute_action(
            decision.action_id,
            approval_token=getattr(decision, "approval_id", None),
        )

        observed = result if isinstance(result, dict) else {"output": str(result)}
        obs = IndependentObservation(
            source_id="langchain_tool_output",
            observed_state=observed,
        )
        client.verify_outcome(
            decision.action_id,
            OutcomeVerificationRequest(
                transaction_id=tx_id,
                action_id=decision.action_id,
                observability_class=ObservabilityClass.OBS_DIRECT,
                observation=obs,
            ),
        )
        return result

    async def arun(self, *args: Any, **kwargs: Any) -> Any:
        """Execute asynchronously under Gate 3 & Gate 5 assurance."""
        client = self.client or AsyncMirageClient(api_key=os.environ.get("MIRAGE_API_KEY", "mirage_default_key"))
        tx_id = f"tx_{uuid.uuid4().hex[:12]}"
        idemp = f"idemp_{uuid.uuid4().hex[:16]}"

        proposal = ActionProposal(
            transaction_id=tx_id,
            tool_name=self.name,
            action_type=self.action_type,
            target_resource=self.resource,
            parameters=kwargs if kwargs else {"args": [str(a) for a in args]},
            idempotency_key=idemp,
        )

        decision = await client.propose_action(proposal)
        if decision.decision != Decision.ALLOW:
            raise MirageAuthorizationError(
                f"Gate 3 rejected action for tool '{self.name}': {decision.reason or 'Unauthorized'}"
            )

        if hasattr(self.tool, "arun"):
            result = await self.tool.arun(*args, **kwargs)
        elif inspect.iscoroutinefunction(self.tool):
            result = await self.tool(*args, **kwargs)
        elif callable(self.tool):
            result = self.tool(*args, **kwargs)
        else:
            raise TypeError(f"Target tool '{self.name}' is not callable")

        await client.execute_action(
            decision.action_id,
            approval_token=getattr(decision, "approval_id", None),
        )

        observed = result if isinstance(result, dict) else {"output": str(result)}
        obs = IndependentObservation(
            source_id="langchain_tool_output",
            observed_state=observed,
        )
        await client.verify_outcome(
            decision.action_id,
            OutcomeVerificationRequest(
                transaction_id=tx_id,
                action_id=decision.action_id,
                observability_class=ObservabilityClass.OBS_DIRECT,
                observation=obs,
            ),
        )
        return result

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.run(*args, **kwargs)
