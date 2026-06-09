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
        await message.answer(f"❌ Failed to load stats: {e}")
        return

    total = stats.get("total", 0)
    approved = stats.get("approved", 0)
    pending = stats.get("pending", 0)
    rejected = stats.get("rejected", 0)

    # Calculate approval rate
    reviewed = approved + rejected
    approval_rate = round(approved / reviewed * 100) if reviewed > 0 else 0

    await message.answer(
        "📊 <b>System Statistics</b>\n\n"
        f"📦 <b>Total Grants:</b> {total}\n\n"
        f"📥 Pending Review: <b>{pending}</b>\n"
        f"✅ Approved: <b>{approved}</b>\n"
        f"❌ Rejected: <b>{rejected}</b>\n\n"
        f"📈 <b>Approval Rate:</b> {approval_rate}% ({reviewed} reviewed)\n\n"
        f"<i>Use /insights to see AI learning preferences.</i>",
        parse_mode="HTML",
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """/stats — show database statistics."""
    await send_stats(message)
