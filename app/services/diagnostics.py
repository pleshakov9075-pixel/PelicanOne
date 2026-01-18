from __future__ import annotations

import json
from datetime import datetime, timezone

from redis import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.config import settings
from app.worker.queue import queue as rq_queue

logger = get_logger()
redis_conn = Redis.from_url(settings.redis_url)


def record_error(message: str, *, context: dict | None = None) -> None:
    payload = {
        "message": message,
        "context": context or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        redis_conn.lpush("bot:last_errors", json.dumps(payload))
        redis_conn.ltrim("bot:last_errors", 0, 19)
    except Exception as exc:
        logger.exception("record_error_failed", error=str(exc))


def get_recent_errors(limit: int = 5) -> list[dict]:
    try:
        raw_items = redis_conn.lrange("bot:last_errors", 0, limit - 1)
        errors: list[dict] = []
        for item in raw_items:
            try:
                errors.append(json.loads(item))
            except json.JSONDecodeError:
                errors.append({"message": item.decode("utf-8", errors="ignore")})
        return errors
    except Exception as exc:
        logger.exception("recent_errors_failed", error=str(exc))
        return [{"message": "Не удалось загрузить ошибки"}]


def redis_status() -> str:
    try:
        return "ok" if redis_conn.ping() else "error"
    except Exception as exc:
        logger.exception("redis_status_failed", error=str(exc))
        return "error"


async def db_status(session: AsyncSession) -> str:
    try:
        await session.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        logger.exception("db_status_failed", error=str(exc))
        return "error"


def queue_length() -> int:
    try:
        return rq_queue.count()
    except Exception as exc:
        logger.exception("queue_length_failed", error=str(exc))
        return -1
