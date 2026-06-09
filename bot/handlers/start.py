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


HELP_TEXT = (
    "🤖 <b>AI Grant Agent — Command Reference</b>\n\n"
    "<b>🧭 Navigation</b>\n"
    "  /start, /menu — main menu\n"
    "  /guide — how the whole system works\n"
    "  /help — this list\n\n"
    "<b>📋 Browse grants</b>\n"
    "  /pending — new grants awaiting your review\n"
    "  /approved — grants you approved\n"
    "  /rejected — grants you rejected\n"
    "  /deadlines — deadlines in the next 30 days\n\n"
    "<b>🔎 Find grants</b>\n"
    "  /search &lt;query&gt; — keyword + semantic search\n"
    "  /recommend &lt;query&gt; — AI answer grounded in the verified DB\n"
    "  /summarize &lt;id&gt; — AI summary of one grant\n\n"
    "<b>🌐 Sources — what gets scraped</b>\n"
    "  /sources — list your custom sources + health\n"
    "  /addsource &lt;url&gt; [| name] — add a source to scrape\n"
    "  /scrapesource &lt;id&gt; — scrape one source now\n"
    "  /delsource &lt;id&gt; — remove a source\n"
    "  /scrape — run a full scrape of every source now\n\n"
    "<b>⚙️ Manage</b>\n"
    "  /stats — database statistics\n"
    "  /insights — what the AI has learned from your reviews\n"
    "  /delete &lt;id&gt; — delete a grant\n"
    "  /subscribe, /unsubscribe — daily digest\n\n"
    "<b>✅ Reviewing</b>\n"
    "Tap ✅ Approve or ❌ Reject under any grant card — the AI learns from every "
    "decision to sharpen future recommendations.\n\n"
    "<i>New here? Send /guide for a 1-minute walkthrough.</i>"
)

GUIDE_TEXT = (
    "📖 <b>How the AI Grant Agent works</b>\n\n"
    "<b>1. It collects grants</b>\n"
    "The agent scrapes funding opportunities from three places:\n"
    "  • 37 built-in sources (gov, EU, UN, accelerators, fellowships…)\n"
    "  • an AI Search Agent that discovers new pages on the web\n"
    "  • <b>your own sources</b> — any URL you add with /addsource\n\n"
    "<b>2. It stores only verified data</b>\n"
    "Everything found goes into a database as <b>pending</b>. Search and "
    "recommendations answer ONLY from this database — the AI never invents grants. "
    "An empty database means nothing has been scraped yet.\n\n"
    "<b>3. You review</b>\n"
    "Open /pending and tap ✅/❌ on each card. The AI learns your preferences "
    "(see /insights) and ranks future finds accordingly.\n\n"
    "<b>4. You search</b>\n"
    "  • /search — fast keyword + semantic match\n"
    "  • /recommend — an AI explanation grounded in the verified grants\n\n"
    "<b>➕ Adding a source (most common task)</b>\n"
    "Find a page that lists grants, then:\n"
    "  <code>/addsource https://site.org/funding | My label</code>\n"
    "The parser reads that page on every cycle. Pull it in immediately with "
    "<code>/scrapesource &lt;id&gt;</code>. Check health anytime with /sources.\n\n"
    "<b>⏰ Automatic updates</b>\n"
    "A full scrape runs automatically every day at 02:00 (Almaty). Trigger one "
    "manually anytime with /scrape.\n\n"
    "<i>Full command list: /help</i>"
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
