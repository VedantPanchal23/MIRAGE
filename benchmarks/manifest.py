"""Authoritative machine-readable execution manifest for MIRAGE Phase P4 Tier 2 Academic Evaluation.

Specifies every experiment required for full scientific certification with strict adherence to
the governing acceptance criteria defined in Benchmarking_Evaluation.md §17 (v2.1.0) and
Technical_Architecture.md §4.

Governing Criteria Source:
- Benchmarking_Evaluation.md §17: "Target Benchmark Results Summary"
- Technical_Architecture.md §4: "VLM Serving: LLaVA-1.6 (llava-hf/llava-v1.6-mistral-7b-hf) with CLIP pre-filter"
- PRD.md §4: "Cross-Model Testing: Llama 3.1 70B, Mixtral 8x7B, Gemma 2 27B"
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MANIFEST_PROTOCOL_VERSION = "2.1.0-tier2-readiness"
MANIFEST_RATIFIED_COMMIT_SHA = "1177255dd2c7eeb392246858943a2c8802207d69"
MANIFEST_GOVERNING_SPECIFICATION = "Benchmarking_Evaluation.md §17 Table: Target Benchmark Results Summary"


@dataclass
class ExperimentManifestEntry:
    """Individual experiment specification within the Tier 2 execution manifest."""

    experiment_id: str
    benchmark_dataset: str
    dataset_version: str
    acquisition_source: str
    expected_native_sample_count: int
    actual_sample_count: int
    split: str
    deterministic_seed: int
    calibration_count: int
    test_count: int
    model_checkpoint: str
    provider_runtime: str
    generation_parameters: dict[str, Any]
    benchmark_metric: str
    acceptance_threshold: str
    statistical_test: str
    confidence_interval_method: str
    required_hardware: str
    expected_artifact_path: str
    certification_gate_dependency: str

    def to_dict(self) -> dict[str, Any]:
        """Convert entry to dictionary."""
        return asdict(self)


# Authoritative Tier 2 Experiment Specifications
TIER_2_EXPERIMENTS: list[ExperimentManifestEntry] = [
    ExperimentManifestEntry(
        experiment_id="EXP-HALUEVAL-CORE",
        benchmark_dataset="HaluEval",
        dataset_version="EMNLP 2023 (Li et al.)",
        acquisition_source="https://github.com/RUCAIBox/HaluEval / Hugging Face: pminervini/HaluEval",
        expected_native_sample_count=10000,
        actual_sample_count=0,
        split="dialogue (5,000) + qa (5,000); human/ChatGPT 50/50 balanced",
        deterministic_seed=42,
        calibration_count=1000,
        test_count=9000,
        model_checkpoint="microsoft/deberta-v3-large (verifier) + google/flan-t5-base (decomposer)",
        provider_runtime="PyTorch / TorchServe / Local GPU execution",
        generation_parameters={"temperature": 0.0, "max_tokens": 512, "top_p": 1.0},
        benchmark_metric="Macro F1, AUROC, ECE (15 bins), Brier Score",
        acceptance_threshold=(
            "Macro F1 > 0.85 (p < 0.01 vs baselines), AUROC > 0.90, ECE < 0.035, Brier < 0.16 "
            "[Benchmarking_Evaluation.md §17]"
        ),
        statistical_test="Paired bootstrap test (10,000 iterations)",
        confidence_interval_method="95% bootstrap confidence interval (BCa)",
        required_hardware="NVIDIA GeForce RTX 3050 6GB Laptop GPU (CUDA 12.0+) or AWS G5.2xlarge",
        expected_artifact_path="results/tier2/halueval_evaluation.json",
        certification_gate_dependency="no_fixture_datasets, native_sample_size_adequacy",
    ),
    ExperimentManifestEntry(
        experiment_id="EXP-TRUTHFULQA-CORE",
        benchmark_dataset="TruthfulQA",
        dataset_version="ACL 2022 (Lin et al.)",
        acquisition_source="https://github.com/sylin-c/TruthfulQA / Hugging Face: truthful_qa",
        expected_native_sample_count=817,
        actual_sample_count=0,
        split="generation (817 questions spanning 38 categories); zero-shot out-of-domain",
        deterministic_seed=42,
        calibration_count=0,
        test_count=817,
        model_checkpoint="microsoft/deberta-v3-large + sentence-transformers/all-mpnet-base-v2",
        provider_runtime="Local GPU / Qdrant Knowledge Base",
        generation_parameters={"temperature": 0.0, "max_tokens": 256},
        benchmark_metric="Macro F1, Transfer ECE (15 bins)",
        acceptance_threshold=(
            "Macro F1 > 0.80, Transfer ECE < 0.050 (out-of-domain zero-shot stability) [Benchmarking_Evaluation.md §17]"
        ),
        statistical_test="Paired bootstrap test (10,000 iterations)",
        confidence_interval_method="95% bootstrap confidence interval",
        required_hardware="NVIDIA GeForce RTX 3050 6GB Laptop GPU",
        expected_artifact_path="results/tier2/truthfulqa_evaluation.json",
        certification_gate_dependency="no_fixture_datasets, native_sample_size_adequacy, calibration_separation",
    ),
    ExperimentManifestEntry(
        experiment_id="EXP-FACTSCORE-CORE",
        benchmark_dataset="FActScore",
        dataset_version="EMNLP 2023 (Min et al.)",
        acquisition_source="https://github.com/shmsw25/FActScore / Hugging Face datasets",
        expected_native_sample_count=183,
        actual_sample_count=0,
        split="183 Wikipedia person biographies (~3,200 atomic facts); zero-shot out-of-domain",
        deterministic_seed=42,
        calibration_count=0,
        test_count=183,
        model_checkpoint=(
            "google/flan-t5-base (atomic fact extraction) + microsoft/deberta-v3-large (entailment verification)"
        ),
        provider_runtime="Local CPU/GPU pipeline",
        generation_parameters={"temperature": 0.0, "max_tokens": 512},
        benchmark_metric="Atomic Fact F1 / Precision@K, Transfer ECE (15 bins)",
        acceptance_threshold=(
            "Atomic F1 > 0.82, Transfer ECE < 0.050 (competitive with specialized entity baselines) "
            "[Benchmarking_Evaluation.md §17]"
        ),
        statistical_test="Paired bootstrap test (10,000 iterations)",
        confidence_interval_method="95% bootstrap confidence interval",
        required_hardware="NVIDIA GeForce RTX 3050 6GB Laptop GPU",
        expected_artifact_path="results/tier2/factscore_evaluation.json",
        certification_gate_dependency="no_fixture_datasets, native_sample_size_adequacy, calibration_separation",
    ),
    ExperimentManifestEntry(
        experiment_id="EXP-MMHAL-CORE",
        benchmark_dataset="MMHAL-Bench",
        dataset_version="CVPR 2024 / Sun et al. 2023",
        acquisition_source="https://github.com/Shengcao-Cao/MMHAL-Bench",
        expected_native_sample_count=96,
        actual_sample_count=0,
        split="96 challenging multimodal query-image pairs across 8 categories",
        deterministic_seed=42,
        calibration_count=0,
        test_count=96,
        model_checkpoint=(
            "llava-hf/llava-v1.6-mistral-7b-hf (4-bit bitsandbytes AWQ via TGI) "
            "+ openai/clip-vit-large-patch14 (pre-filter)"
        ),
        provider_runtime="Local GPU / TGI container",
        generation_parameters={"temperature": 0.0, "max_tokens": 128},
        benchmark_metric="Visual Grounding Score (VGS) Accuracy, Macro F1",
        acceptance_threshold=(
            "VGS Accuracy > 0.78 (superior to CLIP-only baseline 0.64) [Benchmarking_Evaluation.md §17]"
        ),
        statistical_test="McNemar's test with continuity correction (p < 0.01)",
        confidence_interval_method="Wilson score 95% confidence interval",
        required_hardware=(
            "Local NVIDIA GeForce RTX 3050 6GB Laptop GPU (4-bit quantized LLaVA-1.6 / CLIP pre-filter) "
            "or AWS G5.2xlarge"
        ),
        expected_artifact_path="results/tier2/mmhal_evaluation.json",
        certification_gate_dependency="no_fixture_datasets, native_sample_size_adequacy",
    ),
    ExperimentManifestEntry(
        experiment_id="EXP-BASELINES-COMP",
        benchmark_dataset="HaluEval",
        dataset_version="EMNLP 2023 (Li et al.)",
        acquisition_source="HaluEval external corpus (N=10,000)",
        expected_native_sample_count=10000,
        actual_sample_count=0,
        split="test split (N=9,000)",
        deterministic_seed=42,
        calibration_count=1000,
        test_count=9000,
        model_checkpoint=(
            "B1 (Raw LLM), B2 (SelfCheckGPT-BERTScore Proxy), B3 (SelfCheckGPT-NLI Proxy), "
            "B4 (FACTSCORE Proxy), B5 (SummaC Proxy), B6 (CLIP Grounding), B7 (Uncalibrated Meta-Learner)"
        ),
        provider_runtime="MIRAGE Baseline Evaluator",
        generation_parameters={"temperature": 0.0},
        benchmark_metric="Macro F1 Superiority over all B1-B7 baselines",
        acceptance_threshold=(
            "Statistically significant superiority (p < 0.01) over all B1-B7 baselines [Benchmarking_Evaluation.md §17]"
        ),
        statistical_test="Paired bootstrap test (10,000 resamples per baseline comparison)",
        confidence_interval_method="95% bootstrap confidence interval on delta F1",
        required_hardware="NVIDIA GeForce RTX 3050 6GB Laptop GPU",
        expected_artifact_path="results/tier2/baselines_comparison.json",
        certification_gate_dependency="baseline_qualification, native_sample_size_adequacy",
    ),
    ExperimentManifestEntry(
        experiment_id="EXP-ABLATIONS-12WAY",
        benchmark_dataset="HaluEval",
        dataset_version="EMNLP 2023 (Li et al.)",
        acquisition_source="HaluEval external corpus (N=10,000)",
        expected_native_sample_count=10000,
        actual_sample_count=0,
        split="test split (N=9,000)",
        deterministic_seed=42,
        calibration_count=1000,
        test_count=9000,
        model_checkpoint=(
            "12 systematic configurations: A01 to A11 (ablated sub-ensembles) vs A12 (Full Multi-Signal Pipeline)"
        ),
        provider_runtime="MIRAGE Verification Engine",
        generation_parameters={"temperature": 0.0},
        benchmark_metric="Macro F1 differences across 11 pairwise comparisons (A12 vs A01-A11), Cohen's d",
        acceptance_threshold=(
            "Full Pipeline (A12) significantly superior to all 11 ablated sub-configurations "
            "under Bonferroni correction (p_k < 0.00455, alpha = 0.05 / 11) "
            "[Benchmarking_Evaluation.md §13 & §17]"
        ),
        statistical_test=(
            "Paired bootstrap test (2,000 iterations per comparison) with Bonferroni multiple comparison "
            "correction (FWER alpha=0.05, K=11)"
        ),
        confidence_interval_method="Bonferroni-adjusted bootstrap 99.55% confidence intervals",
        required_hardware="NVIDIA GeForce RTX 3050 6GB Laptop GPU",
        expected_artifact_path="results/tier2/ablations_study.json",
        certification_gate_dependency="native_sample_size_adequacy",
    ),
    ExperimentManifestEntry(
        experiment_id="EXP-CALIBRATION-TRANSFER",
        benchmark_dataset="HaluEval (fitting) -> TruthfulQA & FActScore (transfer evaluation)",
        dataset_version="EMNLP 2023 / ACL 2022",
        acquisition_source="HaluEval + TruthfulQA + FActScore",
        expected_native_sample_count=10000,
        actual_sample_count=0,
        split="Fitting: HaluEval N_cal=1,000. Evaluation: TruthfulQA N=817 and FActScore N=183 (N_eval=1,000)",
        deterministic_seed=42,
        calibration_count=1000,
        test_count=1000,
        model_checkpoint="Isotonic Regression, Platt Scaling, Temperature Scaling",
        provider_runtime="Scikit-Learn / SciPy",
        generation_parameters={"n_bins": 15},
        benchmark_metric="ECE (15 equal-width bins), MCE, Brier Score",
        acceptance_threshold=(
            "Post-Isotonic ECE < 0.035 on HaluEval held-out; Transfer ECE < 0.050 on TruthfulQA and FActScore; "
            "Brier Score < 0.16 [Benchmarking_Evaluation.md §17]"
        ),
        statistical_test="Two-sample permutation test on calibration loss",
        confidence_interval_method="1,000 bootstrap resamples on 15-bin ECE",
        required_hardware="CPU / Local NVIDIA GPU",
        expected_artifact_path="results/tier2/calibration_benchmark.json",
        certification_gate_dependency="calibration_separation, native_sample_size_adequacy",
    ),
    ExperimentManifestEntry(
        experiment_id="EXP-CONFORMAL-SIZING",
        benchmark_dataset="HaluEval",
        dataset_version="EMNLP 2023 (Li et al.)",
        acquisition_source="HaluEval external corpus (N=10,000)",
        expected_native_sample_count=10000,
        actual_sample_count=0,
        split="Calibration subsets N_cal in {250, 500, 1000, 2000}; independent test split N_test=5,000",
        deterministic_seed=42,
        calibration_count=2000,
        test_count=5000,
        model_checkpoint="Group-conditional Mondrian conformal calibrator",
        provider_runtime="MIRAGE HRS Engine",
        generation_parameters={"confidence_level": 0.95},
        benchmark_metric="Marginal Empirical Coverage, Mondrian Conditional Coverage by Risk Tier, Mean Interval Width",
        acceptance_threshold=(
            "Marginal coverage >= 94.5% at alpha=0.05; Mondrian coverage >= 93.5% across all 4 risk tiers; "
            "Mean interval width < 0.18 at N_cal=1000 [Benchmarking_Evaluation.md §17]"
        ),
        statistical_test="Binomial exact test for marginal coverage validity",
        confidence_interval_method="Clopper-Pearson exact 95% confidence interval",
        required_hardware="CPU / Local NVIDIA GPU",
        expected_artifact_path="results/tier2/conformal_sizing.json",
        certification_gate_dependency="calibration_separation, native_sample_size_adequacy",
    ),
    ExperimentManifestEntry(
        experiment_id="EXP-CROSS-MODEL-LIVE",
        benchmark_dataset="HaluEval evaluation split (N=1,000)",
        dataset_version="EMNLP 2023 (Li et al.)",
        acquisition_source="Live model generation endpoints",
        expected_native_sample_count=1000,
        actual_sample_count=0,
        split="1,000 prompts evaluated across 3 live model checkpoints",
        deterministic_seed=42,
        calibration_count=200,
        test_count=800,
        model_checkpoint=(
            "meta-llama/Meta-Llama-3.1-70B-Instruct, mistralai/Mixtral-8x7B-Instruct-v0.1, google/gemma-2-27b-it"
        ),
        provider_runtime=(
            "Hugging Face Dedicated Endpoints / Groq Cloud API / vLLM "
            "+ Local NVIDIA GeForce RTX 3050 6GB Laptop GPU for verifier pipeline"
        ),
        generation_parameters={"temperature": 0.7, "max_tokens": 512, "top_p": 0.9},
        benchmark_metric="Zero-shot transfer Macro F1 across model architectures",
        acceptance_threshold=(
            "Macro F1 > 0.85 across all three live generator model families (performance invariance) "
            "[Benchmarking_Evaluation.md §17]"
        ),
        statistical_test="One-way ANOVA across model families + pairwise Tukey HSD post-hoc",
        confidence_interval_method="95% bootstrap confidence interval",
        required_hardware=("Remote Inference API / Endpoint for 70B models + Local RTX 3050 6GB for MIRAGE verifiers"),
        expected_artifact_path="results/tier2/cross_model_live.json",
        certification_gate_dependency="live_generator_execution",
    ),
    ExperimentManifestEntry(
        experiment_id="EXP-ADVERSARIAL-CORE",
        benchmark_dataset="HaluEval adversarial perturbations (ATK-01 to ATK-04)",
        dataset_version="EMNLP 2023 (Li et al.)",
        acquisition_source="Deterministic adversarial generator on HaluEval",
        expected_native_sample_count=4000,
        actual_sample_count=0,
        split="1,000 cases per attack vector (ATK-01, ATK-02, ATK-03, ATK-04)",
        deterministic_seed=42,
        calibration_count=0,
        test_count=4000,
        model_checkpoint="Full MIRAGE multi-signal pipeline",
        provider_runtime="Local GPU / Qdrant",
        generation_parameters={"perturbation_rate": 0.25},
        benchmark_metric=(
            "Delta F1 (Hedging), Delta HRS (Overconfident), Contradiction F1 (Poisoned Context), "
            "Retrieval Scrutiny Score (Citations)"
        ),
        acceptance_threshold=(
            "ATK-01 Delta F1 < 0.04; ATK-02 Delta HRS < 0.02; ATK-04 Contradiction F1 > 0.82; "
            "ATK-03 classified as known metric-sensitivity test [Benchmarking_Evaluation.md §17]"
        ),
        statistical_test="Fisher's exact test vs clean baseline for binary failure shifts",
        confidence_interval_method="Wilson score 95% confidence interval",
        required_hardware="NVIDIA GeForce RTX 3050 6GB Laptop GPU",
        expected_artifact_path="results/tier2/adversarial_evaluation.json",
        certification_gate_dependency="adversarial_decoupling",
    ),
]


def build_manifest_payload() -> dict[str, Any]:
    """Build canonical structured dictionary of the Tier 2 execution manifest."""
    experiments = [e.to_dict() for e in TIER_2_EXPERIMENTS]
    manifest_body = {
        "manifest_version": MANIFEST_PROTOCOL_VERSION,
        "protocol_status": "FROZEN",
        "governing_specification": MANIFEST_GOVERNING_SPECIFICATION,
        "ratified_commit_sha": MANIFEST_RATIFIED_COMMIT_SHA,
        "total_experiments": len(experiments),
        "target_academic_corpora": {
            "HaluEval": {"native_samples": 10000, "split": "dialogue (5k) + qa (5k)"},
            "TruthfulQA": {"native_samples": 817, "split": "generation (817 questions, 38 cats)"},
            "FActScore": {"native_samples": 183, "atomic_facts": "~3200 facts across 183 person bios"},
            "MMHAL-Bench": {"native_samples": 96, "split": "multimodal query-image (96 queries, 8 cats)"},
        },
        "target_live_generator_models": [
            "meta-llama/Meta-Llama-3.1-70B-Instruct",
            "mistralai/Mixtral-8x7B-Instruct-v0.1",
            "google/gemma-2-27b-it",
        ],
        "hardware_environment": {
            "local_gpu": "NVIDIA GeForce RTX 3050 6GB Laptop GPU",
            "local_vram_mb": 6144,
            "role_local_gpu": "Local execution of DeBERTa-v3-large, CLIP-large, FLAN-T5-base verifier models",
            "role_remote_api": "Remote API endpoints for 70B generator models (Llama-3.1-70B, Mixtral-8x7B)",
        },
        "experiments": experiments,
    }
    # Compute deterministic fingerprint
    serialized = json.dumps(manifest_body, sort_keys=True)
    manifest_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    manifest_body["manifest_sha256"] = manifest_hash
    return manifest_body


def export_tier2_manifest(output_path: str | Path = "benchmarks/tier2_manifest.json") -> Path:
    """Export the authoritative machine-readable manifest JSON file to disk."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_manifest_payload()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path
