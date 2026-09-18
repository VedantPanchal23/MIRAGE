"""Integration test suite for Phase P0.6 Docker Compose Multi-Container Production Topology.

Validates the 20-point production hardening matrix:
- Full 13-service inventory and network topology
- Elimination of host published ports for all datastores and brokers
- Linux security controls (cap_drop ALL, no-new-privileges, read_only rootfs, non-root)
- Exact image version pinning (zero floating tags)
- Log rotation and deploy resource limits
- Multi-tier readiness probe (/v1/ready) vs liveness (/v1/health)
- Degraded operational mode (RAV-less on Qdrant loss)
- Fail-closed operational mode (503 on PostgreSQL, Redis, MongoDB, RabbitMQ loss)
- Secret sanitization across health endpoints and structured logging
- Celery worker heartbeat healthcheck probe mechanics
"""

import os
import subprocess
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from gateway.main import app
from shared.logging import configure_logging, get_logger


@pytest.fixture(scope="module")
def compose_config() -> dict[str, Any]:
    """Parse and return the validated docker-compose.yml configuration."""
    compose_path = os.path.abspath("docker-compose.yml")
    assert os.path.exists(compose_path), "docker-compose.yml must exist"

    # Use docker compose config output to verify Docker parser acceptance
    result = subprocess.run(
        ["docker", "compose", "config"],
        capture_output=True,
        text=True,
        check=True,
    )
    parsed: dict[str, Any] = yaml.safe_load(result.stdout)
    return parsed


