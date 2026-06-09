"""
AI Grant Agent — Telegram Bot Entry Point
Long-polling mode (VPS deployment, no webhook needed)
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from config import get_bot_settings
from middlewares.auth import StaffAuthMiddleware
from handlers import start, grants, reviews, search, subscribe, deadlines, statistics, settings, categories, sources, chat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main():
    bot_settings = get_bot_settings()

    if not bot_settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)

    bot = Bot(
        token=bot_settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Whitelist middleware — only allowed user IDs can interact
    dp.message.middleware(StaffAuthMiddleware())
    dp.callback_query.middleware(StaffAuthMiddleware())

    # Register all routers
    dp.include_router(start.router)
    dp.include_router(grants.router)
    dp.include_router(reviews.router)
    dp.include_router(search.router)
    dp.include_router(subscribe.router)
    dp.include_router(deadlines.router)
    dp.include_router(statistics.router)
    dp.include_router(settings.router)
    dp.include_router(categories.router)
    dp.include_router(sources.router)
    # chat fallback MUST be last — it catches any plain-text message
    dp.include_router(chat.router)

    # Set bot command list (shows in Telegram's "/" menu)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="menu", description="Показать главное меню"),
        BotCommand(command="pending", description="Новые гранты на проверку"),
        BotCommand(command="approved", description="Одобренные гранты"),
        BotCommand(command="rejected", description="Отклонённые гранты"),
        BotCommand(command="deadlines", description="Ближайшие дедлайны (30 дней)"),
        BotCommand(command="search", description="Поиск по словам + смыслу"),
        BotCommand(command="recommend", description="Рекомендации ИИ (RAG)"),
        BotCommand(command="summarize", description="Краткое изложение гранта"),
        BotCommand(command="stats", description="Статистика базы"),
        BotCommand(command="insights", description="Чему научился ИИ"),
        BotCommand(command="scrape", description="Запустить сбор вручную"),
        BotCommand(command="sources", description="Список своих источников"),
        BotCommand(command="addsource", description="Добавить источник (URL)"),
        BotCommand(command="scrapesource", description="Просканировать источник"),
        BotCommand(command="delsource", description="Удалить источник"),
        BotCommand(command="subscribe", description="Подписаться на сводку"),
        BotCommand(command="unsubscribe", description="Отписаться от сводки"),
        BotCommand(command="delete", description="Удалить грант по ID"),
        BotCommand(command="guide", description="Как работает бот"),
        BotCommand(command="help", description="Помощь и список команд"),
    ])

    logger.info("AI Grant Agent bot starting (VPS long-polling mode)...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
