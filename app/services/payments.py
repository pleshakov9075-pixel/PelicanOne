from __future__ import annotations

from dataclasses import dataclass
from structlog import get_logger

from app.config import settings

logger = get_logger()


@dataclass
class PaymentLink:
    url: str
    payment_id: str


class PaymentsClient:
    def __init__(self) -> None:
        self.shop_id = settings.yookassa_shop_id
        self.secret_key = settings.yookassa_secret_key

    async def create_payment(self, amount_rub: int, description: str, return_url: str) -> PaymentLink:
        logger.info("create_payment_stub", amount_rub=amount_rub, description=description)
        return PaymentLink(url=return_url, payment_id=f"stub-{amount_rub}")
