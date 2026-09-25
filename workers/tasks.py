"""Celery background tasks for asynchronous verification and drift tracking.

Implements ADR 0003:
- Durable execution with pre-execution idempotency checking
- Deterministic session_id binding preventing duplicate database records
- Poison-message rejection to DLQ via Reject(requeue=False)
- Exponential backoff with bounded jitter on transient failures
"""

import asyncio
import concurrent.futures
import os
import random
import threading
import time
from typing import Any, cast

from celery.exceptions import MaxRetriesExceededError, Reject
from pydantic import ValidationError

from analytics.drift import LongitudinalDriftTracker
from analytics.pdf_service import default_pdf_generator
from db.persistence import default_persistence_service
from services.storage import default_storage_service
from shared.logging import get_logger
from shared.schemas import VerificationRequest
from workers.celery_app import celery_app
from workers.orchestrator import VerificationOrchestrator
from workers.rav.ingestion import KnowledgeBaseIngestionService

logger = get_logger("celery_tasks")
drift_tracker = LongitudinalDriftTracker()

NON_RETRYABLE_EXCEPTIONS = (
    ValidationError,
    ValueError,
    KeyError,
    TypeError,
)

_HEARTBEAT_PATH = "/tmp/worker_heartbeat"
_stop_heartbeat = threading.Event()


def _heartbeat_loop() -> None:
    while not _stop_heartbeat.is_set():
        try:
            with open(_HEARTBEAT_PATH, "w") as f:
                f.write(str(time.time()))
        except Exception:
            pass
        _stop_heartbeat.wait(5.0)


try:
    from celery import signals

    @signals.worker_ready.connect  # type: ignore[untyped-decorator]
    def on_worker_ready(**_kwargs: Any) -> None:
        logger.info("Celery worker ready, starting heartbeat thread")
        _stop_heartbeat.clear()
        t = threading.Thread(target=_heartbeat_loop, daemon=True, name="celery_heartbeat")
        t.start()

    @signals.worker_shutdown.connect  # type: ignore[untyped-decorator]
    def on_worker_shutdown(**_kwargs: Any) -> None:
        logger.info("Celery worker shutting down, stopping heartbeat")
        _stop_heartbeat.set()
        try:
            if os.path.exists(_HEARTBEAT_PATH):
                os.remove(_HEARTBEAT_PATH)
        except Exception:
            pass
except Exception:
    pass


def _run_async(coro: Any) -> Any:
    """Execute an asynchronous coroutine safely across both sync and async thread contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


@celery_app.task(
    name="workers.tasks.async_verify_task",
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)  # type: ignore[untyped-decorator]
def async_verify_task(
    self: Any,
    prompt: str,
    response: str,
    tenant_id: str = "default_tenant",
    knowledge_base_id: str = "default_kb",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Background task executing complete multi-signal verification pipeline asynchronously."""
    logger.info("Executing async verification task", tenant_id=tenant_id, session_id=session_id)

    # 1. Validation of required inputs (Poison payload check)
    if not prompt or not isinstance(prompt, str) or not response or not isinstance(response, str):
        logger.error(
            "Poison payload received: invalid prompt/response",
            tenant_id=tenant_id,
            session_id=session_id,
        )
        raise Reject("Invalid task arguments; non-retryable poison payload", requeue=False)

    try:
        # 2. Pre-execution Idempotency Check in PostgreSQL
        if session_id and default_persistence_service is not None:
            try:
                existing_sess = _run_async(default_persistence_service.get_session_by_id(tenant_id, session_id))
                if existing_sess is not None:
                    logger.info(
                        "Async task duplicate execution detected; session already committed in PostgreSQL",
                        session_id=session_id,
                        tenant_id=tenant_id,
                    )
                    return {
                        "session_id": existing_sess.session_id,
                        "verified_response": response,
                        "hrs_score": existing_sess.hrs_score,
                        "risk_tier": existing_sess.risk_tier,
                        "idempotent_duplicate": True,
                    }
            except Exception as check_exc:
                logger.warning(
                    "Pre-execution idempotency check encountered error, proceeding to pipeline",
                    error=str(check_exc),
                    session_id=session_id,
                )

        # 3. Pipeline Execution
        orchestrator = VerificationOrchestrator()
        req = VerificationRequest(
            prompt=prompt,
            response=response,
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            session_id=session_id,
        )

        res = _run_async(orchestrator.verify_request(req))

        return {
            "session_id": res.request_id,
            "verified_response": res.verified_response,
            "hrs_score": res.hrs_result.hrs,
            "risk_tier": res.hrs_result.tier.value,
            "conformal_interval": {
                "lower": res.hrs_result.conformal_interval.lower,
                "upper": res.hrs_result.conformal_interval.upper,
            },
            "correction_applied": res.metadata.correction_applied,
            "claims_count": res.hrs_result.claims_count,
            "idempotent_duplicate": False,
        }

    except NON_RETRYABLE_EXCEPTIONS as fatal_exc:
        # Poison message: invalid schema or types -> reject directly to DLQ
        logger.critical(
            "Terminal non-retryable error in async verification; rejecting to DLQ",
            error=str(fatal_exc),
            session_id=session_id,
            tenant_id=tenant_id,
        )
        raise Reject(fatal_exc, requeue=False) from fatal_exc

    except Reject:
        # Re-raise explicit Rejects without wrapping
        raise

    except Exception as exc:
        # Transient failure (network, external timeout, lock blip) -> exponential backoff
        retries = self.request.retries
        delay = min(60.0, (2**retries) + random.uniform(0.1, 1.0))
        logger.warning(
            "Async verification task transient error; scheduling retry with backoff",
            error=str(exc),
            retry_count=retries,
            delay_seconds=round(delay, 2),
            session_id=session_id,
            tenant_id=tenant_id,
        )
        try:
            raise self.retry(exc=exc, countdown=delay, max_retries=3) from exc
        except MaxRetriesExceededError as max_exc:
            logger.critical(
                "Async verification task exhausted all retries; rejecting to DLQ",
                session_id=session_id,
                tenant_id=tenant_id,
                error=str(max_exc),
            )
            raise Reject("Task retries exhausted", requeue=False) from max_exc


