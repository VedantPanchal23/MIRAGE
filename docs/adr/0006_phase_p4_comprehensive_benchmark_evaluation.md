# ADR 0006: Phase P4 Comprehensive Benchmark Evaluation Architecture & Statistical Methodology

## Status
Ratified (Tier 1 Harness Verified / Machine-Checkable Certification Guard Active / Tier 2 Protocol Frozen / Full Academic Corpus Pending)

## Context
Phase P4 focuses on implementing the complete empirical evaluation and statistical validation framework mandated by `Benchmarking_Evaluation.md` (v2.1.0), `PRD.md` (FR-HRS-01..06, FR-AUD-01..04), `Testing_Strategy.md` §4, §10, §13, and `docs/first_review/implementation_status_and_future_roadmap.md` §4 & §5.

Prior to Phase P4, the operational runtime platform (P0.1–P0.6, P1, P2) and resilience testing harness (P3.1–P3.5) achieved full production readiness:
- Multi-tier cryptographic JWT/RBAC security, PostgreSQL 16 RLS persistence, and MongoDB 7 execution trace storage.
- Multi-signal verification runtime combining RAV (Qdrant), SCS (Redis prompt-hash caching), fine-tuned DeBERTa-v3-large NLI, LLaVA-1.6 visual grounding with CLIP-large pre-filtering, and LangGraph agentic correction.
- LightGBM meta-learner aggregation with Isotonic Regression calibration and Mondrian group-conditional conformal prediction.
- Resilient circuit breakers (`pybreaker`), fail-closed distributed rate limiting, Celery/RabbitMQ durability, and complete 10-scenario Toxiproxy chaos validation.

To establish scientific validity while maintaining rigorous honesty regarding experimental reality, Phase P4 establishes an auditable, reproducible, and mathematically grounded benchmarking evaluation suite.

---

## Decisions

### 1. Two-Tier Evaluation Architecture & Machine-Checkable Certification Guard
To eliminate scientific over-claiming while ensuring reproducible automated validation, Phase P4 establishes an auditable two-tier architecture governed by an automated `BenchmarkCertificationGuard`:

- **Tier 1: Curated Demonstration Suite ($N=30$)**:
  - **Purpose**: Functional verification of the full MIRAGE pipeline (`VerificationOrchestrator`), end-to-end database transactions, RLS enforcement, audit hashing, and testing of evaluation math.
  - **Composition**: 10 HaluEval cases, 8 TruthfulQA cases, 4 FActScore cases, 8 MMHAL-Bench cases.
  - **Baselines**: Literature baseline methods are implemented as **explicit heuristic proxies** (B2–B5) and architectural variants (B6–B7).
  - **Cross-Model**: Evaluated via **controlled stylistic perturbation simulation**.
  - **Status**: **Fully Implemented and Verified in CI/Automated Testing** (`TIER_1_HARNESS_COMPLETE`).
  - **Limitation**: Sample size $N=30$ is intentionally insufficient for asymptotic statistical bounds ($\ge 94\%$ finite-sample coverage guarantees at $\alpha=0.05$ require $N \ge 1,000$).
  - **Certification**: Explicitly blocked from emitting `CERTIFIED` status.

- **Tier 2: Full Academic Corpus Execution ($N \ge 1,000$)**:
  - **Purpose**: Large-scale empirical evaluation on full academic corpora matching literature specifications.
  - **Native Requirements**: HaluEval (10,000 instances), TruthfulQA (817 instances), FActScore (183 instances / 3,200 atomic facts), MMHAL-Bench (96 instances).
  - **Prerequisites**: External batch downloads, GPU cluster allocation for full DeBERTa/LLaVA batch inference, live LLM API token generation across model families.
  - **Status**: **Pending Full-Scale Academic Corpus Execution** (`TIER_2_ACADEMIC_CERTIFIED`).

