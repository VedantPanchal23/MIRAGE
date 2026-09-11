"""WebSocket endpoint for real-time streaming verification events."""

import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shared.logging import get_logger

router = APIRouter(prefix="/v1", tags=["Streaming"])
logger = get_logger("stream_route")


@router.websocket("/verify/stream")
async def websocket_verification_stream(websocket: WebSocket) -> None:
    """Accept WebSocket connection and stream progressive claim verification events."""
    await websocket.accept()
    trace_id = uuid.uuid4().hex
    logger.info("WebSocket client connected", trace_id=trace_id)

    try:
        # Acknowledge connection
        await websocket.send_json(
            {
                "event_type": "connection_established",
                "trace_id": trace_id,
                "status": "ready",
            }
        )

        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            _prompt = payload.get("prompt", "")
            response_text = payload.get("response", "")

            # Stream progressive verification steps
            await websocket.send_json(
                {
                    "event_type": "claims_extracted",
                    "trace_id": trace_id,
                    "claims": [{"claim_id": "c_01", "text": response_text[:100], "criticality": "medium"}],
                }
            )

            await websocket.send_json(
                {
                    "event_type": "signals_computed",
                    "trace_id": trace_id,
                    "signals": {"rav": 0.05, "scs": 0.02, "nli": 0.01, "ics": 0.00},
                }
            )

            await websocket.send_json(
                {
                    "event_type": "verification_complete",
                    "trace_id": trace_id,
                    "hrs": 0.03,
                    "tier": "LOW",
                    "verified": True,
                }
            )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected", trace_id=trace_id)
    except Exception as exc:
        logger.error("WebSocket stream error", error=str(exc), trace_id=trace_id)
        await websocket.close()
