from __future__ import annotations

import httpx

from app.config import settings


class TasksAPIClient:
    def __init__(self) -> None:
        self.base_url = settings.api_public_base_url.rstrip("/")

    async def create_task(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self.base_url}/tasks", json=payload)
            response.raise_for_status()
            return response.json()
