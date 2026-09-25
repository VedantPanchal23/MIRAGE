# ADR 0005: REST API Contracts, Object Storage Abstraction & Asynchronous Ingestion/Reporting Architecture

## Status
Ratified

## Context
Phase P1 focuses on completing, reconciling, and certifying the REST API contracts required by `Technical_Architecture.md` §8.2, `PRD.md` (FR-GW-01..05, FR-DFT-01..05, FR-AUD-01..04), and `Security_Access.md` §7, §10, §13.

In Phase P0 (P0.1–P0.6), the platform's multi-tier foundation was hardened:
- **P0.1**: Cryptographic JWT + API Key auth, RBAC enforcement, and ASGI header sanitization (`HeaderSanitizationMiddleware`).
- **P0.2**: PostgreSQL 16 persistence with Row-Level Security (`mirage_app`), MongoDB 7 execution trace storage, and SHA-256 audit chaining.
- **P0.3**: Per-dependency circuit breakers (`pybreaker`) with graceful fallback modes.
- **P0.4**: Distributed Redis 7.2 state (DB0 SCS cache, DB1 token-bucket rate limiter) with zero production in-memory state.
- **P0.5**: RabbitMQ 3.13 Quorum queues (`mirage.verify`, `mirage.drift`, `mirage.ingest`), Celery persistent daemon, and dead-lettering (`mirage.dlx`).
- **P0.6**: 13-container Docker Compose production topology with OTel Collector and zero host-exposed stateful ports.

However, several architectural gaps and contract inconsistencies must be explicitly resolved before implementing Phase P1 REST endpoints:
1. **S3 vs Local Storage Contradiction**: `Technical_Architecture.md` §7.5 and `Security_Access.md` §4 mandate `s3://mirage-audit/{tenant_id}/{report_id}.pdf`. In development and test environments, an AWS S3 bucket is not natively available, but hardcoding raw local filesystem paths directly violates the canonical specification.
2. **Report Generation Execution Model & Idempotency**: TAD §8.2 lists `POST /v1/reports/generate` and `GET /v1/reports/{id}/pdf` as separate endpoints, but does not define sync vs. async threshold rules or duplicate task handling.
3. **Operator Alerts Specification & Lifecycle**: TAD §8.2 specifies `GET /v1/alerts`, and `Security_Access.md` §13.1 grants the `Operator` role the responsibility to "acknowledge alerts", but neither the acknowledgment route nor the alert lifecycle states are defined in the schema.
4. **Knowledge Base Queue Bypass**: In the existing codebase, `POST /v1/knowledge-base/upload` runs synchronously in-process via `_kb_service.ingest_document()`, bypassing the durable `mirage.ingest` Quorum queue established in P0.5.
5. **RBAC Permission Mapping**: Granular permissions must align with the actual P0.1 implementation (`shared/schemas/auth.py`) without inventing arbitrary unvetted permission names.
6. **Session Retrieval Authority & Degradation**: `GET /v1/sessions/{id}` must navigate the PostgreSQL relational boundary and the MongoDB trace boundary with deterministic degradation semantics.

---

## Decisions

### 1. Object Storage Abstraction (`ObjectStorageService`)
To satisfy `Technical_Architecture.md` §7.5 while supporting seamless local development and integration testing:
- An abstract `ObjectStorageService` base class is defined with standard object-storage primitives:
  - `put_object(bucket: str, key: str, data: bytes, content_type: str, metadata: dict | None = None) -> str`
  - `get_object(bucket: str, key: str) -> tuple[bytes, str]`
  - `delete_object(bucket: str, key: str) -> bool`
  - `generate_presigned_url(bucket: str, key: str, expires_in: int = 3600) -> str`
- Two driver implementations are provided:
  1. **`S3StorageDriver`**: Used in production and AWS cloud deployments via `boto3` / `aioboto3`, utilizing server-side encryption (`SSE-KMS` or `SSE-S3`) and enforcing per-tenant prefix scoping `s3://mirage-audit/{tenant_id}/{report_id}.pdf`.
  2. **`LocalStorageDriver`**: Used in local development, testing, and CI. It strictly preserves the exact same bucket-and-key hierarchy (`<storage_root>/mirage-audit/{tenant_id}/{report_id}.pdf`), ensuring that higher-level application code never references local file paths directly.
