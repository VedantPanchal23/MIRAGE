# MIRAGE — Security & Access Document (SAD)
**An Autonomous Multimodal Hallucination Detection and Factual Consistency Verification System for Production LLMs**

---

| Field | Details |
|---|---|
| Document Version | 2.1.0 |
| Status | Final |
| Authors | 23AIML042 Vedant, 23AIML076 Dax |
| Institution | IIIT Bangalore — CTRI-DG |
| Date | September 2026 |
| Classification | Internal — Project Documentation |

---

## Table of Contents

1. Security Overview
2. Threat Model
3. Authentication and Authorization
4. Data Security
5. Secrets Management
6. Network Security
7. API Security
8. Model and AI Security
9. Multi-Tenant Isolation
10. Audit and Compliance
11. Incident Response
12. Security Testing Plan
13. Role-Based Access Control (RBAC)
14. Third-Party and Dependency Security
15. Docker and Container Security
16. Security Training and Awareness
17. Security Checklist
18. Document Changelog

---

## 1. Security Overview

MIRAGE sits in a uniquely sensitive position in an enterprise's AI stack — it intercepts every LLM prompt and response flowing through it. This means it handles potentially confidential business data, proprietary customer information, medical records, legal documents, and financial data depending on the enterprise tenant. Security is therefore not a feature — it is a foundational requirement of the system's architecture.

This document defines the security model, access control policies, data handling standards, threat mitigations, and compliance posture for MIRAGE.

### 1.1 Security Principles

- **Zero Trust**: No component trusts another by default. All inter-service communication is authenticated and authorized explicitly.
- **Least Privilege**: Every service, user, and API key has the minimum permissions required to perform its function and nothing more.
- **Defense in Depth**: Security controls exist at every layer — network, application, data, and model — so that compromise of one layer does not expose the system.
- **Privacy by Design**: Prompt and response data is treated as sensitive by default. No raw data is retained beyond the configured retention window without explicit tenant opt-in.
- **Auditability**: Every access to sensitive data and every system action is logged with sufficient context for forensic investigation using structlog JSON logging.
- **Fail Secure**: When MIRAGE encounters an error, it fails in a way that does not expose sensitive data — defaulting to passthrough with error metadata rather than exposing raw pipeline state.

---

## 2. Threat Model

### 2.1 Assets to Protect

| Asset | Sensitivity | Description |
|---|---|---|
| LLM Prompts | Critical | May contain confidential business data, PII, medical records |
| LLM Responses | Critical | Derived from sensitive prompts |
| Verification Traces | High | Full pipeline output including evidence chunks and claim breakdowns |
| Tenant API Keys | Critical | Compromise enables impersonation and data access |
| Knowledge Base Documents | High | May contain proprietary enterprise documents |
| HRS Drift Data | Medium | Reveals enterprise AI reliability posture |
| Verifier Model Weights | Medium | Proprietary fine-tuned model |
| Database Credentials | Critical | Access to all stored data |

### 2.2 Threat Actors

| Actor | Motivation | Capability |
|---|---|---|
| External attacker | Data exfiltration, service disruption | Moderate — API-level access only |
| Malicious tenant | Access other tenants' data | Moderate — authenticated API access |
| Compromised LLM API | Prompt injection via LLM response | High — controls LLM output |
| Insider threat | Data theft, sabotage | High — internal system access |
| Automated scraper | API abuse, rate limit bypass | Low-Moderate |

### 2.3 Threat Scenarios and Mitigations

| ID | Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| T-01 | API key theft and tenant impersonation | Medium | Critical | API key hashing, short-lived tokens, IP allowlisting |
| T-02 | Cross-tenant data leakage via shared RAV module | Medium | Critical | Strict tenant_id scoping on all DB queries and vector store collections |
| T-03 | Prompt injection via LLM response content | High | High | Response content treated as untrusted data, never executed or evaluated as code |
| T-04 | Man-in-the-middle interception of LLM responses | Low | Critical | TLS 1.3 enforced on all external connections |
| T-05 | Knowledge base poisoning (malicious document upload) | Medium | High | Document scanning via ClamAV, upload authentication, tenant isolation, FLAN-T5 claim decomposer treats all content as untrusted text |
| T-05b | Adversarial LLM response crafted to evade FLAN-T5 claim extraction | Low | Medium | FLAN-T5 fine-tuned on structured extraction task — not following instructions in content; output schema validated before pipeline entry |
| T-05c | SCS cache poisoning — injecting malicious cached SCS samples | Low | High | SCS cache key includes tenant_id and model_id; Redis AUTH + TLS; cache entries expire in 1 hour |
| T-05d | Epistemic Hedging Evasion Attack | Medium | High | Response prefaces falsehoods with doubt ("It is hypothesized that..."). DeBERTa fine-tuned on synthetic hedged negatives; hedging boilerplate stripped during normalization |
| T-05e | Stated Confidence Injection Attack | Medium | Medium | Response injects deceptive authority ("As an established consensus..."). Semantic Entropy across n=5 samples measures semantic dispersion independent of stylistic framing |
| T-05f | Fabricated / Hallucinated Citation Attack | Medium | High | Response cites nonexistent clinical studies or papers. RAV performs strict vector search against authorized tenant knowledge base; ungrounded citations fail retrieval and elevate RSS |
| T-05g | Intra-Response Internal Contradiction Attack | Medium | High | Response crafts mutually exclusive factual predicates within a single completion. Internal Consistency Scorer (ICS) evaluates pairwise claims via DeBERTa to detect contradiction |
| T-06 | Denial of Service via concurrent verification flood | Medium | High | Rate limiting per tenant via Redis, RabbitMQ queue depth limits, pybreaker circuit breakers, async queue overflow protection |
| T-07 | Unauthorized audit log access | Low | High | RBAC enforcement on all audit endpoints, row-level security in PostgreSQL |
| T-08 | Model extraction via repeated API queries | Low | Medium | Rate limiting, query pattern anomaly detection |
| T-09 | Insecure deserialization in MongoDB trace storage | Medium | High | Input validation, no eval() or dynamic deserialization |
| T-10 | GPU server compromise during model training | Low | High | Air-gapped training environment, signed model artifacts |