- **Automated Certification Guard (`BenchmarkCertificationGuard`)**:
  - Automatically evaluates every report payload against 7 machine-checkable gates:
    1. `no_fixture_datasets`: All datasets must be `external_academic_corpus`.
    2. `native_sample_size_adequacy`: Must meet native corpus size thresholds (HaluEval: 10,000; TruthfulQA: 817; FActScore: 183; MMHAL: 96).
    3. `calibration_separation`: Evaluated on held-out split; rejects `methodology_smoke_test_only` and fitting leakage.
    4. `live_generator_execution`: Enforces exact model identities (`meta-llama/Meta-Llama-3.1-70B-Instruct`, `mistralai/Mixtral-8x7B-Instruct-v0.1`, `google/gemma-2-27b-it`), requires `model_identity_confirmed=True`, and fails closed on simulation.
    5. `baseline_qualification`: B2–B5 must have explicit `Heuristic Proxy` fidelity and naming.
    6. `adversarial_decoupling`: ATK-03 must acknowledge metric-sensitivity coupling and report uncertified empirical robustness.
    7. `complete_suite_execution`: All benchmark suites must run fully without omissions.

### 2. Baseline Comparison Implementations & Scientific Fidelity (B1–B7)
To ensure academic honesty, baseline comparisons are explicitly categorized by implementation fidelity:

| Baseline ID | Name | Implementation Fidelity | Reference / Literature Citation | Notes / Deviations |
|-------------|------|------------------------|--------------------------------|-------------------|
| **B1** | Raw LLM Output | Baseline Prior | Empirical Prior | Uncalibrated generation prior without verification |
| **B2** | SelfCheckGPT (BERTScore) Heuristic Proxy | Heuristic Proxy | Wang et al. (EMNLP 2023) | Jaccard token overlap heuristic proxy across prompt/response |
| **B3** | SelfCheckGPT (NLI) Heuristic Proxy | Heuristic Proxy | Wang et al. (EMNLP 2023) | Consistency score simulation without live multi-sample LLM calls |
| **B4** | FACTSCORE Heuristic Proxy | Heuristic Proxy | Min et al. (EMNLP 2023) | Word-level token overlap heuristic against provided evidence |
| **B5** | CLIP-only Visual Grounding Heuristic Proxy | Heuristic Proxy | Radford et al. (ICML 2021) | Image-text similarity proxy without fine-grained VQA grounding |
| **B6** | Uncalibrated Meta-Learner | Architectural Ablation | MIRAGE Meta-Learner | Raw LightGBM ensemble without post-hoc Isotonic Regression |
| **B7** | Standard Split CP | Methodological Variant | Vovk (2005) / Angelopoulos (2021) | Marginal split conformal prediction without Mondrian conditioning |

### 3. 12-Configuration Systematic Ablation Protocol & Hypothesis Family
The 12 ablation configurations isolate every signal component:
- `A01`: RAV only (retrieval evidence alone).
- `A02`: SCS only (generation variance alone).
- `A03`: NLI only (cross-encoder entailment alone).
- `A04`: VGS only (multimodal visual grounding alone).
- `A05`: ICS only (internal contradiction scoring alone).
- `A06`: RAV + NLI (traditional RAG fact-checking baseline).
- `A07`: RAV + SCS (retrieval + sampling).
- `A08`: SCS + NLI (retrieval-free multi-signal verification).
- `A09`: RAV + SCS + NLI (baseline 3-signal text pipeline).
- `A10`: RAV + SCS + NLI + ICS (linear combination with internal consistency).
- `A11`: RAV + SCS + NLI + ICS (non-linear LightGBM GBDT).
- `A12`: Full Pipeline (All 5 Signals: RAV + SCS + NLI + ICS + VGS, LightGBM + Isotonic Calibration).

The formal hypothesis family consists of $K=11$ pairwise one-sided comparisons between the Full Pipeline (`A12`) and each ablated sub-configuration (`A01` through `A11`). Under Bonferroni multiple comparison correction, the family-wise error rate significance threshold is:
$$\alpha_{\text{corrected}} = \frac{0.05}{11} \approx 0.004545$$

