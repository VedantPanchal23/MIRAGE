# MIRAGE: System Architecture & Visual Diagram Catalog

**Institution:** Chandubhai S. Patel Institute of Technology (CSPIT)  
**Department:** Artificial Intelligence and Machine Learning  
**Investigators:** Vedant Panchal (`23AIML042`) & Dax Virani (`23AIML076`)  

This catalog contains all core system architecture diagrams rendered in standard GitHub-compatible Mermaid format for faculty review and presentation slides.

---

## Diagram 1: End-to-End High-Level Execution Pipeline

```mermaid
flowchart TD
    subgraph Ingestion["Ingestion & Boundary Security"]
        App["Client Application<br/>(OpenAI / Custom Client)"] -->|"HTTP POST /v1/chat/completions"| GW["MIRAGE Gateway<br/>(Port 8000)"]
        GW --> Auth["JWT &amp; API-Key Auth<br/>(Tenant Isolation)"]
        Auth --> Rate["Redis Token-Bucket Rate Limiter"]
        Rate --> PII["PII Scrubber &amp; Header Sanitizer"]
    end

    subgraph Decomposition["Claim Decomposition"]
        PII --> FLAN["FLAN-T5-base Claim Decomposer<br/>(&lt;50ms, CPU)"]
        FLAN -->|"List of Atomic Claims c_i"| Broker{"Dispatch Parallel Tasks"}
    end

    subgraph Signals["5-Signal Parallel Evaluation Layer"]
        Broker -->|"Query Vector KB"| RAV["1. RAV Worker<br/>(Qdrant Top-5 Cosine)"]
        Broker -->|"Query LLM n=5"| SCS["2. SCS Worker<br/>(Semantic Entropy)"]
        Broker -->|"Cross-Encoder"| NLI["3. NLI Scorer<br/>(DeBERTa-v3 GPU)"]
        Broker -->|"Intra-Pairs"| ICS["4. ICS Worker<br/>(O(K^2) Consistency)"]
        Broker -->|"Multimodal"| VGS["5. VGS Worker<br/>(CLIP + LLaVA-1.6)"]
    end

    subgraph Aggregation["Scoring & Meta-Learning Engine"]
        RAV --> FEAT["12-Feature Signal Vector x_i"]
        SCS --> FEAT
        NLI --> FEAT
        ICS --> FEAT
        VGS --> FEAT
        FEAT --> LGBM["LightGBM Decision Tree"]
        LGBM --> ISO["Isotonic Calibration (ECE &lt; 0.05)"]
        ISO --> CONF["Mondrian Conformal Prediction (95% CI)"]
        CONF --> SHAP["TreeSHAP Explainability Attribution"]
    end

    subgraph Routing["Gateway Routing & Autonomous Remediation"]
        SHAP --> TIER{"Risk Tier Classification"}
        TIER -->|"HRS &le; 0.30 (LOW)"| RETURN_SAFE["Safe Verified Return<br/>(Direct Pass-Through)"]
        TIER -->|"0.30 &lt; HRS &le; 0.60 (MEDIUM)"| RETURN_FLAG["Flagged Return<br/>(Warning Badges Attached)"]
        TIER -->|"HRS &gt; 0.60 (CRITICAL)"| REMEDIATE["LangGraph Remediation Agent<br/>(Evidence-Grounded Rewrite)"]
        REMEDIATE -->|"Mandatory Re-check Pass"| RETURN_SAFE
    end

    subgraph Persistence["Authoritative Persistence & Audit"]
        RETURN_SAFE --> PG["PostgreSQL 16 (Auditing + RLS)"]
        RETURN_FLAG --> PG
        RETURN_SAFE --> MONGO["MongoDB 7.0 (Raw Traces)"]
        PG --> HASH["Cryptographic SHA-256 Audit Chain"]
    end

    classDef ing fill:#e8eaf6,stroke:#283593,stroke-width:2px;
    classDef sig fill:#e0f2f1,stroke:#00695c,stroke-width:2px;
    classDef agg fill:#fff8e1,stroke:#f57f17,stroke-width:2px;
    classDef dec fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef crit fill:#ffebee,stroke:#c62828,stroke-width:2px;
    class App,GW,Auth,Rate,PII ing;
    class RAV,SCS,NLI,ICS,VGS sig;
    class FEAT,LGBM,ISO,CONF,SHAP agg;
    class RETURN_SAFE,RETURN_FLAG dec;
    class REMEDIATE crit;
```

---

## Diagram 2: 5-Plane Production Microservices Topology

