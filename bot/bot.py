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
from handlers import start, grants, reviews, search, subscribe, deadlines, statistics, settings, categories, chat

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
    # chat fallback MUST be last — it catches any plain-text message
    dp.include_router(chat.router)

    # Set bot command list (shows in Telegram's "/" menu)
    await bot.set_my_commands([
        BotCommand(command="start", description="Main menu"),
        BotCommand(command="menu", description="Show main menu"),
        BotCommand(command="pending", description="New grants for review"),
        BotCommand(command="approved", description="Approved grants"),
        BotCommand(command="rejected", description="Rejected grants"),
        BotCommand(command="deadlines", description="Upcoming deadlines (30 days)"),
        BotCommand(command="search", description="Keyword + semantic search"),
        BotCommand(command="recommend", description="AI RAG recommendations"),
        BotCommand(command="summarize", description="AI summary of a grant"),
        BotCommand(command="stats", description="Database statistics"),
        BotCommand(command="insights", description="AI learning insights"),
        BotCommand(command="scrape", description="Trigger manual scrape"),
        BotCommand(command="subscribe", description="Subscribe to daily digest"),
        BotCommand(command="unsubscribe", description="Unsubscribe from digest"),
        BotCommand(command="delete", description="Delete a grant by ID"),
        BotCommand(command="help", description="Help and command list"),
    ])

    logger.info("AI Grant Agent bot starting (VPS long-polling mode)...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
