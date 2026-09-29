"""Unit tests for WebSocket streaming verification endpoint and authentication state machine.

Implements Technical Architecture Document §3.4 & §7, and Security & Access Document §4.4:
- Connection acceptance -> connection_pending_auth challenge
- First-message JWT authentication validation
- 10-second authentication timeout handling
- Malformed, expired, tampered JWT rejection with close code 1008
- Permission.VERIFY_WRITE enforcement with close code 1008
- Prevention of client tenant spoofing (authoritative tenant enforcement)
- Blocking unauthenticated verification processing
- Progressive verification event stream lifecycle
"""

import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette import status
from starlette.websockets import WebSocketDisconnect

import gateway.routes.stream as stream_module
from gateway.main import create_app
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory


@pytest.fixture
def app_instance() -> FastAPI:
    """Create a fresh FastAPI app instance for testing."""
    return create_app()


@pytest.fixture
def client(app_instance: FastAPI) -> TestClient:
    """Provide a TestClient for WebSocket testing."""
    return TestClient(app_instance)


@pytest.mark.unit
class TestWebSocketAuthentication:
    """Test suite verifying WebSocket first-message authentication state machine."""

    def test_successful_authentication_and_streaming(self, client: TestClient) -> None:
        """Verify successful first-message authentication transitions to streaming."""
        token = AuthTestFactory.valid_jwt(tenant_id="tenant_stream_valid", role=Role.API_CLIENT)

        with client.websocket_connect("/v1/verify/stream") as ws:
            # 1. Challenge event on connection
            challenge = ws.receive_json()
            assert challenge["event_type"] == "connection_pending_auth"
            assert challenge["status"] == "awaiting_auth"
            assert "trace_id" in challenge

            # 2. First message: Send JWT authentication
            ws.send_json({"action": "authenticate", "token": token})

            # 3. Connection established event
            established = ws.receive_json()
            assert established["event_type"] == "connection_established"
            assert established["status"] == "ready"
            assert established["tenant_id"] == "tenant_stream_valid"
            assert established["role"] == Role.API_CLIENT.value

            # 4. Verification processing can now proceed
            ws.send_json(
                {
                    "prompt": "What is the boiling point of water?",
                    "response": "Water boils at 100 degrees Celsius at standard atmospheric pressure.",
                }
            )

            claims_event = ws.receive_json()
            assert claims_event["event_type"] == "claims_extracted"
            assert claims_event["claims_count"] >= 1

            signals_event = ws.receive_json()
            assert signals_event["event_type"] == "signals_computed"
            assert "signal_attribution" in signals_event

            complete_event = ws.receive_json()
            assert complete_event["event_type"] == "verification_complete"
            assert 0.0 <= complete_event["hrs_score"] <= 1.0
            assert complete_event["risk_tier"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    def test_authoritative_tenant_used_for_verification(self, client: TestClient) -> None:
        """Verify that authoritative tenant from JWT is passed to verification request."""
        token = AuthTestFactory.valid_jwt(tenant_id="tenant_authoritative_99", role=Role.TENANT_ADMIN)

        with client.websocket_connect("/v1/verify/stream") as ws:
            ws.receive_json()  # connection_pending_auth
            ws.send_json({"token": token})

            established = ws.receive_json()
            assert established["event_type"] == "connection_established"
            assert established["tenant_id"] == "tenant_authoritative_99"

    def test_client_tenant_spoofing_ignored(self, client: TestClient) -> None:
        """Verify that a non-super-admin client cannot override the authoritative tenant."""
        token = AuthTestFactory.valid_jwt(tenant_id="tenant_legitimate", role=Role.API_CLIENT)

        with patch.object(
            stream_module._orchestrator,
            "verify_request",
            wraps=stream_module._orchestrator.verify_request,
        ) as spy_verify:
            with client.websocket_connect("/v1/verify/stream") as ws:
                ws.receive_json()  # connection_pending_auth
                ws.send_json({"token": token})
                ws.receive_json()  # connection_established

                # Client attempts to spoof tenant as 'tenant_victim'
                ws.send_json(
                    {
                        "prompt": "What is photosynthesis?",
                        "response": "Photosynthesis converts light into chemical energy in plants.",
                        "tenant_id": "tenant_victim",
                    }
                )

                ws.receive_json()  # claims_extracted
                ws.receive_json()  # signals_computed
                ws.receive_json()  # verification_complete

                # Verify orchestrator was called with 'tenant_legitimate', NOT 'tenant_victim'
                assert spy_verify.called
                call_args = spy_verify.call_args[0][0]
                assert call_args.tenant_id == "tenant_legitimate"
                assert call_args.tenant_id != "tenant_victim"

    def test_super_admin_client_tenant_payload_ignored(self, client: TestClient) -> None:
        """Verify that even a SUPER_ADMIN caller cannot override the authoritative tenant via payload."""
        token = AuthTestFactory.valid_jwt(tenant_id="tenant_admin_a", role=Role.SUPER_ADMIN)

        with patch.object(
            stream_module._orchestrator,
            "verify_request",
            wraps=stream_module._orchestrator.verify_request,
        ) as spy_verify:
            with client.websocket_connect("/v1/verify/stream") as ws:
                ws.receive_json()  # connection_pending_auth
                ws.send_json({"token": token})
                established = ws.receive_json()  # connection_established
                assert established["tenant_id"] == "tenant_admin_a"
                assert established["role"] == Role.SUPER_ADMIN.value

                # SUPER_ADMIN sends verification payload attempting to target 'tenant_b'
                ws.send_json(
                    {
                        "prompt": "Explain gravitational waves",
                        "response": "Gravitational waves are ripples in spacetime caused by accelerating masses.",
                        "tenant_id": "tenant_b",
                    }
                )

                ws.receive_json()  # claims_extracted
                ws.receive_json()  # signals_computed
                ws.receive_json()  # verification_complete

                # Verify orchestrator was called with authoritative 'tenant_admin_a', NEVER 'tenant_b'
                assert spy_verify.called
                call_args = spy_verify.call_args[0][0]
                assert call_args.tenant_id == "tenant_admin_a"
                assert call_args.tenant_id != "tenant_b"

    def test_malformed_jwt_rejected_with_1008(self, client: TestClient) -> None:
        """Verify malformed JWT returns auth_failure and closes with code 1008."""
        with client.websocket_connect("/v1/verify/stream") as ws:
            ws.receive_json()  # connection_pending_auth
            ws.send_json({"token": "invalid.jwt.token.string"})

            failure = ws.receive_json()
            assert failure["event_type"] == "auth_failure"
            assert failure["error_code"] == "INVALID_TOKEN"

            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
            assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION

    def test_expired_jwt_rejected_with_1008(self, client: TestClient) -> None:
        """Verify expired JWT returns auth_failure and closes with code 1008."""
        expired_token = AuthTestFactory.expired_jwt(tenant_id="tenant_expired")

        with client.websocket_connect("/v1/verify/stream") as ws:
            ws.receive_json()  # connection_pending_auth
            ws.send_json({"token": expired_token})

            failure = ws.receive_json()
            assert failure["event_type"] == "auth_failure"
            assert failure["error_code"] == "INVALID_TOKEN"

            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
            assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION

    def test_tampered_jwt_rejected_with_1008(self, client: TestClient) -> None:
        """Verify tampered JWT secret returns auth_failure and closes with code 1008."""
        tampered_token = AuthTestFactory.tampered_jwt(tenant_id="tenant_tampered")

        with client.websocket_connect("/v1/verify/stream") as ws:
            ws.receive_json()  # connection_pending_auth
            ws.send_json({"token": tampered_token})

            failure = ws.receive_json()
            assert failure["event_type"] == "auth_failure"
            assert failure["error_code"] == "INVALID_TOKEN"

            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
            assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION

    def test_missing_verify_write_permission_rejected(self, client: TestClient) -> None:
        """Verify roles lacking VERIFY_WRITE (e.g. VIEWER) are rejected with code 1008."""
        viewer_token = AuthTestFactory.valid_jwt(tenant_id="tenant_viewer", role=Role.VIEWER)

        with client.websocket_connect("/v1/verify/stream") as ws:
            ws.receive_json()  # connection_pending_auth
            ws.send_json({"token": viewer_token})

            failure = ws.receive_json()
            assert failure["event_type"] == "auth_failure"
            assert failure["error_code"] == "INSUFFICIENT_PERMISSIONS"
            assert "verify:write" in failure["message"]

            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
            assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION

    def test_unauthenticated_verification_attempt_blocked(self, client: TestClient) -> None:
        """Verify client sending verification request before authenticating is blocked and disconnected."""
        with client.websocket_connect("/v1/verify/stream") as ws:
            ws.receive_json()  # connection_pending_auth

            # Client attempts to send verification request without authenticating first
            ws.send_json(
                {
                    "prompt": "Tell me a story",
                    "response": "Once upon a time in a land far away.",
                }
            )

            failure = ws.receive_json()
            assert failure["event_type"] == "auth_failure"
            assert failure["error_code"] == "AUTH_REQUIRED"

            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
            assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION

    def test_invalid_json_payload_rejected(self, client: TestClient) -> None:
        """Verify non-JSON payload as first message is rejected with code 1008."""
        with client.websocket_connect("/v1/verify/stream") as ws:
            ws.receive_json()  # connection_pending_auth
            ws.send_text("this is not valid json")

            failure = ws.receive_json()
            assert failure["event_type"] == "auth_failure"
            assert failure["error_code"] == "INVALID_PAYLOAD"

            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
            assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION

    def test_authentication_timeout_closes_1008(self, client: TestClient) -> None:
        """Verify client failing to authenticate within deadline is disconnected with code 1008."""
        # Patch timeout to a short duration for fast deterministic unit test
        with patch.object(stream_module, "AUTH_TIMEOUT_SECONDS", 0.05):
            with client.websocket_connect("/v1/verify/stream") as ws:
                challenge = ws.receive_json()
                assert challenge["event_type"] == "connection_pending_auth"

                # Do not send any message; wait for timeout
                time.sleep(0.1)

                failure = ws.receive_json()
                assert failure["event_type"] == "auth_failure"
                assert failure["error_code"] == "AUTH_TIMEOUT"

                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_text()
                assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION

    def test_bearer_prefix_accepted_in_token(self, client: TestClient) -> None:
        """Verify token passed with 'Bearer ' prefix is accepted."""
        token = AuthTestFactory.valid_jwt(tenant_id="tenant_bearer_test", role=Role.API_CLIENT)

        with client.websocket_connect("/v1/verify/stream") as ws:
            ws.receive_json()  # connection_pending_auth
            ws.send_json({"token": f"Bearer {token}"})

            established = ws.receive_json()
            assert established["event_type"] == "connection_established"
            assert established["tenant_id"] == "tenant_bearer_test"
