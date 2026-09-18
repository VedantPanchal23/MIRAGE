"""Integration tests for RabbitMQ broker durability, Quorum queues, publisher confirms, and restart survival."""

import json
import time
from typing import Any

import pytest
from kombu import Connection, Exchange, Queue
from kombu.exceptions import ChannelError

from shared.config import get_settings
from workers.celery_app import celery_app, default_exchange, task_queues
from workers.tasks import async_verify_task

settings = get_settings()


class TestRabbitMQBrokerDurability:
    """Validate durable RabbitMQ messaging semantics using real RabbitMQ 3.13 Testcontainer."""

    def test_quorum_queue_topology_declaration(self, live_rabbitmq_broker: Any) -> None:
        """Verify Celery task queues are declared as durable Quorum queues with DLX routing."""
        if live_rabbitmq_broker is None:
            pytest.skip("Live RabbitMQ container not available")

        with Connection(live_rabbitmq_broker.broker_url) as conn:
            channel = conn.channel()

            for q in task_queues:
                declared_queue = q(channel)
                declared_queue.declare()

                # Verify queue properties
                assert declared_queue.durable is True
                if "dlq" not in declared_queue.name:
                    assert declared_queue.queue_arguments.get("x-queue-type") == "quorum"
                    assert declared_queue.queue_arguments.get("x-dead-letter-exchange") == "mirage.dlx"

    def test_persistent_message_survival_across_broker_restart(self, live_rabbitmq_broker: Any) -> None:
        """Verify persistent messages in durable Quorum queues survive full broker container restart."""
        if live_rabbitmq_broker is None:
            pytest.skip("Live RabbitMQ container not available")

        broker_url = live_rabbitmq_broker.broker_url

        with Connection(broker_url) as conn:
            channel = conn.channel()
            queue = Queue(
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
            )
            queue(channel).declare()
            channel.queue_purge("mirage.verify")

            producer = conn.Producer(channel)
            payload = {
                "id": "task-restart-survive-001",
                "task": "workers.tasks.async_verify_task",
                "args": ["Is diamond hard?", "Yes, diamond is one of the hardest natural substances."],
                "kwargs": {"tenant_id": "tenant_restart", "session_id": "sess_restart_001"},
            }

            # Publish with persistent delivery mode (delivery_mode=2)
            producer.publish(
                json.dumps(payload),
                exchange=default_exchange,
                routing_key="verify.task",
                delivery_mode=2,
                content_type="application/json",
            )

        # Restart the RabbitMQ docker container via testcontainer docker client
        docker_container = live_rabbitmq_broker._container
        docker_container.restart()
        live_rabbitmq_broker.reload()

        # Update broker port and URL with the newly assigned host port
        amqp_port = int(live_rabbitmq_broker.get_exposed_port(5672))
        broker_url = f"amqp://mirage:mirage_rabbit_secret@{live_rabbitmq_broker.host}:{amqp_port}//"
        live_rabbitmq_broker.broker_url = broker_url
        live_rabbitmq_broker.amqp_port = amqp_port
        settings.celery_broker_url = broker_url
        celery_app.conf.broker_url = broker_url

        # Poll broker to recover and accept connections
        for _ in range(20):
            try:
                with Connection(broker_url) as test_conn:
                    test_conn.connect()
                    ch = test_conn.channel()
                    ch.close()
                    break
            except Exception:
                time.sleep(1.0)

        # Reconnect to broker and verify message is still in queue
        with Connection(broker_url) as conn:
            channel = conn.channel()
            msg = channel.basic_get(queue="mirage.verify", no_ack=False)
            assert msg is not None
            data = json.loads(msg.body)
            assert data["id"] == "task-restart-survive-001"
            assert data["kwargs"]["session_id"] == "sess_restart_001"

            # Clean ACK
            channel.basic_ack(delivery_tag=msg.delivery_tag)

    def test_publisher_confirms_positive_ack(self, live_rabbitmq_broker: Any) -> None:
        """Verify publisher confirms receive positive ACK from RabbitMQ when message is stored."""
        if live_rabbitmq_broker is None:
            pytest.skip("Live RabbitMQ container not available")

        with Connection(live_rabbitmq_broker.broker_url, transport_options={"confirm_publish": True}) as conn:
            channel = conn.channel()
            channel.queue_purge("mirage.verify")
            producer = conn.Producer(channel)

            # Publish message with confirm_publish=True; raises exception if NACKed
            producer.publish(
                json.dumps({"test": "confirm"}),
                exchange=default_exchange,
                routing_key="verify.task",
                delivery_mode=2,
                content_type="application/json",
            )

            # Basic get to clean up
            msg = channel.basic_get(queue="mirage.verify", no_ack=True)
            assert msg is not None

    def test_ambiguous_publish_retransmission_handling(
        self, live_rabbitmq_broker: Any, live_postgres_database: Any
    ) -> None:
        """Verify ambiguous publish retransmission produces duplicate messages handled idempotently."""
        if live_rabbitmq_broker is None:
            pytest.skip("Live RabbitMQ container not available")
        if live_postgres_database is None:
            pytest.skip("Live PostgreSQL container not available")

        session_id = "sess_ambig_retransmit_001"
        tenant_id = "tenant_ambig"

        with Connection(live_rabbitmq_broker.broker_url) as conn:
            channel = conn.channel()
            channel.queue_purge("mirage.verify")
            time.sleep(0.3)
            producer = conn.Producer(channel)

            task_body = {
                "id": "task-ambig-1",
                "task": "workers.tasks.async_verify_task",
                "args": ["What is gravity?", "Gravity is a fundamental interaction."],
                "kwargs": {"tenant_id": tenant_id, "session_id": session_id},
            }

            # First publish (simulated ambiguous outcome)
            producer.publish(
                json.dumps(task_body),
                exchange=default_exchange,
                routing_key="verify.task",
                delivery_mode=2,
                content_type="application/json",
            )

            # Retransmission publish with identical session_id
            producer.publish(
                json.dumps(task_body),
                exchange=default_exchange,
                routing_key="verify.task",
                delivery_mode=2,
                content_type="application/json",
            )

            # Worker consumes message 1
            msg1 = None
            for _ in range(30):
                msg1 = channel.basic_get(queue="mirage.verify", no_ack=False)
                if msg1 is not None:
                    break
                time.sleep(0.1)

            assert msg1 is not None
            task1 = json.loads(msg1.body)

            res1 = async_verify_task.run(
                prompt=task1["args"][0],
                response=task1["args"][1],
                tenant_id=task1["kwargs"]["tenant_id"],
                session_id=task1["kwargs"]["session_id"],
            )
            assert res1["idempotent_duplicate"] is False
            channel.basic_ack(delivery_tag=msg1.delivery_tag)

            # Worker consumes message 2 (retransmission)
            msg2 = None
            for _ in range(30):
                msg2 = channel.basic_get(queue="mirage.verify", no_ack=False)
                if msg2 is not None:
                    break
                time.sleep(0.1)

            assert msg2 is not None
            task2 = json.loads(msg2.body)

            res2 = async_verify_task.run(
                prompt=task2["args"][0],
                response=task2["args"][1],
                tenant_id=task2["kwargs"]["tenant_id"],
                session_id=task2["kwargs"]["session_id"],
            )
            assert res2["idempotent_duplicate"] is True
            channel.basic_ack(delivery_tag=msg2.delivery_tag)

    def test_worker_crash_and_late_ack_redelivery(self, live_rabbitmq_broker: Any) -> None:
        """Verify unacknowledged task on worker disconnect is redelivered to next worker."""
        if live_rabbitmq_broker is None:
            pytest.skip("Live RabbitMQ container not available")

        broker_url = live_rabbitmq_broker.broker_url

        # 1. Publish task
        with Connection(broker_url) as conn:
            channel = conn.channel()
            channel.queue_purge("mirage.verify")
            time.sleep(0.3)
            producer = conn.Producer(channel)
            producer.publish(
                json.dumps({"task_id": "crash-test-01"}),
                exchange=default_exchange,
                routing_key="verify.task",
                delivery_mode=2,
                content_type="application/json",
            )

        # 2. Worker 1 receives message, then closes connection abruptly (simulating crash)
        worker1_conn = Connection(broker_url)
        worker1_channel = worker1_conn.channel()
        msg = None
        for _ in range(30):
            msg = worker1_channel.basic_get(queue="mirage.verify", no_ack=False)
            if msg is not None:
                break
            time.sleep(0.1)

        assert msg is not None
        # Disconnect worker without ACK
        worker1_conn.close()

        # 3. Worker 2 connects and verifies message is redelivered with redelivered=True flag
        with Connection(broker_url) as worker2_conn:
            worker2_channel = worker2_conn.channel()
            redelivered_msg = None
            for _ in range(30):
                redelivered_msg = worker2_channel.basic_get(queue="mirage.verify", no_ack=False)
                if redelivered_msg is not None:
                    break
                time.sleep(0.1)

            assert redelivered_msg is not None
            body = json.loads(redelivered_msg.body)
            assert body["task_id"] == "crash-test-01"
            assert redelivered_msg.delivery_info["redelivered"] is True
            worker2_channel.basic_ack(delivery_tag=redelivered_msg.delivery_tag)

    def test_queue_backpressure_reject_publish(self, live_rabbitmq_broker: Any) -> None:
        """Verify queue declared with x-max-length and reject-publish raises when overflowed."""
        if live_rabbitmq_broker is None:
            pytest.skip("Live RabbitMQ container not available")

        with Connection(live_rabbitmq_broker.broker_url, transport_options={"confirm_publish": True}) as conn:
            channel = conn.channel()
            overflow_exchange = Exchange("mirage.overflow_test", type="direct", durable=True)

            # Quorum queue with max-length 2 and reject-publish
            overflow_queue = Queue(
                "mirage.test.overflow",
                exchange=overflow_exchange,
                routing_key="overflow.task",
                queue_arguments={
                    "x-queue-type": "quorum",
                    "x-max-length": 2,
                    "x-overflow": "reject-publish",
                },
                durable=True,
            )
            overflow_queue(channel).declare()

            producer = conn.Producer(channel)

            # Publish 2 messages (within limit)
            producer.publish("msg 1", exchange=overflow_exchange, routing_key="overflow.task", delivery_mode=2)
            producer.publish("msg 2", exchange=overflow_exchange, routing_key="overflow.task", delivery_mode=2)

            # 3rd message exceeds limit; reject-publish returns nack/ChannelError with confirm_publish=True
            with pytest.raises((ChannelError, Exception)):
                for _ in range(5):
                    producer.publish(
                        "overflow msg",
                        exchange=overflow_exchange,
                        routing_key="overflow.task",
                        delivery_mode=2,
                    )
                    time.sleep(0.05)
