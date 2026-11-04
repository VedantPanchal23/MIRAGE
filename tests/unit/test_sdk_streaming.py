"""Unit tests for Mirage Python SDK streaming verification."""

import httpx
import pytest
from mirage_sdk.client import AsyncMirageClient, MirageClient


def _make_sse_response(_request: httpx.Request) -> httpx.Response:
    content = (
        b"event: connected\r\n"
        b'data: {"trace_id": "tr_123"}\r\n\r\n'
        b"event: claims_extracted\r\n"
        b'data: {"claims_count": 2}\r\n\r\n'
        b"event: claim_verified\r\n"
        b'data: {"claim_id": "c1", "status": "SUPPORTED", "attribution": {"rav": 0.95}}\r\n\r\n'
        b"event: verification_complete\r\n"
        b'data: {"hrs_score": 0.04, "risk_tier": "LOW"}\r\n\r\n'
    )
    return httpx.Response(200, content=content, headers={"Content-Type": "text/event-stream"})


def test_sync_stream_verify() -> None:
    transport = httpx.MockTransport(_make_sse_response)
    client = MirageClient(api_key="test_key", transport=transport)

    events = list(client.stream_verify(prompt="test prompt", response="test response"))

    assert len(events) == 4
    assert events[0]["event"] == "connected"
    assert events[0]["data"]["trace_id"] == "tr_123"
    assert events[1]["event"] == "claims_extracted"
    assert events[1]["data"]["claims_count"] == 2
    assert events[2]["event"] == "claim_verified"
    assert events[2]["data"]["status"] == "SUPPORTED"
    assert events[3]["event"] == "verification_complete"
    assert events[3]["data"]["hrs_score"] == 0.04


@pytest.mark.asyncio
async def test_async_stream_verify() -> None:
    transport = httpx.MockTransport(_make_sse_response)
    client = AsyncMirageClient(api_key="test_key", transport=transport)

    events = []
    async for event in client.stream_verify(prompt="test prompt", response="test response"):
        events.append(event)

    assert len(events) == 4
    assert events[0]["event"] == "connected"
    assert events[1]["event"] == "claims_extracted"
    assert events[2]["event"] == "claim_verified"
    assert events[3]["event"] == "verification_complete"
