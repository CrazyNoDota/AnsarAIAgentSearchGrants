"""
Custom source management handlers.

Lets an operator extend what the agent scrapes — beyond the 37 built-in scrapers
and the AI Search Agent — by registering arbitrary grant/funding listing URLs.

Commands:
  /sources              — list registered sources + their health
  /addsource <url> [| name]  — register a new source (optionally a friendly name)
  /delsource <id>       — remove a source
  /scrapesource <id>    — scrape one source right now
"""
from html import escape

import httpx
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

import api_client

router = Router()


def _esc(value) -> str:
    """Escape a value for safe inclusion in Telegram HTML (parse_mode=HTML)."""
    return escape(str(value), quote=False)


def _format_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        try:
            payload = e.response.json()
            detail = payload.get("detail") if isinstance(payload, dict) else None
            # Pydantic validation errors come back as a list of dicts.
            if isinstance(detail, list) and detail:
                msgs = [d.get("msg", "") for d in detail if isinstance(d, dict)]
                if any(msgs):
                    return "; ".join(m for m in msgs if m)
            if detail:
                return f"{e.response.status_code} — {detail}"
        except Exception:
            pass
        return f"HTTP {e.response.status_code}"
    msg = str(e).strip()
    return msg or e.__class__.__name__


_STATUS_ICON = {"ok": "🟢", "error": "🔴", None: "⚪️"}


def _format_source(s: dict) -> str:
    icon = _STATUS_ICON.get(s.get("last_status"), "⚪️")
    enabled = "" if s.get("enabled", True) else " <i>(disabled)</i>"
    name = _esc(s.get("name") or s.get("url"))
    line = f"{icon} <b>#{s['id']}</b> {name}{enabled}\n     {_esc(s['url'])}"
    last = s.get("last_scraped_at")
    if last:
        line += (
            f"\n     last run: {_esc(last[:10])} · "
            f"+{s.get('last_count', 0)} new · {_esc(s.get('last_status') or '—')}"
        )
    if s.get("last_status") == "error" and s.get("last_error"):
        line += f"\n     ⚠️ {_esc(s['last_error'][:160])}"
    return line


_ADD_HELP = (
    "🌐 <b>Add a Grant Source</b>\n\n"
    "Register any page that lists grants/funding — the AI parser will read it on "
    "every scrape cycle and add what it finds to your review queue.\n\n"
    "Usage:\n"
    "  <code>/addsource &lt;url&gt;</code>\n"
    "  <code>/addsource &lt;url&gt; | Friendly name</code>\n\n"
    "Examples:\n"
    "  <code>/addsource https://astanahub.com/en/grants</code>\n"
    "  <code>/addsource https://example.org/funding | Tourism KZ</code>\n\n"
    "<i>Tip: point it at a list/listing page, not a single grant.</i>"
)


async def send_sources(message: Message):
    """Fetch and render the list of registered custom sources."""
    try:
        sources = await api_client.list_sources()
    except Exception as e:
        await message.answer(f"❌ Failed to load sources: {_esc(_format_error(e))}")
        return

    if not sources:
        await message.answer(
            "🌐 <b>Custom Grant Sources</b>\n\n"
            "No custom sources yet. The agent currently scrapes only the built-in "
            "sources + the AI Search Agent.\n\n" + _ADD_HELP,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    lines = [f"🌐 <b>Custom Grant Sources</b> ({len(sources)})\n"]
    lines.extend(_format_source(s) for s in sources)
    lines.append(
        "\n<i>Manage:</i> <code>/addsource &lt;url&gt;</code> · "
        "<code>/scrapesource &lt;id&gt;</code> · <code>/delsource &lt;id&gt;</code>"
    )
    await message.answer(
        "\n".join(lines), parse_mode="HTML", disable_web_page_preview=True
    )


@router.message(Command("sources"))
async def cmd_sources(message: Message):
    await send_sources(message)


@router.message(Command("addsource"))
async def cmd_addsource(message: Message):
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(_ADD_HELP, parse_mode="HTML", disable_web_page_preview=True)
        return

    args = parts[1].strip()
    name = None
    if "|" in args:
        url, name = (p.strip() for p in args.split("|", 1))
        name = name or None
    else:
        # Allow "<url> some name" too (first whitespace-token is the URL).
        url_parts = args.split(maxsplit=1)
        url = url_parts[0].strip()
        if len(url_parts) > 1 and url_parts[1].strip():
            name = url_parts[1].strip()

    added_by = None
    if message.from_user:
        added_by = message.from_user.username or str(message.from_user.id)

    try:
        result = await api_client.add_source(url, name=name, added_by=added_by)
    except Exception as e:
        await message.answer(f"❌ Could not add source: {_esc(_format_error(e))}")
        return

    source = result.get("source", {})
    sid = source.get("id")
    if result.get("status") == "exists":
        await message.answer(
            f"ℹ️ That URL is already registered as <b>#{sid}</b> (re-enabled).\n"
            f"Run it now with <code>/scrapesource {sid}</code>.",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    await message.answer(
        f"✅ <b>Source added</b> — #{sid}\n"
        f"{_esc(source.get('name') or source.get('url'))}\n\n"
        f"It will be scraped on the next cycle. To pull it in now:\n"
        f"<code>/scrapesource {sid}</code>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("delsource"))
async def cmd_delsource(message: Message):
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer(
            "🗑 <b>Remove a Source</b>\n\n"
            "Usage: <code>/delsource &lt;id&gt;</code>\n"
            "Example: <code>/delsource 3</code>\n\n"
            "<i>See IDs with /sources. Grants already collected are kept.</i>",
            parse_mode="HTML",
        )
        return

    source_id = int(parts[1].strip())
    try:
        await api_client.delete_source(source_id)
        await message.answer(f"🗑 Source #{source_id} removed.", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Delete failed: {_esc(_format_error(e))}")


@router.message(Command("scrapesource"))
async def cmd_scrapesource(message: Message):
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer(
            "🔄 <b>Scrape One Source</b>\n\n"
            "Usage: <code>/scrapesource &lt;id&gt;</code>\n"
            "Example: <code>/scrapesource 3</code>\n\n"
            "<i>See IDs with /sources.</i>",
            parse_mode="HTML",
        )
        return

    source_id = int(parts[1].strip())
    await message.answer(
        f"🔄 Scraping source #{source_id}...\n<i>This may take up to a minute.</i>",
        parse_mode="HTML",
    )
    try:
        result = await api_client.run_source(source_id)
    except Exception as e:
        await message.answer(f"❌ Scrape failed: {_esc(_format_error(e))}")
        return

    new = result.get("new", 0)
    total = result.get("total", 0)
    errors = result.get("errors", 0)
    by_source = result.get("by_source", {})
    detail = ""
    if errors and by_source:
        # Surface the first source-level error message if present.
        for label, s in by_source.items():
            if s.get("errors"):
                detail = f"\n⚠️ {_esc(label)}: check the URL is a reachable listing page."
                break

    await message.answer(
        f"✅ <b>Source #{source_id} scraped</b>\n\n"
        f"📦 Found: <b>{total}</b>\n"
        f"🆕 New: <b>{new}</b> added to review queue\n"
        f"⚠️ Errors: {errors}{detail}",
        parse_mode="HTML",
    )


# ── Menu callbacks ───────────────────────────────────────────

@router.callback_query(F.data == "menu:sources")
async def menu_sources(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        await send_sources(callback.message)
