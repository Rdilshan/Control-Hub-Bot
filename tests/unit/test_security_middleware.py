"""Unit tests for security middlewares."""

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.safe_logging import SafeLoggingMiddleware


@pytest.mark.asyncio
async def test_security_headers_and_request_id_middleware():
    test_app = FastAPI()
    test_app.add_middleware(SecurityHeadersMiddleware)
    test_app.add_middleware(RequestIDMiddleware)

    @test_app.get("/test")
    async def sample_endpoint(request: Request):
        return {"status": "ok", "req_id": getattr(request.state, "request_id", None)}

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/test", headers={"X-Request-ID": "custom-uuid-123"})

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "custom-uuid-123"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "Strict-Transport-Security" in response.headers


@pytest.mark.asyncio
async def test_safe_logging_middleware_rejects_oversized_payload():
    test_app = FastAPI()
    test_app.add_middleware(SafeLoggingMiddleware)

    @test_app.post("/test-webhook")
    async def sample_post():
        return {"status": "ok"}

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Simulate Content-Length exceeding 1MB (e.g. 2MB)
        response = await client.post(
            "/test-webhook",
            headers={"Content-Length": "2000000"},
            content=b"test",
        )
        assert response.status_code == 413
        data = response.json()
        assert data["error"] == "Payload Too Large"
