from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.crud import charge_balance, create_job_if_not_exists, get_job_by_idempotency_key
from app.models import Job, Section, User
from app.worker.queue import enqueue_job

logger = get_logger()


class TaskCreateError(Exception):
    pass


async def create_task(
    session: AsyncSession,
    *,
    section: Section,
    payload: dict,
    options: dict,
    user_id: int | None,
    telegram_id: int | None,
    price_rub: int,
    idempotency_key: str | None,
) -> Job:
    request_id = uuid.uuid4().hex
    logger.info(
        "task_create_service_start",
        request_id=request_id,
        user_id=user_id,
        telegram_id=telegram_id,
        section=section.value,
        idempotency_key=idempotency_key,
    )
    if user_id is None and telegram_id is None:
        raise TaskCreateError("user_id or telegram_id is required")
    if price_rub < 0:
        raise TaskCreateError("invalid price")
    user: User | None = None
    if user_id is not None:
        user = await session.get(User, user_id)
    if user is None and telegram_id is not None:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(telegram_id=telegram_id)
            session.add(user)
            await session.commit()
            await session.refresh(user)
    if not user:
        raise TaskCreateError("user not found")
    if price_rub and user.balance_rub < price_rub:
        raise TaskCreateError("insufficient balance")
    if idempotency_key:
        existing = await get_job_by_idempotency_key(session, idempotency_key)
        if existing:
            logger.info(
                "task_create_idempotent_hit",
                request_id=request_id,
                task_id=existing.id,
                idempotency_key=idempotency_key,
            )
            return existing
    merged_payload = {**payload, **options}
    if price_rub:
        await charge_balance(session, user, price_rub, "job_start")
    job = await create_job_if_not_exists(
        session,
        user.id,
        None,
        section,
        price_rub,
        merged_payload,
        idempotency_key=idempotency_key,
    )
    retry_delays = [0.5, 1.5, 3]
    for attempt, delay in enumerate(retry_delays, start=1):
        try:
            rq_job_id = enqueue_job(job.id)
            job.rq_job_id = rq_job_id
            await session.commit()
            logger.info(
                "task_create_enqueued",
                request_id=request_id,
                task_id=job.id,
                job_id=rq_job_id,
                attempt=attempt,
            )
            return job
        except Exception as exc:
            logger.exception(
                "task_enqueue_failed",
                request_id=request_id,
                task_id=job.id,
                attempt=attempt,
                error=str(exc),
            )
            if attempt == len(retry_delays):
                raise TaskCreateError("queue unavailable") from exc
            await asyncio.sleep(delay)
    raise TaskCreateError("queue unavailable")
