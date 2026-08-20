from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from application.identity import MenuContext


def build_menu_keyboard(context: MenuContext) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=item.title,
                    callback_data=item.action_id,
                )
            ]
            for item in context.items
        ]
    )