@celery_app.task(
    name="workers.tasks.recompute_drift_task",
    bind=True,
    max_retries=3,
    acks_late=True,
)  # type: ignore[untyped-decorator]
def recompute_drift_task(self: Any, tenant_id: str = "default_tenant") -> dict[str, Any]:
    """Daily periodic task recomputing longitudinal PSI and KS drift metrics."""
    logger.info("Executing daily drift recomputation task", tenant_id=tenant_id)
    if not tenant_id or not isinstance(tenant_id, str):
        raise Reject("Invalid tenant_id for drift recomputation", requeue=False)

    try:
        report = drift_tracker.get_drift_report(tenant_id)
        return {
            "tenant_id": tenant_id,
            "psi": report.psi,
            "psi_status": report.status.value,
            "ks_p_value": report.ks_pvalue,
            "alert": report.alert_triggered,
        }
    except Exception as exc:
        logger.error("Drift recomputation task failed", error=str(exc), tenant_id=tenant_id)
        try:
            raise self.retry(exc=exc, countdown=10, max_retries=3) from exc
        except MaxRetriesExceededError as max_exc:
            raise Reject("Drift task retries exhausted", requeue=False) from max_exc


@celery_app.task(
    name="workers.tasks.ingest_document_task",
    bind=True,
    max_retries=3,
    acks_late=True,
)  # type: ignore[untyped-decorator]
def ingest_document_task(
    self: Any, filename: str, content: str, tenant_id: str, collection_name: str = "default_kb"
) -> dict[str, Any]:
    """Asynchronous task for processing and indexing large knowledge base uploads."""
    logger.info("Executing async KB ingestion task", filename=filename, tenant_id=tenant_id)
    if not filename or not content or not tenant_id:
        raise Reject("Invalid document ingestion parameters", requeue=False)

    service = KnowledgeBaseIngestionService()
    try:
        result = _run_async(
            service.ingest_document(
                filename=filename,
                content=content,
                tenant_id=tenant_id,
                collection_name=collection_name,
            )
        )
        return cast(dict[str, Any], result)
    except NON_RETRYABLE_EXCEPTIONS as fatal_exc:
        raise Reject(fatal_exc, requeue=False) from fatal_exc
    except Exception as exc:
        logger.error("KB ingestion task transient failure", error=str(exc))
        try:
            raise self.retry(exc=exc, countdown=5, max_retries=3) from exc
        except MaxRetriesExceededError as max_exc:
            raise Reject("Ingestion task retries exhausted", requeue=False) from max_exc


