"""Shared schema exports."""

from shared.schemas.audit import AuditLogEntry, compute_sha256
from shared.schemas.auth import ROLE_PERMISSIONS, AuthContext, Permission, Role
from shared.schemas.claims import (
    CRITICALITY_WEIGHTS,
    Claim,
    ClaimCriticality,
    ClaimType,
    ClaimVerificationResult,
    EvidenceChunk,
    VerificationStatus,
)
from shared.schemas.hrs import (
    ConformalInterval,
    HRSResult,
    RiskTier,
    SignalAttribution,
    determine_risk_tier,
)
from shared.schemas.verification import (
    VerificationMetadata,
    VerificationRequest,
    VerificationResponse,
    VerificationStreamEvent,
)

__all__ = [
    "AuditLogEntry",
    "compute_sha256",
    "AuthContext",
    "Role",
    "Permission",
    "ROLE_PERMISSIONS",
    "Claim",
    "ClaimCriticality",
    "ClaimType",
    "ClaimVerificationResult",
    "CRITICALITY_WEIGHTS",
    "EvidenceChunk",
    "VerificationStatus",
    "ConformalInterval",
    "HRSResult",
    "RiskTier",
    "SignalAttribution",
    "determine_risk_tier",
    "VerificationMetadata",
    "VerificationRequest",
    "VerificationResponse",
    "VerificationStreamEvent",
]
