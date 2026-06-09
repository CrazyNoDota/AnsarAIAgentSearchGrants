from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def confirm_keyboard(url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Отправить форму", callback_data="reg:submit"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="reg:cancel"),
    )
    return builder.as_markup()


def options_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for opt in options[:10]:  # cap at 10 buttons
        builder.button(text=opt, callback_data=f"opt:{opt[:60]}")
    builder.adjust(2)
    return builder.as_markup()


def profile_edit_keyboard() -> InlineKeyboardMarkup:
    from storage.db import PROFILE_FIELDS, PROFILE_LABELS
    builder = InlineKeyboardBuilder()
    for key in PROFILE_FIELDS:
        label = PROFILE_LABELS.get(key, key).split("(")[0].strip()
        builder.button(text=label, callback_data=f"edit:{key}")
    builder.adjust(2)
    return builder.as_markup()
