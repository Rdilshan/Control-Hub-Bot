from fastapi import APIRouter
from app.api.routes import client_bot_webhook, control_hub_webhook, health

api_router = APIRouter()

# Health endpoints (kept at root level /health and /health/ready per spec)
api_router.include_router(health.router)

# Versioned API sub-router
v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(control_hub_webhook.router)
v1_router.include_router(client_bot_webhook.router)
api_router.include_router(v1_router)

