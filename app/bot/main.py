import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from structlog import get_logger

from app.bot.handlers import router
from app.config import settings
from app.db import verify_database_connection

logger = get_logger()


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=RedisStorage.from_url(settings.redis_url))
    dp.include_router(router)
    return dp


async def main() -> None:
    await verify_database_connection()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()
    while True:
        try:
            await dp.start_polling(bot)
        except Exception:
            logger.exception("polling_failed")
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