---

## 3. Authentication and Authorization

### 3.1 Tenant Authentication

Every tenant is issued an API key upon registration. API keys follow this design:

- **Format**: `mrg_{environment}_{32_char_random_hex}` — e.g., `mrg_prod_a3f9b2c1d4e5f6a7b8c9d0e1f2a3b4c5`
- **Storage**: Only the SHA-256 hash of the API key is stored in PostgreSQL. The plaintext key is shown to the tenant exactly once at creation and never stored.
- **Transmission**: API key must be passed as `Authorization: Bearer {key}` header. Never in query parameters or request body.
- **Rotation**: Tenants can rotate their API key via the admin panel. Old key is invalidated immediately.
- **Scoping**: Each API key is scoped to a single tenant and cannot be used to access any other tenant's data or endpoints.

### 3.2 JWT for Dashboard and Admin Panel

The React dashboard and admin panel use JWT-based authentication separate from API keys.

- **Token lifetime**: Access token 15 minutes, refresh token 7 days
- **Algorithm**: RS256 (asymmetric) — private key stored only on auth service, public key distributed to all services for verification
- **Claims**: `{ sub: user_id, tenant_id, role, iat, exp }`
- **Refresh token rotation**: Every refresh issues a new refresh token and invalidates the old one (sliding window)
- **Storage**: Access token in memory only (never localStorage). Refresh token in HttpOnly, Secure, SameSite=Strict cookie.

### 3.3 Service-to-Service Authentication

All internal microservice communication uses mutual TLS (mTLS) with certificates issued by an internal CA.

- Gateway → RAV Worker: mTLS
- Gateway → SCS Worker: mTLS
- Gateway → NLI Model Server: mTLS
- Gateway → HRS Engine: mTLS
- HRS Engine → Correction Agent: mTLS
- All services → PostgreSQL: SSL certificate verification required
- All services → MongoDB: TLS with certificate verification
- All services → Redis: TLS with AUTH password

---

## 4. Data Security

### 4.1 Encryption at Rest

| Data Store | Encryption Standard | Key Management |
|---|---|---|
| PostgreSQL (AWS RDS) | AES-256 (AWS managed) | AWS KMS with tenant-specific CMK |
| MongoDB Atlas | AES-256 (Atlas managed) | Atlas Key Management |
| Qdrant vectors | AES-256 (volume-level) | Cloud provider KMS |
| Redis (ElastiCache) | AES-256 (ElastiCache encryption) | AWS KMS |
| RabbitMQ (AWS MQ) | AES-256 (AWS MQ managed) | AWS KMS |
| S3 (audit PDFs, images) | AES-256 (SSE-S3 or SSE-KMS) | AWS KMS per-tenant prefix |
| DeBERTa verifier model weights | AES-256 (S3 SSE-KMS) | AWS KMS |
| FLAN-T5 decomposer model weights | AES-256 (S3 SSE-KMS) | AWS KMS |
| LLaVA-1.6 model weights | AES-256 (S3 SSE-KMS) | AWS KMS |

### 4.2 Encryption in Transit

- All external traffic (enterprise app → MIRAGE gateway): TLS 1.3 minimum. TLS 1.0 and 1.1 explicitly disabled.
- All internal service traffic: mTLS (see Section 3.3)
- MIRAGE → LLM API providers (Groq, OpenRouter, Hugging Face Inference API; or enterprise-configured OpenAI, Anthropic): TLS 1.3 (enforced by providers) — only during primary LLM call and SCS sampling
- MIRAGE → Qdrant: TLS
- MIRAGE → RabbitMQ (AWS MQ): TLS 1.2+ with AMQPS protocol
- FLAN-T5 decomposer container: no network egress configured — processes data entirely in memory, zero data exfiltration risk
- LLaVA-1.6 model server container: no network egress configured — image data processed entirely in GPU memory, never transmitted externally
- Certificate rotation: Automated via AWS ACM for external certificates. Internal CA certificates rotated every 90 days.

