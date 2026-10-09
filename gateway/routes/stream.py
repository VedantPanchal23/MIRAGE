"""WebSocket endpoint for progressive, real-time streaming verification events.

Implements Technical Architecture Document §3.4 & §7, and Security & Access Document §4.4:
- Explicit authentication state machine:
  1. Transport connection accepted -> enters AWAITING_AUTH state (10s deadline).
  2. First client message must contain valid JWT token.
  3. Token decoded cryptographically; tenant_id and role extracted authoritatively.
  4. Permission.VERIFY_WRITE strictly enforced.
  5. Close code 1008 (Policy Violation) dispatched on timeout, malformed token, or permission failure.
  6. Transition to AUTHENTICATED state -> streams progressive verification events.
  7. Client tenant spoofing strictly rejected/ignored in favor of authoritative tenant.
"""

import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from gateway.middleware.auth import decode_access_token
from models.flan_t5.decomposer import AtomicClaimDecomposer
from services.output_assurance import output_assurance_service
from shared.logging import get_logger
from shared.schemas import VerificationRequest
from shared.schemas.auth import ROLE_PERMISSIONS, Permission
from workers.orchestrator import VerificationOrchestrator

router = APIRouter(prefix="/v1", tags=["Streaming"])
logger = get_logger("stream_route")

_decomposer = AtomicClaimDecomposer()
_orchestrator = VerificationOrchestrator()

# Authentication deadline in seconds (Security & Access Document §4.4)
AUTH_TIMEOUT_SECONDS: float = 10.0


