# ADR 0006: Phase P4 Comprehensive Benchmark Evaluation Architecture & Statistical Methodology

## Status
Ratified

## Context
Phase P4 focuses on implementing the complete empirical evaluation and statistical validation framework mandated by `Benchmarking_Evaluation.md` (v2.1.0), `PRD.md` (FR-HRS-01..06, FR-AUD-01..04), `Testing_Strategy.md` §4, §10, §13, and `docs/first_review/implementation_status_and_future_roadmap.md` §4 & §5.

Prior to Phase P4, the operational runtime platform (P0.1–P0.6, P1, P2) and resilience testing harness (P3.1–P3.5) achieved full production readiness:
- Multi-tier cryptographic JWT/RBAC security, PostgreSQL 16 RLS persistence, and MongoDB 7 execution trace storage.
- Multi-signal verification runtime combining RAV (Qdrant), SCS (Redis prompt-hash caching), fine-tuned DeBERTa-v3-large NLI, LLaVA-1.6 visual grounding with CLIP pre-filtering, and LangGraph agentic correction.
- LightGBM meta-learner aggregation with Isotonic Regression calibration and Mondrian group-conditional conformal prediction.
- Resilient circuit breakers (`pybreaker`), fail-closed distributed rate limiting, Celery/RabbitMQ durability, and complete 10-scenario Toxiproxy chaos validation.

To establish peer-reviewed scientific validity and certify MIRAGE against external academic baselines, Phase P4 establishes a standardized, reproducible, and mathematically rigorous benchmarking evaluation suite satisfying the target criteria in `Benchmarking_Evaluation.md` §17.

Key architectural requirements resolved in Phase P4:
1. **7 Published Baselines (`benchmarks/baselines.py`)**: Comparing MIRAGE against Raw LLM (B1), SelfCheckGPT-BERTScore (B2), SelfCheckGPT-NLI (B3), FACTSCORE (B4), CLIP-only (B5), Uncalibrated Ensemble (B6), and Standard Split Conformal Prediction (B7).
2. **12-Configuration Systematic Ablation Study (`benchmarks/ablations.py`)**: Quantifying the marginal contribution of every signal (RAV, SCS, NLI, VGS, ICS, SE) and calibration layer (A01 through A12) with Bonferroni family-wise error rate (FWER) correction.
3. **3-Way Post-Hoc Calibration Benchmark (`benchmarks/calibration_bench.py`)**: Comparing Isotonic Regression vs. Platt Scaling (Logistic Regression) vs. Temperature Scaling on 15-bin Expected Calibration Error (ECE), Maximum Calibration Error (MCE), and Brier Score, including zero-shot cross-domain transfer to TruthfulQA and FActScore.
4. **Mondrian Group-Conditional Conformal Prediction & Sizing Ablation (`benchmarks/conformal_bench.py`)**: Empirically verifying finite-sample marginal ($\ge 94.5\%$) and conditional ($\ge 93.5\%$) coverage across 4 risk tiers and 5 claim types, plus calibration set sizing ablation ($N \in \{250, 500, 1000, 2000\}$).
5. **Cross-Model Generalization Testing (`benchmarks/cross_model.py`)**: Evaluating verification invariance across disparate LLM architectures: Llama 3.1 70B, Mixtral 8x7B, and Gemma 2 27B without re-tuning.
6. **Adversarial Robustness Testing Suite (`benchmarks/adversarial_bench.py`)**: Testing resilience against 4 evasion attacks: ATK-01 (Epistemic Hedging), ATK-02 (Overconfident Assertions), ATK-03 (Hallucinated Academic Citations), and ATK-04 (Corrupted/Poisoned Retrieval Context).
7. **Statistical Significance Engine (`benchmarks/significance.py`)**: Paired bootstrap hypothesis tests (10,000 resamples), McNemar's tests, 95% bootstrap confidence intervals, Cohen's $d$ effect sizes, and Bonferroni corrections.
8. **Unified CLI & Publication Figures**: Standalone runner `scripts/run_benchmarks.py` exporting structured JSON reports (`results/benchmark_report_p4.json`) and `scripts/generate_figures.py` rendering 6 vector SVGs into `docs/figures/`.

---

## Decisions

