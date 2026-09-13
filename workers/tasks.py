"""Celery background tasks for asynchronous verification and drift tracking."""

import asyncio
from typing import Any

from analytics.drift import LongitudinalDriftTracker
from shared.logging import get_logger
from shared.schemas import VerificationRequest
from workers.celery_app import celery_app
from workers.orchestrator import VerificationOrchestrator
from workers.rav.ingestion import KnowledgeBaseIngestionService

logger = get_logger("celery_tasks")
drift_tracker = LongitudinalDriftTracker()


@celery_app.task(name="workers.tasks.async_verify_task", bind=True, max_retries=2)  # type: ignore[untyped-decorator]
def async_verify_task(
    self: Any,
    prompt: str,
    response: str,
    tenant_id: str = "default_tenant",
    knowledge_base_id: str = "default_kb",
) -> dict[str, Any]:
    """Background task executing complete multi-signal verification pipeline asynchronously."""
    logger.info("Executing async verification task", tenant_id=tenant_id)
    try:
        orchestrator = VerificationOrchestrator()
        req = VerificationRequest(
            prompt=prompt,
            response=response,
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
        )

        # Run async coroutine within sync Celery task worker thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(orchestrator.verify_request(req))
        finally:
            loop.close()

        return {
            "verified_response": res.verified_response,
            "hrs_score": res.hrs_result.hrs,
            "risk_tier": res.hrs_result.tier.value,
            "conformal_interval": {
                "lower": res.hrs_result.conformal_interval.lower,
                "upper": res.hrs_result.conformal_interval.upper,
            },
            "correction_applied": res.metadata.correction_applied,
            "claims_count": res.hrs_result.claims_count,
        }
    except Exception as exc:
        logger.error("Async verification failed", error=str(exc))
        raise self.retry(exc=exc, countdown=2) from exc


@celery_app.task(name="workers.tasks.recompute_drift_task")  # type: ignore[untyped-decorator]
def recompute_drift_task(tenant_id: str = "default_tenant") -> dict[str, Any]:
    """Daily periodic task recomputing longitudinal PSI and KS drift metrics."""
    logger.info("Executing daily drift recomputation task", tenant_id=tenant_id)
    report = drift_tracker.get_drift_report(tenant_id)
    return {
        "tenant_id": tenant_id,
        "psi": report.psi,
        "psi_status": report.status.value,
        "ks_p_value": report.ks_pvalue,
        "alert": report.alert_triggered,
    }


@celery_app.task(name="workers.tasks.ingest_document_task")  # type: ignore[untyped-decorator]
def ingest_document_task(filename: str, content: str, tenant_id: str) -> dict[str, Any]:
    """Asynchronous task for processing and indexing large knowledge base uploads."""
    logger.info("Executing async KB ingestion task", filename=filename, tenant_id=tenant_id)
    service = KnowledgeBaseIngestionService()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            service.ingest_document(filename=filename, content=content, tenant_id=tenant_id)
        )
    finally:
        loop.close()
    return result
