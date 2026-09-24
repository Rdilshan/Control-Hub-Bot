"""Integration tests for health, readiness, and middleware tracking."""

import pytest
from httpx import AsyncClient
from app.core.constants import HEADER_REQUEST_ID


@pytest.mark.asyncio
async def test_health_liveness_endpoint(app_client: AsyncClient):
    """Verifies /health endpoint returns 200 status ok."""
    response = await app_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert HEADER_REQUEST_ID in response.headers


@pytest.mark.asyncio
async def test_health_readiness_both_healthy(app_client: AsyncClient, mocker):
    """Verifies /health/ready returns 200 when database and redis are healthy."""
    mocker.patch("app.api.routes.health.check_db_health", return_value=True)
    mocker.patch("app.api.routes.health.check_redis_health", return_value=True)

    response = await app_client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["services"]["database"] == "ok"
    assert data["services"]["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_readiness_db_failure(app_client: AsyncClient, mocker):
    """Verifies /health/ready returns 503 when database is unhealthy."""
    mocker.patch("app.api.routes.health.check_db_health", return_value=False)
    mocker.patch("app.api.routes.health.check_redis_health", return_value=True)

    response = await app_client.get("/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["services"]["database"] == "unhealthy"
    assert data["services"]["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_readiness_redis_failure(app_client: AsyncClient, mocker):
    """Verifies /health/ready returns 503 when redis is unhealthy."""
    mocker.patch("app.api.routes.health.check_db_health", return_value=True)
    mocker.patch("app.api.routes.health.check_redis_health", return_value=False)

    response = await app_client.get("/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["services"]["database"] == "ok"
    assert data["services"]["redis"] == "unhealthy"


@pytest.mark.asyncio
async def test_root_endpoint(app_client: AsyncClient):
    """Verifies root endpoint returns service metadata."""
    response = await app_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert data["version"] == "0.1.0"
