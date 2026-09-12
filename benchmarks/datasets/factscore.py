"""FActScore benchmark dataset loader for entity-level biography factual precision.

Reference:
    Min et al., 'FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation', EMNLP 2023.
"""

import json
from pathlib import Path
from typing import Any

from benchmarks.evaluator import BenchmarkCase

CURATED_FACTSCORE_SAMPLES: list[dict[str, Any]] = [
    # Biography 1: Alan Turing - Factual
    {
        "id": "factscore_01_true",
        "domain": "biography",
        "prompt": "Write a brief biographical profile of Alan Turing.",
        "response": "Alan Turing was an English mathematician, computer scientist, and cryptanalyst who played a pivotal role in cracking intercepted coded messages at Bletchley Park during World War II.",
        "label": 0,
        "evidence": [
            "Alan Mathison Turing was an English mathematician, computer scientist, logician, cryptanalyst, philosopher, and theoretical biologist.",
            "Turing played a pivotal role in cracking intercepted coded messages during the Second World War at Bletchley Park.",
        ],
    },
    # Biography 1: Alan Turing - Hallucinated
    {
        "id": "factscore_01_false",
        "domain": "biography",
        "prompt": "Write a brief biographical profile of Alan Turing.",
        "response": "Alan Turing was a French physicist born in Lyon who won the Nobel Prize in Physics in 1952 for inventing the silicon transistor at Bell Labs.",
        "label": 1,
        "evidence": [
            "Alan Turing was born in London, England, and was a mathematician and cryptanalyst, not a French physicist.",
            "The point-contact transistor was invented at Bell Labs by John Bardeen, Walter Brattain, and William Shockley.",
        ],
    },
    # Biography 2: Marie Curie - Factual
    {
        "id": "factscore_02_true",
        "domain": "biography",
        "prompt": "Summarize the major achievements of Marie Curie.",
        "response": "Marie Curie was a Polish-French physicist and chemist who conducted pioneering research on radioactivity, becoming the first woman to win a Nobel Prize and the first person to win Nobel Prizes in two scientific fields.",
        "label": 0,
        "evidence": [
            "Marie Sklodowska Curie was a Polish and naturalized-French physicist and chemist who conducted pioneering research on radioactivity.",
            "She was the first woman to win a Nobel Prize, the first person to win a Nobel Prize twice, and the only person to win a Nobel Prize in two scientific fields (Physics 1903, Chemistry 1911).",
        ],
    },
    # Biography 2: Marie Curie - Hallucinated
    {
        "id": "factscore_02_false",
        "domain": "biography",
        "prompt": "Summarize the major achievements of Marie Curie.",
        "response": "Marie Curie was the first female President of the Royal Society of London and won the Fields Medal for her work on differential equations.",
        "label": 1,
        "evidence": [
            "Marie Curie was never President of the Royal Society of London, nor did she win the Fields Medal.",
            "Her Nobel prizes were in Physics and Chemistry for research in radioactivity and isolation of radium and polonium.",
        ],
    },
]


class FActScoreLoader:
    """Streams and loads FActScore biography evaluation cases."""

    def __init__(self, dataset_path: str | Path | None = None) -> None:
        self.dataset_path = Path(dataset_path) if dataset_path else None

    def load_cases(self, limit: int | None = None) -> list[BenchmarkCase]:
        """Load benchmark cases from curated sample or external file."""
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
                            case_id=item.get("id", f"factscore_{idx:04d}"),
                            prompt=item.get("prompt", item.get("topic", "")),
                            response=item.get("response", item.get("text", "")),
                            ground_truth_label=int(item.get("label", 0)),
                            domain="biography",
                            reference_evidence=item.get("evidence", item.get("facts", [])),
                        )
                    )
            return cases

        # Default to curated set
        for item in CURATED_FACTSCORE_SAMPLES[:limit]:
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
