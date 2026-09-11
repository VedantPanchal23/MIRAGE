# MIRAGE: Benchmarking & Evaluation Strategy

| Metadata | Details |
| :--- | :--- |
| **Version** | 2.1.0 |
| **Status** | Final |
| **Authors** | 23AIML042 Vedant, 23AIML076 Dax |
| **Institution** | IIIT Bangalore — CTRI-DG |
| **Date** | September 2026 |

---

## 1. Evaluation Philosophy

Rigorous benchmarking is the cornerstone of a factual consistency verification system. A hallucination detection middleware cannot simply provide binary "True/False" outputs; it must provide calibrated, reliable, and statistically sound metrics of its own performance. The evaluation philosophy for MIRAGE distinguishes strictly between **offline evaluation** (static benchmarks measuring accuracy, calibration, and latency under controlled conditions) and **online evaluation** (production monitoring of drift, throughput, and real-world cost). 

Reproducibility is treated as a first-class requirement. All benchmarks must be runnable with a single command, deterministic across identical hardware, and fully transparent regarding datasets, random seeds, and metric definitions.

## 2. Benchmark Datasets

MIRAGE utilizes a diverse set of academic benchmarks for training, calibration, and out-of-domain evaluation.

| Dataset | Source | Domain | Size | Use in MIRAGE | Preprocessing |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **HaluEval** | Li et al., 2023 | Dialogue, QA, Summarization | 30K (train) / 5K (val) / 5K (test) | Primary training and evaluation for DeBERTa-v3 and FLAN-T5. | Split into Train/Val/Test (60/20/20). 1000 val samples held out for conformal calibration. |
| **TruthfulQA** | Lin et al., 2021 | General Knowledge, Misconceptions | 817 questions | Out-of-domain calibration generalization evaluation. | Evaluated zero-shot to test calibration robustness against distribution shift. |
| **FActScore** | Min et al., 2023 | Biographies | 500 entity bios | Entity-level factual precision and retrieval evaluation. | Prompts are used to generate biographies, evaluated against Wikipedia dumps. |
| **MMHAL-Bench** | Sun et al., 2023 | Vision-Language, Multimodal | 96 image-text pairs | Multimodal hallucination evaluation (VGS module). | Extracted ground-truth descriptions for visual grounding comparison. |
| **MNLI** | Williams et al., 2018 | Multi-genre NLI | 392K (train) | General NLI pretraining signal for DeBERTa-v3-large. | Standard premise-hypothesis pairs converted to verification format. |

## 3. Evaluation Metrics

MIRAGE is evaluated across classification performance, calibration, uncertainty quantification, system latency, explainability fidelity, and task-specific module accuracy.

### 3.1 Classification Performance
* **Macro F1 Score**: The unweighted mean of F1 scores across Hallucination and Non-Hallucination classes. Used as the primary threshold-based accuracy metric:
  $$Precision = \frac{TP}{TP + FP}, \quad Recall = \frac{TP}{TP + FN}, \quad F_1 = \frac{2 \cdot Precision \cdot Recall}{Precision + Recall}$$
* **Area Under ROC Curve (AUROC)**: Evaluates ranking discrimination of the continuous HRS across all decision thresholds without relying on an arbitrary cutoff.
* **Area Under PR Curve (AUPRC)**: Particularly informative under class imbalance where hallucinated claims represent a minority fraction.

### 3.2 Calibration Metrics
* **Expected Calibration Error (ECE)**: Measures the weighted average discrepancy between model confidence and empirical accuracy across $M=15$ equal-width probability bins $B_m$:
  $$ECE = \sum_{m=1}^{15} \frac{|B_m|}{N} |\text{acc}(B_m) - \text{conf}(B_m)|$$
* **Maximum Calibration Error (MCE)**: Quantifies worst-case risk across bins:
  $$MCE = \max_{m \in \{1,\dots,15\}} |\text{acc}(B_m) - \text{conf}(B_m)|$$
* **Brier Score**: Measures mean squared error between calibrated probability and binary outcome: $\frac{1}{N} \sum_{i=1}^N (p_i - y_i)^2$.

