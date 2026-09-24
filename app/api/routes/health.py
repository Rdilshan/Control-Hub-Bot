"""Health and readiness check endpoints."""

from fastapi import APIRouter, Response, status
from app.db.session import check_db_health
from app.redis.client import check_redis_health

router = APIRouter(tags=["Health"])


@router.get("/health", status_code=status.HTTP_200_OK)
async def liveness_check():
    """Liveness probe to check if the application process is running."""
    return {"status": "ok"}


@router.get("/health/ready", status_code=status.HTTP_200_OK)
@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check(response: Response):
    """Readiness probe to check if PostgreSQL and Redis dependencies are accessible."""
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()

    is_ready = db_ok and redis_ok

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if is_ready else "not_ready",
        "services": {
            "database": "ok" if db_ok else "unhealthy",
            "redis": "ok" if redis_ok else "unhealthy",
        },
    }
