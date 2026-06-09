from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from config import get_settings


class AllowlistMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        allowed = get_settings().allowed_user_ids
        if not allowed:
            return  # no allowlist = nobody allowed

        user = data.get("event_from_user")
        if user is None:
            if isinstance(event, Update):
                msg = event.message or event.callback_query
                if msg:
                    user = getattr(msg, "from_user", None)

        if user is None or user.id not in allowed:
            return

        return await handler(event, data)