@celery_app.task(
    name="workers.tasks.generate_report_task",
    bind=True,
    max_retries=3,
    acks_late=True,
)  # type: ignore[untyped-decorator]
def generate_report_task(
    self: Any,
    tenant_id: str,
    report_id: str,
    title: str,
    start_date_iso: str,
    end_date_iso: str,
    model_id: str | None = None,
    risk_tier: str | None = None,
) -> dict[str, Any]:
    """Asynchronous background compilation of multi-session compliance audit reports."""
    logger.info("Executing async report generation task", report_id=report_id, tenant_id=tenant_id)
    if not tenant_id or not report_id:
        raise Reject("Invalid report parameters", requeue=False)

    try:
        start_date = datetime.fromisoformat(start_date_iso)
        end_date = datetime.fromisoformat(end_date_iso)
    except Exception as exc:
        logger.error("Invalid date strings for report task", error=str(exc))
        raise Reject(f"Malformed date strings: {exc}", requeue=False) from exc

    try:
        # 1. Update status to PROCESSING
        _run_async(
            default_persistence_service.update_report_status(
                tenant_id=tenant_id,
                report_id=report_id,
                status="PROCESSING",
            )
        )

        # 2. Query sessions in audit window
        sessions = _run_async(
            default_persistence_service.get_sessions_for_audit(
                tenant_id=tenant_id,
                start_date=start_date,
                end_date=end_date,
                model_id=model_id,
                risk_tier=risk_tier,
            )
        )

        total_sessions = len(sessions)
        mean_hrs = float(sum(s.hrs_score for s in sessions) / total_sessions) if total_sessions > 0 else 0.0
        tier_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
        for s in sessions:
            tier_upper = str(s.risk_tier).upper()
            tier_counts[tier_upper] = tier_counts.get(tier_upper, 0) + 1
        corrections = sum(1 for s in sessions if s.correction_applied)
        correction_rate = float(corrections / total_sessions) if total_sessions > 0 else 0.0

        summary = {
            "total_sessions": total_sessions,
            "mean_hrs": round(mean_hrs, 4),
            "tier_counts": tier_counts,
            "correction_rate": round(correction_rate, 4),
        }

        # 3. Format session sample for PDF
        session_dicts = [
            {
                "session_id": s.session_id,
                "created_at": s.created_at.isoformat() if s.created_at else "",
                "model_id": s.model_id,
                "hrs_score": s.hrs_score,
                "risk_tier": s.risk_tier,
                "correction_applied": s.correction_applied,
            }
            for s in sessions
        ]

        # 4. Generate PDF bytes
        pdf_bytes = default_pdf_generator.generate_aggregate_audit_report_pdf(
            report_id=report_id,
            tenant_id=tenant_id,
            title=title,
            start_date=start_date,
            end_date=end_date,
            summary=summary,
            sessions=session_dicts,
            model_id=model_id,
            risk_tier=risk_tier,
        )

        # 5. Store PDF in Object Storage
        storage_key = f"{tenant_id}/{report_id}.pdf"
        canonical_uri = default_storage_service.put_object(
            bucket="mirage-audit",
            key=storage_key,
            data=pdf_bytes,
            content_type="application/pdf",
        )

        # 6. Mark report COMPLETED in PostgreSQL
        _run_async(
            default_persistence_service.update_report_status(
                tenant_id=tenant_id,
                report_id=report_id,
                status="COMPLETED",
                summary=summary,
                storage_key=canonical_uri,
            )
        )

        logger.info(
            "Audit report generation completed successfully",
            report_id=report_id,
            tenant_id=tenant_id,
            total_sessions=total_sessions,
        )
        return {
            "report_id": report_id,
            "tenant_id": tenant_id,
            "status": "COMPLETED",
            "storage_key": canonical_uri,
            "total_sessions": total_sessions,
        }

    except NON_RETRYABLE_EXCEPTIONS as fatal_exc:
        _run_async(
            default_persistence_service.update_report_status(
                tenant_id=tenant_id,
                report_id=report_id,
                status="FAILED",
            )
        )
        raise Reject(fatal_exc, requeue=False) from fatal_exc

    except Exception as exc:
        logger.error("Audit report generation task transient error", error=str(exc), report_id=report_id)
        try:
            raise self.retry(exc=exc, countdown=10, max_retries=3) from exc
        except MaxRetriesExceededError as max_exc:
            _run_async(
                default_persistence_service.update_report_status(
                    tenant_id=tenant_id,
                    report_id=report_id,
                    status="FAILED",
                )
            )
            raise Reject("Report generation retries exhausted", requeue=False) from max_exc

