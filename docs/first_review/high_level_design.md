# High-Level Design (HLD): MIRAGE Verification Platform

**Institution:** Chandubhai S. Patel Institute of Technology (CSPIT)  
**Department:** Artificial Intelligence and Machine Learning  
**Investigators:** Vedant Panchal (`23AIML042`) & Dax Virani (`23AIML076`)  

---

## 1. Problem Statement & Motivation

Generative Large Language Models (LLMs) frequently generate **hallucinations**—untrue, fabricated, or internally contradictory assertions stated with uncalibrated certainty. In high-consequence domains such as healthcare, jurisprudence, and finance, undetected hallucinations cause catastrophic outcomes (e.g., lethal drug dosage recommendations, fictional judicial citations, regulatory non-compliance).

**MIRAGE** is an autonomous, multimodal, factual consistency verification and remediation middleware that intercepts LLM outputs, evaluates factual accuracy across five independent mathematical and evidentiary signals, calculates a calibrated **Hallucination Risk Score (HRS)** bounded by 95% conformal prediction intervals, and autonomously remediates corrupted claims prior to client delivery.

---

## 2. Product Classification: The 5 Product Interfaces

MIRAGE is not merely an API or a standalone application. It delivers a **five-layer hybrid product taxonomy** satisfying diverse enterprise integration patterns:

```mermaid
graph TD
    subgraph Clients["Client Applications & Developers"]
        C1["Standard OpenAI / LangChain Apps"]
        C2["Enterprise Backend Workflows"]
        C3["Real-Time Streaming Chatbots"]
        C4["AI Code Editors (Cursor, Claude)"]
        C5["Compliance Officers & Safety Auditors"]
    end

    subgraph Interfaces["MIRAGE Product Interfaces"]
        I1["1. Drop-in REST Proxy API<br/><code>/v1/chat/completions</code>"]
        I2["2. Direct Verification REST API<br/><code>/v1/verify</code>"]
        I3["3. Streaming WebSocket Server<br/><code>/v1/verify/stream</code>"]
        I4["4. Model Context Protocol (MCP) Server<br/><code>mirage-mcp-server</code>"]
        I5["5. Longitudinal Drift Dashboard<br/><code>React 18 / Vite Web App</code>"]
    end

    subgraph Core["MIRAGE Core Verification Engine"]
        ENG["Claim Decomposer + 5 Signals + HRS Engine + LangGraph Remediation"]
    end

    C1 --> I1
    C2 --> I2
    C3 --> I3
    C4 --> I4
    C5 --> I5

    I1 --> ENG
    I2 --> ENG
    I3 --> ENG
    I4 --> ENG
    I5 --> ENG

    classDef client fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    classDef iface fill:#e8f5e9,stroke:#388e3c,stroke-width:2px;
    classDef core fill:#fff3e0,stroke:#f57c00,stroke-width:2px;
    class C1,C2,C3,C4,C5 client;
    class I1,I2,I3,I4,I5 iface;
    class ENG core;
```

### Detailed Interface Specifications

1. **Drop-in REST Proxy API (`/v1/chat/completions`)**: Wire-compatible with the official OpenAI SDK. Enterprise clients change only their `base_url` (`https://api.mirage.internal/v1`) to gain transparent hallucination interception with zero application code changes.
2. **Direct Verification REST API (`/v1/verify`)**: Direct synchronous and asynchronous endpoints accepting a `(prompt, response, optional_image)` payload, returning atomic claims, signal breakdowns, and conformal confidence bounds.
3. **Real-Time Streaming WebSocket (`/v1/verify/stream`)**: Full-duplex WebSocket delivering progressive verification events (token chunking, atomic claim completion, signal completion) for interactive conversational agents.
4. **Model Context Protocol (MCP) Server**: A standard MCP server exposing tools (`verify_text`, `get_risk_score`, `search_knowledge_base`) to agentic development environments like Cursor, Windsurf, and Claude Desktop.
5. **Longitudinal Drift Web Dashboard**: React 18 / Vite web application visualizing tenant-level hallucination rates, SHAP feature contributions, latency percentiles, and compliance audit reports.

---

## 3. High-Level Architectural Pipeline

The verification lifecycle follows an end-to-end six-stage pipeline:

