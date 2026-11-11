"""Authoritative SQLAlchemy ORM Models Package for MIRAGE 3.0.

Provides modular domain definitions:
- core: Tenants, Users, Agents, Identities, API Credentials
- governance: ActionContracts, Approvals, Leases, Delegations, Handoffs, Tools, MCP
- assurance: VerificationSessions, Claims, Output/Outcome records, KB documents
- audit: AuditLogRecord, TenantAuditLedger, Checkpoints, Operator Alerts, Reports
- finance: Budgets, Cost records, Model pricing, Transactions, Inquiries, Webhooks
"""

from db.session import Base

from .assurance import (
    ClaimRecord,
    KBDocumentRecord,
    OutcomeVerificationRecord,
    OutputAssuranceRecord,
    VerificationSession,
)
from .audit import (
    AuditCheckpointRecord,
    AuditLogRecord,
    AuditReport,
    OperatorAlert,
    TenantAuditLedger,
)
from .core import (
    ActorIdentity,
    Agent,
    ApiCredential,
    Tenant,
    User,
)
from .finance import (
    AccountingIncidentRecord,
    AITransaction,
    Budget,
    BudgetReservationRecord,
    InquiryRecord,
    ModelPricingProfileRecord,
    ModelRegistryRecord,
    ProviderInvocationRecord,
    TenantBudgetRecord,
    TransactionCostRecord,
    WebhookSubscriptionRecord,
)
from .governance import (
    ActionApproval,
    ActionContract,
    AgentDelegation,
    AgentHandoff,
    Capability,
    GovernedMemory,
    MCPServer,
    Policy,
    ResourceLease,
    ToolDefinition,
)

__all__ = [
    "Base",
    "AccountingIncidentRecord",
    "ActionApproval",
    "ActionContract",
    "ActorIdentity",
    "Agent",
    "AgentDelegation",
    "AgentHandoff",
    "AITransaction",
    "ApiCredential",
    "AuditCheckpointRecord",
    "AuditLogRecord",
    "AuditReport",
    "Budget",
    "BudgetReservationRecord",
    "Capability",
    "ClaimRecord",
    "GovernedMemory",
    "InquiryRecord",
    "KBDocumentRecord",
    "MCPServer",
    "ModelPricingProfileRecord",
    "ModelRegistryRecord",
    "OperatorAlert",
    "OutcomeVerificationRecord",
    "OutputAssuranceRecord",
    "Policy",
    "ProviderInvocationRecord",
    "ResourceLease",
    "Tenant",
    "TenantAuditLedger",
    "TenantBudgetRecord",
    "ToolDefinition",
    "TransactionCostRecord",
    "User",
    "VerificationSession",
    "WebhookSubscriptionRecord",
]
