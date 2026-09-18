"""Tests for RabbitMQ AMQPS (TLS 1.2+) enforcement per Security_Access.md §4.1 and ADR 0003."""

import pytest
from pydantic import ValidationError

from shared.config.settings import EnvironmentType, Settings


class TestRabbitMQTLSValidation:
    """Validate that plaintext AMQP is strictly prohibited in production mode."""

    def test_settings_prohibits_plaintext_amqp_in_production(self) -> None:
        """Verify settings validation raises ValueError if celery_broker_url uses amqp:// in production."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                environment=EnvironmentType.PRODUCTION,
                celery_broker_url="amqp://mirage:secret@broker.mirage.internal:5672//",
                secret_key="a" * 32,
            )

        assert "Production security policy violation: CELERY_BROKER_URL must use AMQPS (TLS 1.2+)" in str(
            exc_info.value
        )
        assert "Plaintext amqp:// is strictly prohibited" in str(exc_info.value)

    def test_production_amqps_validates_successfully(self) -> None:
        """Verify settings validation accepts amqps:// in production mode."""
        s = Settings(
            environment=EnvironmentType.PRODUCTION,
            celery_broker_url="amqps://mirage:secret@broker.mirage.internal:5671//",
            secret_key="a" * 32,
        )
        assert s.celery_broker_url == "amqps://mirage:secret@broker.mirage.internal:5671//"
        assert s.environment == EnvironmentType.PRODUCTION

    def test_development_allows_plaintext_amqp(self) -> None:
        """Verify development and test environments permit amqp:// for local containers."""
        s_dev = Settings(
            environment=EnvironmentType.DEVELOPMENT,
            celery_broker_url="amqp://mirage:secret@localhost:5672//",
            secret_key="a" * 32,
        )
        assert s_dev.celery_broker_url.startswith("amqp://")

        s_test = Settings(
            environment=EnvironmentType.TEST,
            celery_broker_url="amqp://mirage:secret@localhost:5672//",
            secret_key="a" * 32,
        )
        assert s_test.celery_broker_url.startswith("amqp://")