- Direct filesystem writes in production route handlers are strictly prohibited.

### 2. PDF Rendering Engine Selection: ReportLab
- `reportlab` is selected as the canonical compliance PDF generation engine for MIRAGE.
- **Rationale**:
  - Pure-Python implementation with zero headless browser dependencies (unlike Puppeteer/Playwright) and zero C-library runtime headaches (unlike WeasyPrint/cairo on Alpine/Debian slim).
  - High performance: Compiles comprehensive tabular compliance reports with embedded SHA-256 signatures, headers, and conformal intervals in $<100$ms.
  - Generates compact, standard PDF documents suitable for streaming and archival.

### 3. Asynchronous Report Execution & Idempotency Architecture
- **Execution Model**: `POST /v1/reports/generate` is strictly asynchronous for date-range compliance reports:
  1. Validates the requested date range, model filters, and rate limit (Security_Access §7.1: 5 req/hr).
  2. Inserts a row in PostgreSQL `audit_reports` with status `PENDING`.
  3. Dispatches Celery task `workers.tasks.generate_report_task` to RabbitMQ Quorum queue `mirage.reports` with publisher confirms.
  4. Returns `HTTP 202 Accepted` with:
     ```json
     {
       "report_id": "rep_3f1a2b0c",
       "tenant_id": "tenant_123",
       "status": "PENDING",
       "poll_url": "/v1/reports/rep_3f1a2b0c",
       "download_url": "/v1/reports/rep_3f1a2b0c/pdf"
     }
     ```
- **Single-Session Report Endpoint**: `GET /v1/audit/report/{session_id}/pdf` provides on-demand synchronous compilation and streaming for individual session verification certificates.
- **API Idempotency**: A deterministic request hash `sha256(tenant_id + start_date + end_date + model_id + risk_tier)[:16]` is computed. If an identical report exists for the tenant within a 1-hour window and is `PENDING`, `PROCESSING`, or `COMPLETED`, the gateway returns the existing record rather than enqueuing duplicate work.
- **Task Idempotency**: The worker acquires a row-level lock (`SELECT ... FOR UPDATE`) on the `audit_reports` table before compiling the PDF, preventing duplicate execution.
- **Failure Semantics**: If broker publishing fails, gateway returns `HTTP 503 Service Unavailable` with `Retry-After: 30`. If worker execution fails, Celery retries up to 3 times with exponential backoff; upon exhaustion, the task routes to `mirage.dlq` and marks the PostgreSQL report row `FAILED`.

### 4. Operator Alerts Lifecycle, Schema & Trigger Rules
- **Canonical Grounding**: `Technical_Architecture.md` §8.2 (`GET /v1/alerts`) and `PRD.md` `FR-DFT-04`.
- **Supporting Route**: `POST /v1/alerts/{id}/acknowledge` is formally ratified as a supporting endpoint enabling the `Operator` role to fulfill the responsibilities defined in `Security_Access.md` §13.1.
- **Alert Lifecycle**:
  - `ACTIVE`: Created automatically when operational thresholds are breached.
  - `ACKNOWLEDGED`: Operator acknowledges receipt via `POST /v1/alerts/{id}/acknowledge`. Recorded with `acknowledged_at` and `acknowledged_by`.
  - `RESOLVED`: System marks alert resolved when the triggering condition clears during subsequent drift evaluations.
- **Trigger Conditions**:
  1. *Canonical (PRD FR-DFT-04)*: 7-day rolling average HRS exceeds the tenant's configured threshold (default: $HRS > 0.25$).
  2. *Operational (ADR 0003/0004)*: Dependency circuit breaker trips `OPEN` (Qdrant, Redis, RabbitMQ, LLM API).
  3. *Operational (PRD §11)*: Critical risk surge where $>3$ consecutive verifications in a 5-minute window score in the `CRITICAL` tier ($HRS > 0.80$).
- **Deduplication**: Active alerts of the same `alert_type` for the same tenant are deduplicated within a 1-hour rolling window to avoid alert storms.
- **Persistence**: Persisted in PostgreSQL table `operator_alerts` with Row-Level Security (`ALTER TABLE operator_alerts ENABLE ROW LEVEL SECURITY`).

