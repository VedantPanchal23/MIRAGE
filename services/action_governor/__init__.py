"""Gate 3 Action Assurance and Governance Service Package.

Authoritative module for capability-based access control, tool registration,
concurrency lease verification, sandboxed tool dispatch, and action reconciliation.
"""

from db import session as db_session
from services.agent_governance import agent_governance_service
from services.concurrency_service import concurrency_service

from .audit import _record_action_audit_event
from .proxy import (
    GovernedToolProxy,
    ToolProxyBypassError,
    _safe_eval_math,
)
from .service import (
    MAX_WINDOW_ACTION_COUNT,
    MAX_WINDOW_CUMULATIVE_COST,
    MAX_WINDOW_CUMULATIVE_RISK,
    MAX_WINDOW_HOURS,
    ActionGovernorService,
)

__all__ = [
    "ActionGovernorService",
    "GovernedToolProxy",
    "MAX_WINDOW_ACTION_COUNT",
    "MAX_WINDOW_CUMULATIVE_COST",
    "MAX_WINDOW_CUMULATIVE_RISK",
    "MAX_WINDOW_HOURS",
    "ToolProxyBypassError",
    "_record_action_audit_event",
    "_safe_eval_math",
    "agent_governance_service",
    "concurrency_service",
    "db_session",
]
