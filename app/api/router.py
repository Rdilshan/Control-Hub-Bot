"""Main API router registry."""

from fastapi import APIRouter
from app.api.routes import health

api_router = APIRouter()

# Health endpoints (kept at root level /health and /health/ready per spec)
api_router.include_router(health.router)

# Versioned API sub-router for future endpoints
v1_router = APIRouter(prefix="/api/v1")
api_router.include_router(v1_router)
