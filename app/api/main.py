from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.services.task_service import TaskCreateError, create_task
from app.db import get_session
from app.models import JobStatus, Section
from app.services.payments import PaymentsClient

logger = get_logger()
app = FastAPI(title="PelicanOneBot API")


class TaskCreateRequest(BaseModel):
    section: Section
    payload: dict = Field(default_factory=dict)
    options: dict = Field(default_factory=dict)
    user_id: int | None = None
    telegram_id: int | None = None
    price_rub: int = 0
    idempotency_key: str | None = None

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
async def create_task_endpoint(
    payload: TaskCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> TaskCreateResponse:
    logger.info(
        "task_create_request",
        section=payload.section.value,
        user_id=payload.user_id,
        telegram_id=payload.telegram_id,
    )
    try:
        job = await create_task(
            session,
            section=payload.section,
            payload=payload.payload,
            options=payload.options,
            user_id=payload.user_id,
            telegram_id=payload.telegram_id,
            price_rub=payload.price_rub,
            idempotency_key=payload.idempotency_key,
        )
    except TaskCreateError as exc:
        detail = str(exc)
        if detail in {"user not found"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        if detail in {"invalid price", "insufficient balance"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc
    logger.info(
        "task_created",
        task_id=job.id,
        job_id=job.rq_job_id,
        status=job.status.value,
        user_id=job.user_id,
    )
    return TaskCreateResponse(task_id=job.id, job_id=job.rq_job_id or "", status=job.status)
