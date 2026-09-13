"""Model unit tests for the Visual Grounding Module (CLIP Pre-Filter and LLaVA-1.6 VQA)."""

import pytest

from shared.schemas import Claim, ClaimCriticality, ClaimType
from workers.visual.clip_filter import CLIPPreFilter
from workers.visual.worker import VisualGroundingVerdict, VisualGroundingWorker


@pytest.fixture
def clip_filter() -> CLIPPreFilter:
    """Instantiate CLIP pre-filter in deterministic CPU mode."""
    return CLIPPreFilter(use_neural=False, default_threshold=0.85)


@pytest.fixture
def visual_worker() -> VisualGroundingWorker:
    """Instantiate Visual Grounding Worker."""
    return VisualGroundingWorker()


@pytest.mark.model_unit
class TestCLIPPreFilter:
    """Unit tests for Tier-1 CLIP fast-path filtering."""

    def test_threshold_logic(self, clip_filter: CLIPPreFilter) -> None:
        """Verify threshold boundary conditions for default (0.85) and custom overrides."""
        assert clip_filter.default_threshold == 0.85

        # Default threshold check
        assert clip_filter.should_bypass_llava(0.86) is True
        assert clip_filter.should_bypass_llava(0.85) is False
        assert clip_filter.should_bypass_llava(0.84) is False

        # Custom tenant threshold check (e.g. strict 0.90, relaxed 0.75)
        assert clip_filter.should_bypass_llava(0.88, threshold=0.90) is False
        assert clip_filter.should_bypass_llava(0.91, threshold=0.90) is True
        assert clip_filter.should_bypass_llava(0.78, threshold=0.75) is True

    def test_mock_registry_registration(self, clip_filter: CLIPPreFilter) -> None:
        """Verify mock registry allows deterministic test overrides."""
        img_id = "test_img_satellite_01.png"
        clip_filter.register_mock_similarity(img_id, "solar farm", 0.94)
        clip_filter.register_mock_similarity(img_id, "oil refinery", 0.12)

        sim_high = clip_filter.compute_similarity(img_id, "The facility is a massive solar farm.")
        sim_low = clip_filter.compute_similarity(img_id, "The facility is an oil refinery.")

        assert sim_high == 0.94
        assert sim_low == 0.12
        assert clip_filter.should_bypass_llava(sim_high) is True
        assert clip_filter.should_bypass_llava(sim_low) is False

    def test_deterministic_pseudo_embedding_properties(self, clip_filter: CLIPPreFilter) -> None:
        """Verify deterministic fallback produces consistent scores in [0.0, 1.0]."""
        img_id = "chart_revenue_2023.png"
        claim_1 = "The chart displays revenue for 2023."
        claim_2 = "A portrait of a Renaissance painter."

        sim_1a = clip_filter.compute_similarity(img_id, claim_1)
        sim_1b = clip_filter.compute_similarity(img_id, claim_1)
        sim_2 = clip_filter.compute_similarity(img_id, claim_2)

        # Idempotence
        assert sim_1a == sim_1b
        assert 0.0 <= sim_1a <= 1.0
        assert 0.0 <= sim_2 <= 1.0
        # Overlap with token 'revenue' should produce higher similarity
        assert sim_1a > sim_2

    def test_empty_claim_text(self, clip_filter: CLIPPreFilter) -> None:
        """Verify empty claim text yields 0.0 similarity."""
        assert clip_filter.compute_similarity("img.jpg", "") == 0.0
        assert clip_filter.compute_similarity("img.jpg", "   ") == 0.0


