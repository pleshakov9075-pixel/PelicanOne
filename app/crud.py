from collections.abc import Sequence
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Draft, Job, JobStatus, LedgerEntry, Price, Section, User


async def get_or_create_user(session: AsyncSession, telegram_id: int, username: str | None, full_name: str | None) -> User:
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


async def get_or_create_draft(session: AsyncSession, user_id: int, section: Section) -> Draft:
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


async def update_draft_payload(session: AsyncSession, draft: Draft, payload: dict) -> Draft:
    draft.payload = payload
    await session.commit()
    await session.refresh(draft)
    return draft


async def clear_draft(session: AsyncSession, draft: Draft) -> None:
    await session.delete(draft)
    await session.commit()


async def create_job_if_not_exists(
    session: AsyncSession,
    user_id: int,
    draft: Draft | None,
    section: Section,
    price_rub: int,
    payload: dict,
) -> Job:
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


async def update_job_status(session: AsyncSession, job_id: int, status: JobStatus, result_payload: dict | None = None, error_message: str | None = None) -> None:
    stmt = (
        update(Job)
        .where(Job.id == job_id)
        .values(status=status, result=result_payload, error_message=error_message)
    )
    await session.execute(stmt)
    await session.commit()


async def list_recent_jobs(session: AsyncSession, user_id: int, limit: int = 10) -> Sequence[Job]:
    result = await session.execute(
        select(Job).where(Job.user_id == user_id).order_by(Job.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


async def get_price(session: AsyncSession, code: str) -> Price | None:
    result = await session.execute(select(Price).where(Price.code == code, Price.is_active.is_(True)))
    return result.scalar_one_or_none()


async def list_prices(session: AsyncSession) -> Sequence[Price]:
    result = await session.execute(select(Price).order_by(Price.code.asc()))
    return result.scalars().all()


async def set_price(session: AsyncSession, code: str, price_rub: float) -> bool:
    result = await session.execute(select(Price).where(Price.code == code))
    price = result.scalar_one_or_none()
    if not price:
        return False
    price.price_rub = price_rub
    await session.commit()
    return True


async def add_balance(session: AsyncSession, user: User, amount: int, reason: str) -> None:
    user.balance_rub += amount
    session.add(LedgerEntry(user_id=user.id, amount_rub=amount, reason=reason))
    await session.commit()


async def charge_balance(session: AsyncSession, user: User, amount: int, reason: str) -> None:
    user.balance_rub -= amount
    session.add(LedgerEntry(user_id=user.id, amount_rub=-amount, reason=reason))
    await session.commit()
