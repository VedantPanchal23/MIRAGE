"""Correction State: State definition for LangGraph correction state machine."""

from typing import Any, TypedDict


class MirageAgentState(TypedDict):
    """State schema for the MIRAGE autonomous correction loop."""

    response_id: str
    original_response: str
    flagged_claims: list[dict[str, Any]]
    evidence_map: dict[str, list[str]]
    rewritten_claims: dict[str, str]
    rewrite_hrs: float
    correction_attempts: int
    escalated: bool
    final_response: str
    history: list[dict[str, Any]]