### 4. 3-Way Post-Hoc Calibration & Data Separation
Evaluates probability calibration using 15 equal-width bins across Isotonic Regression, Platt Scaling, and Temperature Scaling:
- **Strict Data Separation**: Calibrator fitting data and evaluation data are strictly disjoint. In Tier 1 demonstration runs, the evaluation split is small ($N=5$) and explicitly labeled `methodology_smoke_test_only` to prevent training-error leakage from being reported as generalization.
- **Cross-Domain Transfer**: Zero-shot transfer from HaluEval ($N_{\text{cal}} = 1,000$) to TruthfulQA ($N=817$) and FActScore ($N=183$) tests distributional stability against the governing threshold ($ECE < 0.050$).

### 5. Mondrian Conformal Prediction & Calibration Sizing Semantics
To evaluate non-asymptotic coverage validity without undercovering safety-critical tail hallucinations:
- **Group-Conditional Nonconformity Quantile $\hat{q}_{k}$**:
  $$\hat{q}_k = \text{Quantile}\left( \left\{ s_i : i \in \mathcal{D}_{\text{cal}}, G(x_i) = k \right\}, \frac{\lceil (n_k + 1)(1 - \alpha) \rceil}{n_k} \right)$$
- **Disjoint Sizing Semantics**: Tracks `synthetic_calibration_resample_size` ($N_{\text{cal}} \in \{250, 500, 1000, 2000\}$) independently from `held_out_test_sample_count` ($N_{\text{test}}$). Labeled as `methodology_algorithm_test` to prevent resampled $N$ from being reported as actual corpus sample count.

### 6. Cross-Model Evaluation Reality & Generator Checkpoints
Completions evaluated across 3 distinct, open-weights LLM generator architectures per PRD §4:
1. `meta-llama/Meta-Llama-3.1-70B-Instruct` (Dense Decoder-only, 128k context)
2. `mistralai/Mixtral-8x7B-Instruct-v0.1` (Sparse Mixture-of-Experts with 8 experts, 32k context)
3. `google/gemma-2-27b-it` (Dense Decoder-only, 8k context)

Protocol: In Tier 1, evaluated via controlled stylistic perturbation simulation modeling generator variance. Live multi-turn generation from remote inference API endpoints (e.g. Groq, Together, Hugging Face Dedicated Endpoints) is designated for Tier 2, while the local RTX 3050 6GB GPU serves the MIRAGE verifier models (`microsoft/deberta-v3-large`, `openai/clip-vit-large-patch14`, `google/flan-t5-base`).

### 7. Adversarial Robustness Testing Suite
Four attack vectors evaluate robustness via programmatic algorithmic text transformations:
- **ATK-01 (Epistemic Hedging)**: Injecting epistemic hedges ("It is hypothesized and widely discussed that..."). Governing target: $\Delta F_1 < 0.04$.
- **ATK-02 (Overconfident Assertions)**: Injecting authoritative certainty ("It is an undisputed, universally accepted fact that..."). Governing target: $\Delta \text{HRS} < 0.02$.
- **ATK-03 (Hallucinated Academic Citations)**: Injecting fabricated studies and DOIs. Metric: Retrieval Scrutiny Score (Ungrounded Citation Risk). Classified as a **known metric-sensitivity harness test**, noting that lexical ungroundedness against reference evidence measures token absence rather than certifying adversarial robustness against deceptive retrieval poisoning.
- **ATK-04 (Corrupted/Poisoned Context)**: Poisoning retrieval chunks with contradicted facts. Governing target: Contradiction Detection $F_1 > 0.82$.

### 8. Reproducibility CLI & Vector SVGs
- `scripts/run_benchmarks.py`: Provides deterministic, argument-driven CLI execution (`--benchmark all`, `--seed 42`) with fixed random seed, logging, formatted tabular summaries, machine-checkable certification audit table, and JSON serialization to `results/benchmark_report_p4.json`.
- `scripts/generate_figures.py`: Generates 6 publication-ready vector SVGs in `docs/figures/`, with explicit "Heuristic Proxy" qualifiers on baseline curves.

