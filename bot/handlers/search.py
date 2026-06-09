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
            "🔍 <b>Search Grants</b>\n\n"
            "Usage: <code>/search &lt;your query&gt;</code>\n\n"
            "Examples:\n"
            "  <code>/search AI startup grants</code>\n"
            "  <code>/search university Europe funding</code>\n"
            "  <code>/search no equity accelerator</code>\n\n"
            "<i>Uses hybrid search: keyword + AI semantic matching.</i>",
            parse_mode="HTML",
        )
        return

    query = parts[1].strip()
    await message.answer(f"🔍 Searching: <b>{query}</b>...", parse_mode="HTML")

    try:
        data = await api_client.hybrid_search(query, limit=5)
        items = data.get("results", [])

        if not items:
            await message.answer(
                f"No grants found for <b>{query}</b>.\n"
                f"<i>Try /recommend for AI-powered suggestions.</i>",
                parse_mode="HTML",
            )
            return

        await message.answer(
            f"Found <b>{len(items)}</b> result(s) for: <b>{query}</b>",
            parse_mode="HTML",
        )
        for i, grant in enumerate(items):
            text = format_grant(grant, index=i + 1, total=len(items))
            await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        await message.answer(f"❌ Search error: {_format_error(e)}")


@router.message(Command("recommend"))
async def cmd_recommend(message: Message):
    """/recommend <query> — RAG-powered AI recommendations (anti-hallucination)."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "🤖 <b>AI Grant Recommendations</b>\n"
            "<i>Powered by NVIDIA Qwen3 + RAG (verified database only)</i>\n\n"
            "Usage: <code>/recommend &lt;description&gt;</code>\n\n"
            "Examples:\n"
            "  <code>/recommend grants for AI startups in Central Asia</code>\n"
            "  <code>/recommend university research funding Europe no equity</code>\n"
            "  <code>/recommend NGO environmental impact programs</code>\n\n"
            "<i>The AI only answers from our verified grant database — never invents information.</i>",
            parse_mode="HTML",
        )
        return

    query = parts[1].strip()
    user_id = str(message.from_user.id) if message.from_user else None

    await message.answer(
        f"🤖 <b>AI analyzing query:</b>\n<i>{query}</i>\n\n"
        f"<i>Searching verified grant database... (up to 30s)</i>",
        parse_mode="HTML",
    )

    try:
        result = await api_client.rag_chat(query, limit=5, user_id=user_id)

        grants = result.get("grants", [])
        response_text = result.get("response", "")

        if not grants:
            await message.answer(
                "Verified information was not found in our database for this query.\n\n"
                "<i>Try a different query or wait for the next scraping cycle to add more grants.</i>",
                parse_mode="HTML",
            )
            return

        # Send the grounded AI response first
        if response_text:
            await message.answer(
                f"🤖 <b>AI Analysis:</b>\n\n{response_text}",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

        # Then send individual grant cards
        await message.answer(f"📋 <b>Verified grants from database ({len(grants)}):</b>", parse_mode="HTML")
        for i, grant in enumerate(grants):
            text = format_grant(grant, index=i + 1, total=len(grants))
            await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        await message.answer(f"❌ Recommendation error: {_format_error(e)}")


@router.message(Command("delete"))
async def cmd_delete(message: Message):
    """/delete <grant_id> — permanently remove a grant."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer(
            "🗑 <b>Delete Grant</b>\n\n"
            "Usage: <code>/delete &lt;grant_id&gt;</code>\n"
            "Example: <code>/delete 42</code>\n\n"
            "Grant ID is shown at the bottom of each grant card.",
            parse_mode="HTML",
        )
        return

    grant_id = int(parts[1].strip())
    try:
        await api_client.delete_grant(grant_id)
        await message.answer(f"🗑 Grant #{grant_id} deleted.", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Delete failed: {_format_error(e)}")


@router.message(Command("summarize"))
async def cmd_summarize(message: Message):
    """/summarize <grant_id> — AI-generated summary (NVIDIA LLM)."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer(
            "📝 <b>AI Grant Summary</b>\n\n"
            "Usage: <code>/summarize &lt;grant_id&gt;</code>\n"
            "Example: <code>/summarize 42</code>",
            parse_mode="HTML",
        )
        return

    grant_id = int(parts[1].strip())
    await message.answer(f"📝 Generating AI summary for grant #{grant_id}...", parse_mode="HTML")

    try:
        result = await api_client.summarize_grant(grant_id)
        summary = result.get("summary", "Summary not available.")
        await message.answer(
            f"📝 <b>AI Summary — Grant #{grant_id}</b>\n\n"
            f"{summary}\n\n"
            f"<i>Generated by {result.get('model', 'AI')} | Source: {result.get('source', 'verified_db')}</i>",
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"❌ Summary error: {_format_error(e)}")
