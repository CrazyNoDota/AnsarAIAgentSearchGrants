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
        await message.answer(f"❌ Не удалось загрузить выводы ИИ: {e}")
        return

    lines = ["🧠 <b>Чему научился ИИ</b>\n", "<i>На основе ваших одобрений и отклонений:</i>\n"]

    categories = prefs.get("categories", [])[:5]
    if categories:
        lines.append("📁 <b>Топ категорий (одобрено):</b>")
        for p in categories:
            bar = "▓" * min(10, int(p["weight"]))
            lines.append(f"  {bar} {p['value'].title()} (одобрено ×{p['approved']})")
        lines.append("")

    countries = prefs.get("countries", [])[:5]
    if countries:
        lines.append("🌍 <b>Топ стран:</b>")
        for p in countries:
            lines.append(f"  🔹 {p['value'].title()} — вес: {p['weight']}")
        lines.append("")

    keywords = prefs.get("keywords", [])[:8]
    if keywords:
        lines.append("🔑 <b>Ключевые темы (выявлены):</b>")
        kw_str = " · ".join(p["value"] for p in keywords)
        lines.append(f"  {kw_str}")
        lines.append("")

    if not categories and not countries and not keywords:
        lines.append("Пока нет данных для обучения. Начните одобрять/отклонять гранты, чтобы обучить ИИ!")

    lines.append("<i>💡 Чем больше вы проверяете, тем точнее становятся рекомендации.</i>")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("insights"))
async def cmd_insights(message: Message):
    """/insights — show AI learning preferences."""
    await send_insights(message)


@router.message(Command("scrape"))
async def cmd_scrape(message: Message):
    """/scrape — manually trigger scraper."""
    await message.answer("🔄 Запускаю ручной сбор...\n<i>Это может занять 1–3 минуты.</i>", parse_mode="HTML")
    try:
        result = await api_client.run_scraper()
        new = result.get("new", 0)
        total = result.get("total", 0)
        errors = result.get("errors", 0)
        ai_agent = result.get("ai_agent", {})
        ai_new = ai_agent.get("new", 0)

        await message.answer(
            f"✅ <b>Сбор завершён</b>\n\n"
            f"📦 Найдено всего: <b>{total}</b>\n"
            f"🆕 Новых: <b>{new}</b> добавлено в очередь проверки\n"
            f"🤖 ИИ-агент нашёл: <b>{ai_new}</b> новых\n"
            f"⚠️ Ошибок: {errors}",
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"❌ Сбор не удался: {e}")
