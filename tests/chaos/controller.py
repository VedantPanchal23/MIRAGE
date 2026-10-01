"""Chaos Controller: Reusable Fault-Injection Lifecycle Engine (P3.3).

Provides deterministic, reversible network-fault injection primitives:
- Context managers with guaranteed cleanup (try-finally).
- Pre- and post-fault health verification.
- Safe host validation and secret redaction.
- Bounded fault durations.
- Pre-configured proxy mappings for all 8 MIRAGE dependencies.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager

from shared.logging import get_logger
from tests.chaos.client import ToxiproxyClient
from tests.chaos.config import ChaosConfig, redact_secrets
from tests.chaos.models import (
    DEFAULT_PROXY_DEFINITIONS,
    DependencyName,
    HealthStatus,
    ProxyDefinition,
    Toxic,
    ToxicStream,
    ToxicType,
)

logger = get_logger("chaos_controller")


class ChaosController:
    """Orchestrates network fault injection, cleanup, and health verification."""

    def __init__(
        self,
        client: ToxiproxyClient | None = None,
        config: ChaosConfig | None = None,
    ) -> None:
        self.config = config or ChaosConfig()
        self.client = client or ToxiproxyClient(
            config=self.config,
            use_simulator=not ToxiproxyClient(self.config).is_server_available(),
        )

    def resolve_proxy_name(self, dep: DependencyName | str) -> str:
        """Resolve dependency enum or string to registered proxy name."""
        if isinstance(dep, DependencyName):
            return DEFAULT_PROXY_DEFINITIONS[dep].name

        # If user passed a string (e.g. "redis", "mirage_redis")
        for dep_enum, defn in DEFAULT_PROXY_DEFINITIONS.items():
            if dep == dep_enum.value or dep == defn.name:
                return defn.name

        # If already formatted or custom
        return str(dep)

    def get_proxy_port(self, dep: DependencyName | str) -> int:
        """Return the localhost port on which the proxied dependency listens."""
        proxy_name = self.resolve_proxy_name(dep)
        for defn in DEFAULT_PROXY_DEFINITIONS.values():
            if defn.name == proxy_name:
                # Format: "0.0.0.0:26379" -> 26379
                return int(defn.listen.split(":")[-1])
        raise ValueError(f"Unknown dependency proxy: '{dep}'")

    def setup_all_proxies(self, reset_first: bool = True) -> dict[str, ProxyDefinition]:
        """Ensure all 8 canonical MIRAGE dependency proxies exist and are healthy."""
        self.config.validate_safety()

        if reset_first:
            self.client.reset()

        definitions = list(DEFAULT_PROXY_DEFINITIONS.values())
        created = self.client.populate(definitions)
        return {p.name: p for p in created}

    def check_health(self) -> HealthStatus:
        """Verify the health status of all managed proxies and active toxics."""
        self.config.validate_safety()

        proxies = self.client.list_proxies()
        healthy_proxies: list[str] = []
        unhealthy_proxies: list[str] = []
        total_toxics = 0

        for name, proxy in proxies.items():
            if proxy.enabled and len(proxy.toxics) == 0:
                healthy_proxies.append(name)
            else:
                unhealthy_proxies.append(name)
            total_toxics += len(proxy.toxics)

        is_healthy = len(unhealthy_proxies) == 0 and total_toxics == 0
        return HealthStatus(
            is_healthy=is_healthy,
            healthy_proxies=healthy_proxies,
            unhealthy_proxies=unhealthy_proxies,
            active_toxics_count=total_toxics,
            details={"total_proxies": len(proxies)},
        )

    def restore_all(self) -> HealthStatus:
        """Deterministic cleanup: enable all proxies, remove all toxics, and verify health."""
        self.config.validate_safety()
        logger.info("Restoring all chaos proxies to baseline healthy state")
        self.client.reset()
        status = self.check_health()
        if not status.is_healthy:
            logger.warning(
                "Health check after restore_all indicated residual issues",
                unhealthy=status.unhealthy_proxies,
                toxics=status.active_toxics_count,
            )
        return status

    # ==========================================================================
    # Fault Injection Primitives (Reversible Context Managers)
    # ==========================================================================

    @contextmanager
    def cut_connection(
        self,
        dep: DependencyName | str,
    ) -> Generator[str, None, None]:
        """Disable proxy network traffic (simulates total dependency outage / process kill).

        Guarantees re-enabling the proxy upon exiting the context block.
        """
        self.config.validate_safety()
        proxy_name = self.resolve_proxy_name(dep)
        logger.info("Injecting connection cut fault", proxy=proxy_name)

        self.client.disable_proxy(proxy_name)
        try:
            yield proxy_name
        finally:
            logger.info("Reversing connection cut fault", proxy=proxy_name)
            try:
                self.client.enable_proxy(proxy_name)
            except Exception as exc:
                logger.error("Failed to re-enable proxy during cleanup", error=redact_secrets(str(exc)))

    @contextmanager
    def inject_latency(
        self,
        dep: DependencyName | str,
        latency_ms: int,
        jitter_ms: int = 0,
        toxicity: float = 1.0,
        stream: ToxicStream | str = ToxicStream.DOWNSTREAM,
    ) -> Generator[Toxic, None, None]:
        """Inject artificial network delay (milliseconds) into proxy traffic.

        Guarantees removal of latency toxic upon exiting the context block.
        """
        self.config.validate_safety()
        proxy_name = self.resolve_proxy_name(dep)
        toxic_name = f"fault_latency_{int(time.time() * 1000)}"
        toxic = Toxic(
            name=toxic_name,
            type=ToxicType.LATENCY,
            stream=stream,
            toxicity=toxicity,
            attributes={"latency": latency_ms, "jitter": jitter_ms},
        )

        logger.info(
            "Injecting latency toxic",
            proxy=proxy_name,
            latency_ms=latency_ms,
            jitter_ms=jitter_ms,
        )
        applied = self.client.add_toxic(proxy_name, toxic)
        try:
            yield applied
        finally:
            logger.info("Reversing latency toxic", proxy=proxy_name, toxic=toxic_name)
            try:
                self.client.remove_toxic(proxy_name, toxic_name)
            except Exception as exc:
                logger.error("Failed to remove latency toxic during cleanup", error=redact_secrets(str(exc)))

    @contextmanager
    def inject_timeout(
        self,
        dep: DependencyName | str,
        timeout_ms: int,
        stream: ToxicStream | str = ToxicStream.DOWNSTREAM,
    ) -> Generator[Toxic, None, None]:
        """Inject connection timeout fault: closes connection after specified duration.

        Guarantees toxic removal upon exiting the context block.
        """
        self.config.validate_safety()
        proxy_name = self.resolve_proxy_name(dep)
        toxic_name = f"fault_timeout_{int(time.time() * 1000)}"
        toxic = Toxic(
            name=toxic_name,
            type=ToxicType.TIMEOUT,
            stream=stream,
            toxicity=1.0,
            attributes={"timeout": timeout_ms},
        )

        logger.info("Injecting timeout toxic", proxy=proxy_name, timeout_ms=timeout_ms)
        applied = self.client.add_toxic(proxy_name, toxic)
        try:
            yield applied
        finally:
            logger.info("Reversing timeout toxic", proxy=proxy_name, toxic=toxic_name)
            try:
                self.client.remove_toxic(proxy_name, toxic_name)
            except Exception as exc:
                logger.error("Failed to remove timeout toxic during cleanup", error=redact_secrets(str(exc)))

    @contextmanager
    def inject_connection_reset(
        self,
        dep: DependencyName | str,
        stream: ToxicStream | str = ToxicStream.DOWNSTREAM,
    ) -> Generator[Toxic, None, None]:
        """Inject TCP reset peer fault (simulates abrupt connection reset / RST packet).

        Guarantees toxic removal upon exiting the context block.
        """
        self.config.validate_safety()
        proxy_name = self.resolve_proxy_name(dep)
        toxic_name = f"fault_reset_{int(time.time() * 1000)}"
        toxic = Toxic(
            name=toxic_name,
            type=ToxicType.RESET_PEER,
            stream=stream,
            toxicity=1.0,
            attributes={},
        )

        logger.info("Injecting reset_peer toxic", proxy=proxy_name)
        applied = self.client.add_toxic(proxy_name, toxic)
        try:
            yield applied
        finally:
            logger.info("Reversing reset_peer toxic", proxy=proxy_name, toxic=toxic_name)
            try:
                self.client.remove_toxic(proxy_name, toxic_name)
            except Exception as exc:
                logger.error("Failed to remove reset_peer toxic during cleanup", error=redact_secrets(str(exc)))

    @contextmanager
    def inject_bandwidth_limit(
        self,
        dep: DependencyName | str,
        rate_kbps: int,
        stream: ToxicStream | str = ToxicStream.DOWNSTREAM,
    ) -> Generator[Toxic, None, None]:
        """Constrain bandwidth rate (KB/s) to simulate severe network throttling.

        Guarantees toxic removal upon exiting the context block.
        """
        self.config.validate_safety()
        proxy_name = self.resolve_proxy_name(dep)
        toxic_name = f"fault_bandwidth_{int(time.time() * 1000)}"
        toxic = Toxic(
            name=toxic_name,
            type=ToxicType.BANDWIDTH,
            stream=stream,
            toxicity=1.0,
            attributes={"rate": rate_kbps},
        )

        logger.info("Injecting bandwidth toxic", proxy=proxy_name, rate_kbps=rate_kbps)
        applied = self.client.add_toxic(proxy_name, toxic)
        try:
            yield applied
        finally:
            logger.info("Reversing bandwidth toxic", proxy=proxy_name, toxic=toxic_name)
            try:
                self.client.remove_toxic(proxy_name, toxic_name)
            except Exception as exc:
                logger.error("Failed to remove bandwidth toxic during cleanup", error=redact_secrets(str(exc)))

    def temporary_partition(
        self,
        dep: DependencyName | str,
        duration_sec: float,
    ) -> None:
        """Temporarily partition a dependency for a bounded duration, then automatically restore."""
        self.config.validate_safety()
        max_duration = self.config.default_max_duration_sec
        if duration_sec > max_duration:
            raise ValueError(
                f"Requested partition duration ({duration_sec}s) exceeds maximum allowed duration ({max_duration}s)."
            )

        with self.cut_connection(dep):
            time.sleep(duration_sec)
