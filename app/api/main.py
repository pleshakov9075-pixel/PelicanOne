from fastapi import FastAPI
from structlog import get_logger

from app.services.payments import PaymentsClient

logger = get_logger()
app = FastAPI(title="PelicanOneBot API")


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
