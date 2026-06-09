from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import storage.db as db
from bot.states import ProfileSetup
from storage.db import PROFILE_FIELDS, PROFILE_LABELS

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    profile = await db.get_profile(message.from_user.id)
    if not profile:
        await message.answer(
            "Привет! Я регистрирую тебя на ивенты — просто кинь мне ссылку.\n\n"
            "Сначала заполним твой профиль (один раз, потом автоматически).\n\n"
            f"<b>{PROFILE_LABELS[PROFILE_FIELDS[0]]}</b>",
            parse_mode="HTML",
        )
        await state.set_state(ProfileSetup.collecting)
        await state.update_data(field_index=0, profile_data={})
    else:
        await message.answer(
            "Привет! Кинь мне ссылку на форму регистрации — всё заполню сам.\n\n"
            "Команды:\n"
            "  /profile — посмотреть / изменить профиль\n"
            "  /help — помощь",
        )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Event Registration Bot</b>\n\n"
        "<b>Как зарегистрироваться:</b>\n"
        "Просто отправь ссылку на страницу регистрации — бот откроет её, "
        "заполнит форму твоими данными и покажет скриншот перед отправкой.\n\n"
        "<b>Команды:</b>\n"
        "  /start — начало\n"
        "  /profile — просмотр профиля\n"
        "  /edit_profile — изменить поле профиля\n"
        "  /help — эта справка\n\n"
        "<b>Неизвестные поля:</b>\n"
        "Если в форме есть поле которого нет в профиле, бот спросит тебя. "
        "Ответ запомнится — на следующих ивентах с таким же полем спрашивать не будет.\n\n"
        "<b>Пропустить поле:</b>\n"
        "Отправь <code>-</code> чтобы пропустить необязательное поле.",
        parse_mode="HTML",
    )


@router.message(ProfileSetup.collecting)
async def collect_profile(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    index: int = data.get("field_index", 0)
    profile_data: dict = data.get("profile_data", {})

    key = PROFILE_FIELDS[index]
    value = message.text.strip() if message.text else ""
    if value and value != "-":
        profile_data[key] = value

    index += 1

    if index < len(PROFILE_FIELDS):
        await state.update_data(field_index=index, profile_data=profile_data)
        await message.answer(
            f"<b>{PROFILE_LABELS[PROFILE_FIELDS[index]]}</b>",
            parse_mode="HTML",
        )
    else:
        # All fields collected — save
        await db.upsert_profile(message.from_user.id, profile_data)
        await state.clear()
        await message.answer(
            "Профиль сохранён! Теперь кидай ссылки на регистрацию — всё заполню за тебя.\n\n"
            "Используй /profile чтобы посмотреть сохранённые данные."
        )
