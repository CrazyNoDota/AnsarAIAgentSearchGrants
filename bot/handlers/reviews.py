from aiogram import Router, F
from aiogram.types import CallbackQuery

import api_client
from keyboards.grant_keyboard import delete_confirm_keyboard, grant_review_keyboard

router = Router()

DECISION_LABEL = {
    "approved": ("✅", "Одобрено"),
    "rejected": ("❌", "Отклонено"),
}


def _format_error(e: Exception) -> str:
    msg = str(e).strip()
    return msg or e.__class__.__name__


@router.callback_query(F.data.startswith("review:"))
async def handle_review(callback: CallbackQuery):
    """
    Обработка нажатия кнопок одобрения/отклонения.
    Формат: review:{decision}:{grant_id}
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Неверное действие.", show_alert=True)
        return

    _, decision, grant_id_str = parts
    grant_id = int(grant_id_str)

    # Бекенд ожидает форму прошедшего времени; кнопка отправляет глагол.
    decision = {"approve": "approved", "reject": "rejected"}.get(decision, decision)

    reviewer_name = "unknown"
    if callback.from_user:
        reviewer_name = (
            callback.from_user.username
            or callback.from_user.full_name
            or str(callback.from_user.id)
        )

    try:
        await api_client.review_grant(
            grant_id=grant_id,
            decision=decision,
            reviewer_name=reviewer_name,
        )

        emoji, label = DECISION_LABEL.get(decision, ("•", decision))

        # Видимое подтверждение (всплывающее уведомление + изменение сообщения).
        await callback.answer(
            f"{emoji} {label} — сохранено",
            show_alert=False,
        )

        if callback.message:
            original_text = callback.message.html_text or callback.message.text or ""
            updated_text = (
                f"{original_text}\n\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{emoji} <b>{label}</b> — @{reviewer_name}"
            )
            await callback.message.edit_text(
                updated_text,
                parse_mode="HTML",
                reply_markup=None,
                disable_web_page_preview=True,
            )

    except Exception as e:
        await callback.answer(
            f"❌ Не удалось сохранить решение: {_format_error(e)}",
            show_alert=True,
        )


@router.callback_query(F.data.startswith("delete:"))
async def handle_delete(callback: CallbackQuery):
    """
    Двухшаговое удаление гранта.
    Формат: delete:{action}:{grant_id} где action ∈ {confirm, do, cancel}
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Неверное действие.", show_alert=True)
        return

    _, action, grant_id_str = parts
    grant_id = int(grant_id_str)

    if action == "confirm":
        # Show confirmation buttons in place of the original review keyboard.
        if callback.message:
            await callback.message.edit_reply_markup(
                reply_markup=delete_confirm_keyboard(grant_id),
            )
        await callback.answer("Подтвердите удаление.")
        return

    if action == "cancel":
        # Restore the original review keyboard if the grant was pending,
        # otherwise just remove the confirmation buttons.
        if callback.message:
            try:
                await callback.message.edit_reply_markup(
                    reply_markup=grant_review_keyboard(grant_id),
                )
            except Exception:
                await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Отменено.")
        return

    if action == "do":
        try:
            await api_client.delete_grant(grant_id)
        except Exception as e:
            await callback.answer(
                f"❌ Не удалось удалить: {_format_error(e)}",
                show_alert=True,
            )
            return

        await callback.answer("🗑 Грант удалён.", show_alert=False)

        if callback.message:
            original_text = callback.message.html_text or callback.message.text or ""
            updated_text = (
                f"{original_text}\n\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🗑 <b>УДАЛЕНО</b>"
            )
            await callback.message.edit_text(
                updated_text,
                parse_mode="HTML",
                reply_markup=None,
                disable_web_page_preview=True,
            )
        return

    await callback.answer("Неизвестное действие.", show_alert=True)


@router.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery):
    """Индикатор страницы — ничего не делать."""
    await callback.answer()
