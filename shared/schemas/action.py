"""Typed Phase 3 Action Assurance, Tool Governance, and Action Contract schemas."""

import hashlib
import ipaddress
import json
import re
import unicodedata
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from pydantic import BaseModel, Field

from shared.schemas.control_plane import Decision, Taint


class ActionType(StrEnum):
    """Categorization of real-world state mutations."""

    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"
    EGRESS = "EGRESS"


class ToolType(StrEnum):
    """Execution modality of a registered tool."""

    NATIVE = "NATIVE"
    MCP = "MCP"
    HTTP = "HTTP"


class EgressType(StrEnum):
    """Egress boundary classification for Dynamic Information Flow Control (DIFC)."""

    INTERNAL_ISOLATED = "INTERNAL_ISOLATED"
    EGRESS_EXTERNAL = "EGRESS_EXTERNAL"


class ToolTrustLevel(StrEnum):
    """Trust tier assigned to tools in the registry."""

    UNTRUSTED = "UNTRUSTED"
    VERIFIED = "VERIFIED"
    INTERNAL = "INTERNAL"


class ActionState(StrEnum):
    """Governed lifecycle state of an AI Action Contract."""

    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ApprovalStatus(StrEnum):
    """Human-in-the-loop (L4) approval status."""

    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class PreconditionRule(BaseModel):
    """Executable pre-execution assertion."""

    check_type: str = Field(description="Type of check: RESOURCE_EXISTS, NUMERIC_LTE, ALLOWLIST, etc.")
    target: str = Field(description="Target field or entity path evaluated")
    expected_value: Any = None
    description: str = ""


class PostconditionRule(BaseModel):
    """Verifiable post-execution state assertion for Reality Verification foundation."""

    assertion: str = Field(description="Assertion type: STATUS_EQUALS, OUTPUT_KEY_EXISTS, RECORD_MODIFIED")
    target: str
    expected_value: Any = None
    description: str = ""


class BlastRadiusAssessment(BaseModel):
    """Blast radius and environmental criticality accounting."""

    resource_scope: str = Field(default="DEFAULT", description="Scope of resource impacted")
    estimated_dollar_cost: float = Field(default=0.0, ge=0.0, description="Financial value or fee involved")
    affected_records_count: int = Field(default=1, ge=0, description="Estimated count of database rows/files affected")
    reversibility: str = Field(default="REVERSIBLE", description="REVERSIBLE, COMPENSABLE, or IRREVERSIBLE")
    target_environment: str = Field(default="DEV", description="DEV, STAGING, or PROD")


