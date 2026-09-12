"""Comprehensive test suite for the Multimodal Visual Grounding Module.

Tests:
1. CLIP Pre-Filter semantic similarity, tenant threshold gating, and fast-path bypass.
2. Visual Grounding Worker VQA prompt handling, structured parsing, and circuit breaker degradation.
3. Full VerificationOrchestrator multimodal pipeline with image inputs, VGS scoring, and TreeSHAP.
4. MMHAL-Bench dataset loader.
"""

import pytest

from benchmarks.datasets.mmhal import MMHALBenchLoader
from gateway.middleware.circuit_breaker import llava_circuit, reset_all_circuits
from shared.schemas import (
    Claim,
    ClaimCriticality,
    ClaimType,
    VerificationRequest,
)
from workers.orchestrator import VerificationOrchestrator
from workers.visual import (
    CLIPPreFilter,
    VisualGroundingVerdict,
    VisualGroundingWorker,
)


@pytest.fixture(autouse=True)
def _reset_circuits_before_test() -> None:
    """Ensure all circuit breakers start in a clean CLOSED state."""
    reset_all_circuits()


@pytest.mark.unit
class TestCLIPPreFilter:
    """Unit tests for Tier 1 CLIP pre-filtering engine."""

    def test_clip_similarity_deterministic_range(self) -> None:
        clip = CLIPPreFilter(use_neural=False)
        sim = clip.compute_similarity(
            image_input="https://example.com/satellite_photo_mars.jpg",
            claim_text="Mars is clearly visible with rust-red soil and craters.",
        )
        assert 0.0 <= sim <= 1.0

    def test_clip_high_similarity_threshold_bypass(self) -> None:
        clip = CLIPPreFilter(use_neural=False, default_threshold=0.85)
        # Register high similarity (e.g. 0.94)
        clip.register_mock_similarity(
            image_id="cat_couch.jpg",
            claim_substr="cat sleeping",
            similarity=0.94,
        )
        sim = clip.compute_similarity("cat_couch.jpg", "A ginger cat sleeping peacefully on the sofa.")
        assert sim == 0.94
        assert clip.should_bypass_llava(sim, threshold=0.85) is True

    def test_clip_low_similarity_no_bypass(self) -> None:
        clip = CLIPPreFilter(use_neural=False, default_threshold=0.85)
        clip.register_mock_similarity(
            image_id="cat_couch.jpg",
            claim_substr="elephant",
            similarity=0.22,
        )
        sim = clip.compute_similarity("cat_couch.jpg", "A wild elephant roaming near the sofa.")
        assert sim == 0.22
        assert clip.should_bypass_llava(sim, threshold=0.85) is False

    def test_clip_empty_claim_returns_zero(self) -> None:
        clip = CLIPPreFilter(use_neural=False)
        sim = clip.compute_similarity("test.jpg", "   ...   ")
        assert sim == 0.0


