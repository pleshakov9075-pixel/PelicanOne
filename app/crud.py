from collections.abc import Sequence
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from structlog import get_logger

from app.models import Draft, Job, JobStatus, LedgerEntry, Price, Section, User

logger = get_logger()


def _log_db_error(action: str, **context: object) -> None:
    logger.exception("db_error", action=action, **context)


async def get_or_create_user(session: AsyncSession, telegram_id: int, username: str | None, full_name: str | None) -> User:
    try:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user:
            if user.username != username or user.full_name != full_name:
                user.username = username
                user.full_name = full_name
                await session.commit()
            return user
        user = User(telegram_id=telegram_id, username=username, full_name=full_name)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
    except SQLAlchemyError:
        _log_db_error("get_or_create_user", telegram_id=telegram_id)
        raise


async def get_or_create_draft(session: AsyncSession, user_id: int, section: Section) -> Draft:
    try:
        result = await session.execute(
            select(Draft).where(Draft.user_id == user_id, Draft.section == section)
        )
        draft = result.scalar_one_or_none()
        if draft:
            return draft
        draft = Draft(user_id=user_id, section=section, payload={})
        session.add(draft)
        await session.commit()
        await session.refresh(draft)
        return draft
    except SQLAlchemyError:
        _log_db_error("get_or_create_draft", user_id=user_id, section=section.value)
        raise


async def update_draft_payload(session: AsyncSession, draft: Draft, payload: dict) -> Draft:
    try:
        draft.payload = payload
        await session.commit()
        await session.refresh(draft)
        return draft
    except SQLAlchemyError:
        _log_db_error("update_draft_payload", draft_id=draft.id, user_id=draft.user_id, section=draft.section.value)
        raise


async def clear_draft(session: AsyncSession, draft: Draft) -> None:
    try:
        await session.delete(draft)
        await session.commit()
    except SQLAlchemyError:
        _log_db_error("clear_draft", draft_id=draft.id, user_id=draft.user_id, section=draft.section.value)
        raise


async def create_job_if_not_exists(
    session: AsyncSession,
    user_id: int,
    draft: Draft | None,
    section: Section,
    price_rub: int,
    payload: dict,
) -> Job:
    try:
        if draft:
            result = await session.execute(select(Job).where(Job.draft_id == draft.id))
            job = result.scalar_one_or_none()
            if job:
                return job
        job = Job(user_id=user_id, draft_id=draft.id if draft else None, section=section, price_rub=price_rub, payload=payload)
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job
    except SQLAlchemyError:
        _log_db_error("create_job_if_not_exists", user_id=user_id, section=section.value)
        raise


async def update_job_status(session: AsyncSession, job_id: int, status: JobStatus, result_payload: dict | None = None, error_message: str | None = None) -> None:
    try:
        stmt = (
            update(Job)
            .where(Job.id == job_id)
            .values(status=status, result=result_payload, error_message=error_message)
        )
        await session.execute(stmt)
        await session.commit()
    except SQLAlchemyError:
        _log_db_error("update_job_status", job_id=job_id, status=status.value)
        raise


async def list_recent_jobs(session: AsyncSession, user_id: int, limit: int = 10) -> Sequence[Job]:
    try:
        result = await session.execute(
            select(Job).where(Job.user_id == user_id).order_by(Job.created_at.desc()).limit(limit)
        )
        return result.scalars().all()
    except SQLAlchemyError:
        _log_db_error("list_recent_jobs", user_id=user_id)
        raise


async def get_price(session: AsyncSession, code: str) -> Price | None:
    try:
        result = await session.execute(select(Price).where(Price.code == code, Price.is_active.is_(True)))
        return result.scalar_one_or_none()
    except SQLAlchemyError:
        _log_db_error("get_price", code=code)
        raise


async def list_prices(session: AsyncSession) -> Sequence[Price]:
    try:
        result = await session.execute(select(Price).order_by(Price.code.asc()))
        return result.scalars().all()
    except SQLAlchemyError:
        _log_db_error("list_prices")
        raise


async def set_price(session: AsyncSession, code: str, price_rub: float) -> bool:
    try:
        result = await session.execute(select(Price).where(Price.code == code))
        price = result.scalar_one_or_none()
        if not price:
            return False
        price.price_rub = price_rub
        await session.commit()
        return True
    except SQLAlchemyError:
        _log_db_error("set_price", code=code)
        raise


async def add_balance(session: AsyncSession, user: User, amount: int, reason: str) -> None:
    try:
        user.balance_rub += amount
        session.add(LedgerEntry(user_id=user.id, amount_rub=amount, reason=reason))
        await session.commit()
    except SQLAlchemyError:
        _log_db_error("add_balance", user_id=user.id, amount=amount, reason=reason)
        raise


async def charge_balance(session: AsyncSession, user: User, amount: int, reason: str) -> None:
    try:
        user.balance_rub -= amount
        session.add(LedgerEntry(user_id=user.id, amount_rub=-amount, reason=reason))
        await session.commit()
    except SQLAlchemyError:
        _log_db_error("charge_balance", user_id=user.id, amount=amount, reason=reason)
        raise
