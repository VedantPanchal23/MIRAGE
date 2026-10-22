"""Unit tests for MIRAGE 3.0 Model Router service and API routes."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from gateway.main import app
from services.model_router import model_router_service
from shared.schemas.auth import Role
from shared.schemas.model_router import (
    ModelTier,
    RoutingRequest,
)
from tests.auth_factory import AuthTestFactory


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_router_lists_registered_models() -> None:
    """Verify that model router lists active models with capability profiles."""
    models = await model_router_service.list_models()
    assert len(models) >= 5

    model_ids = {m.model_id for m in models}
    assert "mock-frontier" in model_ids
    assert "mock-capable" in model_ids
    assert "gpt-4o" in model_ids

    mock_frontier = next(m for m in models if m.model_id == "mock-frontier")
    assert mock_frontier.tier == ModelTier.FRONTIER
    assert mock_frontier.supports_tools is True
    assert mock_frontier.is_zero_retention is True
    assert mock_frontier.reliability_index >= 0.90


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_router_filters_by_required_capabilities() -> None:
    """Models lacking required capabilities must be excluded."""
    # Require vision: mock-specialized and mock-capable do not support vision
    req = RoutingRequest(
        tenant_id="default_tenant",
        task_type="extraction",
        required_capabilities=["vision"],
        estimated_input_tokens=100,
        estimated_output_tokens=100,
    )
    decision = await model_router_service.route(req)
    valid_vision_models = (
        "mock-frontier",
        "gpt-4o",
        "gpt-4o-mini",
        "claude-3-5-sonnet-20241022",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    )
    assert decision.selected_model_id in valid_vision_models

    # Inspect exclusions
    excluded_models = {e.model_id: e.rule for e in decision.exclusions}
    assert "mock-capable" in excluded_models
    assert excluded_models["mock-capable"] == "CAPABILITY_VISION_UNSUPPORTED"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_router_enforces_gate1_taint_privacy() -> None:
    """Sensitive taints (PHI, PII, confidential) require zero-retention, isolated deployment, and valid attestation."""
    req = RoutingRequest(
        tenant_id="default_tenant",
        task_type="reasoning",
        taints=["phi", "pii"],
        estimated_input_tokens=200,
        estimated_output_tokens=200,
    )

    # 1. Without authentic attestation provenance, all unattested models fail closed (HTTP 422)
    with pytest.raises(HTTPException) as exc_info:
        await model_router_service.route(req)
    assert exc_info.value.status_code == 422
    assert isinstance(exc_info.value.detail, dict)
    exclusions = {e["model_id"]: e["rule"] for e in exc_info.value.detail["exclusions"]}
    assert exclusions["gpt-4o"] == "GATE1_DATA_RESIDENCY_PRIVACY"
    assert exclusions["mock-frontier"] == "GATE1_PRIVACY_ATTESTATION_UNTRUSTED"

    # 2. When authentic cryptographic attestation is configured, attested models qualify
    from services.privacy_attestation import create_test_notary_keypair, sign_model_attestation
    from shared.config import get_settings

    settings = get_settings()
    priv_key, pub_key_hex, issuer_name = create_test_notary_keypair("test-notary-unit-v1")
    now_dt = datetime.now(UTC)
    expires_dt = now_dt + timedelta(days=30)

    models = await model_router_service.list_models()
    attested_models = []
    for m in models:
        if m.is_zero_retention:
            sig = sign_model_attestation(
                private_key=priv_key,
                model_id=m.model_id,
                provider=m.provider,
                is_zero_retention=True,
                deployment_type=m.deployment_type,
                privacy_policy_version=m.privacy_policy_version,
                verified_at=now_dt,
                expires_at=expires_dt,
                issuer=issuer_name,
            )
            attested_models.append(
                m.model_copy(
                    update={
                        "attestation_issuer": issuer_name,
                        "attestation_signature": sig,
                        "privacy_verified_at": now_dt,
                        "privacy_attestation_expires_at": expires_dt,
                    }
                )
            )
        else:
            attested_models.append(m)

    with (
        patch.object(model_router_service, "list_models", return_value=attested_models),
        patch.object(settings, "trusted_privacy_notary_public_keys", {issuer_name: pub_key_hex}),
    ):
        decision = await model_router_service.route(req)

        # gpt-4o, claude, gemini lack zero-retention in default registry
        excluded_models = {e.model_id: e.rule for e in decision.exclusions}
        assert "gpt-4o" in excluded_models
        assert excluded_models["gpt-4o"] == "GATE1_DATA_RESIDENCY_PRIVACY"

        # Only zero-retention models should qualify (e.g. mock-frontier, mock-capable, allam-2-7b)
        assert decision.selected_model_id in ("mock-frontier", "mock-capable", "allam-2-7b", "mock-specialized")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_router_enforces_gate3_risk_tier() -> None:
    """Risk level L3+ requires FRONTIER tier models with reliability >= 0.85."""
    req = RoutingRequest(
        tenant_id="default_tenant",
        task_type="reasoning",
        risk_level=3,
        estimated_input_tokens=500,
        estimated_output_tokens=500,
    )
    decision = await model_router_service.route(req)
    assert decision.tier == ModelTier.FRONTIER

    excluded_models = {e.model_id: e.rule for e in decision.exclusions}
    # Capable models must be excluded under Gate 3 risk rule
    assert "mock-capable" in excluded_models
    assert excluded_models["mock-capable"] == "GATE3_RISK_TIER_INSUFFICIENT"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_router_enforces_cost_budget() -> None:
    """Models with estimated cost exceeding max_cost_micros must be excluded."""
    req = RoutingRequest(
        tenant_id="default_tenant",
        task_type="chat",
        estimated_input_tokens=2000,
        estimated_output_tokens=2000,
        max_cost_micros=200,  # Very small budget ($0.0002)
    )
    decision = await model_router_service.route(req)

    # Frontier models cost ~2500 micros for 2000 tokens, so they must be excluded
    excluded_models = {e.model_id: e.rule for e in decision.exclusions}
    assert "gpt-4o" in excluded_models
    assert excluded_models["gpt-4o"] == "MAX_COST_BUDGET_EXCEEDED"
    assert decision.estimated_cost_micros <= 200


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_router_circuit_breaker_exclusion() -> None:
    """Models with tripped circuit breakers must be excluded from routing."""
    target_model = "mock-frontier"

    # Trip breaker
    for _ in range(5):
        model_router_service.record_failure(target_model)
    assert model_router_service.is_circuit_open(target_model) is True

    req = RoutingRequest(
        tenant_id="default_tenant",
        task_type="reasoning",
        preferred_model=target_model,
        risk_level=3,
    )
    decision = await model_router_service.route(req)
    assert decision.selected_model_id != target_model

    excluded_models = {e.model_id: e.rule for e in decision.exclusions}
    assert target_model in excluded_models
    assert excluded_models[target_model] == "CIRCUIT_BREAKER_OPEN"

    # Reset breaker
    model_router_service.record_success(target_model)
    assert model_router_service.is_circuit_open(target_model) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_router_produces_decision_provenance_hash() -> None:
    """Decision provenance hash must be non-empty SHA-256 and reproducible."""
    req = RoutingRequest(
        tenant_id="default_tenant",
        task_type="reasoning",
        estimated_input_tokens=100,
        estimated_output_tokens=100,
    )
    decision = await model_router_service.route(req)
    assert len(decision.decision_hash) == 64
    assert decision.decision_id.startswith("dec_")
    assert len(decision.reason) > 0


@pytest.mark.unit
def test_models_api_endpoints() -> None:
    """Test /v1/models and /v1/models/route HTTP endpoints with authentication."""
    headers = AuthTestFactory.auth_headers(tenant_id="default_tenant", role=Role.API_CLIENT)
    client = TestClient(app)

    # 1. GET /v1/models
    resp = client.get("/v1/models", headers=headers)
    assert resp.status_code == 200
    models_data = resp.json()
    assert isinstance(models_data, list)
    assert len(models_data) >= 5

    # 2. POST /v1/models/route
    route_payload = {
        "tenant_id": "default_tenant",
        "task_type": "reasoning",
        "estimated_input_tokens": 150,
        "estimated_output_tokens": 300,
        "risk_level": 1,
    }
    resp = client.post("/v1/models/route", json=route_payload, headers=headers)
    assert resp.status_code == 200
    decision_data = resp.json()
    assert "selected_model_id" in decision_data
    assert "decision_hash" in decision_data
    assert "tier" in decision_data
    assert "estimated_cost_micros" in decision_data