@pytest.mark.unit
class TestVisualGroundingWorker:
    """Unit tests for the Visual Grounding Worker (two-tier pipeline & circuit breakers)."""

    @pytest.mark.asyncio
    async def test_no_image_provided_returns_neutral(self) -> None:
        worker = VisualGroundingWorker()
        claim = Claim(
            claim_id="c_01",
            text="The car is bright red.",
            claim_type=ClaimType.IMAGE_GROUNDED,
            criticality=ClaimCriticality.HIGH,
            criticality_weight=1.0,
        )
        vgs, verdict, meta = await worker.verify_claim(claim, images=[])
        assert vgs == 0.50
        assert verdict == VisualGroundingVerdict.NO_IMAGE_PROVIDED
        assert meta["fast_path"] is False

    @pytest.mark.asyncio
    async def test_fast_path_clip_bypass_llava(self) -> None:
        clip = CLIPPreFilter(use_neural=False)
        clip.register_mock_similarity("golden_dog.jpg", "golden retriever", 0.92)
        worker = VisualGroundingWorker(clip_filter=clip, default_threshold=0.85)

        claim = Claim(
            claim_id="c_02",
            text="There is a golden retriever on the lawn.",
            claim_type=ClaimType.IMAGE_GROUNDED,
            criticality=ClaimCriticality.HIGH,
            criticality_weight=1.0,
        )
        vgs, verdict, meta = await worker.verify_claim(claim, images=["golden_dog.jpg"])
        assert vgs <= 0.10
        assert verdict == VisualGroundingVerdict.CONSISTENT
        assert meta["fast_path"] is True
        assert meta["model"] == "clip_prefilter"

    @pytest.mark.asyncio
    async def test_vqa_consistent_verdict(self) -> None:
        clip = CLIPPreFilter(use_neural=False)
        clip.register_mock_similarity("chart.png", "revenue", 0.50)  # Below 0.85 -> triggers VQA
        worker = VisualGroundingWorker(clip_filter=clip)
        worker.register_mock_vqa("revenue", VisualGroundingVerdict.CONSISTENT)

        claim = Claim(
            claim_id="c_03",
            text="The bar chart indicates Q3 revenue reached $5M.",
            claim_type=ClaimType.IMAGE_GROUNDED,
            criticality=ClaimCriticality.HIGH,
            criticality_weight=1.0,
        )
        vgs, verdict, meta = await worker.verify_claim(claim, images=["chart.png"])
        assert vgs == 0.10
        assert verdict == VisualGroundingVerdict.CONSISTENT
        assert meta["fast_path"] is False
        assert meta["model"] == "llava-1.6-mistral-7b"

    @pytest.mark.asyncio
    async def test_vqa_inconsistent_verdict(self) -> None:
        clip = CLIPPreFilter(use_neural=False)
        clip.register_mock_similarity("house.png", "swimming pool", 0.40)
        worker = VisualGroundingWorker(clip_filter=clip)
        worker.register_mock_vqa("swimming pool", VisualGroundingVerdict.INCONSISTENT)

        claim = Claim(
            claim_id="c_04",
            text="A luxurious swimming pool is visible in the backyard.",
            claim_type=ClaimType.IMAGE_GROUNDED,
            criticality=ClaimCriticality.HIGH,
            criticality_weight=1.0,
        )
        vgs, verdict, meta = await worker.verify_claim(claim, images=["house.png"])
        assert vgs == 0.90
        assert verdict == VisualGroundingVerdict.INCONSISTENT
        assert meta["fast_path"] is False

    @pytest.mark.asyncio
    async def test_vqa_insufficient_evidence_verdict(self) -> None:
        clip = CLIPPreFilter(use_neural=False)
        clip.register_mock_similarity("blur.png", "license plate", 0.35)
        worker = VisualGroundingWorker(clip_filter=clip)
        worker.register_mock_vqa("license plate", VisualGroundingVerdict.INSUFFICIENT_EVIDENCE)

        claim = Claim(
            claim_id="c_05",
            text="The license plate reads 7XYZ999.",
            claim_type=ClaimType.IMAGE_GROUNDED,
            criticality=ClaimCriticality.MEDIUM,
            criticality_weight=0.6,
        )
        vgs, verdict, meta = await worker.verify_claim(claim, images=["blur.png"])
        assert vgs == 0.60
        assert verdict == VisualGroundingVerdict.INSUFFICIENT_EVIDENCE

    @pytest.mark.asyncio
    async def test_llava_circuit_breaker_open_graceful_degradation(self) -> None:
        clip = CLIPPreFilter(use_neural=False)
        clip.register_mock_similarity("img.jpg", "claim", 0.40)
        worker = VisualGroundingWorker(clip_filter=clip)

        # Force trip llava_circuit to OPEN
        llava_circuit.open()
        assert llava_circuit.current_state == "open"

        claim = Claim(
            claim_id="c_06",
            text="Some claim requiring slow-path LLaVA.",
            claim_type=ClaimType.IMAGE_GROUNDED,
            criticality=ClaimCriticality.MEDIUM,
            criticality_weight=0.6,
        )
        vgs, verdict, meta = await worker.verify_claim(claim, images=["img.jpg"])
        assert vgs == 0.50
        assert verdict == VisualGroundingVerdict.CIRCUIT_OPEN_DEGRADED
        assert meta["circuit_breaker"] == "open"

    @pytest.mark.asyncio
    async def test_batch_verify_claims(self) -> None:
        worker = VisualGroundingWorker()
        claims = [
            Claim(
                claim_id="c_a",
                text="The sky is clear blue.",
                claim_type=ClaimType.IMAGE_GROUNDED,
                criticality=ClaimCriticality.LOW,
                criticality_weight=0.3,
            ),
            Claim(
                claim_id="c_b",
                text="There is a tall red brick chimney.",
                claim_type=ClaimType.IMAGE_GROUNDED,
                criticality=ClaimCriticality.HIGH,
                criticality_weight=1.0,
            ),
        ]
        results = await worker.verify_claims(claims, images=["landscape.jpg"])
        assert len(results) == 2
        for vgs, verdict, _meta in results:
            assert 0.0 <= vgs <= 1.0
            assert isinstance(verdict, VisualGroundingVerdict)


@pytest.mark.unit
class TestMultimodalOrchestratorIntegration:
    """Integration tests verifying full pipeline with multimodal requests."""

    @pytest.mark.asyncio
    async def test_orchestrator_with_image_activates_vgs(self) -> None:
        orchestrator = VerificationOrchestrator()
        req = VerificationRequest(
            prompt="Describe what you see in the uploaded image.",
            response="A brown dog is catching a red frisbee in mid-air.",
            tenant_id="test_multimodal_tenant",
            images=[
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ],
        )

        res = await orchestrator.verify_request(req)
        assert res.hrs_result is not None
        assert "vgs" in res.metadata.pipeline_signals_used
        # Check claims have vgs_score populated
        for c in res.claims:
            assert c.vgs_score is not None
            assert 0.0 <= c.vgs_score <= 1.0

    @pytest.mark.asyncio
    async def test_orchestrator_text_only_does_not_activate_vgs(self) -> None:
        orchestrator = VerificationOrchestrator()
        req = VerificationRequest(
            prompt="What is the capital of France?",
            response="Paris is the capital of France.",
            tenant_id="test_text_tenant",
            images=[],
            image_urls=[],
        )

        res = await orchestrator.verify_request(req)
        assert "vgs" not in res.metadata.pipeline_signals_used
        for c in res.claims:
            assert c.vgs_score is None


@pytest.mark.unit
class TestMMHALBenchDataset:
    """Tests for the MMHAL-Bench multimodal hallucination benchmark loader."""

    def test_mmhal_loader_loads_curated_cases(self) -> None:
        loader = MMHALBenchLoader()
        cases = loader.load_cases()
        assert len(cases) >= 8

        labels = {c.ground_truth_label for c in cases}
        assert labels == {0, 1}

        # Check all cases have images attached
        for c in cases:
            assert len(c.images) >= 1
            assert c.case_id.startswith("mmhal_")
            assert c.domain.startswith("mmhal_")

    def test_mmhal_loader_with_limit(self) -> None:
        loader = MMHALBenchLoader()
        cases = loader.load_cases(limit=3)
        assert len(cases) == 3
