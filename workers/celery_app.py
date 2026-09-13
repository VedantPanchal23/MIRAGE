"""Celery application configuration for asynchronous multi-signal processing.

Implements Technical Architecture Document §2:
- Broker: RabbitMQ (amqp://mirage:mirage_rabbit_secret@localhost:5672//)
- Result Backend: Redis (redis://localhost:6379/1)
- Tasks: High-throughput async verification, daily drift recomputation, KB ingestion
"""

from celery import Celery

from shared.config import get_settings

settings = get_settings()

celery_app = Celery(
    "mirage_workers",
    broker=f"amqp://{settings.rabbitmq_user}:{settings.rabbitmq_password}@{settings.rabbitmq_host}:{settings.rabbitmq_port}//",
    backend=f"redis://:{settings.redis_password}@{settings.redis_host}:{settings.redis_port}/1",
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30,  # 30-second hard limit
    worker_prefetch_multiplier=1,
)

celery_app.autodiscover_tasks(["workers.tasks"])
