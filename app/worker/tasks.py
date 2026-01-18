from __future__ import annotations

import asyncio
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import select
from structlog import get_logger

from app.config import settings
from app.crud import update_job_status
from app.db import async_session_factory
from app.models import Job, JobStatus, Section, User
from app.bot.keyboards import summarize_button
from app.text_utils import split_text

logger = get_logger()


async def _process(job_id: int) -> None:
    async with async_session_factory() as session:
        job = await session.get(Job, job_id)
        if not job:
            return
        await update_job_status(session, job.id, JobStatus.processing)
        await session.refresh(job)
        if job.section == Section.text:
            prompt = job.payload.get("prompt", "")
            result_payload = {"message": prompt or "Текст готов."}
        else:
            result_payload = {"message": "Готово"}
        await update_job_status(session, job.id, JobStatus.done, result_payload)
        await session.refresh(job)
        user = await session.get(User, job.user_id)
        if not user:
            return
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    if job.section == Section.text:
        text = job.result.get("message", "Готово")
        parts = split_text(text)
        for part in parts:
            await bot.send_message(user.telegram_id, part)
        await bot.send_message(user.telegram_id, "Нужен краткий вариант?", reply_markup=summarize_button())
    else:
        await bot.send_message(user.telegram_id, "✅ Готово. Результат отправлен документом.")
    await bot.session.close()


def process_job(job_id: int) -> None:
    asyncio.run(_process(job_id))


async def _broadcast(message: str) -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.is_active.is_(True)))
        users = result.scalars().all()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    for user in users:
        try:
            await bot.send_message(user.telegram_id, message)
        except Exception:
            logger.info("broadcast_failed", user_id=user.id)
            async with async_session_factory() as session:
                stored = await session.get(User, user.id)
                if stored:
                    stored.is_active = False
                    await session.commit()
    await bot.session.close()


def broadcast_message(message: str) -> None:
    asyncio.run(_broadcast(message))
