"""
Search and recommendation handlers.
- /search — hybrid search (keyword + semantic)
- /recommend — full RAG pipeline with NVIDIA LLM grounded response
- /summarize — AI summary of specific grant
- /delete — remove a grant
"""
import httpx
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import api_client
from handlers.formatters import format_grant

router = Router()


def _format_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        try:
            payload = e.response.json()
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if detail:
                return f"{e.response.status_code} — {detail}"
        except Exception:
            pass
        return f"HTTP {e.response.status_code}"
    msg = str(e).strip()
    return msg or e.__class__.__name__


@router.message(Command("search"))
async def cmd_search(message: Message):
    """/search <query> — hybrid keyword + semantic search."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "🔍 <b>Поиск грантов</b>\n\n"
            "Использование: <code>/search &lt;ваш запрос&gt;</code>\n\n"
            "Примеры:\n"
            "  <code>/search гранты для ИИ-стартапов</code>\n"
            "  <code>/search финансирование вузов Европа</code>\n"
            "  <code>/search акселератор без доли</code>\n\n"
            "<i>Гибридный поиск: ключевые слова + смысловое сопоставление ИИ.</i>",
            parse_mode="HTML",
        )
        return

    query = parts[1].strip()
    await message.answer(f"🔍 Ищу: <b>{query}</b>...", parse_mode="HTML")

    try:
        data = await api_client.hybrid_search(query, limit=5)
        items = data.get("results", [])

        if not items:
            await message.answer(
                f"По запросу <b>{query}</b> ничего не найдено.\n"
                f"<i>Попробуйте /recommend для подсказок от ИИ.</i>",
                parse_mode="HTML",
            )
            return

        await message.answer(
            f"Найдено результатов: <b>{len(items)}</b> по запросу: <b>{query}</b>",
            parse_mode="HTML",
        )
        for i, grant in enumerate(items):
            text = format_grant(grant, index=i + 1, total=len(items))
            await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        await message.answer(f"❌ Ошибка поиска: {_format_error(e)}")


@router.message(Command("recommend"))
async def cmd_recommend(message: Message):
    """/recommend <query> — RAG-powered AI recommendations (anti-hallucination)."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "🤖 <b>Рекомендации грантов от ИИ</b>\n"
            "<i>На базе NVIDIA Qwen3 + RAG (только проверенная база)</i>\n\n"
            "Использование: <code>/recommend &lt;описание&gt;</code>\n\n"
            "Примеры:\n"
            "  <code>/recommend гранты для ИИ-стартапов в Центральной Азии</code>\n"
            "  <code>/recommend финансирование исследований в Европе без доли</code>\n"
            "  <code>/recommend программы для НКО по экологии</code>\n\n"
            "<i>ИИ отвечает только по нашей проверенной базе грантов и ничего не выдумывает.</i>",
            parse_mode="HTML",
        )
        return

    query = parts[1].strip()
    user_id = str(message.from_user.id) if message.from_user else None

    await message.answer(
        f"🤖 <b>ИИ анализирует запрос:</b>\n<i>{query}</i>\n\n"
        f"<i>Ищу в проверенной базе грантов... (до 30 сек)</i>",
        parse_mode="HTML",
    )

    try:
        result = await api_client.rag_chat(query, limit=5, user_id=user_id)

        grants = result.get("grants", [])
        response_text = result.get("response", "")

        if not grants:
            await message.answer(
                "По этому запросу в нашей базе не нашлось проверенной информации.\n\n"
                "<i>Попробуйте другой запрос или дождитесь следующего цикла сбора грантов.</i>",
                parse_mode="HTML",
            )
            return

        # Send the grounded AI response first
        if response_text:
            await message.answer(
                f"🤖 <b>Анализ ИИ:</b>\n\n{response_text}",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

        # Then send individual grant cards
        await message.answer(f"📋 <b>Проверенные гранты из базы ({len(grants)}):</b>", parse_mode="HTML")
        for i, grant in enumerate(grants):
            text = format_grant(grant, index=i + 1, total=len(grants))
            await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        await message.answer(f"❌ Ошибка рекомендаций: {_format_error(e)}")


@router.message(Command("delete"))
async def cmd_delete(message: Message):
    """/delete <grant_id> — permanently remove a grant."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer(
            "🗑 <b>Удалить грант</b>\n\n"
            "Использование: <code>/delete &lt;id_гранта&gt;</code>\n"
            "Пример: <code>/delete 42</code>\n\n"
            "ID гранта показан внизу каждой карточки.",
            parse_mode="HTML",
        )
        return

    grant_id = int(parts[1].strip())
    try:
        await api_client.delete_grant(grant_id)
        await message.answer(f"🗑 Грант #{grant_id} удалён.", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Не удалось удалить: {_format_error(e)}")


@router.message(Command("summarize"))
async def cmd_summarize(message: Message):
    """/summarize <grant_id> — AI-generated summary (NVIDIA LLM)."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer(
            "📝 <b>Краткое изложение гранта от ИИ</b>\n\n"
            "Использование: <code>/summarize &lt;id_гранта&gt;</code>\n"
            "Пример: <code>/summarize 42</code>",
            parse_mode="HTML",
        )
        return

    grant_id = int(parts[1].strip())
    await message.answer(f"📝 Готовлю краткое изложение гранта #{grant_id}...", parse_mode="HTML")

    try:
        result = await api_client.summarize_grant(grant_id)
        summary = result.get("summary", "Изложение недоступно.")
        await message.answer(
            f"📝 <b>Изложение ИИ — грант #{grant_id}</b>\n\n"
            f"{summary}\n\n"
            f"<i>Сгенерировано: {result.get('model', 'ИИ')} | Источник: {result.get('source', 'проверенная база')}</i>",
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка изложения: {_format_error(e)}")
