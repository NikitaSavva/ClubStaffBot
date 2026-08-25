from datetime import UTC, datetime
from typing import Any

from aiogram.enums import ChatType
from aiogram.methods import GetMe, SendMessage, SendPhoto, TelegramMethod
from aiogram.types import Chat, InlineKeyboardMarkup, Message, User

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
DEFAULT_BOT_USER = User(
    id=123456789,
    is_bot=True,
    first_name="Staff Bot",
    username="staff_test_bot",
)


def telegram_method_result(
    method: TelegramMethod[Any],
    *,
    message_id: int,
    bot_user: User = DEFAULT_BOT_USER,
) -> Any:
    if isinstance(method, GetMe):
        return bot_user
    if isinstance(method, SendMessage):
        return Message(
            message_id=message_id,
            date=NOW,
            chat=Chat(id=int(method.chat_id), type=ChatType.PRIVATE),
            from_user=bot_user,
            text=method.text,
            reply_markup=(
                method.reply_markup
                if isinstance(method.reply_markup, InlineKeyboardMarkup)
                else None
            ),
        )
    if isinstance(method, SendPhoto):
        return Message(
            message_id=message_id,
            date=NOW,
            chat=Chat(id=int(method.chat_id), type=ChatType.PRIVATE),
            from_user=bot_user,
            caption=method.caption,
            reply_markup=(
                method.reply_markup
                if isinstance(method.reply_markup, InlineKeyboardMarkup)
                else None
            ),
        )
    return True
