"""Enterprise Readiness Hardening tests across Security, Billing, WORM Anchors, SDK, Shadow Mode, and Privacy."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import warnings
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from mirage_sdk.decorators import govern_action, governed_action
from mirage_sdk.integrations import MirageCrewAITool, wrap_autogen_tool
from mirage_sdk.models import (
    ActionAuthorizationDecision,
    ActionExecutionResult,
    ActionState,
    Decision,
    ObservabilityClass,
    OutcomeStatus,
    OutcomeVerificationContract,
)

from gateway.main import create_app
from services.audit_anchor import S3ObjectLockAuditAnchorBackend, get_anchor_backend
from services.billing_service import BillingService
from services.tenant_service import TenantService
from shared.config.settings import EnvironmentType, Settings
from shared.schemas import (
    Claim,
    ClaimCriticality,
    ClaimType,
    ClaimVerificationResult,
    VerificationRequest,
    VerificationStatus,
)
from shared.schemas.audit import (
    CheckpointModel,
    NotaryKeyRegistry,
    TrustAssuranceLevel,
    compute_checkpoint_canonical_string,
    sign_checkpoint_payload,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.billing import (
    RazorpayPaymentVerifyRequest,
    StripePaymentVerifyRequest,
    SubscriptionTier,
)
from shared.schemas.hrs import ConformalInterval, HRSResult, RiskTier, SignalAttribution
from shared.schemas.tenant import TenantUserCreateRequest
from workers.orchestrator import VerificationOrchestrator


def _make_mock_decision(action_id: str = "act_ent_1") -> ActionAuthorizationDecision:
    return ActionAuthorizationDecision(
        action_id=action_id,
        decision=Decision.ALLOW,
        state=ActionState.AUTHORIZED,
        reason="Authorized",
        risk_score=10,
        autonomy_level=1,
        normalized_parameters={},
        parameters_hash="h" * 64,
        fencing_token=7,
    )


def _make_mock_outcome(action_id: str = "act_ent_1") -> OutcomeVerificationContract:
    return OutcomeVerificationContract(
        outcome_id="out_ent_1",
        transaction_id="tx_ent_1",
        action_id=action_id,
        tenant_id="tenant_fintech",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.VERIFIED_SUCCESS,
        epistemic_confidence=1.0,
        verifier_adapter="test_observer",
        verification_hash="v" * 64,
        verified_at="2026-11-25T10:00:00Z",
    )


class TestCredentialHygieneAndBillingSecurity:
    """Validate zero hardcoded SMTP secrets and fail-closed payment/webhook verification."""

    def test_no_hardcoded_personal_smtp_credentials(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("SMTP_USER", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        s = Settings()
        assert s.smtp_user == ""
        assert s.smtp_password == ""

    @pytest.mark.asyncio
    async def test_webhook_rejects_unsigned_http_requests(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/billing/webhook",
                json={
                    "event_id": "evt_unauth",
                    "event_type": "checkout.session.completed",
                    "tenant_id": "victim_tenant",
                    "data": {"tier": "enterprise"},
                },
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_webhook_accepts_valid_stripe_hmac_and_rejects_tampered(self) -> None:
        app = create_app()
        secret = "whsec_unit_test_secret_value"
        payload = json.dumps(
            {
                "event_id": "evt_signed_1",
                "event_type": "invoice.payment_succeeded",
                "tenant_id": "tenant_signed",
                "data": {},
            }
        ).encode("utf-8")
        ts = int(datetime.now(UTC).timestamp())
        sig = hmac.new(secret.encode("utf-8"), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()

        with patch("services.billing_service.get_settings", return_value=Settings(stripe_webhook_secret=secret)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                ok_resp = await client.post(
                    "/v1/billing/webhook",
                    content=payload,
                    headers={"Content-Type": "application/json", "Stripe-Signature": f"t={ts},v1={sig}"},
                )
                assert ok_resp.status_code == 200
                bad_resp = await client.post(
                    "/v1/billing/webhook",
                    content=payload,
                    headers={"Content-Type": "application/json", "Stripe-Signature": f"t={ts},v1={'0' * 64}"},
                )
                assert bad_resp.status_code == 401

    @pytest.mark.asyncio
    async def test_stripe_verify_rejects_unsettled_or_unconfigured_in_production(self) -> None:
        service = BillingService()
        admin = AuthContext(
            tenant_id="tenant_fintech",
            role=Role.TENANT_ADMIN,
            user_id="u1",
            identity_id="id_u1",
            principal_type="user",
            token_type="jwt",
        )
        prod_settings = Settings(
            environment=EnvironmentType.PRODUCTION,
            secret_key="p" * 64,
            celery_broker_url="amqps://u:p@rabbit.internal:5671//",
            stripe_secret_key="sk_test_miragePlatformKey",
        )
        with patch("services.billing_service.get_settings", return_value=prod_settings):
            with pytest.raises(RuntimeError, match="Stripe settlement verification"):
                await service.verify_stripe_payment(
                    admin,
                    StripePaymentVerifyRequest(session_id="cs_test_123", tier=SubscriptionTier.ENTERPRISE),
                )

        # Even in test/sandbox, empty payment_intent_id fails closed
        with pytest.raises(PermissionError, match="payment_intent_id"):
            await service.verify_stripe_payment(
                admin,
                StripePaymentVerifyRequest(session_id="cs_test_123", tier=SubscriptionTier.ENTERPRISE),
            )

    @pytest.mark.asyncio
    async def test_razorpay_prefix_shortcut_blocked_outside_test_env(self) -> None:
        service = BillingService()
        admin = AuthContext(
            tenant_id="tenant_fintech",
            role=Role.TENANT_ADMIN,
            user_id="u1",
            identity_id="id_u1",
            principal_type="user",
            token_type="jwt",
        )
        dev_settings = Settings(environment=EnvironmentType.DEVELOPMENT, razorpay_key_secret="real_secret_key")
        with patch("services.billing_service.get_settings", return_value=dev_settings):
            with pytest.raises(ValueError, match="Invalid Razorpay payment signature"):
                await service.verify_razorpay_payment(
                    admin,
                    RazorpayPaymentVerifyRequest(
                        razorpay_order_id="order_1",
                        razorpay_payment_id="pay_1",
                        razorpay_signature="rzp_sig_fake_bypass",
                        tier=SubscriptionTier.BUSINESS,
                    ),
                )


class TestS3ObjectLockAndTeamRBAC:
    """Validate S3 Object Lock COMPLIANCE anchor backend and fail-closed tenant user provisioning."""

    @pytest.mark.asyncio
    async def test_s3_object_lock_anchor_writes_and_chains_proofs(self) -> None:
        store: dict[str, bytes] = {}
        put_calls: list[dict[str, object]] = []

        class FakeS3Client:
            def list_objects_v2(self, Prefix: str, **_kwargs: object) -> dict[str, object]:
                contents = [{"Key": k} for k in sorted(store) if k.startswith(Prefix)]
                return {"Contents": contents, "IsTruncated": False}

            def get_object(self, Key: str, **_kwargs: object) -> dict[str, object]:
                return {"Body": io.BytesIO(store[Key])}

            def put_object(self, **kwargs: object) -> dict[str, object]:
                put_calls.append(kwargs)
                store[str(kwargs["Key"])] = kwargs["Body"]  # type: ignore[assignment]
                return {"ETag": '"ok"'}

        key_bytes = b"01234567890123456789012345678901"
        notary = NotaryKeyRegistry(initial_keys={"notary:s3_test": key_bytes})
        backend = S3ObjectLockAuditAnchorBackend(
            bucket="mirage-worm-audit",
            prefix="anchors",
            retention_days=365,
            notary_keys=notary,
            s3_client=FakeS3Client(),
        )

        cp1 = CheckpointModel(
            checkpoint_id="chk_s3_1",
            tenant_id="tenant_worm",
            checkpoint_hash="a" * 64,
            sequence_number=1,
            ledger_identity="audit_logs",
            signer_identity="notary:s3_test",
            signature="placeholder",
            trust_tier=TrustAssuranceLevel.EXTERNALLY_ANCHORED,
            issued_at=datetime.now(UTC),
        )
        cp1.signature = sign_checkpoint_payload(
            key_bytes,
            compute_checkpoint_canonical_string(
                tenant_id=cp1.tenant_id,
                ledger_identity=cp1.ledger_identity,
                sequence_number=cp1.sequence_number,
                checkpoint_hash=cp1.checkpoint_hash,
                issued_at_iso=cp1.issued_at.isoformat(),
                signer_identity=cp1.signer_identity,
            ),
        )
        proof1 = await backend.write_anchor("tenant_worm", cp1)
        assert proof1.prev_anchor_digest == "0" * 64
        assert put_calls[0]["ObjectLockMode"] == "COMPLIANCE"

        cp2 = cp1.model_copy(update={"checkpoint_id": "chk_s3_2", "sequence_number": 2, "checkpoint_hash": "b" * 64})
        cp2.signature = sign_checkpoint_payload(
            key_bytes,
            compute_checkpoint_canonical_string(
                tenant_id=cp2.tenant_id,
                ledger_identity=cp2.ledger_identity,
                sequence_number=cp2.sequence_number,
                checkpoint_hash=cp2.checkpoint_hash,
                issued_at_iso=cp2.issued_at.isoformat(),
                signer_identity=cp2.signer_identity,
            ),
        )
        proof2 = await backend.write_anchor("tenant_worm", cp2)
        assert proof2.prev_anchor_digest == proof1.anchor_digest

        valid, defects = await backend.verify_anchor_chain("tenant_worm")
        assert valid is True
        assert defects == []

    def test_get_anchor_backend_factory_selects_s3(self) -> None:
        s3_settings = Settings(audit_anchor_backend="s3_object_lock", audit_anchor_s3_bucket="worm-bucket")
        with patch("services.audit_anchor.get_settings", return_value=s3_settings):
            backend = get_anchor_backend()
            assert isinstance(backend, S3ObjectLockAuditAnchorBackend)

    @pytest.mark.asyncio
    async def test_tenant_admin_cannot_escalate_user_to_super_admin(self) -> None:
        from fastapi import HTTPException

        svc = TenantService()
        tenant_admin = AuthContext(
            tenant_id="tenant_a",
            role=Role.TENANT_ADMIN,
            user_id="u_ta",
            identity_id="id_ta",
            principal_type="user",
            token_type="jwt",
        )
        with pytest.raises(HTTPException) as exc:
            await svc.provision_tenant_user(
                tenant_admin,
                TenantUserCreateRequest(email="escalate@a.com", display_name="Escalator", role="super_admin"),
                session=AsyncMock(),
            )
        assert exc.value.status_code == 403


class TestSDKEpistemicHonestyAndShadowMode:
    """Validate SDK Gate 5 epistemic honesty, AutoGen/CrewAI adapters, and shadow mode."""

    def test_govern_action_defaults_to_obs_inferred_without_observer(self) -> None:
        mock_client = MagicMock()
        mock_client.propose_action.return_value = _make_mock_decision()
        mock_client.execute_action.return_value = ActionExecutionResult(
            action_id="act_ent_1", transaction_id="tx_ent_1", state=ActionState.COMPLETED
        )
        mock_client.verify_outcome.return_value = _make_mock_outcome()

        @govern_action(capability="crm:note", client=mock_client)
        def write_note(note: str) -> dict[str, str]:
            return {"note": note}

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            res = write_note("hello")
        assert res["note"] == "hello"
        assert any("OBS_INFERRED" in str(w.message) for w in caught)
        sent_req = mock_client.verify_outcome.call_args.args[1]
        assert sent_req.observability_class == ObservabilityClass.OBS_INFERRED

    def test_governed_action_with_observer_emits_obs_direct(self) -> None:
        mock_client = MagicMock()
        mock_client.propose_action.return_value = _make_mock_decision()
        mock_client.execute_action.return_value = ActionExecutionResult(
            action_id="act_ent_1", transaction_id="tx_ent_1", state=ActionState.COMPLETED
        )
        mock_client.verify_outcome.return_value = _make_mock_outcome()

        @governed_action(
            capability="ledger:post",
            client=mock_client,
            observer=lambda result, _args, _kwargs: {"verified_row": result["id"]},
        )
        def post_entry(amount: float) -> dict[str, object]:
            return {"id": "row_9", "amount": amount}

        out = post_entry(50.0)
        assert out["id"] == "row_9"
        sent_req = mock_client.verify_outcome.call_args.args[1]
        assert sent_req.observability_class == ObservabilityClass.OBS_DIRECT
        assert sent_req.observation.source_id == "independent_observer"

    def test_autogen_and_crewai_adapters_execute_under_governance(self) -> None:
        mock_client = MagicMock()
        mock_client.propose_action.return_value = _make_mock_decision()
        mock_client.execute_action.return_value = ActionExecutionResult(
            action_id="act_ent_1", transaction_id="tx_ent_1", state=ActionState.COMPLETED
        )
        mock_client.verify_outcome.return_value = _make_mock_outcome()

        def notify_crm(account: str) -> dict[str, str]:
            return {"account": account}

        ag_tool = wrap_autogen_tool(
            notify_crm,
            client=mock_client,
            observer=lambda _r, _a, _k: {"confirmed": True},
        )
        assert ag_tool("acc_1")["account"] == "acc_1"

        crew_tool = MirageCrewAITool(
            tool=notify_crm,
            client=mock_client,
            observer=lambda _r, _a, _k: {"confirmed": True},
        )
        assert crew_tool._run("acc_2")["account"] == "acc_2"
        assert mock_client.propose_action.call_count == 2

    @pytest.mark.asyncio
    async def test_shadow_mode_reports_would_block_without_rewriting_response(self) -> None:
        decomposer = MagicMock()
        claim_obj = Claim(
            claim_id="c1", text="False claim.", claim_type=ClaimType.FACTUAL, criticality=ClaimCriticality.HIGH
        )
        decomposer.decompose.return_value = [claim_obj]
        rav = MagicMock()
        rav.search_evidence = AsyncMock(return_value=[])
        rav.compute_rav_score.return_value = 0.05
        scs = MagicMock()
        scs.compute_scs_score = AsyncMock(return_value=(0.1, False))
        ics = MagicMock()
        ics.compute_claim_ics_scores.return_value = [0.1]
        nli = MagicMock()
        nli.aggregate_multi_evidence.return_value = 0.9

        hrs_eng = MagicMock()
        hrs_eng.process_claims.return_value = (
            HRSResult(
                hrs=0.88,
                raw_score=0.88,
                tier=RiskTier.CRITICAL,
                conformal_interval=ConformalInterval(lower=0.80, upper=0.95),
                signal_attribution=SignalAttribution(rav=0.5, scs=0.2, nli=0.2, ics=0.1),
                claims_count=1,
                contradicted_claims_count=1,
                computation_latency_ms=12.0,
            ),
            [
                ClaimVerificationResult(
                    claim=claim_obj,
                    status=VerificationStatus.CONTRADICTED,
                    risk_score=0.88,
                )
            ],
        )
        correction = MagicMock()
        correction.correct_response = AsyncMock(return_value=("Corrected response", True, 1, None, None))

        orch = VerificationOrchestrator(
            decomposer=decomposer,
            rav_worker=rav,
            scs_worker=scs,
            ics_worker=ics,
            nli_verifier=nli,
            hrs_engine=hrs_eng,
            correction_agent=correction,
            persistence_service=None,
            mongo_service=None,
        )
        resp = await orch.verify_request(
            VerificationRequest(
                prompt="Test",
                response="False claim.",
                auto_correct=True,
                enforcement_mode="shadow",
            )
        )
        assert resp.verified_response == "False claim."
        assert resp.metadata.enforcement_mode == "shadow"
        assert resp.metadata.shadow_would_block is True
        correction.correct_response.assert_not_awaited()


class TestPublicStatusSalesAlertingAndPrivacy:
    """Validate public /v1/status, sales notification dispatch, and GDPR privacy routes."""

    @pytest.mark.asyncio
    async def test_public_status_endpoint_is_accessible_without_auth(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["platform_version"] == "3.0.0"
        assert "gate5_outcome" in body["gates"]

    @pytest.mark.asyncio
    async def test_inquiry_dispatches_sales_notification_email(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        with (
            patch(
                "gateway.routes.inquiries.get_settings",
                return_value=Settings(sales_notification_email="sales@mirage.example"),
            ),
            patch("gateway.routes.inquiries.email_service.send_email", return_value=True) as mock_send,
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/v1/inquiries",
                    json={
                        "name": "Dana Lead",
                        "email": "dana@fintech.example",
                        "company": "FinTech Co",
                        "team_size": "50-250",
                        "use_case": "Treasury Agents",
                        "message": "Interested in Gate 3 and Gate 5 production rollout.",
                    },
                )
        assert resp.status_code == 201
        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["to_email"] == "sales@mirage.example"

    @pytest.mark.asyncio
    async def test_privacy_export_requires_auth_and_returns_dsar_json(self) -> None:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            unauth = await client.get("/v1/privacy/export")
            assert unauth.status_code == 401
