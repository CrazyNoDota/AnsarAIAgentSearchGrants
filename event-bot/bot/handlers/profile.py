from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import storage.db as db
from bot.keyboards import profile_edit_keyboard
from bot.states import EditProfile
from storage.db import PROFILE_FIELDS, PROFILE_LABELS

router = Router()


def _format_profile(profile: dict) -> str:
    lines = ["<b>Твой профиль:</b>\n"]
    for key in PROFILE_FIELDS:
        label = PROFILE_LABELS.get(key, key).split("(")[0].strip()
        val = profile.get(key) or "—"
        lines.append(f"  <b>{label}:</b> {val}")
    return "\n".join(lines)


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    profile = await db.get_profile(message.from_user.id)
    if not profile:
        await message.answer("Профиль не заполнен. Используй /start для настройки.")
        return
    await message.answer(_format_profile(profile), parse_mode="HTML")


@router.message(Command("edit_profile"))
async def cmd_edit_profile(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Какое поле хочешь изменить?",
        reply_markup=profile_edit_keyboard(),
    )
    await state.set_state(EditProfile.choosing_field)


@router.callback_query(EditProfile.choosing_field, F.data.startswith("edit:"))
async def edit_field_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    label = PROFILE_LABELS.get(key, key).split("(")[0].strip()
    await state.update_data(editing_key=key)
    await state.set_state(EditProfile.entering_value)
    await callback.message.edit_text(  # type: ignore[union-attr]
        f"Введи новое значение для <b>{label}</b> (или <code>-</code> чтобы очистить):",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(EditProfile.entering_value)
async def edit_field_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    key: str = data.get("editing_key", "")
    value = message.text.strip() if message.text else ""

    new_val = None if value == "-" else value
    await db.upsert_profile(message.from_user.id, {key: new_val})
    await state.clear()

    label = PROFILE_LABELS.get(key, key).split("(")[0].strip()
    await message.answer(
        f"<b>{label}</b> обновлено: {new_val or '(очищено)'}",
        parse_mode="HTML",
    )
