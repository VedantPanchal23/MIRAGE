"""Unit tests for enterprise inquiries API route."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gateway.main import create_app


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.mark.asyncio
async def test_submit_inquiry_success(app: FastAPI) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "name": "Sarah Connor",
            "email": "sarah@cyberdyne.com",
            "company": "Cyberdyne Systems",
            "team_size": "50-250",
            "use_case": "Autonomous FinTech Transfers",
            "message": "We need Gate 3 lease fencing for our autonomous treasury agents.",
        }
        res = await client.post("/v1/inquiries", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["id"].startswith("inq_")
        assert data["name"] == "Sarah Connor"
        assert data["email"] == "sarah@cyberdyne.com"
        assert data["status"] == "PENDING"
        assert "4 hours" in data["confirmation_message"]


@pytest.mark.asyncio
async def test_submit_inquiry_validation_failure(app: FastAPI) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid email and short message
        payload = {
            "name": "S",
            "email": "not-an-email",
            "company": "",
            "message": "hi",
        }
        res = await client.post("/v1/inquiries", json=payload)
        assert res.status_code == 422
