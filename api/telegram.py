"""
Vercel function: Telegram bot webhook receiver.
Verifies the secret header, parses the Update, and feeds it to aiogram.
"""
import sys
import os
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import FastAPI, Header, HTTPException, Request
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Update

from config import get_bot_settings
from middlewares.auth import StaffAuthMiddleware
from handlers import start, grants, reviews, search, subscribe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_bot_settings()

bot = Bot(
    token=settings.telegram_bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
dp.message.middleware(StaffAuthMiddleware())
dp.callback_query.middleware(StaffAuthMiddleware())
dp.include_router(start.router)
dp.include_router(grants.router)
dp.include_router(reviews.router)
dp.include_router(search.router)
dp.include_router(subscribe.router)

app = FastAPI()

WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")


@app.post("/api/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if WEBHOOK_SECRET and x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="bad secret token")
    payload = await request.json()
    update = Update.model_validate(payload, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.get("/api/telegram")
async def telegram_health():
    return {"status": "telegram webhook ready"}
