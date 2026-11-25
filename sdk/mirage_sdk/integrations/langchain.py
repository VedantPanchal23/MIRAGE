"""LangChain and LangGraph tool execution security wrapper for MIRAGE 3.0."""

from __future__ import annotations

import inspect
import os
import uuid
from collections.abc import Callable
from typing import Any, Literal

from mirage_sdk.client import AsyncMirageClient, MirageClient
from mirage_sdk.decorators import _build_outcome_request
from mirage_sdk.exceptions import MirageAuthorizationError
from mirage_sdk.models import ActionProposal, ActionType, Decision


class MirageGovernedTool:
    """Wraps any LangChain BaseTool or arbitrary Python tool function with MIRAGE 5-Gate Assurance.

    Intercepts invocations, enforces Gate 3 Action Assurance before execution,
    acquires distributed lease tokens, and records Gate 5 verification cleanly.
    """

    def __init__(
        self,
        tool: Any,
        client: Any = None,
        capability: str | None = None,
        action_type: ActionType = ActionType.EXECUTE,
        resource: str | None = None,
        observer: Callable[[Any, tuple[Any, ...], dict[str, Any]], dict[str, Any]] | None = None,
        enforcement_mode: Literal["enforce", "shadow"] = "enforce",
    ) -> None:
        self.tool = tool
        self.client = client
        self.name = getattr(tool, "name", getattr(tool, "__name__", "mirage_governed_tool"))
        self.description = getattr(tool, "description", getattr(tool, "__doc__", "Governed AI Tool"))
        self.capability = capability or f"tool:{self.name}"
        self.action_type = action_type
        self.resource = resource or f"resource:{self.name}"
        self.observer = observer
        self.enforcement_mode = enforcement_mode

    def _make_proposal(self, tx_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> ActionProposal:
        return ActionProposal(
            transaction_id=tx_id,
            tool_name=self.name,
            action_type=self.action_type,
            target_resource=self.resource,
            parameters=kwargs if kwargs else {"args": [str(a) for a in args]},
            idempotency_key=f"idemp_{uuid.uuid4().hex[:16]}",
            enforcement_mode=self.enforcement_mode,
        )

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Execute synchronously under Gate 3 & Gate 5 assurance."""
        client = self.client or MirageClient(api_key=os.environ.get("MIRAGE_API_KEY", "mirage_default_key"))
        tx_id = f"tx_{uuid.uuid4().hex[:12]}"
        decision = client.propose_action(self._make_proposal(tx_id, args, kwargs))
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

        observed_dict = self.observer(result, args, kwargs) if self.observer is not None else None
        req_outcome = _build_outcome_request(
            tx_id=tx_id,
            action_id=decision.action_id,
            result=result,
            observed_dict=observed_dict,
            has_independent_observer=self.observer is not None,
        )
        client.verify_outcome(decision.action_id, req_outcome)
        return result

    async def arun(self, *args: Any, **kwargs: Any) -> Any:
        """Execute asynchronously under Gate 3 & Gate 5 assurance."""
        client = self.client or AsyncMirageClient(api_key=os.environ.get("MIRAGE_API_KEY", "mirage_default_key"))
        tx_id = f"tx_{uuid.uuid4().hex[:12]}"
        decision = await client.propose_action(self._make_proposal(tx_id, args, kwargs))
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

        observed_dict: dict[str, Any] | None = None
        if self.observer is not None:
            raw_obs = self.observer(result, args, kwargs)
            observed_dict = await raw_obs if inspect.isawaitable(raw_obs) else raw_obs
        req_outcome = _build_outcome_request(
            tx_id=tx_id,
            action_id=decision.action_id,
            result=result,
            observed_dict=observed_dict,
            has_independent_observer=self.observer is not None,
        )
        await client.verify_outcome(decision.action_id, req_outcome)
        return result

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.run(*args, **kwargs)
