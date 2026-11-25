"""AutoGen tool execution governance adapter for MIRAGE 3.0."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from mirage_sdk.decorators import govern_action
from mirage_sdk.models import ActionType


def wrap_autogen_tool[F: Callable[..., Any]](
    func: F,
    *,
    client: Any = None,
    capability: str | None = None,
    action_type: ActionType = ActionType.EXECUTE,
    target_resource: str | None = None,
    observer: Callable[[Any, tuple[Any, ...], dict[str, Any]], dict[str, Any]] | None = None,
    enforcement_mode: Literal["enforce", "shadow"] = "enforce",
) -> F:
    """Wrap an AutoGen tool function with MIRAGE Gate 3 lease fencing and Gate 5 verification."""
    tool_cap = capability or f"autogen:{func.__name__}"
    res_uri = target_resource or f"autogen://tools/{func.__name__}"
    return govern_action(
        capability=tool_cap,
        client=client,
        action_type=action_type,
        target_resource=res_uri,
        observer=observer,
        enforcement_mode=enforcement_mode,
    )(func)
