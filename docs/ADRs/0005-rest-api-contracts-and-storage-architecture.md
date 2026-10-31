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
- **Queue Preservation**: In-process synchronous ingestion in `POST /v1/kb/upload` is strictly eliminated in production. All uploads strictly enqueue `workers.tasks.ingest_document_task` to the durable RabbitMQ Quorum queue `mirage.ingest`. Passing `sync=true` in production is rejected with `HTTP 400 Bad Request`.
- **Payload & File Constraints**:
  - Maximum payload size: 10MB (enforced at gateway boundary; returns `HTTP 413 Payload Too Large`).
  - Supported formats: `.txt`, `.md`, `.pdf`, `.docx`.
  - Empty files or whitespace-only documents are rejected with `HTTP 400 Bad Request`.
- **Persistent Deduplication & Upload Atomicity Invariant**:
  - Authoritative persistence in PostgreSQL table `kb_documents` with tenant-scoped Row-Level Security (`ALTER TABLE kb_documents ENABLE ROW LEVEL SECURITY`).
  - Uniqueness invariant: `UniqueConstraint("tenant_id", "filename")` and Primary Key on `document_id`.
  - Document contents are hashed with SHA-256 (`content_hash`).
  - If a document with the same filename and identical `content_hash` already exists in PostgreSQL for the authenticated tenant:
    - If `status == "INDEXED"`, the gateway returns the existing document record (`HTTP 200 OK`, `status: "duplicate"`) without re-indexing or enqueuing tasks.
    - If `status == "PENDING"` (e.g. from an earlier unconfirmed publish), the gateway re-dispatches the ingestion task with the identical `generation` without burning a new generation sequence or creating duplicate rows.
  - **Pre-Dispatch Visibility Invariant**: To prevent the dispatch-before-database race condition (where a worker consumes immediately from RabbitMQ before the PostgreSQL row exists), the API Gateway records the authoritative `PENDING` row with an assigned `generation` in PostgreSQL *before* dispatching the task to RabbitMQ.
  - **Definitive Failure vs. Ambiguous Publish Outcome Classification**:
    - **Definitive Failure** (pre-transmission failure, socket connection refused, DNS error, or unreachable probe before dispatch): Zero frames reached RabbitMQ; no message was or will ever be queued. The gateway executes a compensating rollback in PostgreSQL (restoring the previous `INDEXED` state, content hash, and generation if updating an existing document, or deleting the pending row if creating a new document), and returns `HTTP 503 Service Unavailable` with `Retry-After: 30`. Compensation is provably safe.
    - **Ambiguous Publish Outcome** (publisher confirmation timeout, connection drop during confirm wait, or unverified operational failure after frame write): The message frame was transmitted across TCP and may already reside in the Quorum queue. The gateway **MUST NEVER** delete or revert the PostgreSQL `PENDING` record. Compensating deletion/reversion is strictly prohibited because the worker task may subsequently execute against the database. The gateway logs an ambiguous outcome warning and returns `HTTP 503 Service Unavailable` with `Retry-After: 30`.
  - **Worker Reconciliation & Task Idempotency**:
    - If an ambiguously published task was successfully queued, the worker executes against the retained `PENDING` record, indexes vectors under `{doc_id}_g{generation}_*`, commits `status = "INDEXED"`, and purges old generations.
    - If an ambiguously published task is delivered multiple times (or re-enqueued by client retry), the worker detects `generation == current_generation and status == "INDEXED"` with matching content hash and returns `idempotent_duplicate: True` without duplicate vector processing.
    - If a task executes and finds no record in PostgreSQL (`existing_rec is None`, e.g. following explicit document deletion or definitive compensation), the worker aborts with `status = "ABORTED"` without creating orphaned vector points.
  - **Crash-Safe Generation-Based Vector Replacement**:
    - Each document version is assigned a strictly monotonically increasing integer `generation`.
    - Chunk IDs in Qdrant are namespaced by generation (`{doc_id}_g{generation}_c{idx:03d}`) and tagged with `generation` and `doc_generation` (`{doc_id}:g{generation}`) in payload metadata.
    - When executing `ingest_document_task`, the Celery worker upserts the new generation's vectors into Qdrant *first* without deleting the previous generation.
    - The worker transitions PostgreSQL to `INDEXED` conditional on `generation`.
    - Old vector generations are purged from Qdrant *only after* the PostgreSQL transaction successfully commits.
    - If a crash, timeout, or Qdrant write failure occurs prior to database commit, the previous valid generation in Qdrant and PostgreSQL remains 100% intact (zero data-loss risk).
  - **Active-Generation Retrieval Invariant (Vector Visibility Guarantee)**:
    - Once PostgreSQL declares generation $N$ as the authoritative indexed generation, retrieval must never return vectors belonging to generation $< N$, even if post-commit cleanup has not completed or permanently fails.
    - In `workers/rav/worker.py:search_evidence`, retrieval queries PostgreSQL for all active `INDEXED` documents of the tenant and constructs an authoritative generation filter: `doc_generation in [f"{doc_id}:g{N}"]`.
    - Qdrant queries strictly filter by `tenant_id` and `doc_generation in allowed_tokens`. A defense-in-depth post-filter additionally verifies that returned chunks match the authoritative generation before being returned to callers.
    - Old generation cleanup is merely storage hygiene, not a correctness requirement.
  - **Bounded Recovery of Ambiguous PENDING Uploads**:
    - An ambiguous publish must not create a permanently stuck authoritative `PENDING` state.
    - Bounded state reconciliation (`reconcile_stale_pending_kb_documents` and `reconcile_kb_pending_task`) probes vector presence for records remaining in `PENDING` longer than a stale threshold (default 300s):
      - If vector points exist for `(tenant_id, document_id, generation)`, the record is promoted to `INDEXED`.
      - If vector points do not exist, the record is transitioned to `FAILED` (orphaned pending upload; publish unconfirmed).
    - Reconciliation is tenant-safe, preserves deterministic identities, never enqueues duplicate jobs, and never rolls back an already-indexed generation.
  - **Out-of-Order Execution & Stale Task Prevention**:
    - If concurrent divergent uploads for the same document execute out of order (e.g. Generation 2 runs before Generation 1), the worker checks PostgreSQL: if `doc.generation > task.generation`, the task is identified as superseded and discarded immediately without mutating PostgreSQL or storing stale vectors.
  - **Ephemeral Vector Emulation Boundary**:
    - The class-level `_shared_in_memory_docs` dictionary in `KnowledgeBaseIngestionService` is strictly an ephemeral test-only emulation used in local/CI environments lacking a live Qdrant container.
    - It is never authoritative for production KB metadata, deduplication, identity, indexing state, or tenant isolation (which are all strictly governed by PostgreSQL `KBDocumentRecord` and RLS). In production (`ENVIRONMENT="production"`), Qdrant is mandatory and in-memory fallback is disabled.
  - Concurrency is managed at the database engine level via PostgreSQL native `INSERT ... ON CONFLICT (tenant_id, filename) DO UPDATE`, preventing duplicate rows and race conditions across multiple gateway instances.
