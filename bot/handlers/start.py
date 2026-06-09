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
            "👋 <b>AI Grant Discovery System</b>\n\n"
            "📊 <b>Current Stats:</b>\n"
            f"  📥 Pending Review: <b>{stats.get('pending', 0)}</b>\n"
            f"  ✅ Approved: <b>{stats.get('approved', 0)}</b>\n"
            f"  ❌ Rejected: <b>{stats.get('rejected', 0)}</b>\n"
            f"  📦 Total: <b>{stats.get('total', 0)}</b>\n\n"
            "Select an option from the menu below:"
        )
    except Exception:
        return (
            "👋 <b>AI Grant Discovery System</b>\n\n"
            "Automated grant sourcing and recommendations powered by NVIDIA AI.\n\n"
            "Select an option from the menu below:"
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


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🤖 <b>AI Grant Agent — Commands</b>\n\n"
        "<b>Navigation:</b>\n"
        "  /start — Main menu\n"
        "  /menu — Show menu again\n\n"
        "<b>Grants:</b>\n"
        "  /pending — New grants for review\n"
        "  /approved — Approved grants\n"
        "  /rejected — Rejected grants\n"
        "  /deadlines — Upcoming deadlines\n\n"
        "<b>AI Search:</b>\n"
        "  /search &lt;query&gt; — Keyword search\n"
        "  /recommend &lt;query&gt; — RAG AI recommendations\n"
        "  /summarize &lt;id&gt; — AI summary of a grant\n\n"
        "<b>Management:</b>\n"
        "  /stats — Database statistics\n"
        "  /insights — AI learning insights\n"
        "  /scrape — Trigger manual scrape\n"
        "  /delete &lt;id&gt; — Delete a grant\n"
        "  /subscribe — Daily digest\n"
        "  /unsubscribe — Cancel digest\n\n"
        "<b>Review Grants:</b>\n"
        "Tap ✅ Approve or ❌ Reject under any grant card. "
        "The AI learns from every decision to improve future recommendations.",
        parse_mode="HTML",
    )


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
            "🤖 <b>AI Recommendations (RAG)</b>\n\n"
            "Type your query and I'll search our verified grant database:\n\n"
            "Examples:\n"
            "  <code>/recommend grants for AI startups</code>\n"
            "  <code>/recommend university research funding Europe</code>\n"
            "  <code>/recommend equity-free accelerator programs</code>\n"
            "  <code>/recommend scholarships Central Asia students</code>",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "menu:search")
async def menu_search(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "🔍 <b>Search Grants</b>\n\n"
            "Use hybrid search (keyword + semantic AI):\n\n"
            "  <code>/search startup grants Kazakhstan</code>\n"
            "  <code>/search university innovation Europe</code>\n"
            "  <code>/search no-equity accelerator</code>",
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
    await callback.answer("Starting scraper...")
    if callback.message:
        await callback.message.answer(
            "🔄 <b>Manual Scrape</b>\n\nUse: <code>/scrape</code> to trigger a full scrape run.",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()
