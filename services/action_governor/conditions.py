"""Subsystem: Gate 3 Action Assurance.
Module: Precondition, Postcondition, and Outcome Assurance Contract Evaluation.
Authoritative Specs: Technical_Architecture.md §6, AI_Action_Contract.md §4.
"""

from __future__ import annotations

from typing import Any

from db.models import ToolDefinition
from shared.schemas.action import (
    ActionProposal,
    ActionType,
    PostconditionRule,
    PreconditionRule,
    ToolType,
)


def evaluate_precondition(precond: PreconditionRule, params: dict[str, Any], target_resource: str) -> bool:
    """Deterministic evaluation of pre-execution state checks."""
    check = precond.check_type.upper()
    if check == "RESOURCE_EXISTS":
        return bool(target_resource and len(target_resource) > 0)
    elif check == "PARAM_EXISTS":
        return precond.target in params and params[precond.target] is not None
    elif check == "NUMERIC_LTE":
        val = params.get(precond.target)
        if isinstance(val, (int, float)) and isinstance(precond.expected_value, (int, float)):
            return val <= precond.expected_value
        return False
    elif check == "ALLOWLIST":
        val = params.get(precond.target)
        if isinstance(precond.expected_value, list):
            return val in precond.expected_value
        return False
    elif check == "EQUALS":
        return bool(params.get(precond.target) == precond.expected_value)
    return True


def evaluate_postcondition(post: PostconditionRule, observed: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Evaluate postconditions against observed tool outputs."""
    assertion = post.assertion.upper()
    evidence: dict[str, Any] = {
        "assertion": assertion,
        "target": post.target,
        "expected_value": post.expected_value,
        "observed_value": observed.get(post.target),
    }

    if assertion == "KEY_EXISTS":
        satisfied = post.target in observed
    elif assertion == "STATUS_EQUALS":
        satisfied = observed.get("status") == post.expected_value
    elif assertion == "EQUALS":
        satisfied = observed.get(post.target) == post.expected_value
    else:
        satisfied = post.target in observed

    evidence["satisfied"] = satisfied
    return satisfied, evidence


def build_outcome_assurance_contract(
    req: ActionProposal,
    tool: ToolDefinition,
    single_action_risk: int,
    autonomy_level: int,
    effective_cost: float,
    requires_human_approval: bool,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Validate and construct Gate 5 Outcome Assurance Contract specification."""
    requires_outcome_assurance = bool(
        (req.outcome_contract and req.outcome_contract.requires_outcome_assurance)
        or req.action_type in (ActionType.WRITE, ActionType.DELETE, ActionType.EXECUTE, ActionType.EGRESS)
        or single_action_risk >= 40
        or autonomy_level >= 2
        or effective_cost > 0.0
    )

    if not requires_outcome_assurance:
        return False, None, None

    merged_postconditions = list(req.postconditions)
    if req.outcome_contract and req.outcome_contract.expected_postconditions:
        for ep in req.outcome_contract.expected_postconditions:
            if isinstance(ep, dict) and "target" in ep:
                assertion = ep.get("assertion", "EQUALS")
                merged_postconditions.append(
                    PostconditionRule(
                        assertion=assertion,
                        target=ep["target"],
                        expected_value=ep.get("expected_value"),
                    )
                )

    # Criterion 1: Must define expected postconditions for autonomous authorization
    if not requires_human_approval and len(merged_postconditions) == 0:
        return (
            True,
            None,
            (
                "Outcome Assurance contract violation: "
                "action requires outcome assurance but defines zero expected postconditions."
            ),
        )

    # Criterion 2: Acceptable evidence sources
    acceptable_sources: list[str] = []
    if req.outcome_contract and req.outcome_contract.acceptable_evidence_sources:
        acceptable_sources = req.outcome_contract.acceptable_evidence_sources
    elif tool.tool_type == ToolType.HTTP:
        scheme = req.target_resource.split("://")[0] if "://" in req.target_resource else "http"
        acceptable_sources = [f"http:{scheme}", "HTTP_RESOURCE"]
    else:
        acceptable_sources = ["DATABASE", "HTTP_RESOURCE", "ASYNC_EVENT", "INDEPENDENT_OBSERVER"]

    if req.outcome_contract and len(req.outcome_contract.acceptable_evidence_sources) == 0:
        return (
            True,
            None,
            (
                "Outcome Assurance contract violation: "
                "acceptable_evidence_sources cannot be empty when outcome contract is specified."
            ),
        )

    # Criterion 3: Verification deadline
    deadline_sec = 30.0
    if req.outcome_contract:
        if req.outcome_contract.verification_deadline_seconds <= 0:
            return (
                True,
                None,
                "Outcome Assurance contract violation: verification_deadline_seconds must be positive.",
            )
        deadline_sec = req.outcome_contract.verification_deadline_seconds

    outcome_contract_dict = {
        "requires_outcome_assurance": True,
        "expected_postconditions": [p.model_dump() for p in merged_postconditions],
        "acceptable_evidence_sources": acceptable_sources,
        "verification_deadline_seconds": deadline_sec,
        "risk_sensitive_verification_policy": (
            req.outcome_contract.risk_sensitive_verification_policy.value
            if req.outcome_contract
            else "STRICT_DIRECT_ONLY"
            if single_action_risk >= 60
            else "DEFAULT"
        ),
        "on_partial": req.outcome_contract.on_partial.value if req.outcome_contract else "HOLD_FOR_REVIEW",
        "on_uncertain": req.outcome_contract.on_uncertain.value if req.outcome_contract else "ESCALATE",
    }

    return True, outcome_contract_dict, None
