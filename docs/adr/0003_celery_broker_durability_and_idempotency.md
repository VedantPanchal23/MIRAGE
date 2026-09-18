# ADR 0003: Celery Broker Durability, Quorum Queue HA Topology, Dead-Letter Routing, and Task Idempotency

## Status
ACCEPTED (Ratified 2026-09-14)

## Context
MIRAGE requires robust asynchronous task execution for high-throughput verifications, knowledge base document chunking/indexing, and longitudinal drift recomputation. Governing documents (`PRD.md` §6.1/§9/§14, `Technical_Architecture.md` §8.2/§10.1/§12, `Security_Access.md` §4.1/§5/§7, `Testing_Strategy.md` §5/§8.9/§9.6) mandate durable messaging, reliable retries, TLS security, and least-privilege access.

Prior to Phase P0.5, several critical architectural gaps and document divergences existed:
1. **HA Queue Topology**: `Security_Access.md` referenced legacy "mirrored queues". However, in modern RabbitMQ (3.8+ and 3.13+), classic mirrored queues (`ha-mode: all`) are formally deprecated and scheduled for complete removal in RabbitMQ 4.0.
2. **Result Backend Divergence**: `shared/config/settings.py` defaulted to `rpc://`, `workers/celery_app.py` pointed to Redis DB 1 without user credentials, and Phase P0.4 restricted the application Redis user (`mirage_app`) from accessing `celery-task-meta-*` keys.
3. **Transport Security**: `Security_Access.md` §4.1 and §15.2 mandate AMQPS (TLS 1.2+), but settings permitted plaintext `amqp://` across all profiles.
4. **Task Loss on Worker Crash**: Default Celery configurations use early acknowledgements (`acks_late=False`) and drop unacknowledged tasks if worker processes crash (`task_reject_on_worker_lost=False`).
5. **Non-Idempotent Session IDs**: `VerificationOrchestrator` randomly generated `session_id` inside `verify_request()`. Any task redelivery or retry created duplicate database sessions, claims, and corrupted the linear audit hash chain.

## Decisions

### 1. Quorum Queue HA Topology
Adopt **Quorum Queues (`x-queue-type: quorum`)** as the sole production queue architecture for all application queues (`mirage.verify`, `mirage.drift`, `mirage.ingest`).
- Quorum queues utilize the **Raft consensus algorithm** to guarantee FIFO message ordering and replication across cluster nodes.
- Quorum queues write messages directly to disk WAL by default, preventing message loss during unexpected broker node crashes.
- Bounded delivery tracking (`x-delivery-limit: 5`) is enforced at the broker level to eliminate infinite poison-message redelivery loops.

### 2. Strict AMQPS (TLS 1.2+) Enforcement in Production
Plaintext AMQP (`amqp://`) is strictly prohibited in production mode (`ENVIRONMENT="production"`).
- Production connections require `amqps://` with TLS 1.2 minimum version (`ssl.PROTOCOL_TLS_CLIENT`).
- Server certificate verification (`cert_reqs=ssl.CERT_REQUIRED`) is mandatory.
- A Pydantic validator in `Settings` blocks startup if plaintext AMQP is configured in production.

### 3. Broker Durability & Late Acknowledgements
- Celery worker application enforces:
  - `task_acks_late = True`: Tasks are acknowledged to RabbitMQ *only* after verification execution and database commits succeed.
  - `task_reject_on_worker_lost = True`: If a worker child process terminates abruptly (e.g. OOM or SIGKILL), unacknowledged messages are automatically rejected back to RabbitMQ for redelivery.
  - `task_default_delivery_mode = "persistent"` (delivery mode 2) ensures messages are persisted to disk WAL.
  - Publisher confirms (`broker_transport_options = {"confirm_publish": True}`) ensure producers verify broker disk writes.

### 4. Dead-Letter Exchange (DLX) & Queues (DLQ)
Declare durable direct exchange `mirage.dlx` and dedicated DLQs:
- `mirage.verify.dlq` (routing key: `verify.dlq`)
- `mirage.drift.dlq` (routing key: `drift.dlq`)
- `mirage.ingest.dlq` (routing key: `ingest.dlq`)
- Terminal domain exceptions (`ValidationError`, malformed frames, unknown task, invalid tenant) and tasks that exhaust 3 retries are rejected with `requeue=False`, routing them deterministically to their respective DLQ with `x-death` diagnostic headers.

### 5. Pre-Enqueue `session_id` Binding & Task Idempotency
- Every verification request must bind a deterministic `session_id` at the producer boundary *before* publishing to RabbitMQ.
- If an ambiguous publisher-confirm outcome occurs, retried messages use the identical `session_id`.
- Celery tasks perform an authoritative pre-execution check in PostgreSQL.
- Concurrent duplicate deliveries are serialized by PostgreSQL tenant row locks (`SELECT id FROM tenants WHERE id = :tenant_id FOR UPDATE`) and unique primary key constraints on `session_id`. Exactly one transaction commits; duplicate executions roll back, retrieve the committed result, and ACK without creating duplicate claims or appending to the cryptographic audit hash chain.
- MongoDB `idx_session_id_unique` prevents duplicate trace insertion, and duplicate tasks never overwrite an existing completed trace.

### 6. Redis Celery Result Backend Least-Privilege ACL
- Ratify **Redis DB 1** as the transient task metadata store (`result_expires = 86400` / 24 hours).
- A dedicated ACL user `mirage_celery` is configured with minimal necessary commands:
  `GET`, `SET`, `SETEX`, `EXPIRE`, `DEL`, `MGET`, `SELECT`, `CLIENT`, `INFO` on keyspace `~celery-task-meta-* ~celery-chord-*`.
- `mirage_celery` is denied access to DB 0 application keys (`ratelimit:*`, `scs:*`).
- `mirage_app` is denied access to DB 1 Celery keys.
- Result backend data is transient and non-authoritative. Authoritative session state resides exclusively in PostgreSQL and MongoDB.

## Consequences

### Positive
- True at-least-once delivery guaranteed within the documented fault envelope.
- Complete protection against silent task loss on worker crash or broker reboot.
- Zero database duplication or audit hash-chain corruption on duplicate message delivery.
- Poison messages and exhausted retries are safely quarantined in DLQs for operator triage.
- Clean least-privilege security boundaries between Celery workers, RabbitMQ vhosts, and Redis databases.

### Negative / Trade-offs
- Quorum queues require persistent disk storage and have higher I/O overhead than transient memory queues.
- `acks_late=True` combined with at-least-once delivery increases the likelihood of redeliveries, necessitating strict database-level idempotency enforcement.
