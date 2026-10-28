"""Production-grade Python SDK Client for MIRAGE 3.0 Execution Assurance Platform.

Provides both synchronous (MirageClient) and asynchronous (AsyncMirageClient)
interfaces adhering to MIRAGE 3.0 core architectural invariants:

1. Epistemic Outcome Independence:
   Tool execution return value is NOT proof of real-world outcome. Gate 5 reality
   verification is decoupled and independently measured.
2. Execution Uncertainty Preservation:
   Mutating actions encountering network timeouts or disconnects are treated as
   EXECUTION_UNCERTAIN and NEVER blindly redispatched or automatically retried.
3. Fail-Closed Authentication:
   Tenant and agent authorization is strictly server-bound. Credentials are sanitized
   and never logged, leaked in URLs, or reflected in error messages.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import TracebackType
from typing import Any, Self, cast

import httpx

from mirage_sdk.exceptions import (
    MirageAuthenticationError,
    MirageAuthorizationError,
    MirageError,
    MirageExecutionUncertainError,
    MirageNotFoundError,
    MirageRateLimitError,
    MirageServerError,
    MirageTransportError,
    MirageValidationError,
)
from mirage_sdk.models import (
    ActionAuthorizationDecision,
    ActionExecutionRequest,
    ActionExecutionResult,
    ActionProposal,
    ActionState,
    ApprovalDecisionRequest,
    ApprovalResponse,
    AuditChainVerificationResponse,
    MCPServerCreateRequest,
    MCPServerListResponse,
    MCPServerResponse,
    MCPToolDiscoveryResult,
    MCPTrustStatus,
    MCPTrustStatusUpdateRequest,
    OutcomeVerificationContract,
    OutcomeVerificationRequest,
    StrandedActionInfo,
    ToolResponse,
    VerificationRequest,
    VerificationResponse,
)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3


def _extract_request_id(headers: httpx.Headers, body: Any) -> str | None:
    """Extract request correlation ID from HTTP headers or response body."""
    req_id = headers.get("X-Request-ID") or headers.get("x-request-id")
    if not req_id and isinstance(body, dict):
        req_id = body.get("request_id") or body.get("trace_id")
    return str(req_id) if req_id is not None else None


def _handle_error_response(response: httpx.Response, action_id: str | None = None) -> None:
    """Translate HTTP status codes to typed MIRAGE SDK exceptions without leaking secrets."""
    status_code = response.status_code
    req_id = _extract_request_id(response.headers, None)

    try:
        body: Any = response.json()
    except (ValueError, json.JSONDecodeError):
        body = response.text

    error_msg = ""
    detail: Any = None
    if isinstance(body, dict):
        detail = body.get("detail")
        error_msg = str(detail or body.get("message") or response.reason_phrase)
    else:
        error_msg = str(body)[:500] if body else response.reason_phrase

    if status_code == 401:
        raise MirageAuthenticationError(
            f"Authentication failed (HTTP 401): {error_msg}",
            status_code=401,
            response_body=body,
            request_id=req_id,
        )
    elif status_code == 403:
        raise MirageAuthorizationError(
            f"Authorization denied (HTTP 403): {error_msg}",
            status_code=403,
            response_body=body,
            request_id=req_id,
        )
    elif status_code == 404:
        raise MirageNotFoundError(
            f"Resource not found (HTTP 404): {error_msg}",
            status_code=404,
            response_body=body,
            request_id=req_id,
        )
    elif status_code in (400, 422):
        validation_errors = detail if isinstance(detail, list) else None
        raise MirageValidationError(
            f"Validation error (HTTP {status_code}): {error_msg}",
            status_code=status_code,
            response_body=body,
            request_id=req_id,
            errors=validation_errors,
        )
    elif status_code == 429:
        retry_after: float | None = None
        raw_retry = response.headers.get("Retry-After")
        if raw_retry:
            try:
                retry_after = float(raw_retry)
            except ValueError:
                pass
        raise MirageRateLimitError(
            f"Rate limit exceeded (HTTP 429): {error_msg}",
            status_code=429,
            response_body=body,
            request_id=req_id,
            retry_after=retry_after,
        )
    elif 500 <= status_code < 600:
        raise MirageServerError(
            f"Server error (HTTP {status_code}): {error_msg}",
            status_code=status_code,
            response_body=body,
            request_id=req_id,
        )
    else:
        raise MirageError(
            f"Unexpected HTTP {status_code} response: {error_msg}",
            status_code=status_code,
            response_body=body,
            request_id=req_id,
        )


# =============================================================================
# Synchronous MirageClient
# =============================================================================


class MirageClient:
    """Synchronous Python client for MIRAGE 3.0 Execution Assurance APIs.

    Example:
        with MirageClient(api_key="mirage_key_...", base_url="http://localhost:8000") as client:
            resp = client.verify(prompt="...", response="...")
            print("HRS score:", resp.hrs_result.hrs)
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "http://localhost:8000",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key or not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")

        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

        headers = {
            "X-API-Key": self._api_key,
            "User-Agent": "mirage-python-sdk/3.0.0",
            "Accept": "application/json",
        }

        self._http = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP transport session."""
        self._http.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: Any = None,
        params: dict[str, Any] | None = None,
        is_mutating: bool = False,
        action_id: str | None = None,
    ) -> Any:
        """Execute HTTP request with strict retry bounds and execution uncertainty preservation."""
        retries_remaining = 0 if is_mutating else self.max_retries
        backoff = 0.25

        while True:
            try:
                resp = self._http.request(
                    method=method,
                    url=path,
                    json=json_data,
                    params=params,
                )

                # Safe retry for transient 429/502/503/504 on non-mutating requests
                if not is_mutating and resp.status_code in (429, 502, 503, 504) and retries_remaining > 0:
                    retries_remaining -= 1
                    raw_retry = resp.headers.get("Retry-After")
                    delay = float(raw_retry) if raw_retry and raw_retry.isdigit() else backoff
                    time.sleep(min(delay, 5.0))
                    backoff *= 2
                    continue

                if resp.status_code >= 400:
                    _handle_error_response(resp, action_id=action_id)

                return resp.json()

            except (httpx.TimeoutException, TimeoutError) as exc:
                if is_mutating:
                    # CRITICAL: Mutating requests must NEVER be retried on timeout. Outcome is uncertain.
                    raise MirageExecutionUncertainError(
                        f"Mutating {method} {path} timed out after {self.timeout}s: "
                        f"execution outcome is uncertain; blind redispatch is strictly prohibited",
                        action_id=action_id,
                    ) from exc

                if retries_remaining > 0:
                    retries_remaining -= 1
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                raise MirageTransportError(f"Safe request {method} {path} timed out: {exc}") from exc

            except httpx.NetworkError as exc:
                if is_mutating:
                    # CRITICAL: Network failure during/after transmission leaves remote state uncertain
                    raise MirageExecutionUncertainError(
                        f"Network failure during mutating {method} {path}: {exc}: "
                        f"remote side-effect status is uncertain; blind redispatch is prohibited",
                        action_id=action_id,
                    ) from exc

                if retries_remaining > 0:
                    retries_remaining -= 1
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                raise MirageTransportError(f"Network error on {method} {path}: {exc}") from exc

            except MirageError:
                raise
            except Exception as exc:
                raise MirageError(f"Unexpected error executing {method} {path}: {exc}") from exc

    # -------------------------------------------------------------------------
    # Gate 4: Verification API
    # -------------------------------------------------------------------------

    def verify(
        self,
        prompt: str,
        response: str,
        *,
        tenant_id: str = "",
        session_id: str | None = None,
        knowledge_base_id: str | None = None,
        model_id: str = "allam-2-7b",
        auto_correct: bool = True,
        image_urls: list[str] | None = None,
        images: list[str] | None = None,
    ) -> VerificationResponse:
        """Submit text and optional multimodal content for Gate 4 factual consistency verification."""
        req = VerificationRequest(
            prompt=prompt,
            response=response,
            tenant_id=tenant_id,
            session_id=session_id,
            knowledge_base_id=knowledge_base_id,
            model_id=model_id,
            auto_correct=auto_correct,
            image_urls=image_urls or [],
            images=images or [],
        )
        data = self._request("POST", "/v1/verify", json_data=req.model_dump(mode="json"), is_mutating=True)
        return VerificationResponse.model_validate(data)

    def get_output(self, output_id: str) -> dict[str, Any]:
        """Fetch previously recorded output and verification record by ID."""
        return self._request("GET", f"/v1/output/{output_id}", is_mutating=False)  # type: ignore[no-any-return]

    # -------------------------------------------------------------------------
    # Gate 3: Action Assurance & Tool Governance
    # -------------------------------------------------------------------------

    def register_tool(self, tool: dict[str, Any]) -> ToolResponse:
        """Register or update a tool in Gate 3 tenant tool registry."""
        data = self._request("POST", "/v1/tools", json_data=tool, is_mutating=True)
        return ToolResponse.model_validate(data)

    def list_tools(self) -> list[ToolResponse]:
        """List all registered tools for the authenticated tenant."""
        data = self._request("GET", "/v1/tools", is_mutating=False)
        return [ToolResponse.model_validate(item) for item in data]

    def propose_action(
        self,
        proposal: ActionProposal | dict[str, Any],
    ) -> ActionAuthorizationDecision:
        """Submit an ActionProposal to Gate 3 Action Assurance for policy, lease, and risk evaluation."""
        payload = proposal.model_dump(mode="json") if isinstance(proposal, ActionProposal) else proposal
        data = self._request("POST", "/v1/actions/propose", json_data=payload, is_mutating=True)
        return ActionAuthorizationDecision.model_validate(data)

    def execute_action(
        self,
        action_id: str,
        *,
        approval_token: str | None = None,
    ) -> ActionExecutionResult:
        """Execute an authorized action contract through the Governed Tool Proxy.

        Preserves EXECUTION_UNCERTAIN without translating to success or standard failure.
        """
        req = ActionExecutionRequest(action_id=action_id, approval_token=approval_token)
        data = self._request(
            "POST",
            "/v1/actions/execute",
            json_data=req.model_dump(mode="json"),
            is_mutating=True,
            action_id=action_id,
        )
        return ActionExecutionResult.model_validate(data)

    def get_action(self, action_id: str) -> dict[str, Any]:
        """Inspect the lifecycle state, parameters hash, and audit details of an Action Contract."""
        return self._request("GET", f"/v1/actions/{action_id}", is_mutating=False)  # type: ignore[no-any-return]

    def list_stranded_actions(self, *, older_than_seconds: int = 60) -> list[StrandedActionInfo]:
        """List actions stranded in EXECUTING or EXECUTION_UNCERTAIN state across worker lifecycles."""
        data = self._request(
            "GET",
            "/v1/actions/stranded",
            params={"older_than_seconds": older_than_seconds},
            is_mutating=False,
        )
        return [StrandedActionInfo.model_validate(item) for item in data]

    def reconcile_action(
        self,
        action_id: str,
        resolution_state: str | ActionState,
        *,
        rationale: str,
        verified_evidence: dict[str, Any] | None = None,
    ) -> ActionExecutionResult:
        """Idempotently reconcile a stranded action to a terminal verified state."""
        state_str = resolution_state.value if isinstance(resolution_state, ActionState) else str(resolution_state)
        resolution_map = {
            "FAILED": "MARK_FAILED",
            "COMPLETED": "MARK_COMPLETED",
            "EXECUTION_UNCERTAIN": "MARK_UNCERTAIN",
            "MARK_FAILED": "MARK_FAILED",
            "MARK_COMPLETED": "MARK_COMPLETED",
            "MARK_UNCERTAIN": "MARK_UNCERTAIN",
        }
        req_payload = {
            "action_id": action_id,
            "resolution": resolution_map.get(state_str, state_str),
            "notes": rationale,
            "observed_evidence": verified_evidence or {},
        }
        data = self._request(
            "POST",
            f"/v1/actions/{action_id}/reconcile",
            json_data=req_payload,
            is_mutating=True,
            action_id=action_id,
        )
        return ActionExecutionResult.model_validate(data)

    # -------------------------------------------------------------------------
    # Human Approvals
    # -------------------------------------------------------------------------

    def list_pending_approvals(self) -> list[ApprovalResponse]:
        """List pending L4 human approval requests for the authorized tenant."""
        data = self._request("GET", "/v1/approvals/pending", is_mutating=False)
        return [ApprovalResponse.model_validate(item) for item in data]

    def grant_approval(self, approval_id: str, *, reason: str) -> ApprovalResponse:
        """Grant a pending human approval ticket."""
        req = ApprovalDecisionRequest(reason=reason)
        data = self._request(
            "POST",
            f"/v1/approvals/{approval_id}/grant",
            json_data=req.model_dump(mode="json"),
            is_mutating=True,
        )
        return ApprovalResponse.model_validate(data)

    def deny_approval(self, approval_id: str, *, reason: str) -> ApprovalResponse:
        """Deny a pending human approval ticket."""
        req = ApprovalDecisionRequest(reason=reason)
        data = self._request(
            "POST",
            f"/v1/approvals/{approval_id}/deny",
            json_data=req.model_dump(mode="json"),
            is_mutating=True,
        )
        return ApprovalResponse.model_validate(data)

    # -------------------------------------------------------------------------
    # Gate 5: Outcome Assurance (Reality Verification)
    # -------------------------------------------------------------------------

    def get_outcome(self, action_id: str) -> OutcomeVerificationContract:
        """Fetch authoritative Gate 5 outcome verification record for an action."""
        data = self._request("GET", f"/v1/actions/{action_id}/outcome", is_mutating=False)
        return OutcomeVerificationContract.model_validate(data)

    def verify_outcome(
        self,
        action_id: str,
        request: OutcomeVerificationRequest | dict[str, Any],
    ) -> OutcomeVerificationContract:
        """Execute independent Gate 5 reality verification confirming real-world postconditions."""
        payload = request.model_dump(mode="json") if isinstance(request, OutcomeVerificationRequest) else request
        data = self._request(
            "POST",
            f"/v1/actions/{action_id}/outcome",
            json_data=payload,
            is_mutating=True,
            action_id=action_id,
        )
        return OutcomeVerificationContract.model_validate(data)

    # -------------------------------------------------------------------------
    # Audit API
    # -------------------------------------------------------------------------

    def verify_audit_hash_chain(self) -> AuditChainVerificationResponse:
        """Verify the cryptographic SHA-256 hash chain across all audit logs for calling tenant."""
        data = self._request("POST", "/v1/audit/verify-chain", is_mutating=False)
        return AuditChainVerificationResponse.model_validate(data)

    # -------------------------------------------------------------------------
    # MCP Registry Operations
    # -------------------------------------------------------------------------

    def list_mcp_servers(self, *, limit: int = 50, offset: int = 0) -> MCPServerListResponse:
        """List registered external MCP servers under tenant isolation."""
        data = self._request("GET", "/v1/mcp/servers", params={"limit": limit, "offset": offset}, is_mutating=False)
        return MCPServerListResponse.model_validate(data)

    def get_mcp_server(self, server_id: str) -> MCPServerResponse:
        """Retrieve details for a specific registered MCP server."""
        data = self._request("GET", f"/v1/mcp/servers/{server_id}", is_mutating=False)
        return MCPServerResponse.model_validate(data)

    def register_mcp_server(
        self,
        request: MCPServerCreateRequest | dict[str, Any],
    ) -> MCPServerResponse:
        """Register an external MCP server in PENDING_APPROVAL status."""
        payload = request.model_dump(mode="json") if isinstance(request, MCPServerCreateRequest) else request
        data = self._request("POST", "/v1/mcp/servers", json_data=payload, is_mutating=True)
        return MCPServerResponse.model_validate(data)

    def update_mcp_server_trust(
        self,
        server_id: str,
        trust_status: str | MCPTrustStatus,
        *,
        reason: str,
    ) -> MCPServerResponse:
        """Transition MCP server trust status (PENDING_APPROVAL -> TRUSTED, SUSPENDED, REVOKED)."""
        status_val = trust_status.value if isinstance(trust_status, MCPTrustStatus) else str(trust_status)
        req = MCPTrustStatusUpdateRequest(
            trust_status=MCPTrustStatus(status_val),
            reason=reason,
        )
        data = self._request(
            "PUT",
            f"/v1/mcp/servers/{server_id}/trust",
            json_data=req.model_dump(mode="json"),
            is_mutating=True,
        )
        return MCPServerResponse.model_validate(data)

    def discover_mcp_tools(self, server_id: str) -> MCPToolDiscoveryResult:
        """Discover tools from a TRUSTED MCP server, calculate schema fingerprints, and sync tools."""
        data = self._request("POST", f"/v1/mcp/servers/{server_id}/discover", is_mutating=True)
        return MCPToolDiscoveryResult.model_validate(data)

    # -------------------------------------------------------------------------
    # Commercial Billing & Subscription Operations
    # -------------------------------------------------------------------------

    def get_billing_plans(self) -> list[dict[str, Any]]:
        """Fetch available commercial pricing catalog and tier entitlement specifications."""
        return cast(list[dict[str, Any]], self._request("GET", "/v1/billing/plans", is_mutating=False))

    def get_subscription(self) -> dict[str, Any]:
        """Retrieve current tenant subscription tier, headroom, and budget utilization."""
        return cast(dict[str, Any], self._request("GET", "/v1/billing/subscription", is_mutating=False))

    # -------------------------------------------------------------------------
    # Inquiries & Tenant Self-Service Registration
    # -------------------------------------------------------------------------

    def create_inquiry(self, request: dict[str, Any]) -> dict[str, Any]:
        """Submit an enterprise sales inquiry, architecture review request, or custom SLA ticket."""
        return cast(dict[str, Any], self._request("POST", "/v1/inquiries", json_data=request, is_mutating=True))

    def register_tenant(self, request: dict[str, Any]) -> dict[str, Any]:
        """Self-service enterprise onboarding provisioning tenant, admin user, and production API key."""
        return cast(
            dict[str, Any], self._request("POST", "/v1/auth/register-tenant", json_data=request, is_mutating=True)
        )


# =============================================================================
# Asynchronous AsyncMirageClient
# =============================================================================


class AsyncMirageClient:
    """Asynchronous Python client for MIRAGE 3.0 Execution Assurance APIs.

    Example:
        async with AsyncMirageClient(api_key="mirage_key_...", base_url="http://localhost:8000") as client:
            resp = await client.verify(prompt="...", response="...")
            print("HRS score:", resp.hrs_result.hrs)
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "http://localhost:8000",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key or not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")

        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

        headers = {
            "X-API-Key": self._api_key,
            "User-Agent": "mirage-python-sdk/3.0.0",
            "Accept": "application/json",
        }

        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying async HTTP transport session."""
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: Any = None,
        params: dict[str, Any] | None = None,
        is_mutating: bool = False,
        action_id: str | None = None,
    ) -> Any:
        """Execute async HTTP request with strict retry bounds and execution uncertainty preservation."""
        retries_remaining = 0 if is_mutating else self.max_retries
        backoff = 0.25

        while True:
            try:
                resp = await self._http.request(
                    method=method,
                    url=path,
                    json=json_data,
                    params=params,
                )

                if not is_mutating and resp.status_code in (429, 502, 503, 504) and retries_remaining > 0:
                    retries_remaining -= 1
                    raw_retry = resp.headers.get("Retry-After")
                    delay = float(raw_retry) if raw_retry and raw_retry.isdigit() else backoff
                    await asyncio.sleep(min(delay, 5.0))
                    backoff *= 2
                    continue

                if resp.status_code >= 400:
                    _handle_error_response(resp, action_id=action_id)

                return resp.json()

            except (httpx.TimeoutException, TimeoutError) as exc:
                if is_mutating:
                    raise MirageExecutionUncertainError(
                        f"Mutating {method} {path} timed out after {self.timeout}s: "
                        f"execution outcome is uncertain; blind redispatch is strictly prohibited",
                        action_id=action_id,
                    ) from exc

                if retries_remaining > 0:
                    retries_remaining -= 1
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue

                raise MirageTransportError(f"Safe request {method} {path} timed out: {exc}") from exc

            except httpx.NetworkError as exc:
                if is_mutating:
                    raise MirageExecutionUncertainError(
                        f"Network failure during mutating {method} {path}: {exc}: "
                        f"remote side-effect status is uncertain; blind redispatch is prohibited",
                        action_id=action_id,
                    ) from exc

                if retries_remaining > 0:
                    retries_remaining -= 1
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue

                raise MirageTransportError(f"Network error on {method} {path}: {exc}") from exc

            except MirageError:
                raise
            except Exception as exc:
                raise MirageError(f"Unexpected error executing {method} {path}: {exc}") from exc

    # -------------------------------------------------------------------------
    # Gate 4: Verification API
    # -------------------------------------------------------------------------

    async def verify(
        self,
        prompt: str,
        response: str,
        *,
        tenant_id: str = "",
        session_id: str | None = None,
        knowledge_base_id: str | None = None,
        model_id: str = "allam-2-7b",
        auto_correct: bool = True,
        image_urls: list[str] | None = None,
        images: list[str] | None = None,
    ) -> VerificationResponse:
        """Submit text and optional multimodal content for Gate 4 factual consistency verification."""
        req = VerificationRequest(
            prompt=prompt,
            response=response,
            tenant_id=tenant_id,
            session_id=session_id,
            knowledge_base_id=knowledge_base_id,
            model_id=model_id,
            auto_correct=auto_correct,
            image_urls=image_urls or [],
            images=images or [],
        )
        data = await self._request("POST", "/v1/verify", json_data=req.model_dump(mode="json"), is_mutating=True)
        return VerificationResponse.model_validate(data)

    async def get_output(self, output_id: str) -> dict[str, Any]:
        """Fetch previously recorded output and verification record by ID."""
        return await self._request("GET", f"/v1/output/{output_id}", is_mutating=False)  # type: ignore[no-any-return]

    # -------------------------------------------------------------------------
    # Gate 3: Action Assurance & Tool Governance
    # -------------------------------------------------------------------------

    async def register_tool(self, tool: dict[str, Any]) -> ToolResponse:
        """Register or update a tool in Gate 3 tenant tool registry."""
        data = await self._request("POST", "/v1/tools", json_data=tool, is_mutating=True)
        return ToolResponse.model_validate(data)

    async def list_tools(self) -> list[ToolResponse]:
        """List all registered tools for the authenticated tenant."""
        data = await self._request("GET", "/v1/tools", is_mutating=False)
        return [ToolResponse.model_validate(item) for item in data]

    async def propose_action(
        self,
        proposal: ActionProposal | dict[str, Any],
    ) -> ActionAuthorizationDecision:
        """Submit an ActionProposal to Gate 3 Action Assurance for policy, lease, and risk evaluation."""
        payload = proposal.model_dump(mode="json") if isinstance(proposal, ActionProposal) else proposal
        data = await self._request("POST", "/v1/actions/propose", json_data=payload, is_mutating=True)
        return ActionAuthorizationDecision.model_validate(data)

    async def execute_action(
        self,
        action_id: str,
        *,
        approval_token: str | None = None,
    ) -> ActionExecutionResult:
        """Execute an authorized action contract through the Governed Tool Proxy."""
        req = ActionExecutionRequest(action_id=action_id, approval_token=approval_token)
        data = await self._request(
            "POST",
            "/v1/actions/execute",
            json_data=req.model_dump(mode="json"),
            is_mutating=True,
            action_id=action_id,
        )
        return ActionExecutionResult.model_validate(data)

    async def get_action(self, action_id: str) -> dict[str, Any]:
        """Inspect the lifecycle state, parameters hash, and audit details of an Action Contract."""
        return await self._request("GET", f"/v1/actions/{action_id}", is_mutating=False)  # type: ignore[no-any-return]

    async def list_stranded_actions(self, *, older_than_seconds: int = 60) -> list[StrandedActionInfo]:
        """List actions stranded in EXECUTING or EXECUTION_UNCERTAIN state across worker lifecycles."""
        data = await self._request(
            "GET",
            "/v1/actions/stranded",
            params={"older_than_seconds": older_than_seconds},
            is_mutating=False,
        )
        return [StrandedActionInfo.model_validate(item) for item in data]

    async def reconcile_action(
        self,
        action_id: str,
        resolution_state: str | ActionState,
        *,
        rationale: str,
        verified_evidence: dict[str, Any] | None = None,
    ) -> ActionExecutionResult:
        """Idempotently reconcile a stranded action to a terminal verified state."""
        state_str = resolution_state.value if isinstance(resolution_state, ActionState) else str(resolution_state)
        resolution_map = {
            "FAILED": "MARK_FAILED",
            "COMPLETED": "MARK_COMPLETED",
            "EXECUTION_UNCERTAIN": "MARK_UNCERTAIN",
            "MARK_FAILED": "MARK_FAILED",
            "MARK_COMPLETED": "MARK_COMPLETED",
            "MARK_UNCERTAIN": "MARK_UNCERTAIN",
        }
        req_payload = {
            "action_id": action_id,
            "resolution": resolution_map.get(state_str, state_str),
            "notes": rationale,
            "observed_evidence": verified_evidence or {},
        }
        data = await self._request(
            "POST",
            f"/v1/actions/{action_id}/reconcile",
            json_data=req_payload,
            is_mutating=True,
            action_id=action_id,
        )
        return ActionExecutionResult.model_validate(data)

    # -------------------------------------------------------------------------
    # Human Approvals
    # -------------------------------------------------------------------------

    async def list_pending_approvals(self) -> list[ApprovalResponse]:
        """List pending L4 human approval requests for the authorized tenant."""
        data = await self._request("GET", "/v1/approvals/pending", is_mutating=False)
        return [ApprovalResponse.model_validate(item) for item in data]

    async def grant_approval(self, approval_id: str, *, reason: str) -> ApprovalResponse:
        """Grant a pending human approval ticket."""
        req = ApprovalDecisionRequest(reason=reason)
        data = await self._request(
            "POST",
            f"/v1/approvals/{approval_id}/grant",
            json_data=req.model_dump(mode="json"),
            is_mutating=True,
        )
        return ApprovalResponse.model_validate(data)

    async def deny_approval(self, approval_id: str, *, reason: str) -> ApprovalResponse:
        """Deny a pending human approval ticket."""
        req = ApprovalDecisionRequest(reason=reason)
        data = await self._request(
            "POST",
            f"/v1/approvals/{approval_id}/deny",
            json_data=req.model_dump(mode="json"),
            is_mutating=True,
        )
        return ApprovalResponse.model_validate(data)

    # -------------------------------------------------------------------------
    # Gate 5: Outcome Assurance (Reality Verification)
    # -------------------------------------------------------------------------

    async def get_outcome(self, action_id: str) -> OutcomeVerificationContract:
        """Fetch authoritative Gate 5 outcome verification record for an action."""
        data = await self._request("GET", f"/v1/actions/{action_id}/outcome", is_mutating=False)
        return OutcomeVerificationContract.model_validate(data)

    async def verify_outcome(
        self,
        action_id: str,
        request: OutcomeVerificationRequest | dict[str, Any],
    ) -> OutcomeVerificationContract:
        """Execute independent Gate 5 reality verification confirming real-world postconditions."""
        payload = request.model_dump(mode="json") if isinstance(request, OutcomeVerificationRequest) else request
        data = await self._request(
            "POST",
            f"/v1/actions/{action_id}/outcome",
            json_data=payload,
            is_mutating=True,
            action_id=action_id,
        )
        return OutcomeVerificationContract.model_validate(data)

    # -------------------------------------------------------------------------
    # Audit API
    # -------------------------------------------------------------------------

    async def verify_audit_hash_chain(self) -> AuditChainVerificationResponse:
        """Verify the cryptographic SHA-256 hash chain across all audit logs for calling tenant."""
        data = await self._request("POST", "/v1/audit/verify-chain", is_mutating=False)
        return AuditChainVerificationResponse.model_validate(data)

    # -------------------------------------------------------------------------
    # MCP Registry Operations
    # -------------------------------------------------------------------------

    async def list_mcp_servers(self, *, limit: int = 50, offset: int = 0) -> MCPServerListResponse:
        """List registered external MCP servers under tenant isolation."""
        data = await self._request(
            "GET",
            "/v1/mcp/servers",
            params={"limit": limit, "offset": offset},
            is_mutating=False,
        )
        return MCPServerListResponse.model_validate(data)

    async def get_mcp_server(self, server_id: str) -> MCPServerResponse:
        """Retrieve details for a specific registered MCP server."""
        data = await self._request("GET", f"/v1/mcp/servers/{server_id}", is_mutating=False)
        return MCPServerResponse.model_validate(data)

    async def register_mcp_server(
        self,
        request: MCPServerCreateRequest | dict[str, Any],
    ) -> MCPServerResponse:
        """Register an external MCP server in PENDING_APPROVAL status."""
        payload = request.model_dump(mode="json") if isinstance(request, MCPServerCreateRequest) else request
        data = await self._request("POST", "/v1/mcp/servers", json_data=payload, is_mutating=True)
        return MCPServerResponse.model_validate(data)

    async def update_mcp_server_trust(
        self,
        server_id: str,
        trust_status: str | MCPTrustStatus,
        *,
        reason: str,
    ) -> MCPServerResponse:
        """Transition MCP server trust status (PENDING_APPROVAL -> TRUSTED, SUSPENDED, REVOKED)."""
        status_val = trust_status.value if isinstance(trust_status, MCPTrustStatus) else str(trust_status)
        req = MCPTrustStatusUpdateRequest(
            trust_status=MCPTrustStatus(status_val),
            reason=reason,
        )
        data = await self._request(
            "PUT",
            f"/v1/mcp/servers/{server_id}/trust",
            json_data=req.model_dump(mode="json"),
            is_mutating=True,
        )
        return MCPServerResponse.model_validate(data)

    async def discover_mcp_tools(self, server_id: str) -> MCPToolDiscoveryResult:
        """Discover tools from a TRUSTED MCP server, calculate schema fingerprints, and sync tools."""
        data = await self._request("POST", f"/v1/mcp/servers/{server_id}/discover", is_mutating=True)
        return MCPToolDiscoveryResult.model_validate(data)

    # -------------------------------------------------------------------------
    # Commercial Billing & Subscription Operations
    # -------------------------------------------------------------------------

    async def get_billing_plans(self) -> list[dict[str, Any]]:
        """Fetch available commercial pricing catalog and tier entitlement specifications."""
        return cast(list[dict[str, Any]], await self._request("GET", "/v1/billing/plans", is_mutating=False))

    async def get_subscription(self) -> dict[str, Any]:
        """Retrieve current tenant subscription tier, headroom, and budget utilization."""
        return cast(dict[str, Any], await self._request("GET", "/v1/billing/subscription", is_mutating=False))

    # -------------------------------------------------------------------------
    # Inquiries & Tenant Self-Service Registration
    # -------------------------------------------------------------------------

    async def create_inquiry(self, request: dict[str, Any]) -> dict[str, Any]:
        """Submit an enterprise sales inquiry, architecture review request, or custom SLA ticket."""
        return cast(dict[str, Any], await self._request("POST", "/v1/inquiries", json_data=request, is_mutating=True))

    async def register_tenant(self, request: dict[str, Any]) -> dict[str, Any]:
        """Self-service enterprise onboarding provisioning tenant, admin user, and production API key."""
        return cast(
            dict[str, Any], await self._request("POST", "/v1/auth/register-tenant", json_data=request, is_mutating=True)
        )
