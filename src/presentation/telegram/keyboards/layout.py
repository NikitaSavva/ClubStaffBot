from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

MAX_CALLBACK_DATA_BYTES = 64


def build_callback_button(
    *,
    text: str,
    callback_data: str,
) -> InlineKeyboardButton:
    if len(callback_data.encode()) > MAX_CALLBACK_DATA_BYTES:
        raise ValueError("callback_data exceeds Telegram 64-byte limit")
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def build_web_app_button(*, text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))


def build_inline_keyboard(
    *rows: Sequence[InlineKeyboardButton],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        if row:
            builder.row(*row, width=len(row))
    return builder.as_markup()
