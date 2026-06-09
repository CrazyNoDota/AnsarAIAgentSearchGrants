"""
Main menu keyboard for Telegram bot.
Displayed on /start and when user taps the menu button.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Full main menu with all sections."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 Новые гранты", callback_data="menu:pending"),
            InlineKeyboardButton(text="✅ Одобренные", callback_data="menu:approved"),
        ],
        [
            InlineKeyboardButton(text="❌ Отклонённые", callback_data="menu:rejected"),
            InlineKeyboardButton(text="⏰ Дедлайны", callback_data="menu:deadlines"),
        ],
        [
            InlineKeyboardButton(text="🤖 Рекомендации ИИ", callback_data="menu:recommend"),
        ],
        [
            InlineKeyboardButton(text="🏷 По категориям", callback_data="menu:categories"),
        ],
        [
            InlineKeyboardButton(text="🔍 Поиск грантов", callback_data="menu:search"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Что узнал ИИ", callback_data="menu:insights"),
            InlineKeyboardButton(text="🔄 Запустить сбор", callback_data="menu:scrape"),
        ],
        [
            InlineKeyboardButton(text="🌐 Свои источники", callback_data="menu:sources"),
        ],
        [
            InlineKeyboardButton(text="❓ Помощь и гайд", callback_data="menu:help"),
        ],
    ])
