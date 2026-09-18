"""Tests for poison-message rejection and dead-letter queue routing per ADR 0003."""

import json
import time
from typing import Any

import pytest
from celery.exceptions import Reject
from kombu import Connection, Exchange, Queue

from shared.config import get_settings
from workers.tasks import async_verify_task, ingest_document_task, recompute_drift_task

settings = get_settings()


class TestPoisonMessageHandling:
    """Validate terminal non-retryable exception rejection and DLQ quarantine."""

    def test_async_verify_task_rejects_empty_prompt_poison(self) -> None:
        """Verify empty prompt raises Reject(requeue=False) directly without retries."""
        with pytest.raises(Reject) as exc_info:
            async_verify_task.run(
                prompt="",
                response="Valid response text",
                tenant_id="default_tenant",
            )

        assert exc_info.value.requeue is False
        assert "poison payload" in str(exc_info.value)

    def test_async_verify_task_rejects_non_string_response_poison(self) -> None:
        """Verify non-string response raises Reject(requeue=False) directly without retries."""
        with pytest.raises(Reject) as exc_info:
            async_verify_task.run(
                prompt="Valid prompt",
                response=12345,  # type: ignore[arg-type]
                tenant_id="default_tenant",
            )

        assert exc_info.value.requeue is False

    def test_recompute_drift_task_rejects_invalid_tenant(self) -> None:
        """Verify invalid tenant raises Reject(requeue=False)."""
        with pytest.raises(Reject) as exc_info:
            recompute_drift_task.run(tenant_id="")

        assert exc_info.value.requeue is False

    def test_ingest_document_task_rejects_missing_content(self) -> None:
        """Verify missing content raises Reject(requeue=False)."""
        with pytest.raises(Reject) as exc_info:
            ingest_document_task.run(
                filename="doc.txt",
                content="",
                tenant_id="default_tenant",
            )

        assert exc_info.value.requeue is False

    def test_live_rabbitmq_poison_frame_routed_to_dlq(self, live_rabbitmq_broker: Any) -> None:
        """Publish a malformed/poison task frame to live RabbitMQ and verify rejection into mirage.verify.dlq."""
        if live_rabbitmq_broker is None:
            pytest.skip("Live RabbitMQ container not available")

        broker_url = live_rabbitmq_broker.broker_url

        with Connection(broker_url) as conn:
            channel = conn.channel()

            direct_exchange = Exchange("mirage.direct", type="direct", durable=True)
            dlx_exchange = Exchange("mirage.dlx", type="direct", durable=True)

            verify_dlq = Queue(
                "mirage.verify.dlq",
                exchange=dlx_exchange,
                routing_key="verify.dlq",
                queue_arguments={"x-queue-type": "quorum"},
                durable=True,
            )
            verify_dlq(channel).declare()

            verify_queue = Queue(
                "mirage.verify",
                exchange=direct_exchange,
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
            )
            verify_queue(channel).declare()

            channel.queue_purge("mirage.verify")
            channel.queue_purge("mirage.verify.dlq")
            time.sleep(0.3)

            # Publish a message with a poison payload (empty prompt)
            producer = conn.Producer(channel)
            poison_payload = {
                "id": "poison-task-001",
                "task": "workers.tasks.async_verify_task",
                "args": ["", "Valid response"],
                "kwargs": {"tenant_id": "default_tenant", "session_id": "poison_sess_001"},
            }

            producer.publish(
                json.dumps(poison_payload),
                exchange=direct_exchange,
                routing_key="verify.task",
                delivery_mode=2,
                content_type="application/json",
            )

            # Poll for message arrival in verify_queue
            msg = None
            for _ in range(30):
                msg = channel.basic_get(queue="mirage.verify", no_ack=False)
                if msg is not None:
                    break
                time.sleep(0.1)

            assert msg is not None
            delivery_tag = msg.delivery_tag

            # Reject with requeue=False -> forces RabbitMQ to route to DLX
            channel.basic_reject(delivery_tag=delivery_tag, requeue=False)

            # Poll for message arrival in mirage.verify.dlq
            dlq_msg = None
            for _ in range(30):
                dlq_msg = channel.basic_get(queue="mirage.verify.dlq", no_ack=True)
                if dlq_msg is not None:
                    break
                time.sleep(0.1)

            assert dlq_msg is not None
            dlq_body = json.loads(dlq_msg.body)
            assert dlq_body["id"] == "poison-task-001"
            assert dlq_body["kwargs"]["session_id"] == "poison_sess_001"

            # Check x-death header
            headers = dlq_msg.headers
            assert headers is not None
            assert "x-death" in headers
            death_info = headers["x-death"][0]
            assert death_info["queue"] == "mirage.verify"
            assert death_info["reason"] == "rejected"