@router.websocket("/verify/stream")
async def websocket_verification_stream(websocket: WebSocket) -> None:
    """Accept WebSocket connection and stream progressive claim verification events in real time."""
    # 1. Transport Acceptance
    await websocket.accept()
    trace_id = uuid.uuid4().hex
    logger.info("WebSocket client transport connected", trace_id=trace_id)

    try:
        # Emit transport acceptance challenge (State: AWAITING_AUTH)
        await websocket.send_json(
            {
                "event_type": "connection_pending_auth",
                "trace_id": trace_id,
                "status": "awaiting_auth",
                "timeout_seconds": AUTH_TIMEOUT_SECONDS,
            }
        )

        # 2. First-Message Authentication (10-second deadline)
        try:
            auth_raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning("WebSocket authentication timed out after deadline", trace_id=trace_id)
            try:
                await websocket.send_json(
                    {
                        "event_type": "auth_failure",
                        "trace_id": trace_id,
                        "error_code": "AUTH_TIMEOUT",
                        "message": "Authentication timed out after 10 seconds",
                    }
                )
            except Exception:
                pass
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        try:
            auth_payload = json.loads(auth_raw)
        except json.JSONDecodeError:
            logger.warning("WebSocket first message is not valid JSON", trace_id=trace_id)
            try:
                await websocket.send_json(
                    {
                        "event_type": "auth_failure",
                        "trace_id": trace_id,
                        "error_code": "INVALID_PAYLOAD",
                        "message": "First message must be valid JSON authentication payload",
                    }
                )
            except Exception:
                pass
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        if not isinstance(auth_payload, dict):
            logger.warning("WebSocket first message is not a JSON object", trace_id=trace_id)
            try:
                await websocket.send_json(
                    {
                        "event_type": "auth_failure",
                        "trace_id": trace_id,
                        "error_code": "INVALID_PAYLOAD",
                        "message": "First message payload must be a JSON object",
                    }
                )
            except Exception:
                pass
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        raw_token = auth_payload.get("token") or auth_payload.get("authorization")
        if not raw_token or not isinstance(raw_token, str) or not raw_token.strip():
            logger.warning("WebSocket first message missing authentication token", trace_id=trace_id)
            try:
                await websocket.send_json(
                    {
                        "event_type": "auth_failure",
                        "trace_id": trace_id,
                        "error_code": "AUTH_REQUIRED",
                        "message": "First message must contain 'token' for authentication",
                    }
                )
            except Exception:
                pass
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        token = raw_token.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()

        # 3. Cryptographic Token Validation
        try:
            auth_context = await decode_access_token(token)
        except HTTPException as exc:
            logger.warning("WebSocket JWT validation rejected", trace_id=trace_id, error=str(exc.detail))
            try:
                await websocket.send_json(
                    {
                        "event_type": "auth_failure",
                        "trace_id": trace_id,
                        "error_code": "INVALID_TOKEN",
                        "message": str(exc.detail),
                    }
                )
            except Exception:
                pass
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        except Exception as exc:
            logger.warning("WebSocket unexpected token decoding error", trace_id=trace_id, error=str(exc))
            try:
                await websocket.send_json(
                    {
                        "event_type": "auth_failure",
                        "trace_id": trace_id,
                        "error_code": "INVALID_TOKEN",
                        "message": "Authentication token verification failed",
                    }
                )
            except Exception:
                pass
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # 4. Permission Enforcement (VERIFY_WRITE required for verification streaming)
        allowed_permissions = ROLE_PERMISSIONS.get(auth_context.role, set())
        if Permission.VERIFY_WRITE not in allowed_permissions:
            logger.warning(
                "WebSocket authentication rejected: role lacks verify:write",
                trace_id=trace_id,
                role=auth_context.role.value,
                tenant_id=auth_context.tenant_id,
            )
            try:
                await websocket.send_json(
                    {
                        "event_type": "auth_failure",
                        "trace_id": trace_id,
                        "error_code": "INSUFFICIENT_PERMISSIONS",
                        "message": f"Role '{auth_context.role.value}' lacks required permission 'verify:write'",
                    }
                )
            except Exception:
                pass
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # 5. Authoritative Identity Established
        authoritative_tenant_id = auth_context.tenant_id
        authoritative_role = auth_context.role

        logger.info(
            "WebSocket authenticated successfully",
            trace_id=trace_id,
            tenant_id=authoritative_tenant_id,
            role=authoritative_role.value,
        )

        await websocket.send_json(
            {
                "event_type": "connection_established",
                "trace_id": trace_id,
                "status": "ready",
                "tenant_id": authoritative_tenant_id,
                "role": authoritative_role.value,
            }
        )

        # 6. Post-Authentication Progressive Verification Loop
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {
                        "event_type": "error",
                        "trace_id": trace_id,
                        "message": "Invalid JSON message payload",
                    }
                )
                continue

            if not isinstance(payload, dict):
                await websocket.send_json(
                    {
                        "event_type": "error",
                        "trace_id": trace_id,
                        "message": "Verification request payload must be a JSON object",
                    }
                )
                continue

            prompt = payload.get("prompt", "")
            response_text = payload.get("response", "")
            images = payload.get("images", [])

            if not response_text.strip():
                await websocket.send_json(
                    {
                        "event_type": "error",
                        "trace_id": trace_id,
                        "message": "Response text cannot be empty",
                    }
                )
                continue

            # Authoritative tenant isolation enforcement:
            # Client-supplied tenant_id is NEVER used to determine the verification tenant.
            # Authoritative tenant is derived exclusively from the validated JWT for ALL roles (including SUPER_ADMIN).
            client_tenant = payload.get("tenant_id")
            if client_tenant and client_tenant != authoritative_tenant_id:
                logger.warning(
                    "WebSocket client tenant mismatch ignored; strictly enforcing authoritative tenant",
                    trace_id=trace_id,
                    authoritative_tenant=authoritative_tenant_id,
                    attempted_tenant=client_tenant,
                    role=authoritative_role.value,
                )
            effective_tenant = authoritative_tenant_id

            # Extract atomic claims via FLAN-T5
            claims = _decomposer.decompose(response_text)
            await websocket.send_json(
                {
                    "event_type": "claims_extracted",
                    "trace_id": trace_id,
                    "assurance_status": "UNVERIFIED_SPECULATIVE",
                    "claims_count": len(claims),
                    "claims": [
                        {
                            "claim_id": c.claim_id,
                            "text": c.text,
                            "type": c.claim_type.value,
                            "criticality": c.criticality.value,
                        }
                        for c in claims
                    ],
                }
            )

            # Execute multi-signal verification pipeline
            req = VerificationRequest(
                prompt=prompt or response_text,
                response=response_text,
                tenant_id=effective_tenant,
                images=images,
            )
            result = await _orchestrator.verify_request(req)

            # Stream signals computed
            await websocket.send_json(
                {
                    "event_type": "signals_computed",
                    "trace_id": trace_id,
                    "assurance_status": "UNVERIFIED_SPECULATIVE",
                    "signal_attribution": result.hrs_result.signal_attribution.model_dump(),
                    "contradicted_claims": [
                        c.claim.claim_id for c in result.claims if c.status.value == "CONTRADICTED"
                    ],
                }
            )

            # Gate 4 Tier 1 DLP & Safety Inspection
            final_stream_text = result.verified_response
            safety_res = output_assurance_service.run_dlp_and_safety(final_stream_text)
            if safety_res.redacted_content is not None:
                final_stream_text = safety_res.redacted_content
            if safety_res.prompt_injection_leakage:
                final_stream_text = (
                    "[RESPONSE BLOCKED BY MIRAGE GATE 4: Prompt injection/jailbreak control tokens detected]"
                )

            # Derive honest verification status
            if not safety_res.safe:
                ver_status = "BLOCKED"
            elif result.hrs_result.contradicted_claims_count > 0:
                ver_status = "CONTRADICTED"
            elif result.hrs_result.hrs >= 0.60:
                ver_status = "PARTIALLY_VERIFIED"
            else:
                ver_status = "VERIFIED"

            # Stream final verification verdict
            await websocket.send_json(
                {
                    "event_type": "verification_complete",
                    "trace_id": trace_id,
                    "hrs_score": result.hrs_result.hrs,
                    "risk_tier": result.hrs_result.tier.value,
                    "verification_status": ver_status,
                    "conformal_interval": {
                        "lower": result.hrs_result.conformal_interval.lower,
                        "upper": result.hrs_result.conformal_interval.upper,
                    },
                    "safety": {
                        "safe": safety_res.safe,
                        "secrets_detected": safety_res.secrets_detected,
                        "pii_detected": safety_res.pii_detected,
                        "prompt_injection_leakage": safety_res.prompt_injection_leakage,
                    },
                    "correction_applied": result.metadata.correction_applied,
                    "verified_response": final_stream_text,
                }
            )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected", trace_id=trace_id)
    except Exception as exc:
        logger.error("WebSocket stream error", error=str(exc), trace_id=trace_id)
        try:
            await websocket.close()
        except Exception:
            pass