```mermaid
graph TB
    subgraph P1["PLANE 1: GATEWAY & SECURITY LAYER (PORT 8000)"]
        G_APP["FastAPI Reverse Proxy & ASGI Gateway"]
        G_RATELIMIT["Token-Bucket Rate Limiter (Redis DB1)"]
        G_AUTH["Cryptographic JWT / API Key RBAC Engine"]
        G_PII["Presidio PII Detection & Header Sanitizer"]
    end

    subgraph P2["PLANE 2: ML INFERENCE & MODEL SERVING LAYER"]
        M_FLAN["FLAN-T5-base (Local CPU / Claim Decomposer)"]
        M_NLI["DeBERTa-v3-large (TorchServe FP16 GPU)"]
        M_LLAVA["LLaVA-1.6-Mistral-7B (TGI 4-bit AWQ GPU)"]
        M_CLIP["CLIP ViT-B/32 (Vision Embedding Pre-filter)"]
    end

    subgraph P3["PLANE 3: DISTRIBUTED ASYNCHRONOUS WORKER LAYER"]
        W_CELERY["Celery Persistent Daemon Workers"]
        W_RABBIT["RabbitMQ 3.13 Quorum Queues (Raft Durability)"]
        W_DLQ["Dead-Letter Exchange (mirage.dlx)"]
    end

    subgraph P4["PLANE 4: MULTI-STORE PERSISTENCE LAYER"]
        DB_PG["PostgreSQL 16 (Auditing, Row-Level Security)"]
        DB_MONGO["MongoDB 7.0 (Verification Traces & Raw Payloads)"]
        DB_REDIS["Redis 7.2 (ACL DB0: SCS Cache, DB1: Rate Limiting)"]
        DB_QDRANT["Qdrant Vector DB (HNSW Index, Enterprise KB)"]
    end

    subgraph P5["PLANE 5: OBSERVABILITY & DASHBOARD LAYER (PORTS 3000, 3001)"]
        O_OTEL["OpenTelemetry Collector"]
        O_TEMPO["Grafana Tempo (Distributed Tracing)"]
        O_PROM["Prometheus (Metrics Engine)"]
        O_GRAF["Grafana 11 (Dashboards on Port 3001)"]
        O_UI["React 18 Drift Dashboard (Nginx on Port 3000)"]
    end

    P1 ==> P2
    P1 ==> P3
    P3 ==> P4
    P1 ==> P4
    P1 -.-> P5
    P3 -.-> P5

    classDef plane1 fill:#ede7f6,stroke:#4a148c,stroke-width:2px;
    classDef plane2 fill:#fce4ec,stroke:#880e4f,stroke-width:2px;
    classDef plane3 fill:#e0f7fa,stroke:#006064,stroke-width:2px;
    classDef plane4 fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px;
    classDef plane5 fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    class G_APP,G_RATELIMIT,G_AUTH,G_PII plane1;
    class M_FLAN,M_NLI,M_LLAVA,M_CLIP plane2;
    class W_CELERY,W_RABBIT,W_DLQ plane3;
    class DB_PG,DB_MONGO,DB_REDIS,DB_QDRANT plane4;
    class O_OTEL,O_TEMPO,O_PROM,O_GRAF,O_UI plane5;
```

---

## Diagram 3: Happy Path Execution Sequence (Low Risk Pass-Through)

```mermaid
sequenceDiagram
    autonumber
    actor Client as Client Application
    participant GW as MIRAGE Gateway
    participant Redis as Redis 7.2 (Rate Limiter)
    participant Decom as FLAN-T5 Decomposer
    participant Workers as Parallel Workers (RAV, SCS, NLI)
    participant HRS as HRS Engine
    participant DB as PostgreSQL + MongoDB

    Client->>GW: POST /v1/verify (Prompt, Response, Auth Header)
    GW->>Redis: Token-bucket quota check (DB1)
    Redis-->>GW: OK (Token available)
    GW->>Decom: Decompose response into atomic claims
    Decom-->>GW: Return [c1, c2] with criticality weights
    
    par Multi-Signal Parallel Evaluation
        GW->>Workers: RAV: Search Qdrant vector store
        GW->>Workers: SCS: Entropy clustering
        GW->>Workers: NLI: Evaluate evidence entailment
    end
    Workers-->>GW: Return [RSS=0.92, SE=0.04, P(entail)=0.95]
    
    GW->>HRS: Score 12-feature vector
    HRS-->>GW: HRS = 0.04 (LOW), 95% CI: [0.00, 0.09], TreeSHAP
    
    par Asynchronous Persistence
        GW-)DB: Insert PostgreSQL audit record (RLS mirage_app)
        GW-)DB: Insert MongoDB full execution trace
    end

    GW-->>Client: 200 OK (Verified Response, Risk Tier: LOW, HRS: 0.04)
```

---

## Diagram 4: Remediation Loop Sequence (High Risk Intercept)