### 3.3 Uncertainty Quantification (Conformal Prediction)
* **Marginal Empirical Coverage**: Proportion of test instances where ground truth falls within the predicted interval:
  $$\text{Coverage}_{\text{marginal}} = \frac{1}{N_{\text{test}}} \sum_{i=1}^{N_{\text{test}}} \mathbb{I}(y_i \in \hat{C}(x_i)) \ge 1 - \alpha$$
* **Mondrian (Group-Conditional) Coverage**: Empirical coverage evaluated independently within each subgroup $g \in \mathcal{G}$ (by risk tier and claim type):
  $$\text{Coverage}_g = \frac{1}{|\mathcal{D}_{\text{test}}^g|} \sum_{i \in \mathcal{D}_{\text{test}}^g} \mathbb{I}(y_i \in \hat{C}(x_i)) \ge 1 - \alpha, \quad \forall g \in \mathcal{G}$$
* **Mean Interval Width**: Average width of confidence intervals: $\frac{1}{N} \sum_{i=1}^N (\hat{C}_{\text{upper}}(x_i) - \hat{C}_{\text{lower}}(x_i))$. Smaller indicates higher certainty.

### 3.4 Signal & Module-Specific Metrics
* **Semantic Entropy ($SE$)**: Information-theoretic uncertainty across $K$ semantic clusters from $n=5$ samples:
  $$SE(x) = -\sum_{k=1}^K p(c_k) \log p(c_k), \quad p(c_k) = \frac{\text{count}(c_k)}{5}$$
* **Internal Consistency Score ($ICS$)**: Maximum contradiction probability across all claim pairs within the response:
  $$ICS_{\text{resp}} = \max_{i \neq j} P_{\text{contra}}(c_i, c_j)$$
