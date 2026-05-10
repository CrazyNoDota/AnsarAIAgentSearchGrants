from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

import api_client

router = Router()


HELP_TEXT = (
    "🤖 <b>AI Grant Agent — Помощь</b>\n\n"
    "<b>Команды:</b>\n"
    "  /start — Приветствие и статистика\n"
    "  /pending — Гранты на рассмотрении (с кнопками Одобрить/Отклонить)\n"
    "  /approved — Одобренные гранты\n"
    "  /rejected — Отклонённые гранты\n"
    "  /search &lt;запрос&gt; — Поиск по ключевым словам\n"
    "  /recommend &lt;запрос&gt; — AI-рекомендации\n"
    "  /summarize &lt;id&gt; — AI-резюме гранта\n"
    "  /delete &lt;id&gt; — Удалить грант навсегда\n"
    "  /subscribe — Подписаться на ежедневный дайджест\n"
    "  /unsubscribe — Отписаться от дайджеста\n"
    "  /notifications — Статус подписки\n\n"
    "<b>Рассмотрение грантов:</b>\n"
    "Используйте кнопки ✅ <b>Одобрить</b> или ❌ <b>Отклонить</b> под каждым грантом. "
    "Решения сохраняются мгновенно и синхронизируются с веб-панелью.\n\n"
    "<b>Обучение AI:</b>\n"
    "Система учится на ваших решениях. Гранты, похожие на одобренные, "
    "автоматически получают более высокий рейтинг."
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    try:
        stats = await api_client.get_stats()
        text = (
            "👋 <b>Добро пожаловать в AI Grant Agent!</b>\n\n"
            "Я помогаю просматривать и управлять грантовыми возможностями.\n\n"
            f"📊 <b>Текущая статистика:</b>\n"
            f"  • ⏳ На рассмотрении: <b>{stats.get('pending', 0)}</b>\n"
            f"  • ✅ Одобрено: <b>{stats.get('approved', 0)}</b>\n"
            f"  • ❌ Отклонено: <b>{stats.get('rejected', 0)}</b>\n"
            f"  • 📦 Всего: <b>{stats.get('total', 0)}</b>\n\n"
            "📋 <b>Доступные команды:</b>\n"
            "  /pending — Просмотр новых грантов\n"
            "  /approved — Одобренные гранты\n"
            "  /rejected — Отклонённые гранты\n"
            "  /search &lt;запрос&gt; — Поиск грантов\n"
            "  /recommend &lt;запрос&gt; — AI-рекомендации\n"
            "  /subscribe — Ежедневный дайджест\n"
            "  /help — Подробная справка"
        )
    except Exception:
        text = (
            "👋 <b>Добро пожаловать в AI Grant Agent!</b>\n\n"
            "📋 <b>Доступные команды:</b>\n"
            "  /pending — Просмотр новых грантов\n"
            "  /approved — Одобренные гранты\n"
            "  /rejected — Отклонённые гранты\n"
            "  /search &lt;запрос&gt; — Поиск грантов\n"
            "  /recommend &lt;запрос&gt; — AI-рекомендации\n"
            "  /subscribe — Ежедневный дайджест\n"
            "  /help — Подробная справка"
        )

    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")