### 4.3 Data Minimization and Retention

MIRAGE applies strict data minimization principles:

- **Prompt content**: By default, prompts are hashed (SHA-256) and only the hash is stored in PostgreSQL for deduplication and caching. Raw prompt text is stored only in MongoDB verification traces.
- **Retention window**: Default 90 days. Configurable per tenant (30/60/90/180 days). After retention window, all raw prompt/response data is hard-deleted from MongoDB and S3. Only aggregate HRS metrics are retained indefinitely for drift analysis.
- **Right to deletion**: Tenants can request immediate deletion of all their data via admin panel. Deletion cascades across PostgreSQL, MongoDB, Qdrant, Redis, and S3.
- **PII handling**: MIRAGE provides an optional PII detection middleware (pre-processing step) using regex-based pattern matching for common PII types: email addresses, phone numbers, SSNs, credit card numbers, IP addresses.
  - PII detection is FLAGGING only — it adds a `pii_detected: true` warning to the response metadata but does NOT block or redact.
  - Full PII masking/redaction is the responsibility of the enterprise application upstream of MIRAGE.
  - Tenant configuration: `pii_detection_enabled: true/false` (default: true for flagging).
  - PII patterns are never logged, even in encrypted MongoDB traces — only the PII type and count are logged.

### 4.4 Data Classification

| Classification | Examples | Handling |
|---|---|---|
| Critical | Raw prompts/responses, API keys, DB credentials | Encrypted at rest + transit, access logged, retention enforced |
| High | Verification traces, knowledge base documents, HRS data | Encrypted at rest + transit, RBAC enforced |
| Medium | Aggregate drift metrics, audit reports | Encrypted at rest, RBAC enforced |
| Low | System health metrics, anonymized performance data | Standard storage, no special restrictions |

### 4.5 Backup RPO/RTO Targets

To ensure high availability and prevent data loss, MIRAGE adheres to strict backup and recovery targets:

- **RPO (Recovery Point Objective)**: 1 hour — maximum acceptable data loss window
- **RTO (Recovery Time Objective)**: 4 hours — maximum acceptable downtime
- **PostgreSQL**: Automated daily snapshots + continuous WAL archiving to S3 (point-in-time recovery within RPO)
- **MongoDB Atlas**: Continuous backup with point-in-time recovery (built-in)
- **Qdrant**: Daily snapshot to S3 (knowledge base data is re-indexable from source documents if needed)
- **Redis**: No backup needed — cache data is ephemeral and reconstructable
- **RabbitMQ**: Mirrored queues ensure no message loss; persistent messages survive broker restart
- **S3**: Cross-region replication for audit PDFs and model weights
- **Recovery Testing**: Full disaster recovery procedure is documented and tested quarterly.

---

## 5. Secrets Management

To guarantee operational security, no credentials exist in application code, version control, or plaintext environment variables. 

- **AWS Secrets Manager** is the single source of truth for all secrets, including:
  - Database credentials (PostgreSQL, MongoDB)
  - API keys (LLM providers)
  - Redis AUTH password
  - RabbitMQ credentials
  - JWT signing keys
  - mTLS private keys
- **Secret Injection**: Secrets are injected into containers at runtime securely via AWS ECS task definitions or Kubernetes secrets (synced directly from AWS Secrets Manager).
- **Hard Constraints**: 
  - NO secrets in environment variables in plain text.
  - NO secrets in Docker images.
  - NO secrets in Git.
- **Secret Rotation Policy**:
  - Database credentials rotated every 90 days.
  - JWT signing keys rotated every 180 days.
  - API keys rotated on demand.
- **Emergency Rotation Procedure**: In the event of a suspected compromise, an automated pipeline triggers immediate regeneration of the affected secret in AWS Secrets Manager, followed by a rolling restart of all dependent containers.

---

## 6. Network Security

### 6.1 Network Architecture

```text
Internet
    │
    ▼
┌──────────────────────────────┐
│   AWS Application Load       │
│   Balancer (Public Subnet)   │
│   TLS Termination            │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│   MIRAGE Gateway             │
│   (Private Subnet)           │
│   Security Group: 443 in     │
└──────────────┬───────────────┘
               │
    ┌──────────┼──────────┬─────────────────┐
    ▼          ▼          ▼                 ▼
┌────────┐ ┌────────┐ ┌────────┐       ┌────────────┐
│RAV     │ │SCS     │ │Visual  │       │FLAN-T5     │
│Worker  │ │Worker  │ │Worker  │       │Decomposer  │
│(Priv.) │ │(Priv.) │ │(Priv.) │       │(Priv.)     │
└────────┘ └────────┘ └────────┘       └────────────┘
                            (G5.2xlarge / NVIDIA A10G)
               │
    ┌──────────┼──────────┬─────────────────┬─────────────────┐
    ▼          ▼          ▼                 ▼                 ▼
┌────────┐ ┌────────┐ ┌────────┐       ┌────────────┐    ┌────────────┐
│Postgres│ │MongoDB │ │Qdrant  │       │Grafana     │    │AWS Secrets │
│(Priv.) │ │(Priv.) │ │(Priv.) │       │Tempo & OTel│    │Manager     │
└────────┘ └────────┘ └────────┘       └────────────┘    └────────────┘
```

