"""
Subscription handler — opt-in/out for deadline reminders and daily digest.
Uses HTTP API calls to backend (not direct DB — bot runs in separate container).
"""
import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import api_client

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    """/subscribe — opt in for deadline reminders and daily digest."""
    user_id = message.from_user.id
    chat_id = message.chat.id

    try:
        result = await api_client.subscribe(user_id, chat_id)
        status = result.get("status", "")
        if status == "updated":
            await message.answer(
                "🔔 <b>Вы уже подписаны</b>\n\n"
                "Вы будете получать:\n"
                "  • 📅 Напоминания о дедлайнах (за 30/14/7/1 дн.)\n"
                "  • 📊 Ежедневную сводку в 09:00 (время Алматы)\n\n"
                "Чтобы отписаться — /unsubscribe.",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "✅ <b>Подписка оформлена!</b>\n\n"
                "Теперь вы будете получать:\n"
                "  • 📅 Напоминания о дедлайнах (за 30/14/7/1 дн.)\n"
                "  • 📊 Ежедневную сводку в 09:00 (время Алматы)\n\n"
                "Чтобы отписаться — /unsubscribe.",
                parse_mode="HTML",
            )
    except Exception as e:
        await message.answer(f"❌ Ошибка подписки: {e}")


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    """/unsubscribe — opt out of all notifications."""
    user_id = message.from_user.id

    try:
        result = await api_client.unsubscribe(user_id)
        if result.get("status") == "removed":
            await message.answer(
                "🔕 <b>Вы отписались</b>\n\n"
                "Напоминания и сводки больше приходить не будут.\n"
                "Чтобы подписаться снова — /subscribe.",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "Вы не были подписаны. Чтобы подписаться — /subscribe.",
                parse_mode="HTML",
            )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("notifications"))
async def cmd_status(message: Message):
    """/notifications — check subscription status."""
    user_id = message.from_user.id

    try:
        result = await api_client.subscription_status(user_id)
        if result.get("subscribed"):
            since = result.get("since", "")[:10]
            await message.answer(
                f"🔔 <b>Подписка активна</b> с {since}\n\n"
                "Вы получаете напоминания о дедлайнах и ежедневную сводку.\n"
                "Чтобы отписаться — /unsubscribe.",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "🔕 <b>Подписка не оформлена</b>\n\n"
                "Команда /subscribe включит напоминания о дедлайнах и ежедневную сводку.",
                parse_mode="HTML",
            )
    except Exception as e:
        await message.answer(f"❌ Не удалось проверить статус: {e}")
