"""Unit tests for MIRAGE 3.0 CLI commands."""

import argparse
from unittest.mock import MagicMock, patch

from cli.main import _get_api_key, cmd_health, cmd_verify


def test_get_api_key_explicit() -> None:
    assert _get_api_key("explicit_key_123") == "explicit_key_123"


def test_get_api_key_env_var() -> None:
    with patch.dict("os.environ", {"MIRAGE_API_KEY": "env_key_456"}):
        assert _get_api_key() == "env_key_456"


@patch("httpx.get")
def test_cmd_health_success(mock_get: MagicMock) -> None:
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"status": "healthy", "version": "3.0.0"}

    args = argparse.Namespace(base_url="http://localhost:8000")
    code = cmd_health(args)
    assert code == 0


@patch("httpx.post")
def test_cmd_verify_success(mock_post: MagicMock) -> None:
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "request_id": "req_cli_test",
        "verified_response": "Verified text",
        "hrs_result": {
            "hrs": 0.12,
            "tier": "LOW",
            "conformal_interval": {"lower": 0.05, "upper": 0.20},
            "claims_count": 1,
            "computation_latency_ms": 12.5,
        },
        "claims": [],
    }

    args = argparse.Namespace(
        text="Verified text",
        prompt="",
        model="allam-2-7b",
        base_url="http://localhost:8000",
        api_key="mirage_test_key",
        timeout=10.0,
    )
    code = cmd_verify(args)
    assert code == 0
