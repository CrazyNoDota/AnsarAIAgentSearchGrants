"""
Per-user opt-in for the daily pending-grants digest.
Writes directly to the shared DB (bot + API run in the same Vercel project).
"""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import delete, select

# These imports work because api/telegram.py prepends backend/ to sys.path
from database.connection import AsyncSessionLocal
from models.notification_subscription import NotificationSubscription

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(
            select(NotificationSubscription).where(
                NotificationSubscription.telegram_user_id == user_id
            )
        )
        if existing:
            existing.telegram_chat_id = chat_id
            await db.commit()
            await message.answer(
                "✅ Вы уже подписаны.\n\n"
                "Ежедневный дайджест новых грантов приходит в 09:00 UTC.\n"
                "Используйте /unsubscribe, чтобы отписаться."
            )
            return

        db.add(NotificationSubscription(
            telegram_user_id=user_id,
            telegram_chat_id=chat_id,
        ))
        await db.commit()

    await message.answer(
        "🔔 Подписка оформлена.\n\n"
        "Со следующего дня вы будете получать ежедневный дайджест "
        "новых грантов на рассмотрении в <b>09:00 UTC</b>.\n"
        "Используйте /unsubscribe, чтобы отписаться."
    )


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(NotificationSubscription).where(
                NotificationSubscription.telegram_user_id == user_id
            )
        )
        await db.commit()

    if result.rowcount:
        await message.answer(
            "🔕 Подписка отменена. Вы больше не будете получать ежедневный дайджест."
        )
    else:
        await message.answer(
            "Вы не были подписаны. Используйте /subscribe, чтобы оформить подписку."
        )


@router.message(Command("notifications"))
async def cmd_status(message: Message):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as db:
        sub = await db.scalar(
            select(NotificationSubscription).where(
                NotificationSubscription.telegram_user_id == user_id
            )
        )
    if sub:
        await message.answer(
            f"🔔 Вы <b>подписаны</b> с {sub.created_at:%Y-%m-%d}.\n"
            "Ежедневный дайджест в 09:00 UTC. Используйте /unsubscribe, чтобы отписаться."
        )
    else:
        await message.answer(
            "🔕 Вы <b>не подписаны</b>. Используйте /subscribe, чтобы оформить подписку."
        )