- **Public subnet**: Only the AWS ALB and NAT Gateway are in the public subnet
- **Private subnet**: All MIRAGE services, databases, caches, and metric collectors are in private subnets with no direct internet ingress
- **Egress**: Only the gateway and worker services have egress access (for LLM API calls). Databases and models have no internet egress.
- **Security Groups**: Each service has its own security group allowing only the specific ports from specific source security groups required for its function

### 6.2 Security Group Rules

| Service | Inbound | Outbound |
|---|---|---|
| ALB | 443 from 0.0.0.0/0 | Gateway SG on 8000 |
| Gateway | 8000 from ALB SG, 8000 from Dashboard SG | Workers SG, LLM APIs (443), Redis (6379) |
| Workers | Worker port from Gateway SG only | NLI Model SG, PostgreSQL SG, MongoDB SG, Qdrant SG, S3 endpoint |
| NLI Model Server | 8080 from Workers SG only | None |
| PostgreSQL | 5432 from Gateway SG + Workers SG only | None |
| MongoDB | 27017 from Workers SG only | None |
| Qdrant | 6333 from Workers SG only | None |
| Redis | 6379 from Gateway SG + Workers SG only | None |

### 6.3 DDoS Protection

- AWS Shield Standard enabled on ALB (included, no additional cost)
- Rate limiting at application layer (see Section 7.2) as first line of defense
- ALB connection draining and request throttling configured
- **Circuit breakers** (via `pybreaker`) in gateway — if upstream LLM API is unavailable, requests are queued and tenants receive 503 with retry-after header rather than cascading failure

---

## 7. API Security

### 7.1 Input Validation

All API inputs are validated before processing:

- Configuration managed securely via `pydantic-settings`
- Request body size limit: 2MB maximum (prevents oversized payload attacks)
- JSON schema validation on all endpoints using Pydantic v2 models with strict mode
- String fields: maximum length enforced, HTML/script tags stripped
- Image inputs: file type validation (MIME type + magic bytes check), maximum 10MB per image
- Knowledge base document uploads: PDF/DOCX only, virus scan via ClamAV before indexing

### 7.2 Rate Limiting

Rate limiting is applied per tenant API key using a sliding window algorithm in Redis:

