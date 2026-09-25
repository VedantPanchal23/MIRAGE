"""Celery application configuration for asynchronous multi-signal processing.

Implements Technical Architecture Document §2, §8.2, §10.1 and ADR 0003:
- Broker: RabbitMQ (AMQP / AMQPS with Quorum queues and publisher confirms)
- Result Backend: Redis DB 1 (dedicated mirage_celery ACL user)
- Durability: task_acks_late=True, task_reject_on_worker_lost=True, delivery_mode=persistent
- Dead-Lettering: mirage.dlx with dedicated DLQs for poison and exhausted tasks
"""

from celery import Celery
from kombu import Exchange, Queue

from shared.config import get_settings

settings = get_settings()

# Define durable exchanges
default_exchange = Exchange("mirage.direct", type="direct", durable=True)
dead_letter_exchange = Exchange("mirage.dlx", type="direct", durable=True)

# Define durable Quorum queues and DLQs per ADR 0003
task_queues = [
    Queue(
        "mirage.verify",
        default_exchange,
        routing_key="verify.task",
        queue_arguments={
            "x-queue-type": "quorum",
            "x-dead-letter-exchange": "mirage.dlx",
            "x-dead-letter-routing-key": "verify.dlq",
            "x-max-length": 10000,
            "x-overflow": "reject-publish",
            "x-delivery-limit": 5,
        },
        durable=True,
    ),
    Queue(
        "mirage.drift",
        default_exchange,
        routing_key="drift.task",
        queue_arguments={
            "x-queue-type": "quorum",
            "x-dead-letter-exchange": "mirage.dlx",
            "x-dead-letter-routing-key": "drift.dlq",
            "x-max-length": 1000,
            "x-overflow": "reject-publish",
            "x-delivery-limit": 5,
        },
        durable=True,
    ),
    Queue(
        "mirage.ingest",
        default_exchange,
        routing_key="ingest.task",
        queue_arguments={
            "x-queue-type": "quorum",
            "x-dead-letter-exchange": "mirage.dlx",
            "x-dead-letter-routing-key": "ingest.dlq",
            "x-max-length": 5000,
            "x-overflow": "reject-publish",
            "x-delivery-limit": 5,
        },
        durable=True,
    ),
    Queue(
        "mirage.reports",
        default_exchange,
        routing_key="report.task",
        queue_arguments={
            "x-queue-type": "quorum",
            "x-dead-letter-exchange": "mirage.dlx",
            "x-dead-letter-routing-key": "report.dlq",
            "x-max-length": 2000,
            "x-overflow": "reject-publish",
            "x-delivery-limit": 5,
        },
        durable=True,
    ),
    # Dead-Letter Queues (DLQ)
    Queue(
        "mirage.verify.dlq",
        dead_letter_exchange,
        routing_key="verify.dlq",
        queue_arguments={
            "x-queue-type": "quorum",
        },
        durable=True,
    ),
    Queue(
        "mirage.drift.dlq",
        dead_letter_exchange,
        routing_key="drift.dlq",
        queue_arguments={
            "x-queue-type": "quorum",
        },
        durable=True,
    ),
    Queue(
        "mirage.ingest.dlq",
        dead_letter_exchange,
        routing_key="ingest.dlq",
        queue_arguments={
            "x-queue-type": "quorum",
        },
        durable=True,
    ),
    Queue(
        "mirage.reports.dlq",
        dead_letter_exchange,
        routing_key="report.dlq",
        queue_arguments={
            "x-queue-type": "quorum",
        },
        durable=True,
    ),
]

celery_app = Celery(
    "mirage_workers",
    broker=settings.celery_broker_url,
    backend=(
        f"redis://{settings.celery_redis_username}:{settings.celery_redis_password}@"
        f"{settings.redis_host}:{settings.redis_port}/1"
    ),
)

celery_app.conf.update(
    # Serialization & Content Security
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Durability & Late Acknowledgements (ADR 0003)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_delivery_mode="persistent",
    broker_connection_retry_on_startup=False,
    broker_connection_max_retries=1,
    broker_connection_timeout=0.5,
    broker_transport_options={
        "confirm_publish": True,
        "max_retries": 1,
        "interval_start": 0.05,
        "interval_step": 0.05,
        "interval_max": 0.1,
    },
    worker_prefetch_multiplier=1,
    # Timeouts grounded in SLA (Technical Architecture §2.6, P95 < 3000ms, k=2 rewrites)
    task_time_limit=30,
    task_soft_time_limit=25,
    result_expires=86400,
    # Queue Topology & Routing
    task_queues=task_queues,
    task_default_queue="mirage.verify",
    task_default_exchange="mirage.direct",
    task_default_routing_key="verify.task",
    task_routes={
        "workers.tasks.async_verify_task": {"queue": "mirage.verify", "routing_key": "verify.task"},
        "workers.tasks.recompute_drift_task": {"queue": "mirage.drift", "routing_key": "drift.task"},
        "workers.tasks.ingest_document_task": {"queue": "mirage.ingest", "routing_key": "ingest.task"},
        "workers.tasks.generate_report_task": {"queue": "mirage.reports", "routing_key": "report.task"},
    },
)

celery_app.autodiscover_tasks(["workers.tasks"])


def is_broker_reachable(timeout: float = 0.05) -> bool:
    """Non-blocking socket probe to verify if RabbitMQ broker is actively accepting connections."""
    import socket

    try:
        with socket.create_connection((settings.rabbitmq_host, settings.rabbitmq_port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False
