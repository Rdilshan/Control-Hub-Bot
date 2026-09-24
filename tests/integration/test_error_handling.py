"""Integration tests for exception handler middleware and JSON response schema."""

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from app.exceptions import NotFoundError, ValidationError
from app.main import create_app


@pytest.mark.asyncio
async def test_custom_exception_response_format():
    """Verifies that throwing ApplicationError returns standard formatted JSON."""
    app = create_app()

    @app.get("/test-not-found")
    async def trigger_not_found():
        raise NotFoundError("Client bot with ID 99 was not found")

    @app.get("/test-validation")
    async def trigger_validation():
        raise ValidationError("Invalid bot token parameter", details={"field": "token"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/test-not-found")
        assert res.status_code == 404
        data = res.json()
        assert data["success"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "ID 99" in data["error"]["message"]
        assert "request_id" in data

        res_val = await client.get("/test-validation")
        assert res_val.status_code == 422
        data_val = res_val.json()
        assert data_val["success"] is False
        assert data_val["error"]["code"] == "VALIDATION_ERROR"
        assert data_val["error"]["details"]["field"] == "token"
