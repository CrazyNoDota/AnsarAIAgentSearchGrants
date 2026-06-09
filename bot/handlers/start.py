"""
Start handler — main menu entry point.
Displays stats + full inline menu on /start.
"""
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

import api_client
from keyboards.main_menu import main_menu_keyboard

router = Router()


async def _build_welcome_text() -> str:
    """Build welcome message with current database stats."""
    try:
        stats = await api_client.get_stats()
        return (
            "👋 <b>ИИ-агент по поиску грантов</b>\n\n"
            "📊 <b>Текущая статистика:</b>\n"
            f"  📥 На рассмотрении: <b>{stats.get('pending', 0)}</b>\n"
            f"  ✅ Одобрено: <b>{stats.get('approved', 0)}</b>\n"
            f"  ❌ Отклонено: <b>{stats.get('rejected', 0)}</b>\n"
            f"  📦 Всего: <b>{stats.get('total', 0)}</b>\n\n"
            "Выберите пункт меню ниже:"
        )
    except Exception:
        return (
            "👋 <b>ИИ-агент по поиску грантов</b>\n\n"
            "Автоматический поиск грантов и рекомендации на базе ИИ NVIDIA.\n\n"
            "Выберите пункт меню ниже:"
        )


@router.message(CommandStart())
async def cmd_start(message: Message):
    # Auto-register this user for notifications (no manual chat ID setup needed)
    if message.from_user:
        try:
            await api_client.subscribe(message.from_user.id, message.chat.id)
        except Exception:
            pass  # Non-fatal — bot still works without subscription

    text = await _build_welcome_text()
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard())


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    text = await _build_welcome_text()
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard())


HELP_TEXT = (
    "🤖 <b>ИИ-агент по грантам — список команд</b>\n\n"
    "<b>🧭 Навигация</b>\n"
    "  /start, /menu — главное меню\n"
    "  /guide — как работает вся система\n"
    "  /help — этот список\n\n"
    "<b>📋 Просмотр грантов</b>\n"
    "  /pending — новые гранты, ждущие вашей проверки\n"
    "  /approved — одобренные вами гранты\n"
    "  /rejected — отклонённые вами гранты\n"
    "  /deadlines — дедлайны в ближайшие 30 дней\n\n"
    "<b>🔎 Поиск грантов</b>\n"
    "  /search &lt;запрос&gt; — поиск по ключевым словам + смысловой\n"
    "  /recommend &lt;запрос&gt; — ответ ИИ строго по проверенной базе\n"
    "  /summarize &lt;id&gt; — краткое изложение гранта от ИИ\n\n"
    "<b>🌐 Источники — что сканируется</b>\n"
    "  /sources — список ваших источников и их состояние\n"
    "  /addsource &lt;url&gt; [| название] — добавить источник\n"
    "  /scrapesource &lt;id&gt; — просканировать один источник сейчас\n"
    "  /delsource &lt;id&gt; — удалить источник\n"
    "  /scrape — запустить полный сбор по всем источникам\n\n"
    "<b>⚙️ Управление</b>\n"
    "  /stats — статистика базы\n"
    "  /insights — что ИИ понял по вашим решениям\n"
    "  /delete &lt;id&gt; — удалить грант\n"
    "  /subscribe, /unsubscribe — ежедневная сводка\n\n"
    "<b>✅ Проверка</b>\n"
    "Нажимайте ✅ Одобрить или ❌ Отклонить под карточкой гранта — ИИ учится на "
    "каждом решении и точнее подбирает гранты в будущем.\n\n"
    "<i>Впервые здесь? Отправьте /guide — обзор за 1 минуту.</i>"
)

