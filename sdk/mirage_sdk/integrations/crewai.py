"""CrewAI tool execution governance adapter for MIRAGE 3.0."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from mirage_sdk.integrations.langchain import MirageGovernedTool
from mirage_sdk.models import ActionType


class MirageCrewAITool(MirageGovernedTool):
    """Wraps a CrewAI BaseTool (or callable with `_run`/`_arun`) under MIRAGE 5-Gate governance."""

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
        super().__init__(
            tool=tool,
            client=client,
            capability=capability or f"crewai:{getattr(tool, 'name', getattr(tool, '__name__', 'tool'))}",
            action_type=action_type,
            resource=resource or f"crewai://tools/{getattr(tool, 'name', getattr(tool, '__name__', 'tool'))}",
            observer=observer,
            enforcement_mode=enforcement_mode,
        )

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        """CrewAI standard synchronous tool entrypoint."""
        target = getattr(self.tool, "_run", self.tool)
        original_tool = self.tool
        self.tool = target
        try:
            return self.run(*args, **kwargs)
        finally:
            self.tool = original_tool

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        """CrewAI standard asynchronous tool entrypoint."""
        target = getattr(self.tool, "_arun", self.tool)
        original_tool = self.tool
        self.tool = target
        try:
            return await self.arun(*args, **kwargs)
        finally:
            self.tool = original_tool