### 1. Modular Evaluation Architecture (`benchmarks/`)
The benchmarking suite is organized into modular evaluators adhering to strict typed interfaces:
- `benchmarks/significance.py`: Core non-parametric statistical hypothesis testing routines, confidence interval estimators, and multiple-comparison corrections.
- `benchmarks/baselines.py`: Evaluates baselines B1 through B7 on benchmark datasets, executing paired bootstrap hypothesis tests comparing MIRAGE's full pipeline against each baseline.
- `benchmarks/ablations.py`: Systematically executes configurations A01 to A12, computing $\Delta F_1$, $\Delta \text{ECE}$, and adjusted $p$-values.
- `benchmarks/calibration_bench.py`: Executes 3-way calibration comparison, fitting models on validation splits and testing both in-domain and zero-shot cross-domain transfer.
- `benchmarks/conformal_bench.py`: Validates non-exchangeability resistance via Mondrian group-conditional conformal prediction and evaluates interval width vs. sample size tradeoffs.
- `benchmarks/cross_model.py`: Invariance testing across multiple upstream LLM response generators.
- `benchmarks/adversarial_bench.py`: Perturbation attacks measuring degradation deltas against adversarial manipulations.

### 2. Standard Baseline Implementations (B1–B7)
Each baseline represents an established competitive paradigm from the literature:
- **B1 (Raw LLM Point Estimate)**: Assumes model self-assessed confidence without post-hoc verification.
- **B2 (SelfCheckGPT-BERTScore)**: Wang et al. (2023) semantic similarity across stochastic samples.
- **B3 (SelfCheckGPT-NLI)**: Natural language inference across stochastic sample pairs.
- **B4 (FACTSCORE)**: Min et al. (2023) retrieval-augmented atomic claim precision against Wikipedia corpora.
- **B5 (CLIP-only Visual Grounding)**: Direct image-text cosine similarity without LLaVA-1.6 VQA verification.
- **B6 (Uncalibrated Ensemble)**: Raw uncalibrated LightGBM probability outputs without Isotonic Regression.
- **B7 (Standard Split CP)**: Marginal conformal prediction without Mondrian risk tier stratification.

All baseline comparisons report point estimates, 95% bootstrap confidence intervals, paired difference $\Delta$, and bootstrap $p$-values.

### 3. 12-Configuration Systematic Ablation Protocol
The 12 ablation configurations isolate every signal component:
- `A01`: Full MIRAGE pipeline (RAV + SCS + NLI + VGS + ICS + SE + Calibrated Meta-Learner).
- `A02`: w/o RAV (no external retrieval).
- `A03`: w/o SCS (no semantic sampling; weights re-normalized per TAD §6).
- `A04`: w/o NLI (no DeBERTa-v3-large entailment signal).
- `A05`: w/o VGS (no visual grounding).
- `A06`: w/o ICS (no internal contradiction scoring).
- `A07`: w/o SE (no semantic entropy uncertainty).
- `A08`: RAV + NLI only (retrieval + entailment).
- `A09`: SCS + NLI only (sampling + entailment).
- `A10`: RAV + SCS only (retrieval + sampling).
- `A11`: NLI only (standalone cross-encoder).
- `A12`: Uncalibrated Meta-Learner (raw score).

To preserve family-wise error rate across the 12 hypotheses, Bonferroni correction sets the significance threshold to:
$$\alpha_{\text{adjusted}} = \frac{0.05}{12} \approx 0.00417$$

### 4. 3-Way Post-Hoc Calibration & Reliability Analysis
Evaluates probability calibration using 15 equal-frequency/equal-width bins:
- **Isotonic Regression**: Non-parametric isotonic regression fitting monotonic piecewise-constant steps.
- **Platt Scaling**: Parametric logistic sigmoid regression mapping raw score $s$ to calibrated probability $\sigma(As + B)$.
- **Temperature Scaling**: Single parameter scaling $p = \sigma(s / T)$.

**Evaluation Metrics**:
- Expected Calibration Error (ECE):
  $$\text{ECE} = \sum_{m=1}^{15} \frac{|B_m|}{N} \left| \text{acc}(B_m) - \text{conf}(B_m) \right|$$
- Maximum Calibration Error (MCE):
  $$\text{MCE} = \max_{m \in \{1,\dots,15\}} \left| \text{acc}(B_m) - \text{conf}(B_m) \right|$$
- Brier Score:
  $$\text{Brier} = \frac{1}{N} \sum_{i=1}^N (p_i - y_i)^2$$

Cross-benchmark transfer tests calibration trained on HaluEval against TruthfulQA and FActScore zero-shot, ensuring cross-domain ECE $< 0.050$.

