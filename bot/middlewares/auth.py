"""
Staff whitelist middleware.
Only Telegram users in TELEGRAM_ALLOWED_USERS can interact with the bot.
If the list is empty, all users are allowed (useful for initial setup).
"""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from config import get_bot_settings

settings = get_bot_settings()


class StaffAuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        allowed = settings.allowed_user_ids

        # If no whitelist configured, allow everyone (development mode)
        if not allowed:
            return await handler(event, data)

        user_id: int | None = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id and user_id not in allowed:
            if isinstance(event, Message):
                await event.answer("⛔ Доступ запрещён. У вас нет прав для использования этого бота.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещён.", show_alert=True)
            return

        return await handler(event, data)
