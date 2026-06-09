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
                "🔔 <b>Already subscribed</b>\n\n"
                "You will receive:\n"
                "  • 📅 Deadline reminders (30/14/7/1 days before)\n"
                "  • 📊 Daily digest at 09:00 (Almaty time)\n\n"
                "Use /unsubscribe to opt out.",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "✅ <b>Subscribed successfully!</b>\n\n"
                "You will now receive:\n"
                "  • 📅 Deadline reminders (30/14/7/1 days before)\n"
                "  • 📊 Daily digest at 09:00 (Almaty time)\n\n"
                "Use /unsubscribe to opt out.",
                parse_mode="HTML",
            )
    except Exception as e:
        await message.answer(f"❌ Subscription error: {e}")


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    """/unsubscribe — opt out of all notifications."""
    user_id = message.from_user.id

    try:
        result = await api_client.unsubscribe(user_id)
        if result.get("status") == "removed":
            await message.answer(
                "🔕 <b>Unsubscribed</b>\n\n"
                "You will no longer receive reminders or digests.\n"
                "Use /subscribe to opt back in.",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "You were not subscribed. Use /subscribe to sign up.",
                parse_mode="HTML",
            )
    except Exception as e:
        await message.answer(f"❌ Error: {e}")


@router.message(Command("notifications"))
async def cmd_status(message: Message):
    """/notifications — check subscription status."""
    user_id = message.from_user.id

    try:
        result = await api_client.subscription_status(user_id)
        if result.get("subscribed"):
            since = result.get("since", "")[:10]
            await message.answer(
                f"🔔 <b>Subscribed</b> since {since}\n\n"
                "You receive deadline reminders and daily digest.\n"
                "Use /unsubscribe to opt out.",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "🔕 <b>Not subscribed</b>\n\n"
                "Use /subscribe to receive deadline reminders and daily digest.",
                parse_mode="HTML",
            )
    except Exception as e:
        await message.answer(f"❌ Error checking status: {e}")
