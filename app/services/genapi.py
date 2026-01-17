from __future__ import annotations

import httpx
from structlog import get_logger

from app.config import settings

logger = get_logger()


class GenAPIClient:
    def __init__(self) -> None:
        self.base_url = settings.genapi_base_url
        self.token = settings.genapi_token

    async def submit_job(self, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self.base_url}/jobs", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

    async def fetch_result(self, job_id: str) -> dict:
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(f"{self.base_url}/jobs/{job_id}", headers=headers)
            response.raise_for_status()
            return response.json()