GUIDE_TEXT = (
    "📖 <b>Как работает ИИ-агент по грантам</b>\n\n"
    "<b>1. Он собирает гранты</b>\n"
    "Агент собирает возможности финансирования из трёх мест:\n"
    "  • 37 встроенных источников (госорганы, ЕС, ООН, акселераторы, стипендии…)\n"
    "  • ИИ-агент поиска, который находит новые страницы в интернете\n"
    "  • <b>ваши собственные источники</b> — любой URL, добавленный через /addsource\n\n"
    "<b>2. Он хранит только проверенные данные</b>\n"
    "Всё найденное попадает в базу со статусом <b>на рассмотрении</b>. Поиск и "
    "рекомендации отвечают ТОЛЬКО по этой базе — ИИ не выдумывает гранты. "
    "Пустая база значит, что сбор ещё не запускался.\n\n"
    "<b>3. Вы проверяете</b>\n"
    "Откройте /pending и жмите ✅/❌ на каждой карточке. ИИ запоминает ваши "
    "предпочтения (см. /insights) и ранжирует находки соответственно.\n\n"
    "<b>4. Вы ищете</b>\n"
    "  • /search — быстрый поиск по словам + по смыслу\n"
    "  • /recommend — объяснение от ИИ строго по проверенным грантам\n\n"
    "<b>➕ Добавление источника (самое частое)</b>\n"
    "Найдите страницу со списком грантов, затем:\n"
    "  <code>/addsource https://site.org/funding | Моя метка</code>\n"
    "Парсер читает эту страницу при каждом цикле. Чтобы собрать сразу — "
    "<code>/scrapesource &lt;id&gt;</code>. Состояние смотрите в /sources.\n\n"
    "<b>⏰ Автообновление</b>\n"
    "Полный сбор запускается автоматически каждый день в 02:00 (Алматы). "
    "Запустить вручную можно в любой момент командой /scrape.\n\n"
    "<i>Полный список команд: /help</i>"
)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("guide"))
async def cmd_guide(message: Message):
    await message.answer(GUIDE_TEXT, parse_mode="HTML", disable_web_page_preview=True)


# ── Callback: main menu navigation ───────────────────────────

@router.callback_query(F.data == "menu:pending")
async def menu_pending(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        from handlers.grants import _send_grants_page
        await _send_grants_page(callback.message, status="pending", page=1)


@router.callback_query(F.data == "menu:approved")
async def menu_approved(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        from handlers.grants import _send_grants_page
        await _send_grants_page(callback.message, status="approved", page=1)


@router.callback_query(F.data == "menu:rejected")
async def menu_rejected(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        from handlers.grants import _send_grants_page
        await _send_grants_page(callback.message, status="rejected", page=1)


@router.callback_query(F.data == "menu:deadlines")
async def menu_deadlines(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        from handlers.deadlines import send_deadlines
        await send_deadlines(callback.message)


@router.callback_query(F.data == "menu:recommend")
async def menu_recommend(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "🤖 <b>Рекомендации ИИ (RAG)</b>\n\n"
            "Напишите запрос — я найду гранты в нашей проверенной базе:\n\n"
            "Примеры:\n"
            "  <code>/recommend гранты для ИИ-стартапов</code>\n"
            "  <code>/recommend финансирование исследований в Европе</code>\n"
            "  <code>/recommend акселераторы без доли в капитале</code>\n"
            "  <code>/recommend стипендии для студентов Центральной Азии</code>",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "menu:search")
async def menu_search(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "🔍 <b>Поиск грантов</b>\n\n"
            "Гибридный поиск (ключевые слова + смысловой ИИ):\n\n"
            "  <code>/search гранты для стартапов Казахстан</code>\n"
            "  <code>/search инновации в вузах Европа</code>\n"
            "  <code>/search акселератор без доли</code>",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "menu:stats")
async def menu_stats(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        from handlers.statistics import send_stats
        await send_stats(callback.message)


@router.callback_query(F.data == "menu:insights")
async def menu_insights(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        from handlers.settings import send_insights
        await send_insights(callback.message)


@router.callback_query(F.data == "menu:scrape")
async def menu_scrape(callback: CallbackQuery):
    await callback.answer("Запускаю сбор...")
    if callback.message:
        await callback.message.answer(
            "🔄 <b>Ручной сбор</b>\n\nКоманда <code>/scrape</code> запускает полный сбор по всем источникам.",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "menu:help")
async def menu_help(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            GUIDE_TEXT, parse_mode="HTML", disable_web_page_preview=True
        )
        await callback.message.answer(
            HELP_TEXT, parse_mode="HTML", disable_web_page_preview=True
        )


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()