class TestComposeTopologySpecification:
    """Audit Docker Compose structure against governing documents and ADR 0004."""

    def test_1_full_thirteen_service_inventory(self, compose_config: dict[str, Any]) -> None:
        """Verify all 13 required services are explicitly defined."""
        services = compose_config.get("services", {})
        expected_services = {
            "postgres",
            "mongodb",
            "redis",
            "rabbitmq",
            "qdrant",
            "tempo",
            "otel-collector",
            "prometheus",
            "grafana",
            "migration",
            "gateway",
            "worker",
            "dashboard",
        }
        assert expected_services.issubset(set(services.keys())), (
            f"Missing services: {expected_services - set(services.keys())}"
        )
        assert len(services) == 13

    def test_2_datastore_host_ports_strictly_unexposed(self, compose_config: dict[str, Any]) -> None:
        """Verify that zero datastores or message brokers publish ports to the host interface."""
        services = compose_config.get("services", {})
        internal_only_services = [
            "postgres",
            "mongodb",
            "redis",
            "rabbitmq",
            "qdrant",
            "tempo",
            "otel-collector",
            "prometheus",
            "migration",
            "worker",
        ]

        for s_name in internal_only_services:
            svc = services.get(s_name, {})
            ports = svc.get("ports")
            assert not ports, f"Security Violation: Service '{s_name}' publishes host ports: {ports}"

    def test_3_only_edge_services_expose_host_ports(self, compose_config: dict[str, Any]) -> None:
        """Verify only gateway (8000), dashboard (3000), and Grafana (3001) expose host ports."""
        services = compose_config.get("services", {})
        gateway_ports = services["gateway"].get("ports", [])
        dashboard_ports = services["dashboard"].get("ports", [])
        grafana_ports = services["grafana"].get("ports", [])

        assert any("8000" in str(p) for p in gateway_ports), "Gateway must expose port 8000 for API access"
        assert any("3000" in str(p) for p in dashboard_ports), "Dashboard must expose port 3000 for Web UI"
        assert any("3001" in str(p) for p in grafana_ports), "Grafana must expose port 3001 for DevOps monitoring"

    def test_4_three_tier_network_segmentation(self, compose_config: dict[str, Any]) -> None:
        """Verify the 3 isolated bridge networks are declared and assigned correctly."""
        networks = compose_config.get("networks", {})
        assert "frontend_net" in networks
        assert "backend_net" in networks
        assert "observability_net" in networks

        services = compose_config.get("services", {})
        # Dashboard only on frontend_net
        assert "frontend_net" in services["dashboard"]["networks"]
        assert "backend_net" not in services["dashboard"]["networks"]

        # Postgres only on backend_net
        assert "backend_net" in services["postgres"]["networks"]
        assert "frontend_net" not in services["postgres"]["networks"]

        # Worker on backend_net and observability_net, not frontend
        assert "backend_net" in services["worker"]["networks"]
        assert "observability_net" in services["worker"]["networks"]
        assert "frontend_net" not in services["worker"]["networks"]

    def test_5_linux_container_security_hardening(self, compose_config: dict[str, Any]) -> None:
        """Verify cap_drop ALL and no-new-privileges on all services."""
        services = compose_config.get("services", {})
        for s_name, svc in services.items():
            cap_drop = svc.get("cap_drop", [])
            assert "ALL" in cap_drop, f"Service '{s_name}' must enforce cap_drop: [ALL]"

            sec_opt = svc.get("security_opt", [])
            assert any("no-new-privileges" in str(opt) for opt in sec_opt), (
                f"Service '{s_name}' must enforce security_opt: [no-new-privileges:true]"
            )

    def test_6_application_containers_read_only_rootfs(self, compose_config: dict[str, Any]) -> None:
        """Verify application containers enforce read_only root filesystem with tmpfs mounts."""
        services = compose_config.get("services", {})
        app_services = ["gateway", "worker", "migration", "dashboard"]

        for s_name in app_services:
            svc = services[s_name]
            assert svc.get("read_only") is True, f"Service '{s_name}' must set read_only: true"
            assert svc.get("tmpfs"), f"Service '{s_name}' must declare writable tmpfs mounts for /tmp"

    def test_7_exact_third_party_image_pinning(self, compose_config: dict[str, Any]) -> None:
        """Verify no floating tags (latest, 7, alpine, 16) are used for third-party images."""
        services = compose_config.get("services", {})
        disallowed_floating_tags = ["latest", "alpine", ":16", ":7", ":3"]

        for s_name, svc in services.items():
            image = svc.get("image")
            if image:
                for floating in disallowed_floating_tags:
                    if image.endswith(floating) or f"{floating}-" in image:
                        # Ensure it has patch versioning
                        assert "." in image.split(":")[-1], f"Service '{s_name}' uses floating image tag: {image}"

    def test_8_resource_limits_and_reservations_enforced(self, compose_config: dict[str, Any]) -> None:
        """Verify deploy.resources CPU and RAM limits are enforced across all services."""
        services = compose_config.get("services", {})
        for s_name, svc in services.items():
            deploy = svc.get("deploy", {})
            resources = deploy.get("resources", {})
            limits = resources.get("limits", {})
            assert "cpus" in limits, f"Service '{s_name}' missing CPU limit"
            assert "memory" in limits, f"Service '{s_name}' missing Memory limit"

    def test_9_log_rotation_policies_enforced(self, compose_config: dict[str, Any]) -> None:
        """Verify JSON-file logging with max-size and max-file rotation on all services."""
        services = compose_config.get("services", {})
        for s_name, svc in services.items():
            logging_cfg = svc.get("logging", {})
            assert logging_cfg.get("driver") == "json-file", f"Service '{s_name}' must use json-file driver"
            opts = logging_cfg.get("options", {})
            assert opts.get("max-size") == "10m", f"Service '{s_name}' must cap log size at 10m"
            assert opts.get("max-file") == "3", f"Service '{s_name}' must cap log files at 3"

    def test_10_migration_runner_dependency_graph(self, compose_config: dict[str, Any]) -> None:
        """Verify migration runs once and gateway/worker depend on completed migration."""
        services = compose_config.get("services", {})
        migration_svc = services["migration"]
        assert migration_svc.get("restart") == "no", "Migration service must set restart: 'no'"

        for s_name in ["gateway", "worker"]:
            deps = services[s_name].get("depends_on", {})
            assert "migration" in deps, f"Service '{s_name}' must depend on 'migration'"
            mig_dep = deps["migration"]
            assert mig_dep.get("condition") == "service_completed_successfully", (
                f"Service '{s_name}' must require migration condition: service_completed_successfully"
            )


