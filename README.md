# MIRAGE (v2.1.0)
**Autonomous Multimodal Hallucination Detection & Factual Consistency Verification System for Production LLMs**

MIRAGE is a production-grade, black-box verification middleware that intercepts Large Language Model (LLM) responses, decomposes them into atomic factual claims, evaluates them across 5 orthogonal evidentiary signals, computes a calibrated Hallucination Risk Score (HRS) with group-conditional conformal prediction intervals, and autonomously corrects detected hallucinations.

---

## 👥 Authors & Academic Affiliation
- **Vedant (23AIML042)** — IIIT Bangalore, CTRI-DG
- **Dax (23AIML076)** — IIIT Bangalore, CTRI-DG
- **Institution**: International Institute of Information Technology Bangalore (IIITB)
- **Date**: September 2026

---

## 📚 Specification & Architectural Documentation

The project is governed strictly by six formal specification documents:

1. **[Product Requirements Document (PRD)](./PRD.md)** — Functional requirements, acceptance criteria, personas, risk register, and timeline.
2. **[Technical Architecture Document (TAD)](./Technical_Architecture.md)** — Microservices topology, data flows, 5-signal pipeline, LightGBM meta-learner, and sequence diagrams.
3. **[Benchmarking & Evaluation Strategy](./Benchmarking_Evaluation.md)** — Benchmark datasets (HaluEval, TruthfulQA, FActScoring, MMHAL-Bench), 12-configuration ablation study, 3-way calibration, and adversarial testing.
4. **[Testing Strategy](./Testing_Strategy.md)** — 8-layer ML testing pyramid, unit/model/integration/contract/chaos testing, and CI gating.
5. **[Security & Access Document (SAD)](./Security_Access.md)** — Threat modeling, multi-tenant isolation, RBAC matrix, secrets management, and cryptographic audit logs.
6. **[Development Workflow & CI/CD](./Development_Workflow.md)** — Monorepo structure, Git flow, code standards, CI/CD pipelines, and work distribution.

---

## 🔬 Core Architectural Innovations

- **5 Evidentiary Signals**:
  1. **RAV**: Hybrid Retrieval-Augmented Verification via Qdrant (dense `all-mpnet-base-v2` + sparse BM25).
  2. **SCS**: $n=5$ Self-Consistency Sampling with DeBERTa bidirectional Semantic Entropy clustering (Kuhn et al., 2023).
  3. **NLI**: Multi-evidence Natural Language Inference via fine-tuned DeBERTa-v3-large.
  4. **ICS**: Intra-response Internal Consistency Scorer computing pairwise contradiction matrices.
  5. **VGS**: Multimodal Visual Grounding via adaptive CLIP pre-filter ($t=0.85$) and LLaVA-1.6 4-bit AWQ.
- **LightGBM Meta-Learner**: 12-feature GBDT pipeline capturing non-linear cross-signal interactions.
- **Calibrated Uncertainty**: Isotonic Regression ensuring Expected Calibration Error ($ECE < 0.035$) and Mondrian Conformal Prediction guaranteeing $\ge 94\%$ conditional coverage.
- **TreeSHAP Explainability**: Exact Shapley feature attributions decomposed per claim.
- **Autonomous Auto-Correction**: Cyclical LangGraph correction loop with bounded retries ($k \le 2$).

---

## 🚀 Quick Start (Development)

### Prerequisites
- Python 3.12+
- Docker & Docker Compose
- Node.js 20+ (for Dashboard)

### Environment Setup
```bash
# Clone the repository
git clone https://github.com/VedantPanchal23/MIRAGE.git
cd MIRAGE

# Start local backing services (Postgres, Mongo, Qdrant, Redis, RabbitMQ)
docker-compose up -d

# Run test suite
pytest
```

---

## 📜 License & Citation
Research project under active development at IIIT Bangalore (CTRI-DG). All rights reserved.
