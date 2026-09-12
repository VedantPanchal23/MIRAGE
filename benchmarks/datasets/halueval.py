"""HaluEval benchmark dataset loader and test split generator.

Reference:
    Li et al., 'HaluEval: A Large-Scale Hallucination Evaluation Benchmark for LLMs', EMNLP 2023.
"""

import json
from pathlib import Path
from typing import Any

from benchmarks.evaluator import BenchmarkCase

# Curated high-fidelity representative split spanning QA, dialogue, and summarization
CURATED_HALUEVAL_SAMPLES: list[dict[str, Any]] = [
    # QA Split - Factual
    {
        "id": "halu_qa_01",
        "domain": "qa",
        "prompt": "Which planet is known as the Red Planet and what gives it this color?",
        "response": "Mars is known as the Red Planet. Its reddish appearance is due to iron oxide (rust) on its surface.",
        "label": 0,
        "evidence": [
            "Mars is the fourth planet from the Sun and is often referred to as the Red Planet due to iron oxide prevalence."
        ],
    },
    # QA Split - Hallucinated
    {
        "id": "halu_qa_02",
        "domain": "qa",
        "prompt": "When was the first iPhone released and who was the CEO of Apple at that time?",
        "response": "The first iPhone was released in November 2011, and Tim Cook was the CEO who introduced it to the world.",
        "label": 1,
        "evidence": [
            "The original iPhone was announced by Steve Jobs on January 9, 2007, and released for sale on June 29, 2007."
        ],
    },
    # Dialogue Split - Factual
    {
        "id": "halu_dial_01",
        "domain": "dialogue",
        "prompt": "User: Can you explain penicillin?\nAssistant:",
        "response": "Penicillin is a group of antibiotics originally derived from Penicillium fungi, discovered by Alexander Fleming in 1928.",
        "label": 0,
        "evidence": [
            "Penicillin was discovered in 1928 by Scottish scientist Alexander Fleming as an antibiotic substance produced by Penicillium notatum."
        ],
    },
    # Dialogue Split - Hallucinated
    {
        "id": "halu_dial_02",
        "domain": "dialogue",
        "prompt": "User: Did penicillin win Fleming a Nobel prize in literature?\nAssistant:",
        "response": "Yes, Alexander Fleming won the Nobel Prize in Literature in 1945 for his written accounts of discovering penicillin.",
        "label": 1,
        "evidence": [
            "Alexander Fleming shared the 1945 Nobel Prize in Physiology or Medicine with Ernst Boris Chain and Howard Florey."
        ],
    },
    # Summarization Split - Factual
    {
        "id": "halu_sum_01",
        "domain": "summarization",
        "prompt": "Summarize the mission of Apollo 11.",
        "response": "Apollo 11 was the 1969 American spaceflight that first landed humans, Neil Armstrong and Buzz Aldrin, on the Moon.",
        "label": 0,
        "evidence": ["Apollo 11 landed Neil Armstrong and Buzz Aldrin on the Moon on July 20, 1969."],
    },
    # Summarization Split - Hallucinated
    {
        "id": "halu_sum_02",
        "domain": "summarization",
        "prompt": "Summarize the founding of the United Nations.",
        "response": "The United Nations was established in Geneva in 1919 immediately after the Treaty of Versailles concluded World War I.",
        "label": 1,
        "evidence": [
            "The United Nations was founded in San Francisco in 1945 following the conclusion of World War II. The League of Nations was founded in 1919."
        ],
    },
    # Entity Clashes - Factual
    {
        "id": "halu_qa_03",
        "domain": "qa",
        "prompt": "What is the speed of light in a vacuum?",
        "response": "The speed of light in vacuum is exactly 299,792,458 meters per second.",
        "label": 0,
        "evidence": ["The speed of light in vacuum, c, is defined as exactly 299,792,458 m/s."],
    },
    # Entity Clashes - Hallucinated
    {
        "id": "halu_qa_04",
        "domain": "qa",
        "prompt": "Who painted the Mona Lisa and where is it exhibited?",
        "response": "The Mona Lisa was painted by Michelangelo Buonarroti and is permanently displayed in the Uffizi Gallery in Florence.",
        "label": 1,
        "evidence": [
            "The Mona Lisa is an oil painting by Leonardo da Vinci, exhibited permanently at the Louvre Museum in Paris."
        ],
    },
    # Additional Factual
    {
        "id": "halu_qa_05",
        "domain": "qa",
        "prompt": "What is the capital city of Australia?",
        "response": "The capital of Australia is Canberra.",
        "label": 0,
        "evidence": ["Canberra is the federal capital city of the Commonwealth of Australia."],
    },
    # Additional Hallucinated
    {
        "id": "halu_qa_06",
        "domain": "qa",
        "prompt": "What is the capital city of Australia?",
        "response": "Sydney is the capital city of Australia, being its most populous metropolis.",
        "label": 1,
        "evidence": [
            "Canberra is the federal capital of Australia, chosen as a compromise between Sydney and Melbourne."
        ],
    },
]


class HaluEvalLoader:
    """Streams and loads HaluEval benchmark cases."""

    def __init__(self, dataset_path: str | Path | None = None) -> None:
        self.dataset_path = Path(dataset_path) if dataset_path else None

    def load_cases(self, limit: int | None = None) -> list[BenchmarkCase]:
        """Load benchmark cases from curated sample or from external file."""
        cases: list[BenchmarkCase] = []

        if self.dataset_path and self.dataset_path.exists():
            with open(self.dataset_path, encoding="utf-8") as f:
                for idx, line in enumerate(f):
                    if limit and len(cases) >= limit:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    cases.append(
                        BenchmarkCase(
                            case_id=item.get("id", f"halueval_{idx:04d}"),
                            prompt=item.get("prompt", item.get("question", "")),
                            response=item.get("response", item.get("hallucinated_answer", "")),
                            ground_truth_label=int(item.get("label", 1)),
                            domain=item.get("domain", "general"),
                            reference_evidence=item.get("evidence", item.get("knowledge", [])),
                        )
                    )
            return cases

        # Default to built-in curated split
        for item in CURATED_HALUEVAL_SAMPLES[:limit]:
            cases.append(
                BenchmarkCase(
                    case_id=item["id"],
                    prompt=item["prompt"],
                    response=item["response"],
                    ground_truth_label=item["label"],
                    domain=item["domain"],
                    reference_evidence=item["evidence"],
                )
            )

        return cases