### 5. Knowledge Base Upload Queue Semantics & Duplicate Handling
- **Queue Preservation**: In-process synchronous ingestion in `POST /v1/kb/upload` is eliminated. All uploads strictly enqueue `workers.tasks.ingest_document_task` to the durable RabbitMQ Quorum queue `mirage.ingest`.
- **Payload & File Constraints**:
  - Maximum payload size: 10MB (enforced at gateway boundary; returns `HTTP 413 Payload Too Large`).
  - Supported formats: `.txt`, `.md`, `.pdf`, `.docx`.
  - Empty files or whitespace-only documents are rejected with `HTTP 400 Bad Request`.
- **Duplicate Handling**: Document contents are hashed with SHA-256 (`content_hash`). If a document with the same filename and identical content hash already exists for the tenant, the gateway returns the existing document record (`HTTP 200 OK`) without re-indexing. If the content differs, the existing document chunks are purged and the new document is queued (`HTTP 202 Accepted`).
- **Canonical Routing & Backward Compatibility**:
  - `POST /v1/kb/upload` is the primary canonical endpoint.
  - `GET /v1/kb/documents` and `DELETE /v1/kb/documents/{document_id}` are canonical aliases.
  - Existing `/v1/knowledge-base/*` paths are preserved as backward-compatible routes.

### 6. RBAC Permission Mapping & Extensions
- Permissions in `shared/schemas/auth.py` are extended minimally and semantically:
  - Add `Permission.ALERTS_ACKNOWLEDGE = "alerts:acknowledge"`.
    - Granted to: `Role.OPERATOR`, `Role.TENANT_ADMIN`, `Role.SUPER_ADMIN`.
  - Add `Permission.KB_READ = "kb:read"`.
    - Granted to: `Role.OPERATOR`, `Role.AUDITOR`, `Role.VIEWER`, `Role.TENANT_ADMIN`, `Role.SUPER_ADMIN`.
- Existing permissions are reused for all other endpoints:
  - `GET /v1/sessions/{id}` $\to$ `Permission.VERIFY_READ` / `Permission.AUDIT_READ`.
  - `POST /v1/reports/generate` $\to$ `Permission.AUDIT_EXPORT`.
  - `GET /v1/reports/{id}` $\to$ `Permission.AUDIT_READ`.
  - `GET /v1/reports/{id}/pdf` $\to$ `Permission.AUDIT_EXPORT`.
  - `GET /v1/alerts` $\to$ `Permission.DASHBOARD_READ`.
  - `POST /v1/kb/upload` $\to$ `Permission.KB_WRITE`.

### 7. Session Retrieval Authority & Degradation Semantics (`GET /v1/sessions/{id}`)
- **Authority Boundary**: PostgreSQL is the primary authority. `GET /v1/sessions/{id}` queries PostgreSQL `verification_sessions` and related `ClaimRecord` rows. If the session does not exist in PostgreSQL for the authenticated tenant, return `HTTP 404 Not Found`.
- **Trace Enrichment**: MongoDB `traces_{tenant_id}` is queried using tenant-isolated collection routing for deep execution trace data (raw prompt, raw response, evidence chunks, PII metadata).
- **Graceful Degradation**: If MongoDB is unavailable or times out, the endpoint returns `HTTP 200 OK` with the complete relational session, relational claim records, `"trace": null`, and response header `X-Trace-Status: DEGRADED`. If PostgreSQL is unavailable, the endpoint returns `HTTP 503 Service Unavailable`.

---

## Consequences

### Positive
- Strict alignment with all governing documents (PRD, TAD, Security_Access).
- S3 compatibility preserved via `ObjectStorageService` without blocking local testing.
- Asynchronous report generation eliminates blocking HTTP timeouts on large audits.
- Ingestion strictly preserves the P0.5 RabbitMQ Quorum queue architecture.
- RBAC remains grounded and verifiable with explicit operator alert duties.
- Complete bidirectional OpenAPI contract testing prevents schema drift.

### Negative / Trade-offs
- Adding `operator_alerts` and `audit_reports` requires an Alembic migration (`003_alerts_and_reports.py`).
- Asynchronous report generation requires clients to handle `HTTP 202 Accepted` and poll `GET /v1/reports/{id}`.
- ReportLab must be added to project dependencies (`reportlab >= 4.2.0`).
