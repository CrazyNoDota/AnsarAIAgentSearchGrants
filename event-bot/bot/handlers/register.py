"""Registration flow handler.

Flow:
  1. User sends a URL (or /register <url>).
  2. Bot starts filling in background (Playwright task).
  3. When filler hits an unknown field it puts a question into ask_queue
     and blocks waiting on answer_queue.
  4. _run_fill loop reads ask_queue, displays question to user, sets FSM state.
  5. field_answer_text / field_answer_option handler puts user reply into
     answer_queue — the filler task picks it up directly.
  6. After all fields, filler returns FillResult; _run_fill shows screenshot
     + confirm buttons.
  7. User confirms → bot runs submit_form (same flow, plus clicks submit).
"""
from __future__ import annotations

import asyncio
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import storage.db as db
from bot.keyboards import confirm_keyboard, options_keyboard
from bot.states import Registration
from config import get_settings
from filler.filler import FillResult, fill_form, submit_form

log = logging.getLogger(__name__)
router = Router()

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _extract_url(text: str) -> str | None:
    m = _URL_RE.search(text)
    return m.group(0).rstrip(".,)>") if m else None


def _fill_summary(result: FillResult) -> str:
    lines: list[str] = []
    if result.filled:
        lines.append("<b>Заполнено:</b>")
        for label, val in result.filled.items():
            short = val[:60] + "…" if len(val) > 60 else val
            lines.append(f"  • {label}: <code>{short}</code>")
    if result.skipped:
        lines.append("\n<b>Пропущено:</b>")
        for label in result.skipped:
            lines.append(f"  • {label}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bridge: connects filler coroutine ↔ Telegram FSM via two async queues.
# ask_queue  : filler → _run_fill loop   (question + options)
# answer_queue: handler → filler task    (user's answer)
# ---------------------------------------------------------------------------

class _DialogBridge:
    def __init__(self) -> None:
        self.ask_queue: asyncio.Queue[tuple[str, list[str] | None]] = asyncio.Queue()
        self.answer_queue: asyncio.Queue[str] = asyncio.Queue()


# One bridge per active registration session (keyed by telegram_id).
_bridges: dict[int, _DialogBridge] = {}


async def _ask_via_telegram(
    bridge: _DialogBridge, question: str, options: list[str] | None
) -> str:
    """Called by filler when it needs user input. Blocks until answer_queue has a value."""
    await bridge.ask_queue.put((question, options))
    return await bridge.answer_queue.get()


# ---------------------------------------------------------------------------
# Core fill runner
# ---------------------------------------------------------------------------

async def _run_fill(message: Message, state: FSMContext, url: str, submit: bool = False) -> None:
    uid = message.from_user.id
    profile = await db.get_profile(uid) or {}
    settings = get_settings()

    bridge = _DialogBridge()
    _bridges[uid] = bridge

    async def ask(question: str, options: list[str] | None) -> str:
        return await _ask_via_telegram(bridge, question, options)

    filler_coro = (submit_form if submit else fill_form)(
        url, uid, profile, ask, headless=settings.headless
    )
    task: asyncio.Task[FillResult] = asyncio.create_task(filler_coro)

    # Pump the ask_queue: every time the filler needs user input, relay to Telegram.
    # The user's reply goes directly into answer_queue via the handler below —
    # the filler task reads it from there without going through this loop.
    while not task.done():
        try:
            question, options = await asyncio.wait_for(bridge.ask_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        if options:
            await message.answer(
                f"Поле «<b>{question}</b>»\n\nВыбери или напиши своё:",
                parse_mode="HTML",
                reply_markup=options_keyboard(options),
            )
        else:
            await message.answer(
                f"Поле «<b>{question}</b>» — что ответить?\n"
                f"(<code>-</code> чтобы пропустить)",
                parse_mode="HTML",
            )
        await state.set_state(Registration.waiting_field_answer)
        # Do NOT read from answer_queue here — the handler does that and puts
        # the value directly; the filler task reads it from answer_queue itself.

    _bridges.pop(uid, None)

    try:
        result: FillResult = task.result()
    except Exception as exc:
        log.exception("Filler task raised: %s", exc)
        await state.clear()
        await message.answer(f"Ошибка во время заполнения: {exc}")
        return

    await state.clear()

    # Error path
    if not result.success:
        caption = f"Ошибка: {result.error or 'неизвестная ошибка'}"
        if result.screenshot:
            await message.answer_photo(
                BufferedInputFile(result.screenshot, "error.png"), caption=caption
            )
        else:
            await message.answer(caption)
        await db.log_registration(uid, url, "error", detail=result.error)
        return

    summary = _fill_summary(result)

    if submit:
        caption = (f"{summary}\n\n✅ Форма отправлена!" if summary else "✅ Форма отправлена!")
        if result.screenshot:
            await message.answer_photo(
                BufferedInputFile(result.screenshot, "result.png"),
                caption=caption,
                parse_mode="HTML",
            )
        else:
            await message.answer(caption, parse_mode="HTML")
        await db.log_registration(uid, url, "submitted", payload=result.filled)

    else:
        # Preview — show screenshot and ask to confirm
        caption = (
            f"{summary}\n\n<b>Всё верно? Отправить форму?</b>"
            if summary
            else "<b>Отправить форму?</b>"
        )
        await state.update_data(pending_url=url)
        await state.set_state(Registration.waiting_confirm)
        if result.screenshot:
            await message.answer_photo(
                BufferedInputFile(result.screenshot, "preview.png"),
                caption=caption,
                parse_mode="HTML",
                reply_markup=confirm_keyboard(url),
            )
        else:
            await message.answer(caption, parse_mode="HTML", reply_markup=confirm_keyboard(url))


# ---------------------------------------------------------------------------
# Entry-point handlers
# ---------------------------------------------------------------------------

@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext) -> None:
    url = _extract_url(message.text or "")
    if not url:
        await message.answer(
            "Укажи ссылку: <code>/register https://example.com/signup</code>",
            parse_mode="HTML",
        )
        return
    if not await db.get_profile(message.from_user.id):
        await message.answer("Сначала заполни профиль: /start")
        return
    await message.answer("Открываю страницу…")
    await _run_fill(message, state, url)


@router.message(F.text.regexp(r"https?://\S+"))
async def url_message(message: Message, state: FSMContext) -> None:
    # Don't intercept URLs while we're mid-conversation
    current = await state.get_state()
    if current in (Registration.waiting_field_answer, Registration.waiting_confirm):
        return
    url = _extract_url(message.text or "")
    if not url:
        return
    if not await db.get_profile(message.from_user.id):
        await message.answer("Сначала заполни профиль: /start")
        return
    await message.answer("Открываю страницу…")
    await _run_fill(message, state, url)


# ---------------------------------------------------------------------------
# Answer to unknown field (text or option button)
# ---------------------------------------------------------------------------

@router.message(Registration.waiting_field_answer)
async def field_answer_text(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id
    bridge = _bridges.get(uid)
    if bridge:
        await bridge.answer_queue.put(message.text or "-")
    # State will be updated by _run_fill when it reads the next question or finishes.


@router.callback_query(Registration.waiting_field_answer, F.data.startswith("opt:"))
async def field_answer_option(callback: CallbackQuery, state: FSMContext) -> None:
    uid = callback.from_user.id
    bridge = _bridges.get(uid)
    if bridge:
        value = callback.data.split(":", 1)[1]
        await bridge.answer_queue.put(value)
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)


# ---------------------------------------------------------------------------
# Confirm / cancel before submit
# ---------------------------------------------------------------------------

@router.callback_query(Registration.waiting_confirm, F.data == "reg:submit")
async def confirm_submit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Отправляю…")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
    data = await state.get_data()
    url: str = data.get("pending_url", "")
    await state.clear()
    if callback.message:
        await callback.message.answer("Заполняю и отправляю форму…")
        await _run_fill(callback.message, state, url, submit=True)  # type: ignore[arg-type]


@router.callback_query(Registration.waiting_confirm, F.data == "reg:cancel")
async def confirm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Регистрация отменена.")
