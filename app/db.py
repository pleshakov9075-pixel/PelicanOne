from collections.abc import AsyncGenerator
import os
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from structlog import get_logger

from app.config import settings

logger = get_logger()


def _detect_db_source() -> str:
    if os.getenv("DATABASE_URL"):
        return "env"
    if Path(".env").exists():
        return "dotenv"
    return "default"


def _log_database_config() -> None:
    url = make_url(settings.database_url)
    logger.info(
        "db_config",
        source=_detect_db_source(),
        user=url.username,
        host=url.host,
        port=url.port,
        database=url.database,
        masked_url=url.render_as_string(hide_password=True),
        env_present=bool(os.getenv("DATABASE_URL")),
        env_file_present=Path(".env").exists(),
    )


async def verify_database_connection() -> None:
    url = make_url(settings.database_url)
    asyncpg_url = url.set(drivername="postgresql")
    masked_url = asyncpg_url.render_as_string(hide_password=True)
    logger.info(
        "db_connect_check_start",
        user=asyncpg_url.username,
        host=asyncpg_url.host,
        port=asyncpg_url.port,
        database=asyncpg_url.database,
        masked_url=masked_url,
    )
    try:
        connection = await asyncpg.connect(asyncpg_url.render_as_string(hide_password=False))
        try:
            result = await connection.fetchval("SELECT 1")
        finally:
            await connection.close()
        logger.info("db_connect_check_ok", result=result)
    except Exception as exc:
        logger.exception(
            "db_connect_check_failed",
            user=asyncpg_url.username,
            host=asyncpg_url.host,
            port=asyncpg_url.port,
            database=asyncpg_url.database,
            masked_url=masked_url,
            error=str(exc),
        )
        raise RuntimeError("Database connection failed. Check DATABASE_URL.") from exc


_log_database_config()
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True, pool_recycle=1800)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
