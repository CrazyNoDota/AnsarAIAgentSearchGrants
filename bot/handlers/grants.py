from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

import api_client
from handlers.formatters import format_grant
from keyboards.grant_keyboard import (
    grant_review_keyboard,
    grant_delete_keyboard,
    pagination_keyboard,
)

router = Router()

STATUS_LABEL = {
    "pending": "на рассмотрении",
    "approved": "одобренных",
    "rejected": "отклонённых",
}


async def _send_grants_page(
    message: Message,
    status: str,
    page: int = 1,
    size: int = 3,
):
    """Получить и отправить страницу грантов."""
    try:
        data = await api_client.get_grants_by_status(status, page=page, size=size)
    except Exception as e:
        msg = str(e).strip() or e.__class__.__name__
        await message.answer(f"❌ Не удалось загрузить гранты: {msg}")
        return

    items = data.get("items", [])
    total = data.get("total", 0)
    label = STATUS_LABEL.get(status, status)

    if not items:
        status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(status, "📋")
        await message.answer(f"{status_emoji} Нет грантов со статусом «{label}».")
        return

    for i, grant in enumerate(items):
        index = (page - 1) * size + i + 1
        text = format_grant(grant, index=index, total=total)

        if status == "pending":
            keyboard = grant_review_keyboard(grant["id"])
        else:
            keyboard = grant_delete_keyboard(grant["id"])

        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )

    if total > size:
        pager = pagination_keyboard(
            command=status,
            current_page=page,
            total=total,
            size=size,
        )
        await message.answer(
            f"Показано {min(size * page, total)}/{total} грантов ({label}).",
            reply_markup=pager,
        )


@router.message(Command("pending"))
async def cmd_pending(message: Message):
    await _send_grants_page(message, status="pending", page=1)


@router.message(Command("approved"))
async def cmd_approved(message: Message):
    await _send_grants_page(message, status="approved", page=1)


@router.message(Command("rejected"))
async def cmd_rejected(message: Message):
    await _send_grants_page(message, status="rejected", page=1)


@router.callback_query(F.data.startswith("page:"))
async def handle_pagination(callback: CallbackQuery):
    """Переход на следующую/предыдущую страницу."""
    await callback.answer()
    _, command, page_str = callback.data.split(":", 2)
    page = int(page_str)

    if callback.message:
        await _send_grants_page(callback.message, status=command, page=page)