@pytest.mark.model_unit
class TestVisualGroundingWorker:
    """Unit tests for VisualGroundingWorker and LLaVA-1.6 VQA orchestration."""

    @pytest.mark.asyncio
    async def test_missing_images_no_image_verdict(self, visual_worker: VisualGroundingWorker) -> None:
        """Verify image claim without provided images returns NO_IMAGE_PROVIDED with neutral score."""
        img_claim = Claim(
            claim_id="c_img_01",
            text="The image shows three red sports cars.",
            claim_type=ClaimType.IMAGE_GROUNDED,
            criticality=ClaimCriticality.MEDIUM,
        )
        score, verdict, meta = await visual_worker.verify_claim(img_claim, images=[])
        assert score == 0.50
        assert verdict == VisualGroundingVerdict.NO_IMAGE_PROVIDED
        assert meta["fast_path"] is False

    @pytest.mark.asyncio
    async def test_clip_fast_path_bypass(self, visual_worker: VisualGroundingWorker) -> None:
        """Verify claim with high CLIP similarity triggers fast-path bypass without LLaVA."""
        img_id = "sample_traffic_camera.jpg"
        visual_worker.clip_filter.register_mock_similarity(img_id, "blue bus", 0.92)

        claim = Claim(
            claim_id="c_img_02",
            text="A large blue bus is driving in the right lane.",
            claim_type=ClaimType.IMAGE_GROUNDED,
            criticality=ClaimCriticality.HIGH,
        )
        score, verdict, meta = await visual_worker.verify_claim(claim, images=[img_id])

        assert score == 0.05
        assert verdict == VisualGroundingVerdict.CONSISTENT
        assert meta["fast_path"] is True
        assert meta["clip_similarity"] == 0.92

    @pytest.mark.asyncio
    async def test_vqa_consistent_verdict(self, visual_worker: VisualGroundingWorker) -> None:
        """Verify VQA consistent verdict maps to low risk (0.10)."""
        img_id = "cat_on_sofa.jpg"
        visual_worker.clip_filter.register_mock_similarity(img_id, "orange tabby", 0.70)
        visual_worker.register_mock_vqa("orange tabby", VisualGroundingVerdict.CONSISTENT)

        claim = Claim(
            claim_id="c_img_03",
            text="An orange tabby cat is sleeping on the couch.",
            claim_type=ClaimType.IMAGE_GROUNDED,
            criticality=ClaimCriticality.LOW,
        )
        score, verdict, meta = await visual_worker.verify_claim(claim, images=[img_id])

        assert score == 0.10
        assert verdict == VisualGroundingVerdict.CONSISTENT
        assert meta["fast_path"] is False

    @pytest.mark.asyncio
    async def test_vqa_inconsistent_verdict(self, visual_worker: VisualGroundingWorker) -> None:
        """Verify VQA inconsistent verdict maps to high risk (0.90)."""
        img_id = "conference_room.jpg"
        visual_worker.clip_filter.register_mock_similarity(img_id, "elephants", 0.30)
        visual_worker.register_mock_vqa("elephants", VisualGroundingVerdict.INCONSISTENT)

        claim = Claim(
            claim_id="c_img_04",
            text="There are two elephants present in the conference room.",
            claim_type=ClaimType.IMAGE_GROUNDED,
            criticality=ClaimCriticality.HIGH,
        )
        score, verdict, meta = await visual_worker.verify_claim(claim, images=[img_id])

        assert score == 0.90
        assert verdict == VisualGroundingVerdict.INCONSISTENT
        assert meta["fast_path"] is False

    def test_parse_vqa_output_robustness(self, visual_worker: VisualGroundingWorker) -> None:
        """Verify VQA output string parsing handles varied casing and unstructured text."""
        v1, _ = visual_worker._parse_vqa_output("CONSISTENT: Verified against the image.")
        assert v1 == VisualGroundingVerdict.CONSISTENT

        v2, _ = visual_worker._parse_vqa_output("The image is INCONSISTENT with the claim.")
        assert v2 == VisualGroundingVerdict.INCONSISTENT

        v3, _ = visual_worker._parse_vqa_output("INSUFFICIENT evidence to determine validity.")
        assert v3 == VisualGroundingVerdict.INSUFFICIENT_EVIDENCE

        v4, _ = visual_worker._parse_vqa_output("I am unable to see clearly.")
        assert v4 == VisualGroundingVerdict.INSUFFICIENT_EVIDENCE

    @pytest.mark.asyncio
    async def test_batch_verification(self, visual_worker: VisualGroundingWorker) -> None:
        """Verify batch verification processes multiple claims concurrently."""
        claims = [
            Claim(
                claim_id="c_01",
                text="Textual historical claim.",
                claim_type=ClaimType.FACTUAL,
            ),
            Claim(
                claim_id="c_02",
                text="Image showing an object.",
                claim_type=ClaimType.IMAGE_GROUNDED,
            ),
        ]
        results = await visual_worker.verify_claims(claims, images=["test_image.png"])
        assert len(results) == 2
        for score, verdict, meta in results:
            assert 0.0 <= score <= 1.0
            assert isinstance(verdict, VisualGroundingVerdict)
            assert isinstance(meta, dict)
