"""Pytest fixtures for MIRAGE chaos engineering and resilience testing (P3.3)."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from tests.chaos.client import ToxiproxyClient
from tests.chaos.config import ChaosConfig
from tests.chaos.controller import ChaosController


@pytest.fixture(scope="session")
def chaos_config() -> ChaosConfig:
    """Session-scoped immutable chaos harness configuration."""
    return ChaosConfig()


@pytest.fixture
def chaos_client(chaos_config: ChaosConfig) -> Generator[ToxiproxyClient, None, None]:
    """Function-scoped ToxiproxyClient instance."""
    client = ToxiproxyClient(
        config=chaos_config,
        use_simulator=not ToxiproxyClient(chaos_config).is_server_available(),
    )
    yield client
    client.close()


@pytest.fixture
def chaos_controller(
    chaos_client: ToxiproxyClient, chaos_config: ChaosConfig
) -> Generator[ChaosController, None, None]:
    """Function-scoped ChaosController instance."""
    controller = ChaosController(client=chaos_client, config=chaos_config)
    controller.setup_all_proxies(reset_first=True)
    yield controller
    controller.restore_all()


@pytest.fixture
def clean_chaos_environment(chaos_controller: ChaosController) -> Generator[ChaosController, None, None]:
    """Guarantees the chaos environment starts and ends in a baseline 100% healthy state."""
    status_before = chaos_controller.check_health()
    if not status_before.is_healthy:
        chaos_controller.restore_all()

    yield chaos_controller

    chaos_controller.restore_all()
