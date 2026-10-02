"""Authoritative machine-readable execution manifest for MIRAGE Phase P4 Tier 2 Academic Evaluation.

Specifies every experiment required for full scientific certification:
1. Four Literature Academic Corpora:
   - HaluEval (N=10,000; Li et al., EMNLP 2023)
   - TruthfulQA (N=817; Lin et al., ACL 2022)
   - FActScore (N=183 biographies / ~3,200 atomic facts; Min et al., EMNLP 2023)
   - MMHAL-Bench (N=96 multimodal queries; Sun et al., CVPR 2024)
2. Comparative Baselines B1 to B7 (7 published baselines / qualified heuristic proxies)
3. 12-Configuration Systematic Signal Ablation Study A01 to A12 (Bonferroni-corrected)
4. Three-Way Calibration & Cross-Domain Transfer (Isotonic, Platt, Temperature)
5. Group-Conditional Mondrian Conformal Prediction & Sizing Ablation (N_cal in {250,500,1000,2000}, N_test >= 1000)
6. Cross-Model Generalization with Live Generator Inference (Llama-3-70B, Mixtral-8x7B, Gemma-2-27B)
7. Adversarial Robustness ATK-01 to ATK-04 with Decoupled Metric-Sensitivity Classification
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


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
        split="dialogue (5,000) + qa (5,000)",
        deterministic_seed=42,
        calibration_count=1000,
        test_count=9000,
        model_checkpoint="microsoft/deberta-v3-large + google/flan-t5-base",
        provider_runtime="PyTorch / TorchServe / Local GPU execution",
        generation_parameters={"temperature": 0.0, "max_tokens": 512, "top_p": 1.0},
        benchmark_metric="Macro F1, AUROC, ECE",
        acceptance_threshold="Macro F1 >= 0.88, AUROC >= 0.90, ECE <= 0.05",
        statistical_test="Paired bootstrap test (10,000 iterations)",
        confidence_interval_method="BCa bootstrap 95% confidence intervals",
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
        split="generation (817 questions spanning 38 categories)",
        deterministic_seed=42,
        calibration_count=0,
        test_count=817,
        model_checkpoint="microsoft/deberta-v3-large + sentence-transformers/all-mpnet-base-v2",
        provider_runtime="Local GPU / Qdrant Knowledge Base",
        generation_parameters={"temperature": 0.0, "max_tokens": 256},
        benchmark_metric="Macro F1, Truthfulness %",
        acceptance_threshold="Macro F1 >= 0.85, Transfer ECE <= 0.08",
        statistical_test="Paired bootstrap test (10,000 iterations)",
        confidence_interval_method="BCa bootstrap 95% confidence intervals",
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
        split="183 Wikipedia person biographies (~3,200 atomic facts)",
        deterministic_seed=42,
        calibration_count=0,
        test_count=183,
        model_checkpoint="google/flan-t5-base (atomic claim decomposition) + deberta-v3-large (verification)",
        provider_runtime="Local CPU/GPU pipeline",
        generation_parameters={"temperature": 0.0, "max_tokens": 512},
        benchmark_metric="Atomic Fact Precision (FActScore %), Macro F1",
        acceptance_threshold="Atomic F1 >= 0.86, Precision >= 80.0%",
        statistical_test="Paired bootstrap test (10,000 iterations)",
        confidence_interval_method="BCa bootstrap 95% confidence intervals",
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
        model_checkpoint="openai/clip-vit-base-patch32 (pre-filter) + llava-hf/llava-1.5-7b-hf (4-bit quant / TGI)",
        provider_runtime="Local GPU / TGI container",
        generation_parameters={"temperature": 0.0, "max_tokens": 128},
        benchmark_metric="Visual Grounding Macro F1, VGS Accuracy",
        acceptance_threshold="VGS Macro F1 >= 0.82, Image Hallucination Detection Rate >= 85.0%",
        statistical_test="Exact McNemar test",
        confidence_interval_method="Wilson score interval 95%",
        required_hardware=(
            "Local NVIDIA GeForce RTX 3050 6GB Laptop GPU (4-bit quantized LLaVA / CLIP pre-filter) or AWS G5.2xlarge"
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
            "B1 (Raw LLM), B2 (SelfCheckGPT Proxy), B3 (AlignScore Proxy), "
            "B4 (FACTSCORE Proxy), B5 (SummaC Proxy), B6 (CLIP Grounding), B7 (Uncalibrated Ensemble)"
        ),
        provider_runtime="MIRAGE Baseline Evaluator",
        generation_parameters={"temperature": 0.0},
        benchmark_metric="Macro F1 Superiority over all baselines",
        acceptance_threshold="Statistically significant superiority (p < 0.001) over all B1-B7 baselines",
        statistical_test="Paired bootstrap test (10,000 resamples)",
        confidence_interval_method="Percentile bootstrap 95% CI",
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
        model_checkpoint="A01 to A12 signal configurations",
        provider_runtime="MIRAGE Verification Engine",
        generation_parameters={"temperature": 0.0},
        benchmark_metric="Macro F1 difference, Cohen's d, Bonferroni-corrected p-value",
        acceptance_threshold=(
            "Full pipeline A01 significantly superior to all sub-ensembles at alpha = 0.05 / 12 = 0.00417"
        ),
        statistical_test="Paired bootstrap test with Bonferroni correction",
        confidence_interval_method="Bonferroni-adjusted bootstrap 99.58% CI",
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
        split="Fitting: HaluEval N_cal=1,000. Evaluation: TruthfulQA N=817 and FActScore N=183",
        deterministic_seed=42,
        calibration_count=1000,
        test_count=1000,
        model_checkpoint="Isotonic Regression, Platt Scaling, Temperature Scaling",
        provider_runtime="Scikit-Learn / SciPy",
        generation_parameters={"n_bins": 15},
        benchmark_metric="ECE (Expected Calibration Error), MCE (Max Calibration Error), Brier Score",
        acceptance_threshold=(
            "Post-calibration ECE <= 0.05 on HaluEval held-out; Transfer ECE <= 0.08 on TruthfulQA and FActScore"
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
        benchmark_metric="Empirical Coverage % (target 95%), Mean Interval Width",
        acceptance_threshold=("Empirical coverage >= 94.0% at alpha=0.05; Mean interval width <= 0.20 at N_cal=1000"),
        statistical_test="Binomial exact test for marginal coverage validity",
        confidence_interval_method="Clopper-Pearson exact confidence interval",
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
            "meta-llama/Meta-Llama-3-70B-Instruct, mistralai/Mixtral-8x7B-Instruct-v0.1, google/gemma-2-27b-it"
        ),
        provider_runtime=(
            "Hugging Face Dedicated Endpoints / Groq Cloud API / vLLM "
            "+ Local NVIDIA GeForce RTX 3050 6GB Laptop GPU for verifier pipeline"
        ),
        generation_parameters={"temperature": 0.7, "max_tokens": 512, "top_p": 0.9},
        benchmark_metric="Zero-shot transfer Macro F1, AUROC, ECE across generator families",
        acceptance_threshold="Macro F1 >= 0.85 across all three live model families",
        statistical_test="ANOVA across model families + pairwise Tukey HSD",
        confidence_interval_method="Bootstrap 95% CI",
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
        benchmark_metric="Attack Detection Rate %, F1 Under Attack, Scrutiny Score",
        acceptance_threshold=(
            "Detection Rate >= 80.0% for ATK-01, ATK-02, ATK-04; ATK-03 classified as metric sensitivity"
        ),
        statistical_test="Fisher's exact test vs clean baseline",
        confidence_interval_method="Wilson score interval 95%",
        required_hardware="NVIDIA GeForce RTX 3050 6GB Laptop GPU",
        expected_artifact_path="results/tier2/adversarial_evaluation.json",
        certification_gate_dependency="adversarial_decoupling",
    ),
]


def build_manifest_payload() -> dict[str, Any]:
    """Build canonical structured dictionary of the Tier 2 execution manifest."""
    experiments = [e.to_dict() for e in TIER_2_EXPERIMENTS]
    manifest_body = {
        "manifest_version": "2.1.0-tier2-readiness",
        "protocol_status": "FROZEN",
        "governing_adr": "ADR 0006: Phase P4 Comprehensive Benchmark Evaluation",
        "total_experiments": len(experiments),
        "target_academic_corpora": {
            "HaluEval": {"native_samples": 10000, "split": "dialogue + qa"},
            "TruthfulQA": {"native_samples": 817, "split": "generation"},
            "FActScore": {"native_samples": 183, "atomic_facts": "~3200"},
            "MMHAL-Bench": {"native_samples": 96, "split": "multimodal query-image"},
        },
        "target_live_generator_models": [
            "meta-llama/Meta-Llama-3-70B-Instruct",
            "mistralai/Mixtral-8x7B-Instruct-v0.1",
            "google/gemma-2-27b-it",
        ],
        "hardware_environment": {
            "local_gpu": "NVIDIA GeForce RTX 3050 6GB Laptop GPU",
            "local_vram_mb": 6144,
            "role_local_gpu": "Local execution of DeBERTa-v3-large, CLIP, FLAN-T5-base verifier models",
            "role_remote_api": "Remote API endpoints for 70B generator models (Llama-3-70B, Mixtral-8x7B)",
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
