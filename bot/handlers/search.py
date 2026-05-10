import httpx
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import api_client
from handlers.formatters import format_grant

router = Router()


def _format_error(e: Exception) -> str:
    """Surface enough detail that users (and we) can diagnose failures.

    - httpx.HTTPStatusError: include the backend-reported `detail` if any.
    - Other httpx errors (ReadTimeout/ConnectError): can have empty str(e),
      so fall back to the class name.
    """
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
    """/search <query> — поиск грантов по ключевым словам."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "🔍 <b>Поиск грантов</b>\n\n"
            "Использование: <code>/search &lt;ваш запрос&gt;</code>\n\n"
            "Примеры:\n"
            "  <code>/search AI стартап</code>\n"
            "  <code>/search образование Европа</code>",
            parse_mode="HTML",
        )
        return

    query = parts[1].strip()
    await message.answer(f"🔍 Ищу: <b>{query}</b>...", parse_mode="HTML")

    try:
        data = await api_client.search_grants(query, page=1, size=5)
        items = data.get("items", [])
        total = data.get("total", 0)

        if not items:
            await message.answer(
                f"Гранты не найдены по запросу <b>{query}</b>.", parse_mode="HTML"
            )
            return

        await message.answer(
            f"Найдено <b>{total}</b> результат(ов) по запросу <b>{query}</b>:",
            parse_mode="HTML",
        )
        for i, grant in enumerate(items):
            text = format_grant(grant, index=i + 1, total=total)
            await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        await message.answer(f"❌ Ошибка поиска: {_format_error(e)}")


@router.message(Command("recommend"))
async def cmd_recommend(message: Message):
    """/recommend <query> — AI-рекомендации (Qwen3-480B)."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "🤖 <b>AI-рекомендации грантов</b>\n"
            "<i>На базе Qwen3-480B через NVIDIA AI</i>\n\n"
            "Использование: <code>/recommend &lt;описание&gt;</code>\n\n"
            "Примеры:\n"
            "  <code>/recommend гранты для стартапов в образовании</code>\n"
            "  <code>/recommend научное финансирование университеты Европа</code>\n"
            "  <code>/recommend зелёная энергетика устойчивое развитие НКО</code>",
            parse_mode="HTML",
        )
        return

    query = parts[1].strip()
    await message.answer(
        f"🤖 <b>Qwen3-480B</b> ищет рекомендации по запросу:\n<i>{query}</i>\n\n"
        f"<i>Это может занять до минуты — модель анализирует все гранты в базе.</i>",
        parse_mode="HTML",
    )

    try:
        grants = await api_client.get_recommendations(query, limit=5)

        if not grants:
            await message.answer(
                "Подходящие гранты не найдены. Попробуйте другой запрос.\n"
                "<i>Совет: одобрите несколько грантов, чтобы AI лучше понимал ваши предпочтения!</i>",
                parse_mode="HTML",
            )
            return

        await message.answer(
            f"🎯 Топ-<b>{len(grants)}</b> рекомендаций от AI:",
            parse_mode="HTML",
        )
        for i, grant in enumerate(grants):
            text = format_grant(grant, index=i + 1, total=len(grants))
            await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        await message.answer(f"❌ Ошибка рекомендации: {_format_error(e)}")


@router.message(Command("delete"))
async def cmd_delete(message: Message):
    """/delete <grant_id> — удалить грант навсегда."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer(
            "🗑 <b>Удаление гранта</b>\n\n"
            "Использование: <code>/delete &lt;id_гранта&gt;</code>\n\n"
            "Пример: <code>/delete 42</code>\n\n"
            "ID гранта указан внизу каждого сообщения о гранте.",
            parse_mode="HTML",
        )
        return

    grant_id = int(parts[1].strip())
    try:
        await api_client.delete_grant(grant_id)
        await message.answer(
            f"🗑 Грант #{grant_id} удалён.",
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"❌ Не удалось удалить: {_format_error(e)}")


@router.message(Command("summarize"))
async def cmd_summarize(message: Message):
    """/summarize <grant_id> — AI-резюме конкретного гранта."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer(
            "📝 <b>AI-резюме гранта</b>\n\n"
            "Использование: <code>/summarize &lt;id_гранта&gt;</code>\n\n"
            "Пример: <code>/summarize 42</code>\n\n"
            "ID гранта указан внизу каждого сообщения о гранте.",
            parse_mode="HTML",
        )
        return

    grant_id = int(parts[1].strip())
    await message.answer(
        f"📝 Генерирую AI-резюме для гранта #{grant_id}...", parse_mode="HTML"
    )

    try:
        result = await api_client.summarize_grant(grant_id)
        summary = result.get("summary", "Резюме недоступно.")
        await message.answer(
            f"📝 <b>AI-резюме — Грант #{grant_id}</b>\n\n"
            f"{summary}\n\n"
            f"<i>Создано моделью {result.get('model', 'AI')}</i>",
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка резюме: {_format_error(e)}")
