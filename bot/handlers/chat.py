"""
Free-form chat fallback.

Any plain-text message that did not match a /command or callback is routed to
the RAG endpoint — so users can just *ask* questions about grants instead of
needing to remember /recommend.

Must be registered LAST so commands and other routers consume their messages first.
"""
import logging

from aiogram import Router, F
from aiogram.types import Message

import api_client
from handlers.formatters import format_grant
from handlers.nlu import detect_intent

logger = logging.getLogger(__name__)
router = Router()

MIN_CHARS = 3


async def _dispatch_intent(message: Message, intent: str, arg) -> None:
    """Route a detected natural-language intent to the matching command handler.

    Imports are local to avoid import cycles between handler modules.
    """
    if intent == "deadlines":
        from handlers.deadlines import send_deadlines
        await send_deadlines(message)
    elif intent in ("pending", "approved", "rejected"):
        from handlers.grants import _send_grants_page
        await _send_grants_page(message, status=intent, page=1)
    elif intent == "stats":
        from handlers.statistics import send_stats
        await send_stats(message)
    elif intent == "insights":
        from handlers.settings import send_insights
        await send_insights(message)
    elif intent == "sources":
        from handlers.sources import send_sources
        await send_sources(message)
    elif intent == "scrape":
        from handlers.settings import cmd_scrape
        await cmd_scrape(message)
    elif intent == "addsource":
        from handlers.sources import add_source_and_reply
        await add_source_and_reply(message, arg)
    elif intent == "help":
        from handlers.start import HELP_TEXT
        await message.answer(HELP_TEXT, parse_mode="HTML", disable_web_page_preview=True)
    elif intent == "guide":
        from handlers.start import GUIDE_TEXT
        await message.answer(GUIDE_TEXT, parse_mode="HTML", disable_web_page_preview=True)


@router.message(F.text & ~F.text.startswith("/"))
async def cmd_freeform(message: Message):
    text = (message.text or "").strip()
    if len(text) < MIN_CHARS:
        return

    # Plain-language commands (RU/EN): "покажи новые гранты", "статистика",
    # "какие гранты скоро истекают", "добавь источник <url>"… If no action intent
    # is recognised, fall through to RAG search below.
    intent = detect_intent(text)
    if intent:
        await _dispatch_intent(message, intent[0], intent[1])
        return

    user_id = str(message.from_user.id) if message.from_user else None
    thinking = await message.answer(
        "🤖 Ищу в проверенной базе грантов…", parse_mode="HTML"
    )

    try:
        result = await api_client.rag_chat(text, limit=5, user_id=user_id)
    except Exception as e:
        logger.exception("RAG fallback failed")
        await thinking.edit_text(f"❌ Ошибка поиска: {e}")
        return

    grants = result.get("grants") or []
    response_text = (result.get("response") or "").strip()

    if not grants and not response_text:
        await thinking.edit_text(
            "По этому запросу в проверенной базе ничего не нашлось.\n"
            "Попробуйте другой запрос или команду <code>/search</code>.",
            parse_mode="HTML",
        )
        return

    await thinking.delete()

    if response_text:
        await message.answer(
            f"🤖 <b>Анализ ИИ:</b>\n\n{response_text}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    if grants:
        await message.answer(
            f"📋 <b>Проверенные гранты ({len(grants)}):</b>", parse_mode="HTML"
        )
        for i, grant in enumerate(grants):
            await message.answer(
                format_grant(grant, index=i + 1, total=len(grants)),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
