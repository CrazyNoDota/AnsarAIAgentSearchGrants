"""
Deadline handler — shows upcoming grant deadlines with urgency indicators.
"""
from datetime import date
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import api_client

router = Router()

URGENCY_EMOJI = {
    "critical": "🔴",
    "high": "🟡",
    "medium": "🔵",
    "normal": "🟢",
}


async def send_deadlines(message: Message, days: int = 30):
    """Fetch and display upcoming deadlines."""
    try:
        data = await api_client.get_deadlines(days=days)
        items = data.get("items", [])
    except Exception as e:
        await message.answer(f"❌ Не удалось загрузить дедлайны: {e}")
        return

    if not items:
        await message.answer(
            f"📅 <b>Ближайших дедлайнов нет</b>\n\n"
            f"Нет одобренных грантов с дедлайном в ближайшие {days} дн.",
            parse_mode="HTML",
        )
        return

    lines = [f"⏰ <b>Ближайшие дедлайны ({days} дн.)</b>\n"]
    for item in items:
        emoji = URGENCY_EMOJI.get(item.get("urgency", "normal"), "📅")
        days_left = item.get("days_left", 0)
        title = item.get("title", "Без названия")[:60]
        deadline = item.get("deadline", "?")
        gid = item.get("id")

        lines.append(
            f"{emoji} <b>{title}</b>\n"
            f"   📅 {deadline} — осталось {days_left} дн.\n"
            f"   🆔 ID: <code>{gid}</code>\n"
        )

    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("deadlines"))
async def cmd_deadlines(message: Message):
    """/deadlines — show upcoming grant deadlines."""
    await send_deadlines(message, days=30)


@router.message(Command("deadlines7"))
async def cmd_deadlines_7(message: Message):
    """/deadlines7 — urgent: deadlines in next 7 days."""
    await send_deadlines(message, days=7)
