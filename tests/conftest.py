"""Global pytest fixtures for MIRAGE test suite with live PostgreSQL Testcontainer."""

import os
from collections.abc import Generator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from db.session import create_app_engine, reset_sessionmaker
from gateway.main import create_app
from shared.config import get_settings
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory


@pytest.fixture(scope="session", autouse=True)
def live_postgres_database() -> Generator[PostgresContainer | None, None, None]:
    """Spin up an ephemeral PostgreSQL 16 Testcontainer and apply Alembic migrations for test session."""
    settings = get_settings()
    try:
        with PostgresContainer("postgres:16-alpine") as pg:
            sync_url = pg.get_connection_url().replace("+psycopg2", "")
            async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://")

            settings.database_url = async_url
            settings.database_sync_url = sync_url
            os.environ["DATABASE_URL"] = async_url
            os.environ["DATABASE_SYNC_URL"] = sync_url

            engine = create_app_engine(async_url, poolclass=NullPool)
            reset_sessionmaker(engine)

            # Apply Alembic migrations to create tables and RLS policies
            cfg = Config("alembic.ini")
            cfg.set_main_option("sqlalchemy.url", sync_url)
            command.upgrade(cfg, "head")

            yield pg
    except Exception as exc:
        print(f"Warning: Testcontainers PostgreSQL failed to start: {exc}")
        yield None


@pytest.fixture(scope="session", autouse=True)
def live_mongo_database() -> Generator[Any, None, None]:
    """Spin up an ephemeral MongoDB 7 Testcontainer with authentication and least-privilege application user."""
    import pymongo
    from testcontainers.community.mongodb import MongoDbContainer

    from db.mongo import reset_default_mongo_service

    settings = get_settings()
    try:
        with MongoDbContainer("mongo:7.0", username="root", password="mirage_root_secret", dbname="admin") as mongo:
            root_url = mongo.get_connection_url()
            root_client = pymongo.MongoClient(root_url)

            # Create unprivileged application user on mirage_traces
            trace_db = root_client["mirage_traces"]
            trace_db.command(
                "createUser",
                "mirage_app",
                pwd="mirage_mongo_secret",
                roles=[{"role": "readWrite", "db": "mirage_traces"}],
            )
            root_client.close()

            # Construct authenticated application connection URL
            host = mongo.get_container_host_ip()
            port = mongo.get_exposed_port(27017)
            app_url = f"mongodb://mirage_app:mirage_mongo_secret@{host}:{port}/mirage_traces?authSource=mirage_traces"

            settings.mongo_uri = app_url
            settings.mongo_db = "mirage_traces"
            os.environ["MONGO_URI"] = app_url
            os.environ["MONGO_DB"] = "mirage_traces"

            reset_default_mongo_service(uri=app_url, db_name="mirage_traces")
            mongo.app_url = app_url
            mongo.root_url = root_url

            yield mongo

            # Teardown
            reset_default_mongo_service()
    except Exception as exc:
        print(f"Warning: Testcontainers MongoDB failed to start: {exc}")
        yield None


@pytest.fixture(scope="session", autouse=True)
def live_redis_database() -> Generator[Any, None, None]:
    """Spin up an ephemeral Redis 7 Testcontainer with restricted ACL application user."""
    import redis
    from testcontainers.community.redis import RedisContainer

    from db.redis import reset_default_redis_client

    settings = get_settings()
    try:
        with RedisContainer("redis:7-alpine") as r_cont:
            host = r_cont.get_container_host_ip()
            port = r_cont.get_exposed_port(6379)

            # 1. Connect as admin to configure restricted application ACL users
            admin_client = redis.Redis(host=host, port=port)
            # mirage_app restricted to DB 0 app keys
            admin_client.execute_command(
                "ACL",
                "SETUSER",
                "mirage_app",
                "on",
                ">mirage_redis_secret",
                "resetkeys",
                "~ratelimit:*",
                "~scs:*",
                "~config:*",
                "~rav_embed:*",
                "+@read",
                "+@write",
                "+@connection",
                "+@scripting",
                "+time",
                "-@admin",
                "-@dangerous",
            )
            # mirage_celery restricted to DB 1 task metadata per ADR 0003
            admin_client.execute_command(
                "ACL",
                "SETUSER",
                "mirage_celery",
                "on",
                ">mirage_celery_secret",
                "resetkeys",
                "~celery-task-meta-*",
                "~celery-chord-*",
                "-@admin",
                "-@dangerous",
                "+@connection",
                "+get",
                "+set",
                "+setex",
                "+expire",
                "+del",
                "+mget",
                "+client",
                "+info",
            )
            admin_client.close()

            # 2. Configure application settings to connect as mirage_app
            app_redis_url = f"redis://mirage_app:mirage_redis_secret@{host}:{port}/0"
            settings.redis_host = host
            settings.redis_port = int(port)
            settings.redis_username = "mirage_app"
            settings.redis_password = "mirage_redis_secret"
            settings.redis_url = app_redis_url

            settings.celery_redis_username = "mirage_celery"
            settings.celery_redis_password = "mirage_celery_secret"

            os.environ["REDIS_HOST"] = host
            os.environ["REDIS_PORT"] = str(port)
            os.environ["REDIS_USERNAME"] = "mirage_app"
            os.environ["REDIS_PASSWORD"] = "mirage_redis_secret"
            os.environ["REDIS_URL"] = app_redis_url
            os.environ["CELERY_REDIS_USERNAME"] = "mirage_celery"
            os.environ["CELERY_REDIS_PASSWORD"] = "mirage_celery_secret"

            reset_default_redis_client(
                url=app_redis_url,
                username="mirage_app",
                password="mirage_redis_secret",
            )

            r_cont.admin_port = port
            r_cont.app_url = app_redis_url
            yield r_cont

            # Teardown
            reset_default_redis_client(settings.redis_url)
    except Exception as exc:
        print(f"Warning: Testcontainers Redis failed to start: {exc}")
        yield None


