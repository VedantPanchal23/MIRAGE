"""Focused verification suite for the MIRAGE Chaos Harness & Fault-Injection Infrastructure (P3.3).

Verifies all governing safety and architectural requirements:
1. Toxiproxy configuration is deterministic and matches docker/toxiproxy.json.
2. All 8 required dependency proxies are correctly represented.
3. Faults (cut, latency, timeout, reset, bandwidth) can be applied and removed.
4. Cleanup executes and restores health even when a test raises an exception.
5. Unsafe targets (production hosts, external domains, production environments) are rejected.
6. Secrets, credentials, and tokens are scrubbed and never emitted into logs or errors.
7. The harness does not modify production connection settings or database contracts.
8. Pre- and post-fault health checks verify zero residual degradation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.config.settings import get_settings
from tests.chaos.client import ToxiproxyClient
from tests.chaos.config import ChaosConfig, ChaosSafetyViolation, redact_secrets
from tests.chaos.controller import ChaosController
from tests.chaos.models import (
    DEFAULT_PROXY_DEFINITIONS,
    DependencyName,
    ToxicType,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestChaosHarnessInfrastructure:
    """Verifies Toxiproxy configuration, safety boundaries, and lifecycle management."""

    @pytest.fixture
    def controller(self) -> ChaosController:
        """Create a controller with simulated client for deterministic testing."""
        client = ToxiproxyClient(use_simulator=True)
        ctrl = ChaosController(client=client)
        ctrl.setup_all_proxies(reset_first=True)
        return ctrl

    # --------------------------------------------------------------------------
    # 1. Deterministic Configuration & Proxy Representation
    # --------------------------------------------------------------------------

    def test_toxiproxy_configuration_is_deterministic(self) -> None:
        """Verify DEFAULT_PROXY_DEFINITIONS defines all 8 dependencies with unique ports."""
        expected_deps = {
            DependencyName.REDIS,
            DependencyName.QDRANT,
            DependencyName.POSTGRES,
            DependencyName.RABBITMQ,
            DependencyName.NLI,
            DependencyName.LLAVA,
            DependencyName.FLAN_T5,
            DependencyName.UPSTREAM_LLM,
        }
        assert set(DEFAULT_PROXY_DEFINITIONS.keys()) == expected_deps

        # Verify all listen ports are unique
        listen_ports = [d.listen for d in DEFAULT_PROXY_DEFINITIONS.values()]
        assert len(listen_ports) == len(set(listen_ports)), "Proxy listen ports must be unique"

        # Verify all proxy names are unique and prefixed
        names = [d.name for d in DEFAULT_PROXY_DEFINITIONS.values()]
        assert len(names) == len(set(names)), "Proxy names must be unique"
        for name in names:
            assert name.startswith("mirage_")

    def test_docker_toxiproxy_json_matches_python_definitions(self) -> None:
        """Verify docker/toxiproxy.json matches the Python DEFAULT_PROXY_DEFINITIONS."""
        json_path = PROJECT_ROOT / "docker" / "toxiproxy.json"
        assert json_path.is_file(), f"Missing docker/toxiproxy.json at {json_path}"

        with open(json_path, encoding="utf-8") as f:
            file_proxies: list[dict[str, object]] = json.load(f)

        assert len(file_proxies) == 8
        file_proxy_map = {str(p["name"]): p for p in file_proxies}

        for defn in DEFAULT_PROXY_DEFINITIONS.values():
            assert defn.name in file_proxy_map, f"Missing {defn.name} in docker/toxiproxy.json"
            f_entry = file_proxy_map[defn.name]
            assert f_entry["listen"] == defn.listen
            assert f_entry["upstream"] == defn.upstream
            assert f_entry["enabled"] is True

    def test_required_proxies_are_correctly_represented_in_controller(self, controller: ChaosController) -> None:
        """Verify controller correctly resolves proxy names and ports for all 8 dependencies."""
        for dep in DependencyName:
            proxy_name = controller.resolve_proxy_name(dep)
            assert proxy_name == DEFAULT_PROXY_DEFINITIONS[dep].name

            port = controller.get_proxy_port(dep)
            expected_port = int(DEFAULT_PROXY_DEFINITIONS[dep].listen.split(":")[-1])
            assert port == expected_port

        # String resolution also supported
        assert controller.resolve_proxy_name("redis") == "mirage_redis"
        assert controller.get_proxy_port("redis") == 26379

    # --------------------------------------------------------------------------
    # 2. Reversible Fault Injection Primitives
    # --------------------------------------------------------------------------

    def test_fault_cut_connection_can_be_applied_and_removed(self, controller: ChaosController) -> None:
        """Verify cut_connection disables proxy and restores it upon context exit."""
        proxy_name = controller.resolve_proxy_name(DependencyName.REDIS)
        assert controller.client.get_proxy(proxy_name).enabled is True

        with controller.cut_connection(DependencyName.REDIS):
            # Inside context block: proxy is disabled
            assert controller.client.get_proxy(proxy_name).enabled is False

        # After exiting context block: proxy is re-enabled
        assert controller.client.get_proxy(proxy_name).enabled is True

    def test_fault_latency_can_be_applied_and_removed(self, controller: ChaosController) -> None:
        """Verify inject_latency adds a latency toxic and removes it upon context exit."""
        proxy_name = controller.resolve_proxy_name(DependencyName.QDRANT)
        assert len(controller.client.list_toxics(proxy_name)) == 0

        with controller.inject_latency(DependencyName.QDRANT, latency_ms=500, jitter_ms=50) as toxic:
            assert toxic.type == ToxicType.LATENCY
            assert toxic.attributes["latency"] == 500
            assert toxic.attributes["jitter"] == 50
            toxics = controller.client.list_toxics(proxy_name)
            assert len(toxics) == 1
            assert toxics[0].name == toxic.name

        # After exiting: toxic is removed
        assert len(controller.client.list_toxics(proxy_name)) == 0

    def test_fault_timeout_can_be_applied_and_removed(self, controller: ChaosController) -> None:
        """Verify inject_timeout applies and cleans up timeout toxic."""
        proxy_name = controller.resolve_proxy_name(DependencyName.POSTGRES)
        with controller.inject_timeout(DependencyName.POSTGRES, timeout_ms=1000) as toxic:
            assert toxic.type == ToxicType.TIMEOUT
            assert toxic.attributes["timeout"] == 1000
            assert len(controller.client.list_toxics(proxy_name)) == 1

        assert len(controller.client.list_toxics(proxy_name)) == 0

    def test_fault_connection_reset_and_bandwidth(self, controller: ChaosController) -> None:
        """Verify reset_peer and bandwidth toxics apply and cleanly reverse."""
        p_rabbit = controller.resolve_proxy_name(DependencyName.RABBITMQ)
        p_llm = controller.resolve_proxy_name(DependencyName.UPSTREAM_LLM)

        with controller.inject_connection_reset(DependencyName.RABBITMQ):
            assert len(controller.client.list_toxics(p_rabbit)) == 1

        assert len(controller.client.list_toxics(p_rabbit)) == 0

        with controller.inject_bandwidth_limit(DependencyName.UPSTREAM_LLM, rate_kbps=64):
            assert len(controller.client.list_toxics(p_llm)) == 1

        assert len(controller.client.list_toxics(p_llm)) == 0

    # --------------------------------------------------------------------------
    # 3. Guaranteed Cleanup on Test Failure
    # --------------------------------------------------------------------------

    def test_cleanup_guaranteed_even_on_exception(self, controller: ChaosController) -> None:
        """Verify that if an unhandled exception occurs inside a fault block, cleanup still executes."""
        proxy_name = controller.resolve_proxy_name(DependencyName.REDIS)

        with pytest.raises(ZeroDivisionError):
            with controller.cut_connection(DependencyName.REDIS):
                assert controller.client.get_proxy(proxy_name).enabled is False
                _ = 1 / 0

        # After exception: proxy was safely restored by finally block
        assert controller.client.get_proxy(proxy_name).enabled is True

        with pytest.raises(ValueError, match="simulated failure"):
            with controller.inject_latency(DependencyName.REDIS, latency_ms=1000):
                assert len(controller.client.list_toxics(proxy_name)) == 1
                raise ValueError("simulated failure")

        # After exception: toxic was cleanly purged
        assert len(controller.client.list_toxics(proxy_name)) == 0

    # --------------------------------------------------------------------------
    # 4. Safety Controls & Host Validation
    # --------------------------------------------------------------------------

    def test_unsafe_production_environment_is_rejected(self) -> None:
        """Verify ChaosConfig raises ChaosSafetyViolation if run against production."""
        config_prod = ChaosConfig(environment="production")
        with pytest.raises(ChaosSafetyViolation, match=r"(?i)refusing chaos execution in declared environment"):
            config_prod.validate_safety()

        config_live = ChaosConfig(environment="live")
        with pytest.raises(ChaosSafetyViolation, match=r"(?i)refusing chaos execution in declared environment"):
            config_live.validate_safety()

    def test_disabled_chaos_flag_is_rejected(self) -> None:
        """Verify ChaosConfig raises ChaosSafetyViolation when MIRAGE_CHAOS_ENABLED is False."""
        config_disabled = ChaosConfig(enabled=False)
        with pytest.raises(ChaosSafetyViolation, match="MIRAGE_CHAOS_ENABLED is false"):
            config_disabled.validate_safety()

    def test_unsafe_target_hosts_are_rejected(self) -> None:
        """Verify unsafe external or cloud host targets are rejected."""
        config = ChaosConfig(enabled=True, environment="test")

        # Allowed safe hosts must pass
        config.validate_safety("localhost:6379")
        config.validate_safety("127.0.0.1:5432")
        config.validate_safety("redis:6379")
        config.validate_safety("mirage-postgres:5432")

        # Unsafe production hosts must be blocked
        with pytest.raises(ChaosSafetyViolation, match="unsafe production indicator"):
            config.validate_safety("mirage-db.prod.internal")

        with pytest.raises(ChaosSafetyViolation, match="unsafe production indicator"):
            config.validate_safety("production-aurora.rds.amazonaws.com")

        with pytest.raises(ChaosSafetyViolation, match="not in the safe target allowlist"):
            config.validate_safety("198.51.100.42:5432")

    # --------------------------------------------------------------------------
    # 5. Secret Redaction & Sanitization
    # --------------------------------------------------------------------------

    def test_secrets_are_redacted_from_strings_and_errors(self) -> None:
        """Verify passwords, JWTs, and API keys are redacted by redact_secrets."""
        text_with_db_pw = "postgresql+asyncpg://mirage:super_secret_pw@localhost:5432/mirage_db"
        clean = redact_secrets(text_with_db_pw)
        assert "super_secret_pw" not in clean
        assert "[REDACTED]" in clean

        text_with_bearer = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secretpayload.sig"
        clean_bearer = redact_secrets(text_with_bearer)
        assert "eyJhbGciOi" not in clean_bearer
        assert "[REDACTED]" in clean_bearer

        text_with_api_key = "Connection failed with api_key=gsk_secret_1234567890abcdef"
        clean_api_key = redact_secrets(text_with_api_key)
        assert "gsk_secret" not in clean_api_key
        assert "[REDACTED]" in clean_api_key

    # --------------------------------------------------------------------------
    # 6. Production Configuration Immutability
    # --------------------------------------------------------------------------

    def test_harness_does_not_modify_production_configuration(self) -> None:
        """Verify importing and using chaos harness leaves application settings unchanged."""
        from shared.config.settings import Settings

        # 1. Verify default production configuration schema definitions remain unpolluted
        assert Settings.model_fields["postgres_port"].default == 5432
        assert Settings.model_fields["redis_port"].default == 6379
        assert Settings.model_fields["rabbitmq_port"].default == 5672
        assert Settings.model_fields["qdrant_port"].default == 6333
        assert "5432" in str(Settings.model_fields["database_url"].default)
        assert "6379" in str(Settings.model_fields["redis_url"].default)

        # 2. Verify ChaosController does not mutate active session settings
        current_settings = get_settings()
        orig_db = current_settings.database_url
        orig_redis = current_settings.redis_url

        sim_client = ToxiproxyClient(use_simulator=True)
        controller = ChaosController(client=sim_client)
        assert current_settings.database_url == orig_db
        assert current_settings.redis_url == orig_redis
        assert controller.get_proxy_port(DependencyName.POSTGRES) == 25432

    # --------------------------------------------------------------------------
    # 7. Pre- and Post-Fault Health Verification
    # --------------------------------------------------------------------------

    def test_health_check_passes_before_and_after_injection(self, controller: ChaosController) -> None:
        """Verify check_health() returns healthy before injection and after restoration."""
        # 1. Pre-fault health check: healthy
        status_before = controller.check_health()
        assert status_before.is_healthy is True
        assert len(status_before.unhealthy_proxies) == 0
        assert status_before.active_toxics_count == 0

        # 2. During fault: unhealthy
        with controller.cut_connection(DependencyName.REDIS):
            status_during = controller.check_health()
            assert status_during.is_healthy is False
            assert "mirage_redis" in status_during.unhealthy_proxies

        # 3. Post-fault health check: restored to healthy
        status_after = controller.check_health()
        assert status_after.is_healthy is True
        assert len(status_after.unhealthy_proxies) == 0
        assert status_after.active_toxics_count == 0

    # --------------------------------------------------------------------------
    # 8. Bounded Temporary Partition
    # --------------------------------------------------------------------------

    def test_temporary_partition_bounds_and_restores(self, controller: ChaosController) -> None:
        """Verify temporary_partition disables, waits, and automatically re-enables."""
        proxy_name = controller.resolve_proxy_name(DependencyName.FLAN_T5)
        controller.temporary_partition(DependencyName.FLAN_T5, duration_sec=0.05)
        assert controller.client.get_proxy(proxy_name).enabled is True

        # Exceeding max duration raises ValueError
        with pytest.raises(ValueError, match="exceeds maximum allowed duration"):
            controller.temporary_partition(DependencyName.FLAN_T5, duration_sec=999.0)

    # --------------------------------------------------------------------------
    # 9. Real Toxiproxy Container Integration
    # --------------------------------------------------------------------------

    def test_live_toxiproxy_container_integration(self) -> None:
        """Integration test directly against live running Toxiproxy container."""
        real_client = ToxiproxyClient(use_simulator=False)
        if not real_client.is_server_available():
            pytest.skip("Live Toxiproxy daemon not running on localhost:8474")

        try:
            # 1. Version check against live daemon
            version_str = real_client.get_version()
            assert "2.11.0" in version_str

            # 2. Verify all 8 pre-seeded proxies exist on live daemon
            proxies = real_client.list_proxies()
            assert len(proxies) == 8
            for dep in DependencyName:
                assert DEFAULT_PROXY_DEFINITIONS[dep].name in proxies

            # 3. Live fault lifecycle via ChaosController
            real_controller = ChaosController(client=real_client)
            with real_controller.inject_latency(DependencyName.REDIS, latency_ms=100, jitter_ms=10) as toxic:
                active_toxics = real_client.list_toxics("mirage_redis")
                assert any(t.name == toxic.name for t in active_toxics)

            # 4. Toxic cleaned up after context exit
            assert len(real_client.list_toxics("mirage_redis")) == 0

            # 5. Restore all and verify healthy baseline
            health = real_controller.restore_all()
            assert health.is_healthy is True
        finally:
            real_client.close()
