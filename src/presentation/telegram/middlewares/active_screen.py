from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, TelegramObject

from presentation.telegram.ui_context import get_active_ui_message

STALE_SCREEN_TEXT = (
    "Этот экран уже неактивен. Используйте последнее сообщение."
)


class ActiveScreenCallbackMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[
            [TelegramObject, dict[str, Any]],
            Awaitable[Any],
        ],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        state = data.get("state")
        active = (
            await get_active_ui_message(state)
            if isinstance(state, FSMContext)
            else None
        )
        message_id = getattr(event.message, "message_id", None)
        if active is None or message_id != active.message_id:
            await event.answer(STALE_SCREEN_TEXT)
            return None

        return await handler(event, data)
