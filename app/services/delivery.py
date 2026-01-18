from __future__ import annotations

from pathlib import Path
import uuid

from aiogram import Bot
from aiogram.types import FSInputFile
from structlog import get_logger

from app.models import Job, User

logger = get_logger()


async def deliver_result(bot: Bot, user: User, job: Job) -> bool:
    request_id = uuid.uuid4().hex
    result = job.result or {}
    file_path = result.get("file_path")
    file_url = result.get("file_url")
    message = result.get("message")
    try:
        if file_path:
            path = Path(file_path)
            if path.exists():
                await bot.send_document(user.telegram_id, FSInputFile(path))
                logger.info("task_delivered_file", request_id=request_id, task_id=job.id, user_id=user.id)
                return True
        if file_url:
            await bot.send_message(user.telegram_id, f"✅ Готово. Ссылка на результат:\n{file_url}")
            logger.info("task_delivered_url", request_id=request_id, task_id=job.id, user_id=user.id)
            return True
        if message:
            await bot.send_message(user.telegram_id, message)
            logger.info("task_delivered_message", request_id=request_id, task_id=job.id, user_id=user.id)
            return True
        await bot.send_message(user.telegram_id, "✅ Готово.")
        logger.info("task_delivered_default", request_id=request_id, task_id=job.id, user_id=user.id)
        return True
    except Exception as exc:
        logger.exception("task_delivery_failed", request_id=request_id, task_id=job.id, error=str(exc))
        return False