def compute_parameters_hash(normalized_params: dict[str, Any]) -> str:
    """Compute a canonical cryptographic SHA-256 hash of normalized parameters."""
    canonical_repr = json.dumps(normalized_params, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()


def compute_contract_binding_hash(
    *,
    tenant_id: str,
    transaction_id: str,
    action_id: str,
    tool_name: str,
    action_type: str,
    target_resource: str,
    parameters_hash: str,
    required_capability: str | None = None,
    estimated_dollar_cost: float = 0.0,
    taint_flags: list[str] | None = None,
) -> str:
    """Compute an immutable, cryptographic SHA-256 fingerprint binding all security-critical contract fields.

    Protects against post-approval tampering of target_resource, tool_name, action_type,
    capabilities, blast radius, or context taints.
    """
    sorted_taints = sorted(taint_flags or [])
    envelope = {
        "tenant_id": tenant_id,
        "transaction_id": transaction_id,
        "action_id": action_id,
        "tool_name": tool_name,
        "action_type": str(action_type).upper(),
        "target_resource": target_resource,
        "parameters_hash": parameters_hash,
        "required_capability": required_capability or "",
        "estimated_dollar_cost": round(float(estimated_dollar_cost), 4),
        "taint_flags": sorted_taints,
    }
    canonical_repr = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()


# SSRF security constants
_FORBIDDEN_URL_SCHEMES = {"file", "gopher", "dict", "ftp", "ldap", "tftp", "telnet", "ssh"}
_RESTRICTED_HOSTNAMES = {
    "localhost",
    "localhost.",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}


def _is_ip_restricted(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address belongs to loopback, private, link-local, multicast, or unspecified ranges."""
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True

    # IPv4-mapped IPv6 check (e.g., ::ffff:127.0.0.1 or ::ffff:169.254.169.254)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return _is_ip_restricted(ip.ipv4_mapped)

    return False


def _check_and_normalize_url(val: str, clean_key: str) -> str:
    """Validate and normalize a URL with comprehensive anti-SSRF protections."""
    parsed = urlparse(val)
    scheme = parsed.scheme.lower()

    if scheme in _FORBIDDEN_URL_SCHEMES:
        raise ValueError(f"Restricted URL scheme '{scheme}' blocked in parameter '{clean_key}'")

    if scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme '{scheme}' in parameter '{clean_key}'")

    raw_hostname = parsed.hostname
    if not raw_hostname:
        raise ValueError(f"Missing or invalid hostname in URL for parameter '{clean_key}'")

    hostname = raw_hostname.lower().strip("[]")

    # Hostname blocklist
    if hostname in _RESTRICTED_HOSTNAMES or hostname.endswith(".localhost"):
        raise ValueError(f"SSRF attempt blocked to restricted host '{hostname}' in parameter '{clean_key}'")

    # IP detection (decimal, hex, octal, standard dotted-quad, or IPv6)
    target_ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None

    # Try standard IP parsing first
    try:
        target_ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass

    # Try integer/decimal IP (e.g. 2130706433 or 0x7f000001)
    if target_ip is None:
        try:
            if hostname.startswith("0x"):
                val_int = int(hostname, 16)
                target_ip = ipaddress.IPv4Address(val_int)
            elif hostname.isdigit():
                val_int = int(hostname, 10)
                if 0 <= val_int <= 0xFFFFFFFF:
                    target_ip = ipaddress.IPv4Address(val_int)
        except (ValueError, OverflowError):
            pass

    # Try octal-dotted IPv4 (e.g. 0177.0.0.1)
    if target_ip is None and "." in hostname:
        parts = hostname.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            try:
                octets = [int(p, 8 if (len(p) > 1 and p.startswith("0")) else 10) for p in parts]
                if all(0 <= o <= 255 for o in octets):
                    target_ip = ipaddress.IPv4Address(bytes(octets))
            except (ValueError, OverflowError):
                pass

    if target_ip is not None and _is_ip_restricted(target_ip):
        raise ValueError(
            f"SSRF attempt blocked to restricted IP address '{target_ip}' in parameter '{clean_key}'"
        )

    # Standard port and host normalization
    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        canonical_netloc = f"{hostname}:{port}"
    else:
        canonical_netloc = hostname

    # Deterministically sort query params
    query_dict = parse_qs(parsed.query, keep_blank_values=True)
    sorted_query = urlencode(sorted((qk, qv[0]) for qk, qv in query_dict.items()))
    normalized_url = f"{scheme}://{canonical_netloc}{parsed.path}"
    if sorted_query:
        normalized_url += f"?{sorted_query}"
    return normalized_url


def normalize_action_parameters(raw_params: dict[str, Any]) -> dict[str, Any]:
    """Recursively sanitize, normalize paths and URLs, and format parameters canonically.

    Prevents evasion via path traversal, SSRF, URL scheme variation, query parameter scrambling,
    and trailing whitespace tricks.
    """
    normalized: dict[str, Any] = {}

    for k, v in raw_params.items():
        clean_key = str(k).strip()
        if isinstance(v, str):
            val_clean = unicodedata.normalize("NFKC", v).strip()

            # Reject null bytes
            if "\x00" in val_clean or "%00" in val_clean:
                raise ValueError(f"Null byte detected in parameter '{clean_key}'")

            # Check for non-HTTP URI schemes
            for scheme in _FORBIDDEN_URL_SCHEMES:
                if val_clean.lower().startswith(f"{scheme}:"):
                    raise ValueError(f"Restricted URI scheme '{scheme}' in parameter '{clean_key}'")

            # Path traversal check & normalization (unquote to catch %2e%2e)
            unquoted_val = unquote(val_clean)
            if ".." in unquoted_val or unquoted_val.startswith("../") or unquoted_val.startswith("..\\"):
                if re.search(r"(?:^|[/\\])\.\.(?:[/\\]|$)", unquoted_val):
                    raise ValueError(f"Path traversal detected in parameter '{clean_key}': {val_clean}")

            # Windows drive or UNC path traversal check
            if re.match(r"^[A-Za-z]:[/\\]", unquoted_val) or unquoted_val.startswith(("\\\\", "//")):
                raise ValueError(f"Absolute filesystem or UNC path blocked in parameter '{clean_key}': {val_clean}")

            # URL normalization
            if val_clean.lower().startswith(("http://", "https://")):
                normalized[clean_key] = _check_and_normalize_url(val_clean, clean_key)
            else:
                normalized[clean_key] = val_clean
        elif isinstance(v, dict):
            normalized[clean_key] = normalize_action_parameters(v)
        elif isinstance(v, list):
            normalized_list: list[Any] = []
            for item in v:
                if isinstance(item, dict):
                    normalized_list.append(normalize_action_parameters(item))
                elif isinstance(item, str):
                    clean_item = unicodedata.normalize("NFKC", item).strip()
                    if "\x00" in clean_item or "%00" in clean_item:
                        raise ValueError(f"Null byte detected in parameter '{clean_key}'")
                    unquoted_item = unquote(clean_item)
                    if re.search(r"(?:^|[/\\])\.\.(?:[/\\]|$)", unquoted_item):
                        raise ValueError(f"Path traversal detected in parameter '{clean_key}': {item}")
                    if clean_item.lower().startswith(("http://", "https://")):
                        normalized_list.append(_check_and_normalize_url(clean_item, clean_key))
                    else:
                        normalized_list.append(clean_item)
                else:
                    normalized_list.append(item)
            normalized[clean_key] = normalized_list
        else:
            normalized[clean_key] = v

    return normalized


class ActionProposal(BaseModel):
    """Proposal for a single real-world action generated by agent/planner."""

    transaction_id: str = Field(min_length=1, max_length=64)
    tool_name: str = Field(min_length=1, max_length=128)
    action_type: ActionType = ActionType.EXECUTE
    target_resource: str = Field(min_length=1, max_length=512)
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=255)
    preconditions: list[PreconditionRule] = Field(default_factory=list)
    postconditions: list[PostconditionRule] = Field(default_factory=list)
    blast_radius: BlastRadiusAssessment = Field(default_factory=BlastRadiusAssessment)


class ActionBatchProposal(BaseModel):
    """Atomic batch proposal containing parallel tool calls."""

    transaction_id: str = Field(min_length=1, max_length=64)
    actions: list[ActionProposal] = Field(min_length=1, max_length=16)


class ActionAuthorizationDecision(BaseModel):
    """Gate 3 Action Assurance deterministic decision."""

    action_id: str
    decision: Decision
    state: ActionState
    reason: str
    risk_score: int = Field(ge=0, le=100)
    autonomy_level: int = Field(ge=0, le=4)
    normalized_parameters: dict[str, Any]
    parameters_hash: str
    approval_id: str | None = None
    cumulative_window_risk: int = 0
    cumulative_window_cost: float = 0.0
    is_salami_slice_violation: bool = False


class BatchAuthorizationDecision(BaseModel):
    """Batch-level atomic decision enforcing all-or-nothing execution semantics."""

    transaction_id: str
    batch_decision: Decision
    batch_reason: str
    actions: list[ActionAuthorizationDecision]


class ActionExecutionRequest(BaseModel):
    """Request to execute an authorized action via Tool Proxy."""

    action_id: str
    approval_token: str | None = None


class ActionExecutionResult(BaseModel):
    """Result of governed execution through Tool Proxy."""

    action_id: str
    transaction_id: str
    state: ActionState
    observed_output: dict[str, Any] = Field(default_factory=dict)
    taints: set[Taint] = Field(default_factory=set)
    postconditions_satisfied: bool
    postcondition_evidence: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None


class BatchExecutionResult(BaseModel):
    """Result of atomic batch execution."""

    transaction_id: str
    results: list[ActionExecutionResult]
    all_completed: bool


class ToolRegistrationRequest(BaseModel):
    """Registration contract for managed native, MCP, or HTTP tools."""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    tool_type: ToolType = ToolType.NATIVE
    egress_type: EgressType = EgressType.INTERNAL_ISOLATED
    trust_level: ToolTrustLevel = ToolTrustLevel.VERIFIED
    required_capability: str = Field(min_length=1, max_length=128)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    active: bool = True


class ToolResponse(BaseModel):
    """Public representation of registered tool."""

    id: str
    tenant_id: str
    name: str
    description: str
    tool_type: ToolType
    egress_type: EgressType
    trust_level: ToolTrustLevel
    required_capability: str
    parameters_schema: dict[str, Any]
    active: bool
    created_at: str


class ApprovalDecisionRequest(BaseModel):
    """Human approval sign-off or denial."""

    decision: str = Field(pattern="^(GRANT|DENY)$")
    reason: str = Field(min_length=1, max_length=1000)


class ApprovalResponse(BaseModel):
    """Public representation of human approval record."""

    id: str
    tenant_id: str
    action_id: str
    transaction_id: str
    required_role: str
    status: ApprovalStatus
    parameters_hash: str
    requested_by: str
    decided_by: str | None
    decision_reason: str | None
    expires_at: str
    created_at: str