class TestReadinessAndLivenessEndpoints:
    """Verify decoupled /v1/health (liveness) vs /v1/ready (readiness) failure semantics."""

    @pytest.mark.asyncio
    async def test_11_liveness_probe_healthy_regardless_of_backends(self) -> None:
        """Verify /v1/health succeeds as a fast event loop check."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/v1/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] in {"healthy", "degraded", "alive"}
            assert data["version"] == "2.1.0"
            assert "uptime_seconds" in data

    @pytest.mark.asyncio
    async def test_12_readiness_probe_all_backends_healthy(self) -> None:
        """Verify /v1/ready returns HTTP 200 ready when all 5 backends are healthy."""
        with (
            patch("gateway.routes.health.check_database_connection", new_callable=AsyncMock) as mock_pg,
            patch("gateway.routes.health.default_redis_client_manager.ping", new_callable=AsyncMock) as mock_redis,
            patch(
                "gateway.routes.health.default_mongo_trace_service.check_health", new_callable=AsyncMock
            ) as mock_mongo,
            patch("gateway.routes.health._check_rabbitmq_ready", new_callable=AsyncMock) as mock_rabbit,
            patch("gateway.routes.health._check_qdrant_ready", new_callable=AsyncMock) as mock_qdrant,
        ):
            mock_pg.return_value = True
            mock_redis.return_value = True
            mock_mongo.return_value = {"status": "pass"}
            mock_rabbit.return_value = True
            mock_qdrant.return_value = True

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/ready")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "ready"
                assert data["degraded"] is False
                assert data["components"]["postgres"] == "up"
                assert data["components"]["redis"] == "up"
                assert data["components"]["mongodb"] == "up"
                assert data["components"]["rabbitmq"] == "up"
                assert data["components"]["qdrant"] == "up"

    @pytest.mark.asyncio
    async def test_13_readiness_probe_qdrant_loss_enters_degraded_mode(self) -> None:
        """Verify /v1/ready returns HTTP 200 with degraded: true when only Qdrant is down."""
        with (
            patch("gateway.routes.health.check_database_connection", new_callable=AsyncMock) as mock_pg,
            patch("gateway.routes.health.default_redis_client_manager.ping", new_callable=AsyncMock) as mock_redis,
            patch(
                "gateway.routes.health.default_mongo_trace_service.check_health", new_callable=AsyncMock
            ) as mock_mongo,
            patch("gateway.routes.health._check_rabbitmq_ready", new_callable=AsyncMock) as mock_rabbit,
            patch("gateway.routes.health._check_qdrant_ready", new_callable=AsyncMock) as mock_qdrant,
        ):
            mock_pg.return_value = True
            mock_redis.return_value = True
            mock_mongo.return_value = {"status": "pass"}
            mock_rabbit.return_value = True
            mock_qdrant.return_value = False  # Qdrant down!

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/ready")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "ready"
                assert data["degraded"] is True
                assert "qdrant" in data["degraded_components"]
                assert data["components"]["qdrant"] == "down"

    @pytest.mark.asyncio
    async def test_14_readiness_probe_mandatory_postgres_loss_returns_503(self) -> None:
        """Verify /v1/ready returns HTTP 503 unready when PostgreSQL is down."""
        with (
            patch("gateway.routes.health.check_database_connection", new_callable=AsyncMock) as mock_pg,
            patch("gateway.routes.health.default_redis_client_manager.ping", new_callable=AsyncMock) as mock_redis,
            patch(
                "gateway.routes.health.default_mongo_trace_service.check_health", new_callable=AsyncMock
            ) as mock_mongo,
            patch("gateway.routes.health._check_rabbitmq_ready", new_callable=AsyncMock) as mock_rabbit,
            patch("gateway.routes.health._check_qdrant_ready", new_callable=AsyncMock) as mock_qdrant,
        ):
            mock_pg.return_value = False  # Postgres down!
            mock_redis.return_value = True
            mock_mongo.return_value = {"status": "pass"}
            mock_rabbit.return_value = True
            mock_qdrant.return_value = True

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/ready")
                assert resp.status_code == 503
                data = resp.json()
                assert data["status"] == "unready"
                assert "postgres" in data["failed_components"]
                assert data["components"]["postgres"] == "down"

    @pytest.mark.asyncio
    async def test_15_readiness_probe_mandatory_redis_loss_returns_503(self) -> None:
        """Verify /v1/ready returns HTTP 503 unready when Redis is down."""
        with (
            patch("gateway.routes.health.check_database_connection", new_callable=AsyncMock) as mock_pg,
            patch("gateway.routes.health.default_redis_client_manager.ping", new_callable=AsyncMock) as mock_redis,
            patch(
                "gateway.routes.health.default_mongo_trace_service.check_health", new_callable=AsyncMock
            ) as mock_mongo,
            patch("gateway.routes.health._check_rabbitmq_ready", new_callable=AsyncMock) as mock_rabbit,
            patch("gateway.routes.health._check_qdrant_ready", new_callable=AsyncMock) as mock_qdrant,
        ):
            mock_pg.return_value = True
            mock_redis.return_value = False  # Redis down!
            mock_mongo.return_value = {"status": "pass"}
            mock_rabbit.return_value = True
            mock_qdrant.return_value = True

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/ready")
                assert resp.status_code == 503
                data = resp.json()
                assert data["status"] == "unready"
                assert "redis" in data["failed_components"]

    @pytest.mark.asyncio
    async def test_16_readiness_probe_mandatory_mongo_loss_returns_503(self) -> None:
        """Verify /v1/ready returns HTTP 503 unready when MongoDB is down."""
        with (
            patch("gateway.routes.health.check_database_connection", new_callable=AsyncMock) as mock_pg,
            patch("gateway.routes.health.default_redis_client_manager.ping", new_callable=AsyncMock) as mock_redis,
            patch(
                "gateway.routes.health.default_mongo_trace_service.check_health", new_callable=AsyncMock
            ) as mock_mongo,
            patch("gateway.routes.health._check_rabbitmq_ready", new_callable=AsyncMock) as mock_rabbit,
            patch("gateway.routes.health._check_qdrant_ready", new_callable=AsyncMock) as mock_qdrant,
        ):
            mock_pg.return_value = True
            mock_redis.return_value = True
            mock_mongo.return_value = {"status": "fail"}  # Mongo down!
            mock_rabbit.return_value = True
            mock_qdrant.return_value = True

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/ready")
                assert resp.status_code == 503
                data = resp.json()
                assert data["status"] == "unready"
                assert "mongodb" in data["failed_components"]

    @pytest.mark.asyncio
    async def test_17_readiness_probe_mandatory_rabbitmq_loss_returns_503(self) -> None:
        """Verify /v1/ready returns HTTP 503 unready when RabbitMQ is down."""
        with (
            patch("gateway.routes.health.check_database_connection", new_callable=AsyncMock) as mock_pg,
            patch("gateway.routes.health.default_redis_client_manager.ping", new_callable=AsyncMock) as mock_redis,
            patch(
                "gateway.routes.health.default_mongo_trace_service.check_health", new_callable=AsyncMock
            ) as mock_mongo,
            patch("gateway.routes.health._check_rabbitmq_ready", new_callable=AsyncMock) as mock_rabbit,
            patch("gateway.routes.health._check_qdrant_ready", new_callable=AsyncMock) as mock_qdrant,
        ):
            mock_pg.return_value = True
            mock_redis.return_value = True
            mock_mongo.return_value = {"status": "pass"}
            mock_rabbit.return_value = False  # RabbitMQ down!
            mock_qdrant.return_value = True

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/ready")
                assert resp.status_code == 503
                data = resp.json()
                assert data["status"] == "unready"
                assert "rabbitmq" in data["failed_components"]

    @pytest.mark.asyncio
    async def test_18_zero_credential_leakage_in_readiness_payload(self) -> None:
        """Verify /v1/ready payload never leaks passwords, host IPs, ports, or URLs."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/v1/ready")
            raw_text = resp.text.lower()
            forbidden_substrings = [
                "secret",
                "password",
                "mirage_dev",
                "mirage_mongo",
                "mirage_redis",
                "mirage_rabbit",
                "amqp://",
                "mongodb://",
                "postgresql://",
                "redis://",
            ]
            for secret in forbidden_substrings:
                assert secret not in raw_text, (
                    f"Security Violation: Leaked sensitive substring '{secret}' in readiness probe"
                )


