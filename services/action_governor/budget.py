"""Subsystem: Gate 3 Action Assurance.
Module: Salami-Slicing Defense & Cumulative Blast Radius Accounting.
Authoritative Specs: Technical_Architecture.md §6, Security.md §4.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from db.models import ActionContract, ToolDefinition
from shared.schemas.action import ActionProposal, ActionState, ActionType, ToolTrustLevel

# Constants for Salami-Slicing Defense & Cumulative Blast Radius
MAX_WINDOW_HOURS = 1
MAX_WINDOW_CUMULATIVE_COST = 1000.0  # Max aggregate dollars spent in 1-hour window
MAX_WINDOW_CUMULATIVE_RISK = 250  # Max aggregate risk score points in 1-hour window
MAX_WINDOW_ACTION_COUNT = 50  # Max actions in 1-hour window


async def evaluate_risk_and_salami_budget(
    session: Any,
    tenant_id: str,
    req: ActionProposal,
    tool: ToolDefinition,
    normalized_params: dict[str, Any],
    now: datetime,
) -> tuple[int, int, float, int, float, bool]:
    """Compute single-action risk, autonomy level, and cumulative blast radius budget."""
    base_risk = {
        ActionType.READ.value: 10,
        ActionType.WRITE.value: 35,
        ActionType.EXECUTE.value: 40,
        ActionType.EGRESS.value: 50,
        ActionType.DELETE.value: 65,
    }.get(req.action_type.value, 40)

    trust_mod = {
        ToolTrustLevel.INTERNAL.value: 0,
        ToolTrustLevel.VERIFIED.value: 10,
        ToolTrustLevel.UNTRUSTED.value: 25,
    }.get(tool.trust_level, 10)

    env_mod = {
        "DEV": 0,
        "STAGING": 15,
        "PROD": 30,
    }.get(req.blast_radius.target_environment.upper(), 10)

    param_cost = 0.0
    for cost_key in ("amount", "amount_usd", "estimated_cost", "dollar_cost", "spend"):
        cval = normalized_params.get(cost_key)
        if isinstance(cval, (int, float)):
            param_cost = max(param_cost, float(cval))

    effective_cost = max(float(req.blast_radius.estimated_dollar_cost), param_cost)
    cost_mod = min(25, int(effective_cost / 100.0))
    single_action_risk = min(100, base_risk + trust_mod + env_mod + cost_mod)
    autonomy_level = min(4, single_action_risk // 20)

    # Salami-Slicing Defense & Cumulative Blast Radius Accounting
    window_start = now - timedelta(hours=MAX_WINDOW_HOURS)
    blast_stmt = select(
        func.count(ActionContract.id).label("count"),
        func.coalesce(func.sum(ActionContract.risk_score), 0).label("cumulative_risk"),
    ).where(
        ActionContract.tenant_id == tenant_id,
        ActionContract.created_at >= window_start,
        ActionContract.state.in_(
            [
                ActionState.AUTHORIZED.value,
                ActionState.EXECUTING.value,
                ActionState.COMPLETED.value,
            ]
        ),
    )
    blast_res = await session.execute(blast_stmt)
    blast_row = blast_res.one()
    window_count = int(blast_row[0] or 0)
    window_risk = int(blast_row[1] or 0)

    # Sum cumulative dollar cost
    cost_contracts_stmt = select(ActionContract.blast_radius).where(
        ActionContract.tenant_id == tenant_id,
        ActionContract.created_at >= window_start,
        ActionContract.state.in_(
            [
                ActionState.AUTHORIZED.value,
                ActionState.EXECUTING.value,
                ActionState.COMPLETED.value,
            ]
        ),
    )
    cost_contracts_res = await session.execute(cost_contracts_stmt)
    all_radii = cost_contracts_res.scalars().all()
    window_cost = sum(float(r.get("estimated_dollar_cost", 0.0) or 0.0) for r in all_radii if isinstance(r, dict))

    is_salami_violation = bool(
        (window_risk + single_action_risk > MAX_WINDOW_CUMULATIVE_RISK)
        or (window_cost + effective_cost > MAX_WINDOW_CUMULATIVE_COST)
        or (window_count >= MAX_WINDOW_ACTION_COUNT)
    )

    return single_action_risk, autonomy_level, effective_cost, window_risk, window_cost, is_salami_violation
