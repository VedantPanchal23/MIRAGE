"""Cross-Boundary Contract Tests for MIRAGE Python SDK.

Validates:
1. Request serialization and response deserialization against live FastAPI gateway contracts.
2. Backwards compatibility: resilience against unknown/newly-added server fields (extra="ignore").
3. Schema validation error handling (HTTP 422 -> MirageValidationError).
4. Authentication and scope attenuation enforcement
   (HTTP 401/403 -> MirageAuthenticationError / MirageAuthorizationError).
5. Sanitization of credentials in exceptions, URLs, and representations.
6. Tenant isolation and cross-tenant resource denial.
7. Immediate API key revocation enforcement.
8. Execution uncertainty preservation: mutating action timeouts/disconnects raise
   MirageExecutionUncertainError without blind redispatch or automatic retries.
9. Safe retry handling for non-mutating GET operations with backoff and Retry-After parsing.
10. Gate 5 Outcome Assurance epistemic independence from tool execution return values.
11. AsyncMirageClient asynchronous contract equivalency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from mirage_sdk import (
    ActionAuthorizationDecision,
    ActionProposal,
    ActionState,
    ActionType,
    AsyncMirageClient,
    BlastRadiusAssessment,
    IndependentObservation,
    MCPServerCreateRequest,
    MCPServerResponse,
    MCPServerTransport,
    MirageAuthenticationError,
    MirageAuthorizationError,
    MirageClient,
    MirageExecutionUncertainError,
    MirageNotFoundError,
    MirageRateLimitError,
    MirageServerError,
    MirageValidationError,
    OutcomeStatus,
    OutcomeVerificationContract,
    OutcomeVerificationRequest,
    PostconditionRule,
    VerificationResponse,
)
from starlette.testclient import TestClient

from gateway.main import create_app
from gateway.middleware.auth import register_api_key, revoke_api_key
from shared.schemas.auth import Role

app = create_app()


class _TestClientTransport(httpx.BaseTransport):
    """Sync transport adapter that wraps Starlette TestClient cleanly."""

    def __init__(self, test_client: TestClient) -> None:
        self._client = test_client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        content = request.read()
        headers = dict(request.headers)
        headers.pop("host", None)
        resp = self._client.request(
            method=request.method,
            url=str(request.url),
            headers=headers,
            content=content,
        )
        return httpx.Response(
            status_code=resp.status_code,
            headers=resp.headers,
            content=resp.content,
            request=request,
        )


sync_transport = _TestClientTransport(TestClient(app))


@pytest.fixture(autouse=True)
def _setup_api_keys() -> None:
    """Register test API keys with explicit scopes."""
    register_api_key(
        api_key="sdk_test_write_key",
        tenant_id="tenant_sdk_a",
        role=Role.API_CLIENT,
        scopes=["verify:write", "verify:read", "actions:propose", "actions:execute"],
    )
    register_api_key(
        api_key="sdk_test_read_key",
        tenant_id="tenant_sdk_a",
        role=Role.API_CLIENT,
        scopes=["verify:read"],
    )
    register_api_key(
        api_key="sdk_test_admin_key",
        tenant_id="tenant_sdk_a",
        role=Role.TENANT_ADMIN,
        scopes=["*"],
    )
    register_api_key(
        api_key="sdk_tenant_b_key",
        tenant_id="tenant_sdk_b",
        role=Role.TENANT_ADMIN,
        scopes=["*"],
    )


# =============================================================================
# 1. Verification API Contracts (Gate 4)
# =============================================================================


class TestVerificationContract:
    """Contract tests for Gate 4 Verification endpoint."""

    @patch("gateway.routes.verify.orchestrator.verify_request")
    def test_verify_success_deserialization(self, mock_verify: AsyncMock) -> None:
        """Verify POST /v1/verify response maps correctly to typed VerificationResponse."""
        mock_response = {
            "request_id": "req_sdk_test_001",
            "verified_response": "Water is H2O.",
            "original_response": "Water is H2O.",
            "hrs_result": {
                "hrs": 0.05,
                "raw_score": 0.04,
                "tier": "LOW",
                "conformal_interval": {
                    "lower": 0.01,
                    "upper": 0.09,
                    "confidence_level": 0.95,
                    "conditional_group": "overall",
                },
                "signal_attribution": {"rav": 0.01, "scs": 0.02, "nli": 0.01, "ics": 0.01, "vgs": None},
                "claims_count": 1,
                "contradicted_claims_count": 0,
                "computation_latency_ms": 12.5,
            },
            "claims": [
                {
                    "claim": {
                        "claim_id": "c_1",
                        "text": "Water is H2O.",
                        "claim_type": "factual",
                        "criticality": "high",
                        "criticality_weight": 1.0,
                    },
                    "status": "SUPPORTED",
                    "risk_score": 0.05,
                }
            ],
            "metadata": {
                "trace_id": "trace_sdk_123",
                "execution_time_ms": 15.0,
                "pipeline_signals_used": ["rav", "scs"],
            },
            # Future extra field simulation (backwards compatibility check):
            "future_experimental_field": "should_be_safely_ignored",
        }
        mock_verify.return_value = mock_response

        with MirageClient(
            api_key="sdk_test_write_key",
            base_url="http://testserver",
            transport=sync_transport,
        ) as client:
            res = client.verify(prompt="What is water?", response="Water is H2O.")

            assert isinstance(res, VerificationResponse)
            assert res.request_id == "req_sdk_test_001"
            assert res.verified_response == "Water is H2O."
            assert res.hrs_result.hrs == 0.05
            assert res.hrs_result.tier == "LOW"
            assert res.hrs_result.conformal_interval.lower == 0.01
            assert res.hrs_result.conformal_interval.upper == 0.09
            assert len(res.claims) == 1
            assert res.claims[0].status == "SUPPORTED"

    def test_verify_validation_error_on_empty_prompt(self) -> None:
        """Verify POST /v1/verify with invalid/empty prompt raises MirageValidationError with HTTP 422."""
        with MirageClient(
            api_key="sdk_test_write_key",
            base_url="http://testserver",
            transport=sync_transport,
        ) as client:
            with pytest.raises(MirageValidationError) as exc_info:
                client.verify(prompt="", response="Some text")

            assert exc_info.value.status_code == 422
            assert exc_info.value.errors is not None
            assert len(exc_info.value.errors) > 0


# =============================================================================
# 2. Authentication & Scope Attenuation Contracts
# =============================================================================


class TestAuthAndScopeContract:
    """Contract tests for authentication, scope enforcement, and secret protection."""

    def test_missing_or_invalid_api_key(self) -> None:
        """Invalid API key raises MirageAuthenticationError (HTTP 401)."""
        with MirageClient(
            api_key="invalid_unknown_key_xyz",
            base_url="http://testserver",
            transport=sync_transport,
        ) as client:
            with pytest.raises(MirageAuthenticationError) as exc_info:
                client.verify(prompt="Test", response="Test")

            assert exc_info.value.status_code == 401

    def test_scope_attenuation_denial(self) -> None:
        """Read-only API key cannot execute mutating verify:write action."""
        with MirageClient(
            api_key="sdk_test_read_key",  # Scoped strictly to ["verify:read"]
            base_url="http://testserver",
            transport=sync_transport,
        ) as client:
            with pytest.raises(MirageAuthorizationError) as exc_info:
                client.verify(prompt="Test", response="Test")

            assert exc_info.value.status_code == 403
            assert "Forbidden" in exc_info.value.message or "verify:write" in exc_info.value.message

    def test_api_key_never_leaked_in_exceptions_or_representations(self) -> None:
        """Secret API key is never reflected in error messages, exception reprs, or string casts."""
        secret_key = "mirage_super_secret_token_never_log_98765"
        client = MirageClient(
            api_key=secret_key,
            base_url="http://testserver",
            transport=sync_transport,
        )
        try:
            with pytest.raises(MirageAuthenticationError) as exc_info:
                client.verify(prompt="Prompt", response="Response")

            err = exc_info.value
            assert secret_key not in str(err)
            assert secret_key not in repr(err)
            assert secret_key not in repr(client)
        finally:
            client.close()

    def test_revoked_api_key_immediately_denies_requests(self) -> None:
        """Revoking an active API key immediately halts access without caching leaks."""
        ephemeral_key = "sdk_ephemeral_revocable_key_123"
        register_api_key(
            api_key=ephemeral_key,
            tenant_id="tenant_sdk_a",
            role=Role.API_CLIENT,
            scopes=["verify:write"],
        )

        with MirageClient(
            api_key=ephemeral_key,
            base_url="http://testserver",
            transport=sync_transport,
        ) as client:
            # Revoke key immediately
            revoke_api_key(ephemeral_key)

            with pytest.raises(MirageAuthenticationError) as exc_info:
                client.verify(prompt="Test", response="Test")

            assert exc_info.value.status_code == 401


# =============================================================================
# 3. Action Assurance & Execution Uncertainty (Gate 3)
# =============================================================================


class TestActionAssuranceContract:
    """Contract tests for Gate 3 Action Assurance, lease coordination, and execution uncertainty."""

    @patch("services.action_governor.ActionGovernorService.propose_and_authorize_action")
    def test_propose_action_contract(self, mock_propose: AsyncMock) -> None:
        """Verify ActionProposal serialization and ActionAuthorizationDecision parsing."""
        mock_propose.return_value = ActionAuthorizationDecision(
            action_id="act_contract_test_01",
            decision="ALLOW",
            state=ActionState.AUTHORIZED,
            reason="Approved by tenant action policy",
            risk_score=15,
            autonomy_level=2,
            normalized_parameters={"amount": 100},
            parameters_hash="sha256_mock_hash_123",
            fencing_token=42,
        )

        proposal = ActionProposal(
            transaction_id="tx_sdk_test_01",
            tool_name="stripe.create_charge",
            action_type=ActionType.WRITE,
            target_resource="customer:cus_12345",
            parameters={"amount": 100},
            idempotency_key="idemp_key_unique_12345",
            postconditions=[
                PostconditionRule(
                    assertion="STATUS_EQUALS",
                    target="customer:cus_12345.balance",
                    expected_value=100,
                )
            ],
            blast_radius=BlastRadiusAssessment(
                resource_scope="BILLING",
                estimated_dollar_cost=100.0,
                reversibility="REVERSIBLE",
            ),
        )

        with MirageClient(
            api_key="sdk_test_write_key",
            base_url="http://testserver",
            transport=sync_transport,
        ) as client:
            decision = client.propose_action(proposal)

            assert isinstance(decision, ActionAuthorizationDecision)
            assert decision.action_id == "act_contract_test_01"
            assert decision.decision == "ALLOW"
            assert decision.state == ActionState.AUTHORIZED
            assert decision.fencing_token == 42

    def test_mutating_execution_timeout_raises_uncertainty_without_retry(self) -> None:
        """CRITICAL: Mutating action execution timeout raises MirageExecutionUncertainError.

        Verifies that mutating operations are NEVER automatically retried on timeout.
        """
        request_count = 0

        def timeout_handler(_request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            raise httpx.ReadTimeout("Server took too long to execute tool side-effect")

        mock_transport = httpx.MockTransport(timeout_handler)
        with MirageClient(
            api_key="sdk_test_write_key",
            base_url="http://testserver",
            transport=mock_transport,
            max_retries=3,  # max_retries must be IGNORED for mutating execution!
        ) as client:
            with pytest.raises(MirageExecutionUncertainError) as exc_info:
                client.execute_action("act_critical_mutating_123")

            # Must have attempted exactly once (NO automatic retries!)
            assert request_count == 1
            assert exc_info.value.action_id == "act_critical_mutating_123"
            assert exc_info.value.state == "EXECUTION_UNCERTAIN"
            assert "blind redispatch is strictly prohibited" in exc_info.value.message

    def test_safe_get_retries_transient_failures(self) -> None:
        """Safe read (GET) requests retry on transient 503 errors up to max_retries."""
        attempts = 0

        def transient_handler(_request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return httpx.Response(503, json={"detail": "Service Temporarily Unavailable"})
            return httpx.Response(200, json={"id": "out_recovered_123", "verified": True})

        mock_transport = httpx.MockTransport(transient_handler)
        with MirageClient(
            api_key="sdk_test_read_key",
            base_url="http://testserver",
            transport=mock_transport,
            max_retries=3,
        ) as client:
            res = client.get_output("out_recovered_123")
            assert attempts == 3
            assert res["id"] == "out_recovered_123"


# =============================================================================
# 4. Gate 5: Outcome Assurance & Reality Verification
# =============================================================================


class TestOutcomeAssuranceContract:
    """Contract tests for Gate 5 Reality Verification and Epistemic Independence."""

    @patch("services.reality_verifier.reality_verifier_service.verify_action_outcome")
    def test_verify_outcome_epistemic_separation(self, mock_verify: AsyncMock) -> None:
        """Verifies Gate 5 reality verification returns an independent OutcomeVerificationContract."""
        mock_contract = OutcomeVerificationContract(
            outcome_id="outc_sdk_test_999",
            transaction_id="tx_sdk_test_01",
            action_id="act_contract_test_01",
            tenant_id="tenant_sdk_a",
            observability_class="OBS_DIRECT",
            outcome_status=OutcomeStatus.VERIFIED_SUCCESS,
            epistemic_confidence=0.99,
            verifier_adapter="POSTGRES_DIRECT_PROBE",
            is_simulated=False,
            expected_postconditions={"status": "CANCELLED"},
            observed_state={"status": "CANCELLED", "rows_updated": 1},
            discrepancies=[],
            evidence_payload={"table": "orders", "pk": 45678},
            reconciliation_notes=["Postconditions matched authoritative database row"],
            verification_hash="sha256_mock_verification_hash_abc",
            verified_at="2026-10-19T20:00:00Z",
        )
        mock_verify.return_value = mock_contract

        with MirageClient(
            api_key="sdk_test_admin_key",
            base_url="http://testserver",
            transport=sync_transport,
        ) as client:
            req = OutcomeVerificationRequest(
                transaction_id="tx_sdk_test_01",
                action_id="act_contract_test_01",
                observation=IndependentObservation(
                    observation_id="obs_001",
                    source_id="db_probe_agent",
                    target_resource="orders:123",
                    observed_at=datetime.now(UTC),
                    observed_state={"status": "CANCELLED"},
                    evidence_digest="sha256_mock_evidence_digest_xyz",
                ),
            )
            outcome = client.verify_outcome("act_contract_test_01", req)

            assert isinstance(outcome, OutcomeVerificationContract)
            assert outcome.outcome_id == "outc_sdk_test_999"
            assert outcome.outcome_status == OutcomeStatus.VERIFIED_SUCCESS
            assert outcome.epistemic_confidence == 0.99
            assert outcome.verification_hash == "sha256_mock_verification_hash_abc"


# =============================================================================
# 5. MCP Server Governance Contract
# =============================================================================


class TestMCPGovernanceContract:
    """Contract tests for Governed MCP server registry operations."""

    @patch("services.mcp_registry_service.MCPRegistryService.register_server")
    def test_register_mcp_server_contract(self, mock_reg: AsyncMock) -> None:
        """Registering an MCP server returns MCPServerResponse in PENDING_APPROVAL status."""
        mock_reg.return_value = MCPServerResponse(
            id="mcp_server_contract_01",
            tenant_id="tenant_sdk_a",
            name="test-stdio-mcp",
            description="Test MCP server",
            transport_type="STDIO",
            connection_config={"command": "python", "args": ["-m", "mcp_dummy"]},
            trust_status="PENDING_APPROVAL",
            permitted_capabilities=["tools:read"],
            egress_allowlist=["localhost"],
            timeout_seconds=30,
            tool_count=0,
            created_at="2026-10-19T20:00:00Z",
            updated_at="2026-10-19T20:00:00Z",
        )

        with MirageClient(
            api_key="sdk_test_admin_key",
            base_url="http://testserver",
            transport=sync_transport,
        ) as client:
            req = MCPServerCreateRequest(
                name="test-stdio-mcp",
                description="Test MCP server",
                transport_type=MCPServerTransport.STDIO,
                connection_config={"command": "python", "args": ["-m", "mcp_dummy"]},
                permitted_capabilities=["tools:read"],
                egress_allowlist=["localhost"],
                timeout_seconds=30,
            )
            res = client.register_mcp_server(req)

            assert isinstance(res, MCPServerResponse)
            assert res.id == "mcp_server_contract_01"
            assert res.trust_status == "PENDING_APPROVAL"


# =============================================================================
# 6. Rate Limit, Not Found, and Server Error Contracts
# =============================================================================


class TestErrorContractMappings:
    """Contract tests verifying standard HTTP errors translate accurately to SDK exceptions."""

    def test_rate_limit_parsing_with_retry_after(self) -> None:
        """HTTP 429 response is translated to MirageRateLimitError with retry_after."""

        def rate_limit_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                headers={"Retry-After": "4.5"},
                json={"detail": "Too Many Requests: Rate quota exceeded"},
            )

        mock_transport = httpx.MockTransport(rate_limit_handler)
        with MirageClient(
            api_key="sdk_test_read_key",
            base_url="http://testserver",
            transport=mock_transport,
            max_retries=0,
        ) as client:
            with pytest.raises(MirageRateLimitError) as exc_info:
                client.get_output("out_123")

            assert exc_info.value.status_code == 429
            assert exc_info.value.retry_after == 4.5
            assert "Rate quota exceeded" in exc_info.value.message

    def test_not_found_handling(self) -> None:
        """HTTP 404 response is translated to MirageNotFoundError."""

        def not_found_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Resource out_completely_nonexistent_xyz not found"})

        mock_transport = httpx.MockTransport(not_found_handler)
        with MirageClient(
            api_key="sdk_test_read_key",
            base_url="http://testserver",
            transport=mock_transport,
        ) as client:
            with pytest.raises(MirageNotFoundError) as exc_info:
                client.get_output("out_completely_nonexistent_xyz")

            assert exc_info.value.status_code == 404

    def test_server_error_handling(self) -> None:
        """HTTP 500 response is translated to MirageServerError."""

        def error_500_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "Internal database deadlock"})

        mock_transport = httpx.MockTransport(error_500_handler)
        with MirageClient(
            api_key="sdk_test_read_key",
            base_url="http://testserver",
            transport=mock_transport,
            max_retries=0,
        ) as client:
            with pytest.raises(MirageServerError) as exc_info:
                client.get_output("out_123")

            assert exc_info.value.status_code == 500
            assert "database deadlock" in exc_info.value.message


# =============================================================================
# 7. Asynchronous Client Equivalency (AsyncMirageClient)
# =============================================================================


class TestAsyncClientEquivalency:
    """Verify AsyncMirageClient behaves identically under async context."""

    @pytest.mark.asyncio
    @patch("gateway.routes.verify.orchestrator.verify_request")
    async def test_async_verify_contract(self, mock_verify: AsyncMock) -> None:
        """Verify AsyncMirageClient executes async verify correctly."""
        mock_verify.return_value = {
            "request_id": "req_async_001",
            "verified_response": "Async verified text",
            "original_response": "Async verified text",
            "hrs_result": {
                "hrs": 0.02,
                "raw_score": 0.01,
                "tier": "LOW",
                "conformal_interval": {"lower": 0.0, "upper": 0.05, "confidence_level": 0.95},
                "signal_attribution": {"rav": 0.0, "scs": 0.0, "nli": 0.0, "ics": 0.0, "vgs": None},
                "claims_count": 0,
                "contradicted_claims_count": 0,
                "computation_latency_ms": 5.0,
            },
            "claims": [],
            "metadata": {"trace_id": "trace_async_01", "execution_time_ms": 5.0, "pipeline_signals_used": []},
        }

        async_transport = httpx.ASGITransport(app=app)
        async with AsyncMirageClient(
            api_key="sdk_test_write_key",
            base_url="http://testserver",
            transport=async_transport,
        ) as client:
            res = await client.verify(prompt="Test async", response="Async verified text")

            assert isinstance(res, VerificationResponse)
            assert res.request_id == "req_async_001"
            assert res.hrs_result.hrs == 0.02

    @pytest.mark.asyncio
    async def test_async_billing_and_inquiry_contract(self) -> None:
        """AsyncMirageClient retrieves billing plans and submits inquiry asynchronously."""
        async_transport = httpx.ASGITransport(app=app)
        async with AsyncMirageClient(
            api_key="sdk_test_read_key",
            base_url="http://testserver",
            transport=async_transport,
        ) as client:
            plans = await client.get_billing_plans()
            assert isinstance(plans, list)
            business_plan = next(p for p in plans if p["tier"] == "business")
            assert business_plan["price_dollars_monthly"] == 29.0
            assert business_plan["price_inr_monthly"] == 1999.0

            inquiry = await client.create_inquiry({
                "name": "Jane Doe",
                "email": "jane@startup.io",
                "company": "Startup AI",
                "team_size": "1-10",
                "use_case": "Gate 1 Guardrails",
                "message": "Testing async client inquiry submission.",
            })
            assert isinstance(inquiry, dict)
            assert inquiry["id"].startswith("inq_")
            assert inquiry["name"] == "Jane Doe"


# =============================================================================
# 8. Commercial Billing, Subscriptions & Inquiries Contract
# =============================================================================


class TestBillingAndInquiriesContract:
    """Contract tests for commercial billing, tier catalogs, and enterprise inquiries."""

    def test_get_billing_plans_contract(self) -> None:
        """SDK client retrieves available commercial billing plans and verifies new accessible pricing."""
        with MirageClient(
            api_key="sdk_test_read_key",
            base_url="http://testserver",
            transport=sync_transport,
        ) as client:
            plans = client.get_billing_plans()
            assert isinstance(plans, list)
            assert len(plans) >= 3

            # Verify recalibrated accessible tiers
            plan_tiers = {p["tier"]: p for p in plans}
            assert "developer" in plan_tiers
            assert "business" in plan_tiers
            assert "enterprise" in plan_tiers

            assert plan_tiers["business"]["price_dollars_monthly"] == 29.0
            assert plan_tiers["business"]["price_inr_monthly"] == 1999.0
            assert plan_tiers["enterprise"]["price_dollars_monthly"] == 299.0
            assert plan_tiers["enterprise"]["price_inr_monthly"] == 24999.0

    def test_create_inquiry_contract(self) -> None:
        """SDK client submits enterprise contact and demo inquiry."""
        with MirageClient(
            api_key="sdk_test_read_key",
            base_url="http://testserver",
            transport=sync_transport,
        ) as client:
            payload = {
                "name": "Alex Mercer",
                "email": "alex@genentech-ai.org",
                "company": "Genentech AI Labs",
                "team_size": "11-50",
                "use_case": "Autonomous Clinical Actions",
                "message": "We need Gate 5 reality verification for diagnostic tool calls.",
            }
            res = client.create_inquiry(payload)
            assert isinstance(res, dict)
            assert res["id"].startswith("inq_")
            assert res["name"] == "Alex Mercer"
            assert res["email"] == "alex@genentech-ai.org"
            assert res["status"] == "PENDING"
            assert "4 hours" in res["confirmation_message"]

