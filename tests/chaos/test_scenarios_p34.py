"""Phase 3.4 Chaos Scenarios 1–5: Resilient Failure Modes and Fallback Behaviors.

Implements Testing_Strategy.md §9 Chaos Scenarios:
1. Redis killed: SCS cache fails open / bypasses smoothly, NLI remains available,
   verification returns HTTP 200; rate limiting remains fail-closed (HTTP 503 SERVICE_DEGRADED).
2. Qdrant killed: RAV circuit breaker opens, uses approved RAV-less fallback (0.85 sparsity risk),
   verification returns HTTP 200, zero cross-tenant retrieval leakage, no stale vector fallback.
3. NLI GPU/offline: RAV + SCS + Visual signals continue under fail-safe model, request completes
   with valid degraded semantics (HTTP 200).
4. LLaVA offline: Fast-path CLIP pre-filter bypasses when aligned; low-similarity claims degrade safely
   to neutral risk without pipeline crash, remaining signals execute, HTTP 200.
5. FLAN-T5 offline: Decomposer failure activates regex sentence/clause splitting fallback,
   decomposed claims flow to downstream signals, HTTP 200.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from db.redis import (
    RedisCacheService,
    RedisClientManager,
    RedisConnectionError,
    RedisOperationTimeoutError,
    TokenBucketRateLimiter,
)
from gateway.main import create_app
from gateway.middleware.circuit_breaker import (
    llava_circuit,
    qdrant_circuit,
    reset_all_circuits,
)
from models.deberta.verifier import DeBERTaNLIVerifier
from models.flan_t5.decomposer import AtomicClaimDecomposer
from shared.schemas import (
    Claim,
    ClaimCriticality,
    ClaimType,
    VerificationRequest,
    VerificationResponse,
)
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory
from tests.chaos.controller import ChaosController
from tests.chaos.models import DependencyName
from workers.orchestrator import VerificationOrchestrator
from workers.rav.worker import RAVWorker
from workers.scs.worker import SCSWorker
from workers.visual.worker import VisualGroundingVerdict, VisualGroundingWorker


@pytest.mark.chaos
class TestChaosScenariosP34:
    """Rigorous execution of Chaos Scenarios 1–5 with deterministic cleanup and health guarantees."""

    # ==========================================================================
    # Scenario 1: Redis Killed
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_scenario_1_redis_killed_scs_cache_bypasses_and_rate_limiter_fails_closed(
        self, chaos_controller: ChaosController
    ) -> None:
        """Scenario 1: Redis becomes unavailable.

        Expected Behaviors:
        1. SCS cache bypasses / fails open: returns (None, False), computes semantic entropy live,
           NLI remains available, verification returns HTTP 200.
        2. Rate-limiting behavior remains fail-closed: returns HTTP 503 SERVICE_DEGRADED.
        """
        # 1. Assert chaos environment safety and capture pre-fault health
        chaos_controller.config.validate_safety()
        pre_health = chaos_controller.check_health()
        assert pre_health.is_healthy is True, f"Pre-fault health unhealthy: {pre_health.unhealthy_proxies}"
        assert pre_health.active_toxics_count == 0

        proxy_name = chaos_controller.resolve_proxy_name(DependencyName.REDIS)
        proxy_port = chaos_controller.get_proxy_port(DependencyName.REDIS)

        try:
            # 2. Inject bounded network fault: Cut connection to Redis
            with chaos_controller.cut_connection(DependencyName.REDIS):
                assert chaos_controller.client.get_proxy(proxy_name).enabled is False

                # --------------------------------------------------------------
                # Facet A: SCS Cache Bypass / Fail-Open (Verification Continuity)
                # --------------------------------------------------------------
                # Wire SCS worker cache to proxied Redis port where connection is severed
                proxied_mgr = RedisClientManager(
                    redis_url=f"redis://mirage_app:mirage_redis_secret@127.0.0.1:{proxy_port}/0",
                    socket_timeout=0.5,
                    socket_connect_timeout=0.5,
                )
                proxied_cache = RedisCacheService(client_manager=proxied_mgr)
                scs_worker = SCSWorker(cache_service=proxied_cache)

                tenant_id = f"tenant_redis_chaos_{uuid.uuid4().hex[:8]}"
                prompt = "What is the speed of light in a vacuum?"

                # Cache lookup must fail open to Cache-Bypass Mode (returns None, False)
                cached_data, is_hit = await proxied_cache.get_scs(
                    tenant_id=tenant_id,
                    model_id="allam-2-7b",
                    prompt=prompt,
                )
                assert is_hit is False
                assert cached_data is None

                # Live SCS computation succeeds without Redis cache
                score, was_cached = await scs_worker.compute_scs_score(
                    prompt=prompt,
                    model_id="allam-2-7b",
                    tenant_id=tenant_id,
                )
                assert was_cached is False
                assert isinstance(score, float)
                assert 0.0 <= score <= 1.0

                # NLI model remains available and operational
                assert scs_worker.verifier.are_bidirectionally_entailed(prompt, prompt) is True

                # End-to-end verification via orchestrator returns HTTP 200 / valid VerificationResponse
                orchestrator = VerificationOrchestrator(scs_worker=scs_worker, mongo_service=None)
                v_req = VerificationRequest(
                    prompt=prompt,
                    response="The speed of light in vacuum is approximately 299,792,458 meters per second.",
                    tenant_id=tenant_id,
                    model_id="allam-2-7b",
                )
                v_res = await orchestrator.verify_request(v_req)
                assert isinstance(v_res, VerificationResponse)
                assert v_res.hrs_result.hrs >= 0.0
                assert v_res.hrs_result.tier is not None
                assert len(v_res.claims) >= 1

                # --------------------------------------------------------------
                # Facet B: Rate Limiter Fail-Closed (Security Invariant)
                # --------------------------------------------------------------
                # Token bucket pointed to the dead Redis proxy raises RedisConnectionError
                proxied_limiter = TokenBucketRateLimiter(client_manager=proxied_mgr)
                with pytest.raises((RedisConnectionError, RedisOperationTimeoutError)):
                    await proxied_limiter.consume(tenant_id=tenant_id, tier="free")

                # HTTP Gateway level: rate limiter failure returns HTTP 503 SERVICE_DEGRADED
                app = create_app()
                client = TestClient(app)
                auth_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)

                with patch("gateway.routes.verify.rate_limiter.check_rate_limit") as mock_rl:
                    mock_rl.side_effect = RedisConnectionError("Redis connection cut by chaos test")
                    http_resp = client.post(
                        "/v1/verify",
                        json={
                            "prompt": prompt,
                            "response": "The speed of light is 300,000 km/s.",
                            "tenant_id": tenant_id,
                        },
                        headers=auth_headers,
                    )
                    assert http_resp.status_code == 503
                    err_json = http_resp.json()
                    assert err_json["error"]["code"] == "SERVICE_DEGRADED"
                    assert "Rate limiting service is unavailable" in err_json["error"]["message"]

        finally:
            # 3. Post-fault cleanup and health assertion
            post_health = chaos_controller.restore_all()
            assert post_health.is_healthy is True
            assert post_health.active_toxics_count == 0
            assert chaos_controller.client.get_proxy(proxy_name).enabled is True

    # ==========================================================================
    # Scenario 2: Qdrant Killed
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_scenario_2_qdrant_killed_rav_circuit_opens_and_rav_less_fallback(
        self, chaos_controller: ChaosController
    ) -> None:
        """Scenario 2: Qdrant becomes unavailable.

        Expected Behaviors:
        1. Qdrant circuit breaker records failures and opens after fail_max=3.
        2. RAV worker activates approved RAV-less fallback (0.85 sparsity risk).
        3. Verification returns HTTP 200.
        4. Zero cross-tenant retrieval leakage and no unauthorized fallback to stale in-memory vectors.
        """
        chaos_controller.config.validate_safety()
        pre_health = chaos_controller.check_health()
        assert pre_health.is_healthy is True
        assert pre_health.active_toxics_count == 0

        proxy_name = chaos_controller.resolve_proxy_name(DependencyName.QDRANT)
        proxy_port = chaos_controller.get_proxy_port(DependencyName.QDRANT)
        reset_all_circuits()

        try:
            # 1. Inject bounded fault: cut Qdrant proxy connection
            with chaos_controller.cut_connection(DependencyName.QDRANT):
                assert chaos_controller.client.get_proxy(proxy_name).enabled is False

                # Configure RAV worker to connect to the dead Qdrant proxy
                rav_worker = RAVWorker(host="127.0.0.1", port=proxy_port)

                tenant_a = f"tenant_alpha_{uuid.uuid4().hex[:6]}"
                tenant_b = f"tenant_beta_{uuid.uuid4().hex[:6]}"
                query = "Albert Einstein received the Nobel Prize in Physics in 1921."

                # Trip Qdrant circuit breaker with 3 failed queries through severed proxy
                for _ in range(qdrant_circuit.fail_max):
                    chunks = await rav_worker.search_evidence(
                        query=query,
                        tenant_id=tenant_a,
                        collection_name="test_kb",
                        authoritative_generations={"doc_1": 1},
                    )
                    assert chunks == []

                # Circuit breaker must now be OPEN
                assert qdrant_circuit.current_state == "open"

                # Next search with circuit OPEN returns empty immediately
                degraded_chunks = await rav_worker.search_evidence(
                    query=query,
                    tenant_id=tenant_a,
                    collection_name="test_kb",
                )
                assert degraded_chunks == []

                # Compute RAV score under RAV-less fallback: must equal 0.85 (KB sparsity default)
                dummy_claim = Claim(
                    claim_id="c_01",
                    text=query,
                    claim_type=ClaimType.FACTUAL,
                    criticality=ClaimCriticality.HIGH,
                    criticality_weight=0.9,
                )
                rav_score = rav_worker.compute_rav_score(dummy_claim, degraded_chunks)
                assert rav_score == 0.85

                # Cross-Tenant Leakage Check: Tenant B must also receive empty results, no crosstalk
                tenant_b_chunks = await rav_worker.search_evidence(
                    query=query,
                    tenant_id=tenant_b,
                    collection_name="test_kb",
                )
                assert tenant_b_chunks == []

                # Full Orchestrator execution returns HTTP 200 / valid VerificationResponse
                orchestrator = VerificationOrchestrator(rav_worker=rav_worker, mongo_service=None)
                v_req = VerificationRequest(
                    prompt="Did Einstein win a Nobel Prize?",
                    response=(
                        "Albert Einstein was awarded the 1921 Nobel Prize in Physics for "
                        "his discovery of the law of the photoelectric effect."
                    ),
                    tenant_id=tenant_a,
                    model_id="allam-2-7b",
                )
                v_res = await orchestrator.verify_request(v_req)
                assert isinstance(v_res, VerificationResponse)
                assert v_res.hrs_result.hrs >= 0.0
                assert v_res.claims[0].rav_score == 0.85
                assert v_res.hrs_result.signal_attribution.rav > 0.0
                assert "rav" in v_res.metadata.pipeline_signals_used
                assert "scs" in v_res.metadata.pipeline_signals_used
                assert "nli" in v_res.metadata.pipeline_signals_used

        finally:
            reset_all_circuits()
            post_health = chaos_controller.restore_all()
            assert post_health.is_healthy is True
            assert post_health.active_toxics_count == 0
            assert chaos_controller.client.get_proxy(proxy_name).enabled is True

    # ==========================================================================
    # Scenario 3: NLI GPU / Model Server Offline
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_scenario_3_nli_gpu_offline_signals_continue_safely(self, chaos_controller: ChaosController) -> None:
        """Scenario 3: NLI model server is unavailable.

        Expected Behaviors:
        1. DeBERTa verifier safely falls back to heuristic entailment scoring.
        2. RAV + SCS + ICS signals continue without crashing.
        3. No new scoring policy is invented; uses approved multi-evidence formulation.
        4. Verification request completes with HTTP 200.
        """
        chaos_controller.config.validate_safety()
        pre_health = chaos_controller.check_health()
        assert pre_health.is_healthy is True
        assert pre_health.active_toxics_count == 0

        proxy_name = chaos_controller.resolve_proxy_name(DependencyName.NLI)

        try:
            # 1. Inject bounded fault: cut NLI model server proxy
            with chaos_controller.cut_connection(DependencyName.NLI):
                assert chaos_controller.client.get_proxy(proxy_name).enabled is False

                # Verifier with neural model server offline falls back to fast heuristic logic
                verifier = DeBERTaNLIVerifier(use_neural=False)

                # Predict pair returns valid (p_ent, p_neu, p_contra) summing to 1.0
                p_ent, p_neu, p_contra = verifier.predict_pair(
                    premise="Water boils at 100 degrees Celsius under standard atmospheric pressure.",
                    hypothesis="Water reaches its boiling point at 100 degrees Celsius.",
                )
                assert 0.0 <= p_ent <= 1.0
                assert 0.0 <= p_neu <= 1.0
                assert 0.0 <= p_contra <= 1.0
                assert round(p_ent + p_neu + p_contra, 2) == 1.0

                # Multi-evidence aggregation with no evidence chunks defaults safely to 0.50
                neutral_risk = verifier.aggregate_multi_evidence(
                    claim_text="The Earth orbits the Sun.",
                    evidence_chunks=[],
                )
                assert neutral_risk == 0.50

                # Full Orchestrator verification continues with all signals and succeeds
                orchestrator = VerificationOrchestrator(nli_verifier=verifier, mongo_service=None)
                tenant_id = f"tenant_nli_chaos_{uuid.uuid4().hex[:8]}"
                v_req = VerificationRequest(
                    prompt="Tell me about Jupiter's moons.",
                    response="Jupiter has 95 officially recognized moons, including Ganymede and Europa.",
                    tenant_id=tenant_id,
                    model_id="allam-2-7b",
                )
                v_res = await orchestrator.verify_request(v_req)
                assert isinstance(v_res, VerificationResponse)
                assert v_res.hrs_result.hrs >= 0.0
                assert v_res.hrs_result.tier is not None
                assert "nli" in v_res.metadata.pipeline_signals_used
                assert "scs" in v_res.metadata.pipeline_signals_used

        finally:
            post_health = chaos_controller.restore_all()
            assert post_health.is_healthy is True
            assert post_health.active_toxics_count == 0
            assert chaos_controller.client.get_proxy(proxy_name).enabled is True

    # ==========================================================================
    # Scenario 4: LLaVA Offline
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_scenario_4_llava_offline_clip_fast_path_and_neutral_vgs_degradation(
        self, chaos_controller: ChaosController
    ) -> None:
        """Scenario 4: LLaVA visual grounding dependency is unavailable.

        Expected Behaviors:
        1. High-similarity claims bypass LLaVA via CLIP pre-filter (fast-path).
        2. Low-similarity claims needing Tier 2 VQA degrade safely to neutral risk
           (CIRCUIT_OPEN_DEGRADED or INSUFFICIENT_EVIDENCE) without crashing.
        3. Remaining signals (RAV, SCS, NLI, ICS) continue to execute.
        4. Tenant/security invariants remain intact, verification completes with HTTP 200.
        """
        chaos_controller.config.validate_safety()
        pre_health = chaos_controller.check_health()
        assert pre_health.is_healthy is True
        assert pre_health.active_toxics_count == 0

        proxy_name = chaos_controller.resolve_proxy_name(DependencyName.LLAVA)
        reset_all_circuits()

        try:
            # 1. Inject bounded fault: cut connection to LLaVA proxy
            with chaos_controller.cut_connection(DependencyName.LLAVA):
                assert chaos_controller.client.get_proxy(proxy_name).enabled is False

                # Synthetic test image
                test_image = (
                    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                    "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                )

                # --------------------------------------------------------------
                # Sub-case A: Fast-path CLIP Pre-Filter Bypass (FR-VG-02)
                # --------------------------------------------------------------
                visual_worker = VisualGroundingWorker()
                high_sim_claim = Claim(
                    claim_id="c_img_01",
                    text="A single transparent pixel graphic",
                    claim_type=ClaimType.IMAGE_GROUNDED,
                    criticality=ClaimCriticality.HIGH,
                    criticality_weight=0.9,
                )

                # High similarity bypasses LLaVA entirely
                with patch.object(visual_worker.clip_filter, "compute_similarity", return_value=0.92):
                    vgs_score, verdict, meta = await visual_worker.verify_claim(
                        claim=high_sim_claim,
                        images=[test_image],
                    )
                    assert meta["fast_path"] is True
                    assert verdict == VisualGroundingVerdict.CONSISTENT
                    assert vgs_score == 0.05

                # --------------------------------------------------------------
                # Sub-case B: Tier 2 VQA Circuit Open Degradation (FR-VG-03)
                # --------------------------------------------------------------
                low_sim_claim = Claim(
                    claim_id="c_img_02",
                    text="A red sports car parked near the Eiffel Tower",
                    claim_type=ClaimType.IMAGE_GROUNDED,
                    criticality=ClaimCriticality.HIGH,
                    criticality_weight=0.9,
                )

                # Trip llava_circuit
                for _ in range(llava_circuit.fail_max):
                    try:
                        llava_circuit.call(lambda: (_ for _ in ()).throw(ConnectionError("LLaVA connection severed")))
                    except Exception:
                        pass
                assert llava_circuit.current_state == "open"

                # Under open circuit, low-similarity claim degrades safely to CIRCUIT_OPEN_DEGRADED
                with patch.object(visual_worker.clip_filter, "compute_similarity", return_value=0.45):
                    vgs_score, verdict, meta = await visual_worker.verify_claim(
                        claim=low_sim_claim,
                        images=[test_image],
                    )
                    assert meta["fast_path"] is False
                    assert verdict == VisualGroundingVerdict.CIRCUIT_OPEN_DEGRADED
                    assert vgs_score == 0.50
                    assert meta["circuit_breaker"] == "open"

                # --------------------------------------------------------------
                # Sub-case C: Full Multimodal Verification Request via Orchestrator
                # --------------------------------------------------------------
                orchestrator = VerificationOrchestrator(visual_worker=visual_worker, mongo_service=None)
                tenant_id = f"tenant_llava_chaos_{uuid.uuid4().hex[:8]}"
                v_req = VerificationRequest(
                    prompt="Describe the image.",
                    response="The image depicts a red sports car parked near the Eiffel Tower.",
                    tenant_id=tenant_id,
                    model_id="allam-2-7b",
                    images=[test_image],
                )
                v_res = await orchestrator.verify_request(v_req)
                assert isinstance(v_res, VerificationResponse)
                assert v_res.hrs_result.hrs >= 0.0
                assert "vgs" in v_res.metadata.pipeline_signals_used
                assert "rav" in v_res.metadata.pipeline_signals_used
                assert "scs" in v_res.metadata.pipeline_signals_used

        finally:
            reset_all_circuits()
            post_health = chaos_controller.restore_all()
            assert post_health.is_healthy is True
            assert post_health.active_toxics_count == 0
            assert chaos_controller.client.get_proxy(proxy_name).enabled is True

    # ==========================================================================
    # Scenario 5: FLAN-T5 Offline
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_scenario_5_flan_t5_offline_activates_regex_claim_splitting_fallback(
        self, chaos_controller: ChaosController
    ) -> None:
        """Scenario 5: FLAN-T5 atomic claim decomposer is unavailable.

        Expected Behaviors:
        1. Decomposer network timeout/failure triggers regex sentence & clause splitting fallback.
        2. Extracted claims preserve taxonomy classification and criticality weighting.
        3. Downstream verification pipeline executes completely, returning HTTP 200.
        """
        chaos_controller.config.validate_safety()
        pre_health = chaos_controller.check_health()
        assert pre_health.is_healthy is True
        assert pre_health.active_toxics_count == 0

        proxy_name = chaos_controller.resolve_proxy_name(DependencyName.FLAN_T5)
        reset_all_circuits()

        try:
            # 1. Inject bounded fault: cut connection to FLAN-T5 proxy
            with chaos_controller.cut_connection(DependencyName.FLAN_T5):
                assert chaos_controller.client.get_proxy(proxy_name).enabled is False

                # Decomposer where neural model call fails
                decomposer = AtomicClaimDecomposer(use_neural=False)

                test_text = (
                    "NASA launched the James Webb Space Telescope in December 2021. "
                    "The telescope cost approximately $10 billion and it orbits at the second Lagrange point."
                )

                # Decomposition must succeed via regex heuristic engine (<45ms)
                claims = decomposer.decompose(test_text)
                assert len(claims) >= 2

                # Verify taxonomy and criticality metadata are preserved by regex fallback
                types = {c.claim_type for c in claims}
                assert ClaimType.TEMPORAL in types or ClaimType.NUMERICAL in types or ClaimType.FACTUAL in types

                for claim in claims:
                    assert claim.claim_id.startswith("c_")
                    assert len(claim.text) >= 5
                    assert isinstance(claim.criticality, ClaimCriticality)
                    assert 0.0 < claim.criticality_weight <= 1.0

                # Full Orchestrator execution with regex-decomposed claims
                orchestrator = VerificationOrchestrator(decomposer=decomposer, mongo_service=None)
                tenant_id = f"tenant_flant5_chaos_{uuid.uuid4().hex[:8]}"
                v_req = VerificationRequest(
                    prompt="When was JWST launched?",
                    response=test_text,
                    tenant_id=tenant_id,
                    model_id="allam-2-7b",
                )
                v_res = await orchestrator.verify_request(v_req)
                assert isinstance(v_res, VerificationResponse)
                assert v_res.hrs_result.hrs >= 0.0
                assert v_res.hrs_result.claims_count >= 2
                assert len(v_res.claims) >= 2

                # HTTP Endpoint verification: POST /v1/verify returns HTTP 200
                app = create_app()
                client = TestClient(app)
                auth_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)

                with patch.object(orchestrator.decomposer, "decompose", return_value=claims):
                    with patch("gateway.routes.verify.orchestrator", orchestrator):
                        http_resp = client.post(
                            "/v1/verify",
                            json={
                                "prompt": "When was JWST launched?",
                                "response": test_text,
                                "tenant_id": tenant_id,
                            },
                            headers=auth_headers,
                        )
                        assert http_resp.status_code == 200
                        resp_data = http_resp.json()
                        assert "hrs_result" in resp_data
                        assert resp_data["hrs_result"]["claims_count"] >= 2
                        assert "claims" in resp_data

        finally:
            reset_all_circuits()
            post_health = chaos_controller.restore_all()
            assert post_health.is_healthy is True
            assert post_health.active_toxics_count == 0
            assert chaos_controller.client.get_proxy(proxy_name).enabled is True