* **Claim Extraction F1**: Token-level and entity-level precision/recall of the FLAN-T5 claim decomposer against gold human segmentations.
* **JSON Validity Rate**: Percentage of FLAN-T5 outputs parsing into valid schema without regex fallback.
* **Visual Grounding Score Accuracy**: Classification accuracy of LLaVA-1.6 VQA verdicts evaluated against MMHAL-Bench annotations.
* **TreeSHAP Attribution Fidelity**: Pearson correlation between estimated feature importance $\phi_j$ and observed model prediction shift when feature $j$ is masked.
* **Inter-Annotator Agreement (Cohen's $\kappa$)**:
  $$\kappa = \frac{p_o - p_e}{1 - p_e}$$
  where $p_o$ is observed agreement and $p_e$ is hypothetical chance agreement between evaluators.

---

## 4. Baseline Comparisons

To establish empirical rigor, MIRAGE is compared against 7 published baselines and architectural variants:

| # | Baseline | Signal Family | Description |
|---|---|---|---|
| **B1** | **No Verification (Raw LLM)** | None | Baseline hallucination frequency of the primary model (e.g., Llama 3.1 70B, Mixtral 8x7B). |
| **B2** | **SelfCheckGPT (BERTScore)** | Sampling | Wang et al. (2023) text-only self-consistency using naive token-level similarity across samples. |
| **B3** | **SelfCheckGPT (NLI)** | Sampling | Wang et al. (2023) using zero-shot DeBERTa NLI across prompt samples without external retrieval. |
| **B4** | **FACTSCORE** | Retrieval | Min et al. (2023) retrieval-based atomic claim verification using Wikipedia as gold knowledge base. |
| **B5** | **CLIP-only Visual Grounding** | Multimodal | Pure cosine similarity between claim and image embeddings without fine-grained VQA reasoning. |
| **B6** | **Uncalibrated Ensemble** | Meta-Learner | LightGBM meta-learner without Isotonic Regression to quantify the specific impact of post-hoc calibration. |
| **B7** | **Standard Split CP** | Uncertainty | Marginal conformal prediction without Mondrian conditioning to demonstrate the necessity of group guarantees. |

---

## 5. Systematic Ablation Study Plan

To isolate the marginal contribution of each signal and architectural choice, MIRAGE evaluates 12 systematic configurations on HaluEval, TruthfulQA, and MMHAL-Bench:

| Config | Active Signals | Meta-Learner | Calibrated | Multimodal | Research Question Answered |
|---|---|---|---|---|---|
| **A01** | RAV only | Single-signal | No | No | How predictive is external retrieval evidence alone? |
| **A02** | SCS (Semantic Entropy) only | Single-signal | No | No | How effective is self-consistency without retrieval? |
| **A03** | NLI only (Premise=Prompt) | Single-signal | No | No | Can NLI directly evaluate response without evidence? |
| **A04** | VGS only (LLaVA) | Single-signal | No | Yes | Baseline performance on multimodal benchmark. |
| **A05** | ICS only (Intra-response) | Single-signal | No | No | How many hallucinations are self-contradictions? |
| **A06** | RAV + NLI | Logistic Reg. | Yes | No | Traditional RAG fact-checking baseline. |
| **A07** | RAV + SCS | Logistic Reg. | Yes | No | Combining retrieval with generation variance. |
| **A08** | SCS + NLI | Logistic Reg. | Yes | No | Retrieval-free multi-signal verification. |
| **A09** | RAV + SCS + NLI | Logistic Reg. | Yes | No | Baseline 3-signal text pipeline (without ICS). |
| **A10** | RAV + SCS + NLI + ICS | Logistic Reg. | Yes | No | Marginal value of adding Internal Consistency (ICS). |
| **A11** | RAV + SCS + NLI + ICS | **LightGBM** | Yes | No | Value of non-linear GBDT vs linear Logistic Regression. |
| **A12** | **Full Pipeline (All 5 Signals)**| **LightGBM** | **Isotonic**| **Yes** | **Complete MIRAGE architecture.** |

Each ablation is evaluated on: Macro F1, AUROC, ECE, Brier Score, and Mondrian Conformal Coverage.

---

## 6. Calibration Analysis Protocol

Proper calibration ensures that an HRS of 0.80 corresponds to an empirical 80% hallucination frequency.

### 6.1 3-Way Calibration Benchmark
MIRAGE compares three post-hoc calibration algorithms on the held-out validation set:
1. **Isotonic Regression (Non-parametric)**: Fits a piecewise constant isotonic function $m(z)$ minimizing squared error subject to monotonicity. Evaluated across 1000 calibration points.
2. **Platt Scaling (Parametric)**: Logistic model $\hat{p} = \frac{1}{1 + \exp(A \cdot z + B)}$ fitted via maximum likelihood.
3. **Temperature Scaling**: Logit scaling $\hat{p} = \sigma(z / T)$ optimized for negative log-likelihood.

### 6.2 Calibration Evaluation Procedure
1. **Reliability Diagrams**: Group predictions into $M=15$ equal bins; plot observed empirical accuracy against mean predicted probability with confidence histograms.
2. **Metric Assessment**: Compute ECE, MCE, and Brier score before and after calibration.
3. **Cross-Benchmark Transfer**: Train calibrator on HaluEval validation split; test zero-shot on TruthfulQA (general domain) and FActScoring (biographical entity domain) to prove transferability under distribution shift.

---

## 7. Conformal Prediction & Uncertainty Evaluation

MIRAGE implements **Mondrian (Group-Conditional) Conformal Prediction** to guarantee valid coverage across all risk tiers and claim categories.

### 7.1 Protocol Details
* **Calibration Set**: $N_{\text{cal}} = 1000$ held-out examples from HaluEval, disjoint from training and validation splits.
* **Target Confidence**: Nominal level $1 - \alpha = 0.95$ ($\alpha = 0.05$). Target empirical coverage $\ge 94.0\%$.
* **Mondrian Partitions**:
  - By Risk Tier: Low ($[0.0, 0.3]$), Medium ($[0.3, 0.6]$), High ($[0.6, 0.8]$), Critical ($[0.8, 1.0]$).
  - By Claim Type: Factual, Numerical, Temporal, Relational, Image-grounded.
* **Calibration Set Sizing Ablation**: Compare empirical coverage and mean interval width using calibration sets of size $N \in \{250, 500, 1000, 2000\}$.
* **Informational Efficiency**: Track mean interval width; intervals wider than 0.25 are considered uninformative.

---

## 8. Performance Benchmarking Protocol


Production readiness is assessed using `k6` load testing against the MIRAGE API.

* **Hardware Specs**: Benchmarks run on AWS (G5.2xlarge for GPU nodes, t3.xlarge for API gateways).
* **Warm-up**: 50 warm-up requests are executed and discarded to initialize caches and JIT compilers.
* **Load Profiles**: Ramp from 10 to 100 concurrent sessions over 5 minutes, followed by a 10-minute sustained load at 100 CCUs.
* **Latency Measurement**: End-to-end and per-module (FLAN-T5, DeBERTa, Retrieval, LLaVA) latency tracked at P50, P95, and P99.
* **Throughput**: Maximum sustained requests/second while maintaining P95 < 3000ms.
* **Cold Start**: Time elapsed from container startup to the first successful verification request.
* **Cache Impact**: Comparing P50 latency between a cold cache and a warm cache (simulating the expected >35% SCS cache hit rate).

## 9. Cost Analysis

MIRAGE development and benchmarking is designed to operate at **zero monetary cost** by leveraging free-tier LLM providers, open-source infrastructure, and institute GPU resources.

### 9.1 Development & Research Cost: \$0

| Resource | Provider | Cost |
|---|---|---|
| Primary LLM API (inference, SCS) | Groq free tier (Llama 3.1 70B, Mixtral 8x7B) | **Free** — 30 RPM, 14,400 RPD |
| Fallback LLM API | OpenRouter free models (Llama 3.1, Gemma 2) | **Free** — rate-limited |
| Alternate LLM API | Hugging Face Inference API (Mistral, Llama) | **Free** — rate-limited |
| Synthetic training data generation | Groq (Llama 3.1 70B) or HF Inference API | **Free** |
| GPU compute (fine-tuning + inference) | College GPU (institute-provided) | **Free** |
| All databases, caches, brokers | Self-hosted via Docker Compose | **Free** |
| All ML models (DeBERTa, FLAN-T5, LLaVA, CLIP) | Hugging Face open-source downloads | **Free** |
| Monitoring (Prometheus, Grafana, Tempo) | Self-hosted via Docker | **Free** |
| Benchmark datasets | Public academic datasets | **Free** |
| Experiment tracking | Weights & Biases (academic free tier) | **Free** |
| CI/CD | GitHub Actions (public repo) | **Free** |
| **Total development cost** | | **\$0** |

### 9.2 Free-Tier LLM Provider Comparison

| Provider | Best Model (Free) | Rate Limit | Latency | OpenAI-Compatible API | Best For |
|---|---|---|---|---|---|
| **Groq** | Llama 3.1 70B Versatile | 30 RPM / 14,400 RPD | ~200ms (fastest) | ✅ Yes | Primary development, SCS sampling (fast) |
| **OpenRouter** | Llama 3.1 8B, Gemma 2 9B | Varies per model | ~500-1000ms | ✅ Yes | Fallback, model diversity testing |
| **Hugging Face** | Mistral 7B, Llama 3.1 8B | ~10 RPM (serverless) | ~1-3s | ✅ (via TGI) | Backup, small-model experiments |

**Recommended primary provider for MIRAGE development: Groq** — fastest inference (~200ms), generous free tier, OpenAI-compatible API format requires zero code changes.

### 9.3 SCS Cost with Free Providers

Self-Consistency Sampling requires 3 additional LLM calls per verification. With free-tier providers:
* **Cost per SCS call**: \$0 (Groq free tier)
* **Rate limit constraint**: At 30 RPM, one verification (1 primary + 3 SCS = 4 calls) consumes ~8 seconds of rate budget
* **Effective throughput**: ~7 verifications/minute on Groq free tier (sufficient for development and benchmarking)
* **Caching benefit**: SCS cache hits (>35%) further reduce API calls, stretching the free tier further
* **Recommendation**: For batch benchmarking (1000+ requests), spread calls across Groq + OpenRouter to avoid rate limiting

### 9.4 Infrastructure Cost: Self-Hosted (Development)

All infrastructure runs locally on Docker Compose — zero cloud cost:

| Resource | Solution | Monthly Cost |
|---|---|---|
| GPU compute | College GPU system | \$0 |
| PostgreSQL 16 | Docker container | \$0 |
| MongoDB 7 | Docker container | \$0 |
| Qdrant | Docker container | \$0 |
| Redis 7 | Docker container | \$0 |
| RabbitMQ | Docker container | \$0 |
| S3 equivalent | Local filesystem or MinIO (Docker) | \$0 |
| **Total infrastructure** | | **\$0/month** |

### 9.5 Enterprise Production Cost Reference (For Documentation Only)

For enterprise tenants deploying MIRAGE in production with paid LLM providers and AWS:

| Daily volume | LLM API (GPT-4o-mini, SCS on) | AWS Infrastructure | Total/month |
|---|---|---|---|
| 10,000/day | ~\$293 | ~\$2,275 | ~\$2,568 |
| 50,000/day | ~\$1,463 | ~\$2,500 | ~\$3,963 |
| 100,000/day | ~\$2,925 | ~\$4,200 | ~\$7,125 |

*Note: Enterprise tenants bring their own LLM API keys and cloud infrastructure. These costs are borne by the tenant, not by the MIRAGE project team.*

## 10. Cross-Model Generalization Testing

To evaluate whether MIRAGE is genuinely model-agnostic (rather than overfitted to a specific LLM's stylistic peculiarities), the full benchmark suite is evaluated zero-shot against completions generated by three distinct, open-weights model families:

| Model | Architecture | Serving Endpoint | Parameter Count | Context Window |
|---|---|---|---|---|
| **Llama 3.1 70B** | Dense Decoder-only | Groq API (`llama-3.1-70b-versatile`) | 70B | 128k tokens |
| **Mixtral 8x7B** | Sparse MoE (8 experts) | Groq API (`mixtral-8x7b-32768`) | 46.7B (12.9B active) | 32k tokens |
| **Gemma 2 27B** | Dense Decoder-only | OpenRouter API (`google/gemma-2-27b-it`) | 27B | 8k tokens |

**Generalization Evaluation Protocol**:
1. Run identical benchmark test splits (HaluEval, TruthfulQA) through each of the 3 model generators.
2. Intercept and verify outputs via MIRAGE without fine-tuning or recalibrating on model-specific responses.
3. Target: Macro F1 must remain $> 0.85$ and ECE $< 0.05$ across all three model families.

---

## 11. Adversarial Robustness Testing Suite

Production LLM outputs frequently exhibit stylistic evasion or confidence posturing designed to bypass naive heuristic filters. MIRAGE evaluates robustness against 4 explicit attack profiles:

| Attack Vector | Adversarial Mechanism | Example Prompt/Completion Injection | Evaluated Resilience Target |
|---|---|---|---|
| **ATK-01: Hedged Phrasing** | Prefacing false claims with epistemic doubt to avoid contradiction triggers. | *"It is hypothesized and widely discussed that antibiotics cure viral influenza."* | DeBERTa verifier identifies core factual falsehood despite hedging; Macro F1 drop $\Delta F_1 < 0.05$. |
| **ATK-02: Stated Confidence Injection** | Asserting hyper-confident authority to confuse uncertainty estimators. | *"As an established medical fact confirmed by all doctors, caffeine prevents diabetes."* | Semantic Entropy and NLI signals remain invariant to confidence assertions; zero change in predicted risk. |
| **ATK-03: Hallucinated Citations** | Fabricating plausible academic or clinical references to fake grounding. | *"According to a 2024 Lancet study by Dr. R. Vance, metformin causes immediate hair loss."* | RAV searches Qdrant for nonexistent cited study; zero support triggers elevated retrieval risk ($RSS > 0.85$). |
| **ATK-04: Knowledge Base Evidence Poisoning** | Injecting contradictory or noisy documents into the tenant's vector collection. | Uploading altered Wikipedia chunks with flipped factual predicates. | Multi-signal aggregation resilience: SCS (Semantic Entropy) and ICS penalize internal disagreement even if poisoned KB chunk matches claim. |

---

## 12. Human Evaluation Protocol

Automated metrics are complemented by a rigorous, double-blind human annotation study to validate ecological validity.

### 12.1 Sampling & Annotation Schema
* **Sample Size**: 100 randomly sampled responses (containing 520+ individual atomic claims) stratified across:
  - 40 responses from HaluEval
  - 30 responses from TruthfulQA
  - 30 responses from real-world simulated enterprise chatbot conversations
* **Double-Blind Evaluators**: 2 independent annotators (23AIML042 Vedant, 23AIML076 Dax). Evaluators inspect only the (prompt, response, individual claims) without seeing MIRAGE's computed HRS scores or model predictions.
* **Per-Claim Annotation Task**:
  1. **Factual Grounding**: [Supported, Contradicted, Unverifiable]
  2. **Criticality**: [High, Medium, Low]
  3. **Error Type**: [Entity Error, Relation Error, Arithmetic/Temporal Conflict, None]

### 12.2 Agreement & Consensus Procedure
1. Compute **Cohen's Kappa ($\kappa$)** on claim-level labels. If $\kappa < 0.80$, annotation guidelines are clarified and a 20-sample re-test is performed.
2. Disagreements are reconciled in a structured consensus review to produce a **Gold Human Consensus** benchmark.
3. Calculate MIRAGE's Human-Agreement Macro F1 against the Gold Consensus. Target: $F_1 > 0.85$.

---

## 13. Statistical Significance Testing

To ensure reported improvements over baselines are statistically defensible:
* **Paired Bootstrap Test**: 10,000 resamples for Macro F1 and AUROC comparisons between MIRAGE and SelfCheckGPT/FACTSCORE.
* **McNemar's Test**: Evaluates whether differences in binary classification error distributions are statistically significant ($p < 0.01$).
* **Confidence Intervals**: 95% bootstrap confidence intervals reported for all metric point estimates.
* **Effect Size**: Cohen's $d$ reported for continuous calibration (ECE) and latency differences.
* **Multiple Comparison Correction**: Bonferroni correction applied when comparing across the 12 ablation configurations simultaneously.

---

## 14. Reproducibility Protocol

* **Deterministic Execution**: All random seeds documented and fixed (`seed=42`).
* **Data Provenance**: Exact dataset splits, Hugging Face commit hashes, and SHA-256 checksums recorded.
* **Configuration Management**: Training and evaluation YAML configs versioned in Git.
* **Artifact Tracking**: Model checkpoints, LightGBM tree models, and Isotonic calibration tables stored with SHA-256 hashes.
* **One-Click Benchmarks**: Benchmark suites executable via:
  ```bash
  python scripts/run_benchmarks.py --benchmark all --model groq/llama-3.1-70b
  ```
* **Experiment Logging**: Metrics and calibration curves streamed to Weights & Biases with full run metadata.
* **Automated Visualizations**: All figures generated via headless matplotlib/seaborn scripts directly to SVG.

---

## 15. Reporting and Visualization

All generated figures are stored as vector SVGs in `docs/figures/`:
* Reliability diagrams (calibration curves with 15-bin histograms) for HaluEval, TruthfulQA, and FActScoring.
* ROC and Precision-Recall curves comparing MIRAGE against baselines B1–B5.
* Mondrian conformal coverage plots showing empirical vs. nominal coverage stratified by risk tier.
* Prediction interval width distribution histograms across claim types.
* TreeSHAP summary beeswarm plots demonstrating global signal importance.
* Latency violin plots breaking down execution times across FLAN-T5, RAV, SCS, NLI, VGS, and ICS.

---

## 16. Evaluation Timeline

Mapped to the 6-month development schedule:
* **Month 2**: FLAN-T5 claim extraction F1 evaluation, DeBERTa validation F1 tracking during training on institute GPU.
* **Month 3**: Core text pipeline evaluation on HaluEval test split, 3-way calibration benchmark (Isotonic vs Platt vs Temp), Mondrian conformal coverage validation.
* **Month 4**: Full 12-configuration ablation study, baseline comparisons (SelfCheckGPT, FACTSCORE), out-of-domain generalization on TruthfulQA and FActScoring.
* **Month 5**: Cross-model generalization testing (Llama 3.1, Mixtral, Gemma 2), adversarial robustness suite, k6 performance load tests.
* **Month 6**: Double-blind human evaluation study, statistical significance tests, final paper figure compilation.

---

## 17. Target Benchmark Results Summary

This table serves as the definitive pass/fail acceptance criteria for the MIRAGE evaluation suite.

| Category | Metric | Benchmark / Context | Baseline | MIRAGE Target | Pass Criteria |
|---|---|---|---|---|---|
| Detection Accuracy | Macro F1 | HaluEval test split | 0.72 (SelfCheckGPT) | **> 0.85** | $p < 0.01$ (Bootstrap test) |
| Detection Accuracy | Macro F1 | TruthfulQA | 0.68 (Zero-shot) | **> 0.80** | Out-of-domain zero-shot stability |
| Detection Accuracy | AUROC | HaluEval test split | 0.79 (FACTSCORE) | **> 0.90** | High ranking discrimination |
| Entity Precision | F1 / Precision@K | FActScoring (biography) | 0.76 (FACTSCORE) | **> 0.82** | Competitive with specialized entity baselines |
| Multimodal | VGS Accuracy | MMHAL-Bench | 0.64 (CLIP-only) | **> 0.78** | Superior to CLIP baseline |
| Internal Contradiction| Contradiction F1| Synthetic Contradiction split| 0.50 (No ICS) | **> 0.82** | Catches intra-response factual conflicts |
| Calibration Quality | ECE (15 bins) | HaluEval held-out | 0.14 (Raw LightGBM) | **< 0.035** | Post-Isotonic Regression calibration |
| Calibration Generaliz.| ECE (15 bins) | TruthfulQA | 0.18 (Uncalibrated) | **< 0.050** | Zero-shot transfer without retraining |
| Calibration Generaliz.| ECE (15 bins) | FActScoring | 0.16 (Uncalibrated) | **< 0.050** | Cross-domain transfer stability |
| Calibration Metric | Brier Score | HaluEval held-out | 0.28 (Baseline) | **< 0.16** | Squared probabilistic error reduction |
| Conformal Coverage | Marginal Coverage | HaluEval (1000 cal.) | 0.91 (Split CP) | **≥ 94.5%** | At nominal 95% confidence level |
| Mondrian Coverage | Conditional Coverage | Stratified by Risk Tier | 0.78 (Standard CP) | **≥ 93.5%** | Uniform validity across all 4 tiers |
| Conformal Efficiency | Mean Interval Width | HaluEval test split | 0.35 (Naive) | **< 0.18** | Informative, tight prediction intervals |
| Cross-Model Robustness| Macro F1 | Mixtral 8x7B / Gemma 2 | N/A | **> 0.85** | Performance invariance across model architectures |
| Adversarial Robustness| $\Delta F_1$ (Hedged) | Adversarial Hedging Split | $\Delta F_1 = -0.15$ | **$\Delta F_1 < 0.04$** | Resilient against epistemic hedging |
| Human Agreement | Macro F1 | 100 Sampled Consensus | N/A | **> 0.85** | Alignment with gold human consensus |
| Inter-Annotator Agmt. | Cohen's $\kappa$ | 100 Sampled Pairs | N/A | **$\kappa > 0.80$** | High annotation reliability |
| Claim Decomposer | Claim F1 | Annotated HaluEval | 0.74 (Regex) | **> 0.86** | Single-sentence atomic fact extraction |
| Decomposer Speed | Latency | Single-thread CPU | ~1200ms (LLM API) | **< 45ms** | Sub-50ms CPU constraint satisfied |
| End-to-End Latency | P95 Latency | 100 concurrent CCUs (k6) | N/A | **< 3000ms** | Sustained load over 10 minutes |
| End-to-End Throughput| Sustained RPS | 100 concurrent CCUs | N/A | **> 33 req/s** | Zero queue starvation |
| Correction Quality | Re-verification Pass | LangGraph Rewriter | N/A | **> 95.0%** | Zero introduced hallucinations |
| Cache Efficiency | SCS Hit Rate | Production simulation | N/A | **> 35.0%** | Redis prompt-hash caching |

---

## 18. Document Changelog

| Version | Date | Description |
|---|---|---|
| 1.0.0 | August 2026 | Initial Draft Benchmarking Strategy |
| 2.0.0 | September 2026 | Comprehensive rewrite: Added 13 sections with mathematical formulas, concrete pricing tables, infrastructure cost breakdown, and pass/fail criteria checklist. |
| 2.1.0 | September 2026 | Advanced Research Overhaul: Added Semantic Entropy ($SE$) & Internal Consistency ($ICS$) metrics, 12-configuration ablation study, 3-way calibration benchmark (Isotonic vs Platt vs Temp), Mondrian group-conditional conformal prediction protocol, cross-model generalization testing (Llama, Mixtral, Gemma), adversarial robustness testing suite, double-blind human evaluation protocol (Cohen's $\kappa$), and updated target metrics table. |