```mermaid
sequenceDiagram
    autonumber
    actor Client as Client Application
    participant GW as MIRAGE Gateway
    participant Workers as Evaluator Workers
    participant HRS as HRS Engine
    participant LangGraph as LangGraph Correction Agent
    participant PrimaryLLM as Target LLM
    participant DB as PostgreSQL 16 Ledger

    Client->>GW: POST /v1/chat/completions (Proxy request)
    GW->>PrimaryLLM: Forward initial prompt
    PrimaryLLM-->>GW: Return hallucinated output (e.g., false dosage)
    
    GW->>Workers: Decompose claims & evaluate multi-signal
    Workers-->>GW: Contradiction detected (P_contra = 0.88)
    GW->>HRS: Calculate risk
    HRS-->>GW: HRS = 0.85 (CRITICAL) -> Intercept triggered!

    GW->>LangGraph: Initiate correction state machine
    Note over LangGraph: Isolate contradicted claims & fetch ground truth
    LangGraph->>PrimaryLLM: Prompt rewrite strictly conditioned on evidence
    PrimaryLLM-->>LangGraph: Return candidate rewrite
    
    LangGraph->>Workers: Mandatory re-verification pass
    Workers-->>LangGraph: Re-check confirms entailment
    LangGraph-->>GW: Sanitized factual rewrite (New HRS = 0.04)

    GW-)DB: Log original hallucination + remediation trace
    GW-->>Client: 200 OK (Remediated Response, Flag: REWRITTEN)
```

---

## Diagram 5: Circuit Breaker Failure & Fallback Sequence

```mermaid
sequenceDiagram
    autonumber
    participant GW as MIRAGE Gateway
    participant Qdrant as Qdrant Vector Store
    participant Circuit as pybreaker (Qdrant Circuit)
    participant Fallback as RAV-less Verification Fallback

    Note over Circuit: State: CLOSED (Normal Operation)
    GW->>Circuit: search_evidence(query)
    Circuit->>Qdrant: Query vector embeddings (timeout=1000ms)
    Qdrant--xCircuit: Timeout / Network Failure (Attempt 1)
    Circuit-->>GW: Record failure (fail_counter = 1)
    
    GW->>Circuit: search_evidence(query)
    Circuit->>Qdrant: Query vector embeddings
    Qdrant--xCircuit: Timeout (Attempt 2)
    
    GW->>Circuit: search_evidence(query)
    Circuit->>Qdrant: Query vector embeddings
    Qdrant--xCircuit: Timeout (Attempt 3 = fail_max)
    
    Note over Circuit: State: OPEN (Tripped for 30s reset_timeout)
    GW->>Circuit: search_evidence(query)
    Circuit-->>GW: Fast CircuitBreakerError (0ms)
    GW->>Fallback: Engage RAV-less degradation mode
    Fallback-->>GW: Compute HRS using SCS + NLI + ICS (Re-normalized weights)
    GW-->>GW: Pipeline continues without system crash!
```

---

## Diagram 6: Database Entity-Relationship & Multi-Store Architecture

```mermaid
erDiagram
    TENANTS ||--o{ VERIFICATION_SESSIONS : "issues"
    VERIFICATION_SESSIONS ||--o{ CLAIMS : "contains"
    VERIFICATION_SESSIONS ||--|| AUDIT_LEDGER : "generates"
    VERIFICATION_SESSIONS ||--|| MONGO_TRACES : "persists"
    TENANTS ||--o{ KNOWLEDGE_BASE_DOCS : "owns"

    TENANTS {
        uuid id PK "Primary Key"
        string name "Tenant Name"
        string tier "ENTERPRISE / COMMUNITY"
        int rate_limit_per_minute "Token bucket cap"
        timestamp created_at
    }

    VERIFICATION_SESSIONS {
        uuid id PK "Session UUID"
        uuid tenant_id FK "Row-Level Security key"
        text prompt "User input prompt"
        text original_response "Raw LLM output"
        text verified_response "Final delivered text"
        float hrs_score "Calibrated HRS [0, 1]"
        string risk_tier "LOW / MEDIUM / HIGH / CRITICAL"
        float conformal_lower "95% CI lower bound"
        float conformal_upper "95% CI upper bound"
        boolean was_corrected "LangGraph triggered flag"
        timestamp created_at
    }

    CLAIMS {
        uuid id PK "Claim UUID"
        uuid session_id FK "Parent session"
        text claim_text "Atomic statement"
        string criticality "HIGH / MEDIUM / LOW"
        float weight "1.0 / 0.6 / 0.3"
        float nli_score "Softmax entailment prob"
        float rav_score "Cosine similarity"
        float scs_score "Semantic entropy"
        string status "VERIFIED / CONTRADICTED"
    }

    AUDIT_LEDGER {
        uuid id PK "Audit UUID"
        uuid session_id FK "1-to-1 session mapping"
        string prev_hash "SHA-256 link to prior record"
        string current_hash "SHA-256 cryptographic seal"
        jsonb security_metadata "IP, headers, role"
        timestamp committed_at
    }

    KNOWLEDGE_BASE_DOCS {
        uuid id PK "Document UUID"
        uuid tenant_id FK "Tenant partition"
        string filename "Source document name"
        int chunk_count "Number of vector chunks"
        timestamp indexed_at
    }

    MONGO_TRACES {
        string _id PK "Document ID"
        string session_id "Session reference"
        string tenant_id "Tenant reference"
        jsonb full_request "Raw input payload"
        jsonb intermediate_signals "Raw worker logits"
        jsonb shap_waterfall "Local explainability vector"
        timestamp logged_at
    }
```
