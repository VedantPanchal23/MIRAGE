"""WebSocket endpoint for progressive, real-time streaming verification events.

Implements Technical Architecture Document §3.4 & §7:
- Real-time incremental event protocol over WebSocket:
  1. connection_established (trace_id, status)
  2. claims_extracted (real AtomicClaimDecomposer claims)
  3. signals_computed (real RAV, SCS, NLI, ICS scores)
  4. verification_complete (calibrated HRS, Mondrian CI, risk tier, verified response)
"""

import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from models.flan_t5.decomposer import AtomicClaimDecomposer
from shared.logging import get_logger
from shared.schemas import VerificationRequest
from workers.orchestrator import VerificationOrchestrator

router = APIRouter(prefix="/v1", tags=["Streaming"])
logger = get_logger("stream_route")

_decomposer = AtomicClaimDecomposer()
_orchestrator = VerificationOrchestrator()


@router.websocket("/verify/stream")
async def websocket_verification_stream(websocket: WebSocket) -> None:
    """Accept WebSocket connection and stream progressive claim verification events in real time."""
    await websocket.accept()
    trace_id = uuid.uuid4().hex
    logger.info("WebSocket client connected", trace_id=trace_id)

    try:
        # 1. Connection acknowledgement event
        await websocket.send_json(
            {
                "event_type": "connection_established",
                "trace_id": trace_id,
                "status": "ready",
            }
        )

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

            prompt = payload.get("prompt", "")
            response_text = payload.get("response", "")
            tenant_id = payload.get("tenant_id", "default_tenant")
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

            # 2. Extract real atomic claims via FLAN-T5
            claims = _decomposer.decompose(response_text)
            await websocket.send_json(
                {
                    "event_type": "claims_extracted",
                    "trace_id": trace_id,
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

            # 3. Execute multi-signal verification pipeline
            req = VerificationRequest(
                prompt=prompt or response_text,
                response=response_text,
                tenant_id=tenant_id,
                images=images,
            )
            result = await _orchestrator.verify_request(req)

            # 4. Stream signals computed
            await websocket.send_json(
                {
                    "event_type": "signals_computed",
                    "trace_id": trace_id,
                    "signal_attribution": result.hrs_result.signal_attribution.model_dump(),
                    "contradicted_claims": [
                        c.claim.claim_id for c in result.claims if c.status.value == "CONTRADICTED"
                    ],
                }
            )

            # 5. Stream final verification verdict
            await websocket.send_json(
                {
                    "event_type": "verification_complete",
                    "trace_id": trace_id,
                    "hrs_score": result.hrs_result.hrs,
                    "risk_tier": result.hrs_result.tier.value,
                    "conformal_interval": {
                        "lower": result.hrs_result.conformal_interval.lower,
                        "upper": result.hrs_result.conformal_interval.upper,
                    },
                    "correction_applied": result.metadata.correction_applied,
                    "verified_response": result.verified_response,
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
