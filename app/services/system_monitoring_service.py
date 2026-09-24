"""System Monitoring Service for infrastructure health, worker heartbeats, and operational reporting."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utc_now
from app.db.session import check_db_health
from app.logging_config import get_logger
from app.redis.client import check_redis_health, get_redis

logger = get_logger(__name__)

WORKER_HEARTBEAT_PREFIX = "controlhub:worker:"
WORKER_HEARTBEAT_TTL = 60  # seconds
KNOWN_WORKERS_SET = "controlhub:workers:known"


class SystemMonitoringService:
    """Monitors platform operational health, database connectivity, redis, and worker heartbeats."""

    def __init__(self, session: Optional[AsyncSession] = None):
        self.session = session

    async def record_worker_heartbeat(
        self,
        worker_name: str,
        active_tasks: int = 0,
        completed_tasks: int = 0,
    ) -> None:
        """Records a heartbeat for a Celery or background worker in Redis."""
        try:
            redis = get_redis()
            data = {
                "worker_name": worker_name,
                "active_tasks": active_tasks,
                "completed_tasks": completed_tasks,
                "last_heartbeat_at": utc_now().isoformat(),
            }
            # Set heartbeat key with TTL
            heartbeat_key = f"{WORKER_HEARTBEAT_PREFIX}{worker_name}:heartbeat"
            await redis.set(heartbeat_key, json.dumps(data), ex=WORKER_HEARTBEAT_TTL)
            # Register in known workers set
            await redis.sadd(KNOWN_WORKERS_SET, worker_name)
        except Exception as exc:
            logger.warning(f"Could not record worker heartbeat for '{worker_name}': {exc}")

    async def get_worker_statuses(self) -> Dict[str, Any]:
        """Checks status of all registered background workers."""
        try:
            redis = get_redis()
            known_workers = await redis.smembers(KNOWN_WORKERS_SET)
            if not known_workers:
                return {
                    "total_workers": 0,
                    "online_workers": 0,
                    "offline_workers": 0,
                    "workers": [],
                    "status_label": "⚪ No Workers Registered",
                }

            online_count = 0
            offline_count = 0
            worker_list: List[Dict[str, Any]] = []

            for w_name in known_workers:
                heartbeat_key = f"{WORKER_HEARTBEAT_PREFIX}{w_name}:heartbeat"
                data_raw = await redis.get(heartbeat_key)
                if data_raw:
                    online_count += 1
                    info = json.loads(data_raw)
                    info["status"] = "ONLINE"
                    worker_list.append(info)
                else:
                    offline_count += 1
                    worker_list.append({
                        "worker_name": w_name,
                        "status": "OFFLINE",
                        "last_heartbeat_at": None,
                    })

            if offline_count > 0:
                label = f"⚠️ {offline_count} offline"
            elif online_count > 0:
                label = f"✅ {online_count} online"
            else:
                label = "⚠️ No active workers"

            return {
                "total_workers": len(known_workers),
                "online_workers": online_count,
                "offline_workers": offline_count,
                "workers": worker_list,
                "status_label": label,
            }
        except Exception as exc:
            logger.debug(f"Worker status check error: {exc}")
            return {
                "total_workers": 0,
                "online_workers": 0,
                "offline_workers": 0,
                "workers": [],
                "status_label": "⚠️ Unavailable",
            }

    async def get_system_health(self) -> Dict[str, Any]:
        """Runs fast, lightweight health checks on core platform components."""
        db_ok = await check_db_health()
        redis_ok = await check_redis_health()
        worker_info = await self.get_worker_statuses()

        overall_ok = db_ok and redis_ok

        return {
            "status": "HEALTHY" if overall_ok else "DEGRADED",
            "api": "✅ Online",
            "database": "✅ Online" if db_ok else "❌ Offline",
            "redis": "✅ Online" if redis_ok else "❌ Offline",
            "workers": worker_info["status_label"],
            "worker_details": worker_info,
        }
