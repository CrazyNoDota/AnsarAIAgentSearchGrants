"""
Telegram bot entry point.
Uses aiogram 3.x with long-polling.
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import get_bot_settings
from middlewares.auth import StaffAuthMiddleware
from handlers import start, grants, reviews, search, subscribe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main():
    settings = get_bot_settings()

    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Please configure .env")
        sys.exit(1)

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Register staff whitelist middleware on all updates
    dp.message.middleware(StaffAuthMiddleware())
    dp.callback_query.middleware(StaffAuthMiddleware())

    # Register routers
    dp.include_router(start.router)
    dp.include_router(grants.router)
    dp.include_router(reviews.router)
    dp.include_router(search.router)
    dp.include_router(subscribe.router)

    # Set bot commands for the menu
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start", description="Приветствие и статистика"),
        BotCommand(command="pending", description="Гранты на рассмотрении"),
        BotCommand(command="approved", description="Одобренные гранты"),
        BotCommand(command="rejected", description="Отклонённые гранты"),
        BotCommand(command="search", description="Поиск грантов"),
        BotCommand(command="recommend", description="AI-рекомендации"),
        BotCommand(command="summarize", description="AI-резюме гранта"),
        BotCommand(command="delete", description="Удалить грант по ID"),
        BotCommand(command="subscribe", description="Подписаться на дайджест"),
        BotCommand(command="unsubscribe", description="Отписаться от дайджеста"),
        BotCommand(command="notifications", description="Статус подписки"),
        BotCommand(command="help", description="Помощь"),
    ])

    logger.info("🤖 AI Grant Agent bot starting...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
