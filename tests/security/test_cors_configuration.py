"""Security and contract tests for Gateway CORS policy across development and production modes."""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from gateway.main import DEV_CORS_ORIGINS, PROD_CORS_ORIGINS, create_app
from shared.config.settings import EnvironmentType, Settings


@pytest.mark.security
class TestCORSConfiguration:
    """Verify CORS origin whitelist enforcement, credentials support, and arbitrary origin rejection."""

    def test_development_mode_permits_explicit_local_origins(self) -> None:
        """Verify development/debug mode permits known frontend local origins with credentials."""
        app = create_app()
        client = TestClient(app)

        for dev_origin in DEV_CORS_ORIGINS:
            resp = client.options(
                "/v1/health",
                headers={
                    "Origin": dev_origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization",
                },
            )
            assert resp.status_code == 200
            assert resp.headers.get("access-control-allow-origin") == dev_origin
            assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_development_mode_rejects_arbitrary_untrusted_origins(self) -> None:
        """Verify development/debug mode does NOT permit untrusted/arbitrary external origins."""
        app = create_app()
        client = TestClient(app)

        untrusted_origins = [
            "https://evil.com",
            "http://attacker.local",
            "https://malicious-site.org",
            "http://localhost:8080",
        ]

        for bad_origin in untrusted_origins:
            resp = client.options(
                "/v1/health",
                headers={
                    "Origin": bad_origin,
                    "Access-Control-Request-Method": "GET",
                },
            )
            # When an origin is not allowed, Starlette CORSMiddleware does NOT return allow-origin header
            assert resp.headers.get("access-control-allow-origin") is None

    def test_production_mode_restricts_strictly_to_internal_dashboard(self) -> None:
        """Verify production mode allows ONLY the authoritative internal dashboard origin."""
        prod_settings = Settings(
            environment=EnvironmentType.PRODUCTION,
            debug=False,
            secret_key="a" * 48,
            celery_broker_url="amqps://mirage:mirage_rabbit_secret@localhost:5671//",
        )

        with patch("gateway.main.get_settings", return_value=prod_settings):
            prod_app = create_app()
            prod_client = TestClient(prod_app)

            # 1. Authoritative production dashboard is allowed
            for prod_origin in PROD_CORS_ORIGINS:
                resp = prod_client.options(
                    "/v1/health",
                    headers={
                        "Origin": prod_origin,
                        "Access-Control-Request-Method": "GET",
                    },
                )
                assert resp.status_code == 200
                assert resp.headers.get("access-control-allow-origin") == prod_origin
                assert resp.headers.get("access-control-allow-credentials") == "true"

            # 2. Localhost origins are strictly REJECTED in production
            for dev_origin in DEV_CORS_ORIGINS:
                resp = prod_client.options(
                    "/v1/health",
                    headers={
                        "Origin": dev_origin,
                        "Access-Control-Request-Method": "GET",
                    },
                )
                assert resp.headers.get("access-control-allow-origin") is None