### 9. Tier 2 Authoritative Execution Manifest & Preflight Integrity Engine
To prepare for large-scale external academic benchmark runs without risking premature certification, Phase P4 establishes an auditable manifest and fail-closed preflight engine:
- **Authoritative Execution Manifest (`benchmarks/manifest.py` & `benchmarks/tier2_manifest.json`)**:
  - Encodes all 10 Tier 2 experiment specifications across 19 literature-defined parameters matching governing Section 17 acceptance criteria:
    - HaluEval: Macro F1 > 0.85 (paired bootstrap $p < 0.01$), AUROC > 0.90, ECE < 0.035, Brier < 0.16.
    - TruthfulQA: Macro F1 > 0.80, Transfer ECE < 0.050.
    - FActScore: Atomic F1 > 0.82, Transfer ECE < 0.050.
    - MMHAL-Bench: VGS Accuracy > 0.78 (superior to CLIP baseline 0.64), using `llava-hf/llava-v1.6-mistral-7b-hf` + `openai/clip-vit-large-patch14`.
    - Conformal Prediction: Marginal coverage $\ge 94.5\%$, Mondrian conditional coverage $\ge 93.5\%$ across all 4 tiers, Mean interval width $< 0.18$ at $N_{\text{cal}} = 1,000$.
    - Cross-Model: Macro F1 > 0.85 across all three live generator model families.
    - Adversarial: ATK-01 $\Delta F_1 < 0.04$, ATK-02 $\Delta \text{HRS} < 0.02$, ATK-04 Contradiction F1 > 0.82, ATK-03 classified as metric-sensitivity harness test.
  - Seals the manifest with SHA-256 fingerprint (`status: FROZEN`).
- **Fail-Closed Preflight Validation Engine (`benchmarks/preflight.py`)**:
  - Executes comprehensive pre-inference verification before any Tier 2 evaluation can proceed:
    1. Dataset presence and fixture rejection across all 4 external corpora.
    2. Literature-native sample count verification (HaluEval: 10,000; TruthfulQA: 817; FActScore: 183; MMHAL: 96).
    3. Deep dataset schema, duplicate ID, and label domain $[0, 1]$ validation.
    4. Live generator API credential verification (rejecting simulation).
    5. Hardware runtime verification (detects NVIDIA GeForce RTX 3050 6GB Laptop GPU and verifies local verifier memory fit while noting remote inference requirement for 70B models).
    6. Calibration/test split disjointness ($S_{\text{cal}} \cap S_{\text{test}} = \emptyset$).
    7. Manifest SHA-256 immutability verification matching on-disk `benchmarks/tier2_manifest.json`.
    8. Clean/versioned output directory validation.
    9. Unambiguous Git commit provenance separating runtime execution HEAD from ratified protocol freeze SHA.
  - Automatically halts execution with exit code 1 and actionable diagnostics if any prerequisite is unmet (`scripts/run_benchmarks.py --tier 2` or `--preflight`).

---

## Consequences

### Positive
- Auditable scientific provenance clearly distinguishing Tier 1 demonstration suite from Tier 2 full-scale academic corpus runs.
- Elimination of ungrounded scientific claims, hardcoded arrays, and analytical approximations in favor of genuine empirical evaluation.
- Machine-checkable certification guard prevents automated benchmark runs from prematurely emitting `CERTIFIED`.
- Explicit documentation of baseline fidelities, simulation boundaries, and sample size constraints.
- Complete reproducibility via deterministic CLI runner and scripted SVG rendering.

### Limitations & Current Status
- Tier 1 provides functional and pipeline verification on $N=30$ cases with status `TIER_1_HARNESS_COMPLETE`.
- Academic certification against governing Section 17 criteria requires full-scale execution on academic corpora ($N \ge 1,000$), currently pending external cluster and API resources.
- Final Status: **P4 NOT APPROVED — Tier 1 harness complete; Tier 2 full academic-corpus execution pending**.
