from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def grant_review_keyboard(grant_id: int) -> InlineKeyboardMarkup:
    """Кнопки одобрения/отклонения/удаления под сообщением о гранте."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=f"review:approve:{grant_id}",
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"review:reject:{grant_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=f"delete:confirm:{grant_id}",
            ),
        ],
    ])


def grant_delete_keyboard(grant_id: int) -> InlineKeyboardMarkup:
    """Кнопка удаления под сообщением о гранте (для approved/rejected)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=f"delete:confirm:{grant_id}",
            ),
        ],
    ])


def delete_confirm_keyboard(grant_id: int) -> InlineKeyboardMarkup:
    """Двухшаговое подтверждение удаления — защита от случайного нажатия."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🗑 Да, удалить",
                callback_data=f"delete:do:{grant_id}",
            ),
            InlineKeyboardButton(
                text="◀ Отмена",
                callback_data=f"delete:cancel:{grant_id}",
            ),
        ],
    ])


def pagination_keyboard(
    command: str,
    current_page: int,
    total: int,
    size: int,
) -> InlineKeyboardMarkup:
    """Кнопки пагинации: Назад / Далее."""
    buttons = []
    total_pages = max(1, (total + size - 1) // size)

    row = []
    if current_page > 1:
        row.append(InlineKeyboardButton(
            text="⬅ Назад",
            callback_data=f"page:{command}:{current_page - 1}",
        ))
    if current_page < total_pages:
        row.append(InlineKeyboardButton(
            text="Далее ➡",
            callback_data=f"page:{command}:{current_page + 1}",
        ))

    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton(
        text=f"📄 Стр. {current_page}/{total_pages}",
        callback_data="noop",
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
