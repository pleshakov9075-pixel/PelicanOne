from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.crud import charge_balance, create_job_if_not_exists
from app.db import get_session
from app.models import JobStatus, Section, User
from app.services.payments import PaymentsClient
from app.worker.queue import enqueue_job

logger = get_logger()
app = FastAPI(title="PelicanOneBot API")


class TaskCreateRequest(BaseModel):
    section: Section
    payload: dict = Field(default_factory=dict)
    options: dict = Field(default_factory=dict)
    user_id: int | None = None
    telegram_id: int | None = None
    price_rub: int = 0

    @model_validator(mode="after")
    def validate_user(self) -> "TaskCreateRequest":
        if self.user_id is None and self.telegram_id is None:
            raise ValueError("user_id or telegram_id is required")
        return self


class TaskCreateResponse(BaseModel):
    task_id: int
    job_id: str
    status: JobStatus


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/payments/webhook")
async def payments_webhook(payload: dict) -> dict:
    logger.info("payment_webhook", payload=payload)
    return {"status": "accepted"}


@app.post("/payments/create")
async def create_payment(payload: dict) -> dict:
    amount = int(payload.get("amount", 0))
    client = PaymentsClient()
    link = await client.create_payment(amount, "Пополнение баланса", payload.get("return_url", ""))
    return {"payment_id": link.payment_id, "url": link.url}


@app.post("/tasks", response_model=TaskCreateResponse)
async def create_task(
    payload: TaskCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> TaskCreateResponse:
    logger.info(
        "task_create_request",
        section=payload.section.value,
        user_id=payload.user_id,
        telegram_id=payload.telegram_id,
    )
    user: User | None = None
    if payload.user_id is not None:
        user = await session.get(User, payload.user_id)
    if user is None and payload.telegram_id is not None:
        result = await session.execute(select(User).where(User.telegram_id == payload.telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(telegram_id=payload.telegram_id)
            session.add(user)
            await session.commit()
            await session.refresh(user)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if payload.price_rub < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid price")
    if payload.price_rub and user.balance_rub < payload.price_rub:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient balance")
    if payload.price_rub:
        await charge_balance(session, user, payload.price_rub, "job_start")
    merged_payload = {**payload.payload, **payload.options}
    job = await create_job_if_not_exists(
        session,
        user.id,
        None,
        payload.section,
        payload.price_rub,
        merged_payload,
    )
    rq_job_id = enqueue_job(job.id)
    job.rq_job_id = rq_job_id
    await session.commit()
    logger.info(
        "task_created",
        task_id=job.id,
        job_id=rq_job_id,
        status=job.status.value,
        user_id=user.id,
    )
    return TaskCreateResponse(task_id=job.id, job_id=rq_job_id, status=job.status)
