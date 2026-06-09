"""
AI Insights handler — shows what the AI has learned from review decisions.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import api_client

router = Router()


async def send_insights(message: Message):
    """Display learned AI preferences from Aydar's review history."""
    try:
        prefs = await api_client.get_preferences()
    except Exception as e:
        await message.answer(f"❌ Failed to load AI insights: {e}")
        return

    lines = ["🧠 <b>AI Learning Insights</b>\n", "<i>Based on your approval/rejection history:</i>\n"]

    categories = prefs.get("categories", [])[:5]
    if categories:
        lines.append("📁 <b>Top Categories (approved):</b>")
        for p in categories:
            bar = "▓" * min(10, int(p["weight"]))
            lines.append(f"  {bar} {p['value'].title()} (×{p['approved']} approved)")
        lines.append("")

    countries = prefs.get("countries", [])[:5]
    if countries:
        lines.append("🌍 <b>Top Countries:</b>")
        for p in countries:
            lines.append(f"  🔹 {p['value'].title()} — weight: {p['weight']}")
        lines.append("")

    keywords = prefs.get("keywords", [])[:8]
    if keywords:
        lines.append("🔑 <b>Key Topics (learned):</b>")
        kw_str = " · ".join(p["value"] for p in keywords)
        lines.append(f"  {kw_str}")
        lines.append("")

    if not categories and not countries and not keywords:
        lines.append("No learning data yet. Start approving/rejecting grants to train the AI!")

    lines.append("<i>💡 The more you review, the smarter recommendations become.</i>")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("insights"))
async def cmd_insights(message: Message):
    """/insights — show AI learning preferences."""
    await send_insights(message)


@router.message(Command("scrape"))
async def cmd_scrape(message: Message):
    """/scrape — manually trigger scraper."""
    await message.answer("🔄 Starting manual scrape...\n<i>This may take 1-3 minutes.</i>", parse_mode="HTML")
    try:
        result = await api_client.run_scraper()
        new = result.get("new", 0)
        total = result.get("total", 0)
        errors = result.get("errors", 0)
        ai_agent = result.get("ai_agent", {})
        ai_new = ai_agent.get("new", 0)

        await message.answer(
            f"✅ <b>Scrape Complete</b>\n\n"
            f"📦 Found: <b>{total}</b> total\n"
            f"🆕 New: <b>{new}</b> added to review queue\n"
            f"🤖 AI Agent found: <b>{ai_new}</b> new\n"
            f"⚠️ Errors: {errors}",
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"❌ Scrape failed: {e}")
