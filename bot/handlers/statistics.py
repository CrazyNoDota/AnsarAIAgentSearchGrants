"""
Statistics handler — shows database and system statistics.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import api_client

router = Router()


async def send_stats(message: Message):
    """Fetch and display system statistics."""
    try:
        stats = await api_client.get_stats()
    except Exception as e:
        await message.answer(f"❌ Не удалось загрузить статистику: {e}")
        return

    total = stats.get("total", 0)
    approved = stats.get("approved", 0)
    pending = stats.get("pending", 0)
    rejected = stats.get("rejected", 0)

    # Calculate approval rate
    reviewed = approved + rejected
    approval_rate = round(approved / reviewed * 100) if reviewed > 0 else 0

    await message.answer(
        "📊 <b>Статистика системы</b>\n\n"
        f"📦 <b>Всего грантов:</b> {total}\n\n"
        f"📥 На рассмотрении: <b>{pending}</b>\n"
        f"✅ Одобрено: <b>{approved}</b>\n"
        f"❌ Отклонено: <b>{rejected}</b>\n\n"
        f"📈 <b>Доля одобрений:</b> {approval_rate}% (проверено {reviewed})\n\n"
        f"<i>Команда /insights покажет, что ИИ понял о ваших предпочтениях.</i>",
        parse_mode="HTML",
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """/stats — show database statistics."""
    await send_stats(message)