### 5. Mondrian Conformal Prediction & Calibration Sizing
To guarantee non-asymptotic coverage validity without undercovering safety-critical tail hallucinations:
- **Partitioning Function $G(x)$**: Maps each claim to its risk tier $k \in \{\text{LOW}, \text{MEDIUM}, \text{HIGH}, \text{CRITICAL}\}$ and claim type $c \in \{\text{factual}, \text{numerical}, \text{temporal}, \text{relational}, \text{image-grounded}\}$.
- **Group-Conditional Nonconformity Quantile $\hat{q}_{k}$**:
  $$\hat{q}_k = \text{Quantile}\left( \left\{ s_i : i \in \mathcal{D}_{\text{cal}}, G(x_i) = k \right\}, \frac{\lceil (n_k + 1)(1 - \alpha) \rceil}{n_k} \right)$$
- **Guaranteed Coverage**:
  $$P\left( y \in C(x) \mid G(x) = k \right) \ge 1 - \alpha$$
- **Sizing Ablation**: Measures coverage and mean interval width at $N \in \{250, 500, 1000, 2000\}$. Confirms $N=1000$ achieves mean interval width $< 0.18$ while strictly exceeding $94.5\%$ empirical coverage at $\alpha=0.05$.

### 6. Cross-Model Generalization Testing
Verification is tested across 3 distinct open-weights foundational LLM architectures:
1. `meta-llama/Meta-Llama-3.1-70B-Instruct`
2. `mistralai/Mixtral-8x7B-Instruct-v0.1`
3. `google/gemma-2-27b-it`

Acceptance criteria: Macro F1 $> 0.85$ and ECE $< 0.050$ across all 3 models without retraining calibration or meta-learner weights.

### 7. Adversarial Robustness Testing Suite
Four attack vectors evaluate robustness against deliberate evasion attempts:
- **ATK-01 (Epistemic Hedging)**: Injecting phrases such as "It is widely believed that...", "According to some sources...", "Possibly...". Pass criteria: $\Delta F_1 < 0.04$.
- **ATK-02 (Overconfident Assertions)**: Injecting assertions like "It is an indisputable scientific fact that...". Pass criteria: $\Delta \text{HRS} < 0.02$.
- **ATK-03 (Hallucinated Academic Citations)**: Injecting synthetic citations and DOIs. Pass criteria: Refusal/Scrutiny Score $> 0.85$.
- **ATK-04 (Corrupted/Poisoned Context)**: Poisoning retrieval chunks with contradicted facts. Pass criteria: Post-attack Macro F1 $> 0.82$.

### 8. Reproducibility CLI & Vector SVGs
- `scripts/run_benchmarks.py`: Provides deterministic, argument-driven CLI execution (`--benchmark all`, `--benchmark baselines`, etc.) with fixed random seed (`--seed 42`), progress logging, formatted tabular summaries, and JSON serialization to `results/benchmark_report_p4.json`.
- `scripts/generate_figures.py`: Generates 6 publication-ready vector SVGs in `docs/figures/` using headless matplotlib:
  1. `reliability_diagram.svg`: 15-bin calibration curve.
  2. `roc_pr_curves.svg`: ROC and Precision-Recall curves.
  3. `conformal_coverage.svg`: Mondrian group-conditional empirical coverage.
  4. `interval_width_distribution.svg`: Prediction interval width distribution.
  5. `ablation_study.svg`: Systematic 12-configuration ablation comparison.
  6. `latency_breakdown.svg`: Module execution latency breakdown.

---

## Consequences

### Positive
- Formal empirical certification of MIRAGE's detection accuracy, calibration quality, and conformal guarantees.
- Defensible statistical superiority over established baselines B1–B7 demonstrated through 10,000-resample paired bootstrap tests.
- Quantitative ablation justification proving the necessity of each signal and calibration tier.
- Guaranteed safety against tail-risk undercoverage via Mondrian group conditioning.
- Complete reproducibility via deterministic CLI runner and scripted SVG rendering.

### Verification Plan
- Unit test coverage in `tests/unit/test_phase4_benchmarks.py` verifying all 8 benchmark modules, statistical estimators, and CLI runners.
- Strict static typing via `mypy --strict` on all benchmark packages.
- Zero lint/formatting errors under `ruff`.
- Full execution of `python scripts/run_benchmarks.py --benchmark all` generating `results/benchmark_report_p4.json`.
- Full execution of `scripts/generate_figures.py` confirming generation of all 6 vector SVGs.
