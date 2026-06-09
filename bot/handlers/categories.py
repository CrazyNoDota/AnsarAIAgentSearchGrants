"""
Category filter handler.
Lets users browse grants by direction/category (Aidar's request).
"""
import hashlib

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import api_client
from handlers.formatters import format_grant
from keyboards.grant_keyboard import grant_review_keyboard, grant_delete_keyboard

router = Router()

PAGE_SIZE = 3

# Telegram callback_data is limited to 64 bytes, and category names can be long
# (and contain non-ASCII chars). We map short hashes -> full names per process.
_CATEGORY_MAP: dict[str, str] = {}


def _hash_category(name: str) -> str:
    h = hashlib.md5(name.encode("utf-8")).hexdigest()[:10]
    _CATEGORY_MAP[h] = name
    return h


async def send_category_list(message: Message) -> None:
    try:
        cats = await api_client.list_categories()
    except Exception as e:
        await message.answer(f"❌ Не удалось загрузить категории: {e}")
        return

    if not cats:
        await message.answer("Категорий пока нет. Сначала запустите сбор.")
        return

    rows = []
    for c in cats[:25]:  # cap to avoid an enormous keyboard
        name = c.get("category") or "—"
        count = c.get("count") or 0
        label = f"{name} ({count})"
        if len(label) > 50:
            label = label[:47] + "…"
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"cat:{_hash_category(name)}:1",
            )
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer(
        "🏷 <b>Фильтр по категориям</b>\n\nВыберите направление:",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def _send_category_page(message: Message, cat_hash: str, page: int) -> None:
    category = _CATEGORY_MAP.get(cat_hash)
    if not category:
        await message.answer("Категория устарела — откройте меню заново.")
        return

    try:
        data = await api_client.get_grants_by_status(
            status="approved", page=page, size=PAGE_SIZE, category=category
        )
    except Exception as e:
        await message.answer(f"❌ Не удалось загрузить гранты: {e}")
        return

    items = data.get("items", [])
    total = data.get("total", 0)

    if not items:
        await message.answer(f"В категории <b>{category}</b> грантов нет.", parse_mode="HTML")
        return

    await message.answer(
        f"🏷 <b>{category}</b> — грантов: {total}", parse_mode="HTML"
    )

    for i, grant in enumerate(items):
        index = (page - 1) * PAGE_SIZE + i + 1
        text = format_grant(grant, index=index, total=total)
        status = grant.get("status", "pending")
        kb = grant_review_keyboard(grant["id"]) if status == "pending" else grant_delete_keyboard(grant["id"])
        await message.answer(
            text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True
        )

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if total_pages > 1:
        row = []
        if page > 1:
            row.append(InlineKeyboardButton(
                text="⬅ Назад", callback_data=f"cat:{cat_hash}:{page - 1}"
            ))
        if page < total_pages:
            row.append(InlineKeyboardButton(
                text="Далее ➡", callback_data=f"cat:{cat_hash}:{page + 1}"
            ))
        rows = [row] if row else []
        rows.append([InlineKeyboardButton(
            text=f"📄 Стр. {page}/{total_pages}", callback_data="noop"
        )])
        await message.answer(
            f"Показано {min(page * PAGE_SIZE, total)}/{total} грантов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )


@router.callback_query(F.data == "menu:categories")
async def menu_categories(callback: CallbackQuery):
    await callback.answer()
    if callback.message:
        await send_category_list(callback.message)


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(callback: CallbackQuery):
    await callback.answer()
    if not callback.message:
        return
    _, cat_hash, page_str = callback.data.split(":", 2)
    try:
        page = int(page_str)
    except ValueError:
        page = 1
    await _send_category_page(callback.message, cat_hash, page)