@pytest.fixture(scope="session")
def live_rabbitmq_broker() -> Generator[Any, None, None]:
    """Spin up an ephemeral RabbitMQ 3.13 Testcontainer with Quorum queues and management interface."""
    import time

    from kombu import Connection
    from testcontainers.core.container import DockerContainer

    from workers.celery_app import celery_app

    settings = get_settings()
    try:
        container = (
            DockerContainer("rabbitmq:3.13-management-alpine")
            .with_exposed_ports(5672, 15672)
            .with_env("RABBITMQ_DEFAULT_USER", "mirage")
            .with_env("RABBITMQ_DEFAULT_PASS", "mirage_rabbit_secret")
            .with_env("RABBITMQ_DEFAULT_VHOST", "/")
        )
        with container as rmq:
            host = rmq.get_container_host_ip()
            amqp_port = int(rmq.get_exposed_port(5672))
            mgmt_port = int(rmq.get_exposed_port(15672))

            broker_url = f"amqp://mirage:mirage_rabbit_secret@{host}:{amqp_port}//"
            settings.rabbitmq_host = host
            settings.rabbitmq_port = amqp_port
            settings.rabbitmq_user = "mirage"
            settings.rabbitmq_password = "mirage_rabbit_secret"
            settings.rabbitmq_vhost = "/"
            settings.celery_broker_url = broker_url

            os.environ["RABBITMQ_HOST"] = host
            os.environ["RABBITMQ_PORT"] = str(amqp_port)
            os.environ["RABBITMQ_USER"] = "mirage"
            os.environ["RABBITMQ_PASSWORD"] = "mirage_rabbit_secret"
            os.environ["CELERY_BROKER_URL"] = broker_url

            celery_app.conf.broker_url = broker_url

            # Poll until AMQP broker is actually accepting connections and channels
            for _ in range(20):
                try:
                    with Connection(broker_url) as conn:
                        conn.connect()
                        ch = conn.channel()
                        ch.close()
                    break
                except Exception:
                    time.sleep(1.0)

            rmq.amqp_port = amqp_port
            rmq.mgmt_port = mgmt_port
            rmq.broker_url = broker_url
            rmq.host = host

            yield rmq
    except Exception as exc:
        print(f"Warning: Testcontainers RabbitMQ failed to start: {exc}")
        yield None


@pytest.fixture
def auth_factory() -> type[AuthTestFactory]:
    """Provide the AuthTestFactory class."""
    return AuthTestFactory


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Provide valid default Authorization Bearer headers for default_tenant."""
    return AuthTestFactory.auth_headers(tenant_id="default_tenant", role=Role.API_CLIENT)


@pytest.fixture
def admin_auth_headers() -> dict[str, str]:
    """Provide valid Authorization Bearer headers for Super Admin role."""
    return AuthTestFactory.auth_headers(tenant_id="admin_tenant", role=Role.SUPER_ADMIN)


@pytest.fixture
def auditor_auth_headers() -> dict[str, str]:
    """Provide valid Authorization Bearer headers for Auditor role."""
    return AuthTestFactory.auth_headers(tenant_id="audit_tenant", role=Role.AUDITOR)


@pytest.fixture
def authenticated_client(auth_headers: dict[str, str]) -> TestClient:
    """Provide a TestClient instance pre-configured with default valid authentication."""
    app = create_app()
    client = TestClient(app)
    client.headers.update(auth_headers)
    return client