| Endpoint | Limit | Window |
|---|---|---|
| POST /v1/verify | 60 requests | 1 minute |
| POST /v1/verify | 500 requests | 1 hour |
| POST /v1/kb/upload | 10 requests | 1 hour |
| GET /v1/sessions/* | 200 requests | 1 minute |
| POST /v1/reports/generate | 5 requests | 1 hour |
| WebSocket /v1/verify/stream | 20 connections | concurrent per tenant |
| WebSocket messages | 30 messages | per minute per connection |
| All endpoints | 1000 requests | 1 hour (hard cap) |

Rate limit responses include:
```
HTTP 429 Too Many Requests
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1725369600
Retry-After: 43
```

### 7.3 CORS Policy

```python
# Gateway CORS configuration
allowed_origins = [
    "https://dashboard.mirage-ai.internal",  # Dashboard
    "https://*.tenant-domain.com",            # Configurable per tenant
]
allow_credentials = True
allow_methods = ["GET", "POST", "DELETE"]
allow_headers = ["Authorization", "Content-Type", "X-Tenant-ID"]
```

### 7.4 Security Headers

All API responses include proper security headers. 

```text
Content-Security-Policy for API endpoints:
  default-src 'none'

Content-Security-Policy for Dashboard:
  default-src 'self';
  script-src 'self';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: https:;
  font-src 'self';
  connect-src 'self' wss://dashboard.mirage-ai.internal;
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self'
```
*(Other headers included: `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control`)*

### 7.5 WebSocket Security

For real-time verification streaming, WebSockets implement dedicated security controls:

- **Authentication**: Connections are authenticated via a JWT token sent in the *first message* payload (not in the URL parameter, to prevent token logging).
- **Encryption**: WSS (TLS) is mandatory — plaintext WebSocket connections are immediately rejected.
- **Rate Limiting**: Maximum 5 concurrent WebSocket connections allowed per tenant.
- **Connection Lifecycle**: Idle timeout set to 30 minutes with mandatory ping/pong keepalives.
- **Payload Limits**: Message size limit strictly enforced at 2MB.
- **Validation**: Origin validation checked against the tenant-configured allowed origins.

### 7.6 Prompt Injection Defense

MIRAGE intercepts LLM responses that may contain adversarial content designed to manipulate downstream systems. The following controls are applied:

- LLM response content is **never evaluated as code** at any point in the pipeline
- Claim decomposition uses a sandboxed LLM call with a strict system prompt that explicitly refuses instruction-following from the content being decomposed
- All LLM outputs processed through MIRAGE are treated as **untrusted data**, never as instructions
- Correction agent prompt templates use strict templating with explicit delimiters to prevent injection from evidence chunks

---

## 8. Model and AI Security

### 8.1 Model Security

All model artifacts (DeBERTa Verifier on TorchServe, FLAN-T5 Decomposer, LLaVA Visual Grounder on TGI) follow strict security controls:

- Infrastructure: Models are hosted on AWS G5.2xlarge instances (NVIDIA A10G, 24GB VRAM) for secure, hardware-accelerated inference.
- Model weights stored in S3 with SSE-KMS encryption, one KMS key per model type.
- Model artifacts signed using AWS Signer before deployment — signature verified on load.
- Each model runs in a dedicated Docker container with read-only filesystem (except model cache directory).
- No network egress from any model server container — inference requests arrive only via internal mTLS from workers.
- FLAN-T5 decomposer: additionally hardened with seccomp profile to block all syscalls not required for Python inference.
- LLaVA-1.6 (via TGI): runs with 4-bit bitsandbytes quantization — model loaded into GPU memory only, never written to disk in plaintext during serving.

### 8.2 Training Data Security

- HaluEval, TruthfulQA, MNLI, FActScoring, and MMHAL-Bench datasets downloaded from official sources with SHA-256 checksum verification before any use.
- Synthetic training data generated in an isolated environment — no real enterprise customer data used at any point in training.
- Training runs on institute GPU server with SSH access restricted to 23AIML042 (Vedant) and 23AIML076 (Dax) only.
- Model checkpoints encrypted with AES-256 (SSE-KMS) before upload to S3; plaintext weights never leave the training host.
- FLAN-T5 and DeBERTa model artifacts separately versioned with semantic versioning and independently signed.

### 8.3 Adversarial Robustness

Known attack vectors against MIRAGE's verification pipeline and multi-layered mitigations:

| Attack Vector | Description | Multi-Layered Mitigation Strategy |
|---|---|---|
| **ATK-01: Epistemic Hedging** | Response prefixes factual falsehoods with doubt ("It is hypothesized that X...") to force NLI neutrality. | DeBERTa verifier fine-tuned on synthetic hedged negatives; gateway normalizer strips common hedging phrases before claim-evidence comparison; LightGBM meta-learner combines NLI with RAV retrieval strength. |
| **ATK-02: Stated Confidence Posturing** | Attacker crafts authoritative phrasing ("As an established clinical fact confirmed by all doctors...") to mask hallucinations. | SCS measures Semantic Entropy across n=5 samples at temperature=0.7 — semantic divergence is invariant to superficial authoritative framing; LightGBM discounts linguistic confidence cues. |
| **ATK-03: Hallucinated Citations** | Response fabricates academic papers, journals, or author names to fake grounding. | RAV executes strict vector search against the tenant's verified Qdrant knowledge base; ungrounded citations fail semantic matching and trigger elevated Retrieval Support Score ($RSS > 0.85$) with warning metadata. |
| **ATK-04: Knowledge Base Evidence Poisoning** | Malicious document uploaded to the tenant collection to force positive verification of falsehoods. | Document provenance verification, ClamAV scanning, SHA-256 integrity checks; multi-signal resilience ensures that high SCS Semantic Entropy and ICS intra-response contradiction flag the response even if a single poisoned KB chunk matches. |
| **ATK-05: Intra-Response Inconsistency** | Model generates mutually contradictory claims within a single completion (arithmetic or chronological conflict). | Internal Consistency Scorer (ICS) executes pairwise NLI across all claims in the response; conflicting facts elevate $ICS_{\text{resp}}$ and trigger LangGraph correction loop. |
| **ATK-06: FLAN-T5 Prompt Injection** | Attacker crafts response text attempting to hijack claim decomposition instructions. | FLAN-T5 is fine-tuned strictly on constrained seq2seq claim extraction, not generic instruction-following; output JSON schema is strictly validated by Pydantic before pipeline entry. |
| **ATK-07: LLaVA Visual Manipulation** | Adversarially perturbed image designed to fool multimodal VLM grounding. | Adaptive CLIP pre-filter runs independently as an architectural counter-weight; visual uncertainty verdicts (`INSUFFICIENT_EVIDENCE`) default to neutral risk with operator alerts. |

### 8.4 Model Versioning and Rollback

- All three model artifacts versioned with semantic versioning and stored independently in S3 under separate prefixes.
- TorchServe supports zero-downtime model version switching for DeBERTa.
- TGI supports version rolling for LLaVA.
- Rollback procedure: update model version pointer in config service → hot-swap on model server → run automated ECE/F1 benchmark verification → mark stable.
- A model rollback never requires redeployment of any other system component.

---

## 9. Multi-Tenant Isolation

### 9.1 Data Isolation Design

Multi-tenant isolation is enforced at every layer of the stack:

**PostgreSQL**: Row-level security (RLS) enabled on all tables. Every query from the application layer includes `tenant_id` in the WHERE clause. RLS policies enforce that even if application code has a bug, a tenant can never read another tenant's rows.

```sql
-- Example RLS policy on verification_sessions
ALTER TABLE verification_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON verification_sessions
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

**MongoDB**: Each tenant's verification traces are stored in a separate collection (`traces_{tenant_id}`). Application-level tenant_id scoping is applied before all queries as an additional control.

**Qdrant**: Each tenant has a dedicated Qdrant collection (`kb_{tenant_id}`). The RAV module is initialized with only the tenant's collection ID and cannot query other collections by design.

**Redis**: All tenant-specific keys are namespaced with tenant_id prefix. SCS cache keys include both tenant_id and model_id to prevent cross-tenant cache pollution. Redis AUTH is enforced with TLS.

**S3**: Each tenant has a dedicated S3 prefix (`/{tenant_id}/`). S3 bucket policy enforces that MIRAGE's IAM role can only access paths matching the authenticated tenant's prefix.

### 9.2 Tenant Onboarding Security Checklist

- [ ] API key generated with cryptographically secure random source
- [ ] Only SHA-256 hash stored in database
- [ ] Dedicated Qdrant collection created and scoped
- [ ] S3 prefix created with tenant-specific KMS key
- [ ] RLS context configured in PostgreSQL connection pool
- [ ] Default HRS threshold and rate limits applied
- [ ] Welcome email sent to tenant admin with key (single transmission)
- [ ] Admin panel access credentials provisioned with minimum required role

---

## 10. Audit and Compliance

### 10.1 Audit Logging

Every security-relevant action in MIRAGE is logged to a tamper-evident audit log stored in a separate PostgreSQL schema with append-only access. `structlog` is used throughout the pipeline to enforce strictly typed JSON logging.

Events logged:

| Event | Details Captured |
|---|---|
| API key authentication (success/failure) | tenant_id, source IP, timestamp, user agent |
| Rate limit exceeded | tenant_id, source IP, endpoint, timestamp |
| Verification session created | session_id, tenant_id, model_id, hrs, conformal_ci, timestamp |
| Correction loop triggered | session_id, hrs, flagged_claim_count, correction_attempt_count, timestamp |
| SCS cache hit | session_id, tenant_id, prompt_hash, timestamp |
| Knowledge base document uploaded | tenant_id, document_hash, clamav_scan_result, timestamp |
| Data deletion request | tenant_id, requestor_id, timestamp, scope |
| Model version changed | model_type, previous_version, new_version, changed_by, timestamp |
| Security alert triggered | alert_type, tenant_id, threshold_breached, current_value, timestamp |

### 10.2 Audit Log Integrity

- Audit log table has no UPDATE or DELETE grants for any application service account.
- Each audit log entry includes a SHA-256 chain hash of the previous entry — modification of any historical entry breaks the chain and is detectable.
- Audit logs are replicated to S3 as immutable objects (S3 Object Lock with COMPLIANCE mode).

### 10.3 Compliance Posture

| Standard | MIRAGE Posture |
|---|---|
| GDPR | Data minimization, right to deletion, configurable retention, encrypted storage, right to portability |
| ISO 27001 | Access control, encryption, audit logging, incident response |
| SOC 2 Type II | Security, availability, confidentiality principles addressed |
| DPDP Act (India) | Data localization configurable, consent for retention, right to erasure |

### 10.4 Log Rotation and Archival Policy

- **Application Logs** (`structlog` JSON): Rotated daily, retained for 30 days in AWS CloudWatch Logs, then automatically archived to S3 Glacier.
- **Audit Logs** (PostgreSQL): Partitioned by month. Partitions older than the retention window (default 90 days) have their chain hash integrity verified, are archived to S3 Object Lock, and then dropped from the active database.
- **Verification Traces** (MongoDB): Enforces retention strictly at the database level via a TTL index on the `created_at` field.
- **Metrics**: 15-day retention in Prometheus, followed by long-term storage in Grafana Mimir or Thanos (30-day retention) for robust drift analysis over time.

### 10.5 GDPR Right to Portability (Data Export)

- Tenants can request a full data export via the admin panel.
- **Export Includes**: All verification sessions, HRS scores, audit logs, and knowledge base document metadata (derived vectors are excluded).
- **Export Format**: JSON Lines (.jsonl) contained within a ZIP archive.
- Export generation is processed asynchronously. The tenant receives a secure download link via email within 24 hours.
- Strict RLS ensures the export definitively does NOT include any other tenants' data.

### 10.6 OpenTelemetry Security Considerations

- OpenTelemetry is used for distributed tracing across the microservices.
- Trace data may contain `tenant_id` and session metadata, and is stored securely in **Grafana Tempo** with the same access controls applied to application data.
- **Trace Retention**: 7 days (traces are for operational debugging, not compliance auditing).
- No prompt or response content is ever included in trace spans — spans contain only content hashes, network latencies, and HTTP status codes.
- Access to Grafana Tempo is strictly restricted to the Super Admin and Operator roles only.

---

## 11. Incident Response

### 11.1 Severity Classification

| Severity | Definition | Response Time |
|---|---|---|
| P0 — Critical | Active data breach, service fully down, API key compromise at scale | Immediate (< 15 minutes) |
| P1 — High | Single tenant data leak, verification pipeline failure, model server down | < 1 hour |
| P2 — Medium | Rate limiting failure, single endpoint unavailable, audit log gap | < 4 hours |
| P3 — Low | Performance degradation, non-security bug, minor feature unavailability | < 24 hours |

### 11.2 Incident Response Procedure

**Detection**:
- Prometheus/Grafana alerts for anomalous patterns (error rate spike, unusual HRS distribution)
- AWS CloudTrail alerts for unusual IAM activity
- Database slow query alerts for potential data extraction attempts

**Containment**:
1. Identify affected tenant(s) and scope of impact
2. If API key compromise suspected: revoke active keys, issue new keys
3. If data breach suspected: isolate container, preserve logs, snapshot databases
4. If model server compromised: immediately take offline, fail back to RAV-only mode

**Eradication & Recovery**:
1. Root cause analysis using audit logs and application traces
2. Patch or rollback affected component; rotate relevant credentials
3. Restore service from clean snapshot or redeploy verified container image
4. Verify audit log chain integrity post-recovery
5. Notify affected tenants within 72 hours (GDPR requirement)

---

## 12. Security Testing Plan

### 12.1 Static Analysis

| Tool | Target | Frequency |
|---|---|---|
| Bandit | Python source code — security anti-patterns | Every commit (CI) |
| Safety | Python dependency CVE scan | Every commit (CI) |
| Semgrep | Custom rules for MIRAGE-specific patterns | Every PR merge |
| Trivy | Docker container image CVE scan | Every image build |
| npm audit | React dashboard dependencies | Every commit (CI) |

### 12.2 Dynamic & Penetration Testing

- **OWASP ZAP scan**: Automated API security scan against staging (Weekly)
- **SQL injection & Rate limit testing**: Verified against staging environments (Monthly)
- **mTLS & Tenant isolation**: Verified via automated test suites on every deployment
- **Prompt injection tests**: Adversarial LLM response payloads against full pipeline (Monthly)
- **Penetration Testing**: Planned for Month 5. Scope includes API gateway, dashboard, multi-tenant isolation, and KB upload. Output includes findings report with severity classification.

---

## 13. Role-Based Access Control (RBAC)

### 13.1 Roles

| Role | Description | Who Has It |
|---|---|---|
| Super Admin | Full system access, tenant management, security config | Project team only |
| Tenant Admin | Full access to their tenant's data, users, config, reports | Enterprise tenant admins |
| Operator | View dashboard, query logs, acknowledge alerts, cannot delete | Enterprise ops team |
| Viewer | Read-only access to drift dashboard and aggregate metrics | Stakeholders |
| API Client | Programmatic access via API key for verification calls only | Enterprise applications |

### 13.2 Permission Matrix

| Permission | Super Admin | Tenant Admin | Operator | Viewer | API Client |
|---|---|---|---|---|---|
| Call verification API | ✓ | ✓ | ✗ | ✗ | ✓ |
| View drift dashboard | ✓ | ✓ | ✓ | ✓ | ✗ |
| Query audit logs | ✓ | ✓ | ✓ | ✗ | ✗ |
| Upload knowledge base | ✓ | ✓ | ✗ | ✗ | ✗ |
| Manage tenant users | ✓ | ✓ | ✗ | ✗ | ✗ |
| Configure system / View other | ✓ / ✗ | ✗ / ✗ | ✗ / ✗ | ✗ / ✗ | ✗ / ✗ |

*(Cross-tenant data access is architecturally prevented for all roles, including Super Admins.)*

---

## 14. Third-Party and Dependency Security

### 14.1 Third-Party Service Trust

- **AWS**: Primary infrastructure provider. Shared responsibility model applies.
- **Hugging Face**: Used strictly for model downloads. All artifacts are SHA-256 checksum-verified against the official model card prior to execution.
- **Weights & Biases**: Used for experiment tracking. Logs contain ONLY metrics and hyperparameters — no training data samples or model outputs are shipped externally.
- **LLM API Providers**: MIRAGE sends prompt data to the configured LLM API provider for the primary call and SCS sampling. Default development providers are **Groq** (free tier), **OpenRouter** (free models), and **Hugging Face Inference API** (free tier). Enterprise tenants may configure OpenAI, Anthropic, or any OpenAI-compatible provider.
  - All providers are accessed via TLS 1.3 and the OpenAI-compatible Chat Completions API format.
  - Tenants must explicitly acknowledge prompt transmission in their service agreement.
  - SCS uses the same provider and key as the primary call, minimizing external trust surface.
  - Tenants can opt to disable SCS (`scs_enabled: false`) if they require limiting API calls strictly to one per verification.
- **Groq**: Used as the primary free-tier LLM inference provider. Runs open-source models (Llama, Mixtral) on Groq-proprietary LPU hardware. Groq's API does not store or train on user inputs per their data policy.

### 14.2 Dependency Management

| Category | Policy |
|---|---|
| Python dependencies | Python 3.12, pinned versions, updated via Dependabot, Safety scanned |
| Base Frameworks | `pydantic-settings` for config, `Alembic` for migrations |
| Docker base images | `python:3.12-slim`, rebuilt weekly with latest OS patches |
| Database drivers | Pinned versions, TLS connections enforced |

An SBOM is generated for every production release using Syft and stored in S3.

### 14.3 Dependency Vulnerability SLA

- **Critical CVE**: Patch deployed within 48 hours.
- **High CVE**: Patch deployed within 7 days.
- **Medium CVE**: Patch deployed within 30 days.
- **Low CVE**: Patch deployed in the next scheduled maintenance window.

---

## 15. Docker and Container Security

All MIRAGE microservices and models execute within heavily restricted Docker containers:

- **Base Images**: Built exclusively from official `python:3.12-slim` minimal base images.
- **Execution User**: All containers run as a non-root user (USER `1000:1000`). Root execution is explicitly forbidden.
- **Filesystem**: Containers enforce a read-only root filesystem. Explicit writable volume mounts are granted only for required model cache and temporary processing directories.
- **Capabilities**: All default Linux capabilities are dropped (`--cap-drop=ALL`). Only `NET_BIND_SERVICE` is added back if functionally required.
- **Docker Content Trust**: Enabled across the CI pipeline to ensure only cryptographically signed images are deployed.
- **Host Security**: Seccomp and AppArmor profiles are applied to restrict syscalls.

---

## 16. Security Training and Awareness

- **OWASP Top 10 Review**: Both project members (Vedant, Dax) must complete a comprehensive review of the OWASP Top 10 vulnerabilities before Month 1.
- **Code Review**: A rigorous security review checklist is enforced on every Pull Request that touches authentication, RBAC, or data access code.
- **Incident Response Drill**: An interactive incident response tabletop exercise is conducted once during Month 4 to ensure readiness.

---

## 17. Security Checklist

### 17.1 Pre-Deployment Checklist

- [ ] AWS Secrets Manager secrets provisioned and rotated from defaults
- [ ] OpenTelemetry collector receiving traces from all services
- [ ] Grafana Tempo accessible and retaining traces securely
- [ ] Alembic migrations run successfully against production PostgreSQL database
- [ ] All containers verified running as non-root
- [ ] Docker Content Trust signatures verified on all images
- [ ] Verify Visual worker and NLI model server deployed on AWS G5.2xlarge (NVIDIA A10G) instances
- [ ] RabbitMQ AMQPS (TLS) enforced, plaintext disabled
- [ ] TLS certificates installed and verified on ALB
- [ ] mTLS certificates generated and distributed to all services
- [ ] FLAN-T5 and LLaVA container network egress confirmed disabled
- [ ] S3 buckets have public access blocked at account level
- [ ] PostgreSQL RLS policies enabled and tested
- [ ] Qdrant collections scoped and tested
- [ ] SCS Redis cache key namespacing verified
- [ ] Rate limiting rules tested with automated script
- [ ] Audit log append-only access verified
- [ ] Bandit, Safety, and Trivy scans pass with no high/critical findings
- [ ] Conformal prediction coverage verified on held-out test set
- [ ] Backup and restore procedure tested

---

## 18. Document Changelog

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | Aug 2026 | Vedant | Initial draft of Security Document |
| 1.1.0 | Sep 2026 | Dax/Vedant | CMCS terminology updated to SCS. Added Secrets Management, WebSocket Security, Backup RPOs, Container Security hardening, Vulnerability SLAs, Data Export policies, OpenTelemetry privacy rules, and upgraded target GPU to A10G. |
| 2.1.0 | Sep 2026 | Dax/Vedant | Advanced Research Overhaul: Added explicit threat models and multi-signal defenses for Epistemic Hedging (ATK-01), Stated Confidence Injection (ATK-02), Hallucinated Citations (ATK-03), Knowledge Base Evidence Poisoning (ATK-04), and Intra-Response Inconsistencies (ATK-05). |

*Document ends. Next review scheduled: October 2026.*
*All security decisions are subject to revision as the threat landscape evolves during the 6-month development period.*
