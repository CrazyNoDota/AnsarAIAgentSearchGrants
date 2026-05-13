"""
Main menu keyboard for Telegram bot.
Displayed on /start and when user taps the menu button.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Full main menu with all sections."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 New Resources", callback_data="menu:pending"),
            InlineKeyboardButton(text="✅ Approved", callback_data="menu:approved"),
        ],
        [
            InlineKeyboardButton(text="❌ Rejected", callback_data="menu:rejected"),
            InlineKeyboardButton(text="⏰ Deadlines", callback_data="menu:deadlines"),
        ],
        [
            InlineKeyboardButton(text="🤖 AI Recommendations", callback_data="menu:recommend"),
        ],
        [
            InlineKeyboardButton(text="🏷 Filter by Category", callback_data="menu:categories"),
        ],
        [
            InlineKeyboardButton(text="🔍 Search Grants", callback_data="menu:search"),
            InlineKeyboardButton(text="📊 Statistics", callback_data="menu:stats"),
        ],
        [
            InlineKeyboardButton(text="⚙️ AI Insights", callback_data="menu:insights"),
            InlineKeyboardButton(text="🔄 Run Scraper", callback_data="menu:scrape"),
        ],
    ])