```mermaid
flowchart TD
    Client["Client Application<br/>(OpenAI / Anthropic Payload)"] --> GW["1. MIRAGE Gateway<br/>(JWT Auth, Token-Bucket Rate Limiter, PII Sanitizer)"]
    GW --> DECOM["2. Atomic Claim Decomposer<br/>(Fine-tuned FLAN-T5-base, &lt;50ms)"]

    subgraph Workers["3. Parallel Multi-Signal Worker Layer"]
        RAV["RAV Worker<br/>(Qdrant Vector KB, Top-5 Chunks)"]
        SCS["SCS Worker<br/>(n=5 Entropy Clustering)"]
        NLI["NLI Scorer<br/>(DeBERTa-v3 Cross-Encoder)"]
        VGS["VGS Worker<br/>(CLIP + LLaVA-1.6 Vision)"]
        ICS["ICS Worker<br/>(Pairwise Intra-Claim Consistency)"]
    end

    DECOM --> RAV
    DECOM --> SCS
    DECOM --> NLI
    DECOM --> VGS
    DECOM --> ICS

    RAV --> HRS["4. HRS Meta-Learning Engine<br/>(LightGBM + Mondrian Conformal CI + TreeSHAP)"]
    SCS --> HRS
    NLI --> HRS
    VGS --> HRS
    ICS --> HRS

    HRS --> DECISION{"Risk Tier Assessment"}

    DECISION -->|"Low Risk (HRS &le; 0.30)"| PASS["Safe Pass-Through<br/>Deliver Verified Response"]
    DECISION -->|"Medium Risk (0.30 &lt; HRS &le; 0.60)"| FLAG["Flagged Return<br/>Attach Warning Badges & Citations"]
    DECISION -->|"Critical Risk (HRS &gt; 0.60)"| REMEDIATE["5. LangGraph Correction Agent<br/>(Evidence-Grounded Rewrite &amp; Mandatory Re-Check)"]

    REMEDIATE -->|"Re-Verified Safe"| PASS
    REMEDIATE -->|"Exceeded Retries"| FALLBACK["Safe Fallback / Error Flag"]

    PASS --> AUDIT["6. Cryptographic Audit Ledger<br/>(PostgreSQL RLS + MongoDB Traces + SHA-256 Chaining)"]
    FLAG --> AUDIT
    FALLBACK --> AUDIT

    classDef gw fill:#ede7f6,stroke:#512da8,stroke-width:2px;
    classDef worker fill:#e0f2f1,stroke:#00796b,stroke-width:2px;
    classDef hrs fill:#fff8e1,stroke:#fbc02d,stroke-width:2px;
    classDef safe fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef danger fill:#ffebee,stroke:#c62828,stroke-width:2px;
    class GW,DECOM gw;
    class RAV,SCS,NLI,VGS,ICS worker;
    class HRS hrs;
    class PASS safe;
    class REMEDIATE,FLAG,FALLBACK danger;
```

---

## 4. 5-Plane Microservices Topology

MIRAGE is deployed as a 13-container microservices stack organized across five decoupled infrastructure planes:

```mermaid
graph TB
    subgraph P1["Plane 1: Gateway & Security (Port 8000)"]
        G1["FastAPI Application"]
        G2["Security Headers & PII Scrubbing"]
        G3["Role-Based Access Control (RBAC)"]
    end

    subgraph P2["Plane 2: Machine Learning & Inference"]
        M1["FLAN-T5 Claim Decomposer"]
        M2["DeBERTa-v3 NLI Verifier"]
        M3["LLaVA-1.6-Mistral-7B / CLIP (Vision)"]
    end

    subgraph P3["Plane 3: Distributed Asynchronous Workers"]
        W1["Celery Persistent Daemon"]
        W2["RabbitMQ 3.13 Quorum Queues"]
        W3["Dead-Letter Exchange (mirage.dlx)"]
    end

    subgraph P4["Plane 4: Multi-Store Persistence"]
        DB1["PostgreSQL 16 (Auditing + RLS)"]
        DB2["MongoDB 7.0 (Raw Traces)"]
        DB3["Redis 7.2 ACL (Cache DB0, Rate Limiting DB1)"]
        DB4["Qdrant Vector DB (Knowledge Base Embeddings)"]
    end

    subgraph P5["Plane 5: Observability & Analytics (Ports 3000, 3001)"]
        O1["OpenTelemetry Collector"]
        O2["Grafana Tempo (Distributed Tracing)"]
        O3["Prometheus (Metrics Scraper)"]
        O4["Grafana 11 (Dashboards)"]
        O5["React 18 Drift UI (Port 3000)"]
    end

    P1 ==> P2
    P1 ==> P3
    P3 ==> P4
    P1 ==> P4
    P1 -.-> P5
    P3 -.-> P5

    classDef p1 fill:#e8eaf6,stroke:#283593,stroke-width:2px;
    classDef p2 fill:#fce4ec,stroke:#880e4f,stroke-width:2px;
    classDef p3 fill:#e0f7fa,stroke:#006064,stroke-width:2px;
    classDef p4 fill:#f1f8e9,stroke:#33691e,stroke-width:2px;
    classDef p5 fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    class G1,G2,G3 p1;
    class M1,M2,M3 p2;
    class W1,W2,W3 p3;
    class DB1,DB2,DB3,DB4 p4;
    class O1,O2,O3,O4,O5 p5;
```

---

## 5. Architectural Non-Functional Requirements (NFRs)

* **Verification Latency SLA**: $P95 < 1.5\text{s}$ for cached/pure text payloads; $P95 < 3.0\text{s}$ for cold full-pipeline executions.
* **Calibrated Reliability**: Expected Calibration Error ($ECE$) $< 0.05$; conformal prediction coverage certified at $\ge 94\%$.
* **Security & Tenancy**: Cryptographic tenant isolation enforced via PostgreSQL Row-Level Security (`app.current_tenant_id`) and MongoDB tenant filtering.
* **Resilience**: Fail-closed rate limiting via Redis token bucket; graceful degradation for non-critical vector retrieval via `pybreaker`.