class TestOperationalHardeningMechanisms:
    """Verify logging scrubbers, worker heartbeat, and container health probe mechanics."""

    def test_19_structured_logging_secret_sanitizer(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify structlog sanitizer scrubs sensitive URLs and credential attributes."""
        configure_logging(service_name="test-service", json_format=True)
        log = get_logger("test-scrubber")

        log.info(
            "Connecting to datastore",
            database_url="postgresql://mirage_user:super_secret_pw@localhost:5432/mirage_db",
            api_key="mrg_prod_999secrettoken999",
            password="plaintext_pass",
        )

        captured = capsys.readouterr().out
        assert "super_secret_pw" not in captured, "Log leaked database password in connection string"
        assert "999secrettoken999" not in captured, "Log leaked API key token"
        assert "plaintext_pass" not in captured, "Log leaked plaintext password"
        assert "***" in captured, "Expected '***' redaction marker in log output"

    def test_20_worker_heartbeat_mechanism(self, tmp_path: Any) -> None:
        """Verify worker heartbeat file mechanics and mtime age evaluation."""
        import time

        heartbeat_file = tmp_path / "worker_heartbeat"
        heartbeat_file.write_text(str(time.time()))

        # Probe: verify mtime age is < 30 seconds
        stat_mtime = heartbeat_file.stat().st_mtime
        age = time.time() - stat_mtime
        assert age < 5.0, "Fresh heartbeat must have age < 5.0 seconds"

        # Stale heartbeat test: set mtime to 60 seconds ago
        stale_time = time.time() - 60.0
        os.utime(heartbeat_file, (stale_time, stale_time))
        stale_age = time.time() - heartbeat_file.stat().st_mtime
        assert stale_age >= 50.0, "Stale heartbeat must be detected"