- **Deterministic Document & Chunk Identity**:
  - `doc_id` uses the full 256-bit SHA-256 digest: `doc_{sha256(tenant_id + ":" + filename)}` (68 characters), backed by the PostgreSQL `UniqueConstraint("tenant_id", "filename")`.
  - Full 256-bit cryptographic digest provides robust collision resistance ($2^{128}$ birthday bound) while avoiding claims of mathematical impossibility.
  - Retries of the same upload yield identical `doc_id` and do not produce duplicate logical documents.
  - Identical content across different tenants produces distinct `doc_id` values and remains strictly isolated.
  - Qdrant points are namespaced: `uuid5(NAMESPACE_DNS, f"{tenant_id}_{chunk_id}")`.
- **Tenant-Safe Vector Deletion**:
  - Qdrant deletion filter strictly scopes on both `tenant_id` and `document_id`.
  - A tenant cannot delete another tenant's vector points even if guessing a document ID.
- **Canonical Routing & Backward Compatibility**:
  - `POST /v1/kb/upload` is the primary canonical endpoint.
  - `GET /v1/kb/documents` and `DELETE /v1/kb/documents/{document_id}` are canonical aliases.
  - Existing `/v1/knowledge-base/*` paths are preserved as backward-compatible routes that follow identical queue and deduplication semantics.

### 6. RBAC Permission Mapping & Extensions
- Permissions in `shared/schemas/auth.py` are extended minimally and semantically:
  - Add `Permission.ALERTS_ACKNOWLEDGE = "alerts:acknowledge"`.
    - Granted to: `Role.OPERATOR`, `Role.TENANT_ADMIN`, `Role.SUPER_ADMIN`.
  - Add `Permission.KB_READ = "kb:read"`.
    - Granted to: `Role.OPERATOR`, `Role.TENANT_ADMIN`, `Role.SUPER_ADMIN`.
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
