"""MMHAL-Bench multimodal hallucination benchmark dataset loader.

Reference:
    Sun et al., 'Aligning Large Multimodal Models with Factually Constrained RLHF
    and the MMHAL-Bench Benchmark', 2023.
"""

from collections.abc import Sequence
from typing import Any

from benchmarks.evaluator import BenchmarkCase

CURATED_MMHAL_SAMPLES: list[dict[str, Any]] = [
    # Visual Object Presence - Factual
    {
        "id": "mmhal_01",
        "domain": "object_presence",
        "prompt": "What animals are visible on the grass field in the image?",
        "response": "There are two golden retrievers playing with a red tennis ball on the green grass field.",
        "image": "tests/fixtures/images/two_dogs_field.jpg",
        "label": 0,
        "evidence": ["Image depicts two golden retriever dogs on open grass with a red ball in foreground."],
    },
    # Visual Object Presence - Hallucinated
    {
        "id": "mmhal_02",
        "domain": "object_presence",
        "prompt": "What animals are visible on the grass field in the image?",
        "response": "There is a flock of sheep grazing peacefully alongside a black horse near the fence.",
        "image": "tests/fixtures/images/two_dogs_field.jpg",
        "label": 1,
        "evidence": ["Image only contains two dogs on grass; no sheep or horse is present anywhere."],
    },
    # Visual Attribute / Color - Factual
    {
        "id": "mmhal_03",
        "domain": "attribute_color",
        "prompt": "Describe the vehicle parked in front of the house.",
        "response": "A dark blue sedan is parked on the driveway next to the brick garage.",
        "image": "tests/fixtures/images/blue_car_driveway.jpg",
        "label": 0,
        "evidence": [
            "The photograph clearly displays a navy/dark blue four-door sedan on a paved residential driveway."
        ],
    },
    # Visual Attribute / Color - Hallucinated
    {
        "id": "mmhal_04",
        "domain": "attribute_color",
        "prompt": "Describe the vehicle parked in front of the house.",
        "response": "A bright yellow convertible sports car is parked on the driveway with its top down.",
        "image": "tests/fixtures/images/blue_car_driveway.jpg",
        "label": 1,
        "evidence": ["The car is an ordinary dark blue sedan; no yellow convertible exists in the scene."],
    },
    # Spatial Relationship - Factual
    {
        "id": "mmhal_05",
        "domain": "spatial_relations",
        "prompt": "Where is the coffee mug relative to the laptop on the wooden desk?",
        "response": "The white ceramic coffee mug is placed to the right of the laptop computer.",
        "image": "tests/fixtures/images/desk_laptop_mug.jpg",
        "label": 0,
        "evidence": ["A white mug sits immediately on the right-hand side of a silver laptop on the desk."],
    },
    # Spatial Relationship - Hallucinated
    {
        "id": "mmhal_06",
        "domain": "spatial_relations",
        "prompt": "Where is the coffee mug relative to the laptop on the wooden desk?",
        "response": "The coffee mug is perched directly on top of the closed laptop keyboard.",
        "image": "tests/fixtures/images/desk_laptop_mug.jpg",
        "label": 1,
        "evidence": ["The mug is next to the laptop, not on top of the keyboard."],
    },
    # Numerical Counting - Factual
    {
        "id": "mmhal_07",
        "domain": "counting",
        "prompt": "How many coffee cups are on the meeting table?",
        "response": "There are exactly three coffee cups arranged around the conference table.",
        "image": "tests/fixtures/images/three_cups_table.jpg",
        "label": 0,
        "evidence": ["Three disposable cups are visible on the wooden boardroom table."],
    },
    # Numerical Counting - Hallucinated
    {
        "id": "mmhal_08",
        "domain": "counting",
        "prompt": "How many coffee cups are on the meeting table?",
        "response": "There are eight coffee cups scattered across the table for the participants.",
        "image": "tests/fixtures/images/three_cups_table.jpg",
        "label": 1,
        "evidence": ["Only three cups exist on the table, not eight."],
    },
]


class MMHALBenchLoader:
    """Loader for MMHAL-Bench multimodal hallucination benchmark."""

    def __init__(self, raw_samples: Sequence[dict[str, Any]] | None = None) -> None:
        self.samples = raw_samples or CURATED_MMHAL_SAMPLES

    def load_cases(self, limit: int | None = None) -> list[BenchmarkCase]:
        """Convert MMHAL-Bench samples into standardized BenchmarkCase instances."""
        subset = self.samples[:limit] if limit else self.samples
        cases: list[BenchmarkCase] = []
        for s in subset:
            cases.append(
                BenchmarkCase(
                    case_id=s["id"],
                    prompt=s["prompt"],
                    response=s["response"],
                    ground_truth_label=int(s["label"]),
                    domain=f"mmhal_{s.get('domain', 'general')}",
                    reference_evidence=tuple(s.get("evidence", [])),
                    images=(s["image"],) if "image" in s else (),
                )
            )
        return cases
